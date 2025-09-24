#!/usr/bin/env python
"""
MultiQC Components - Clean DMC Implementation
Modular components for MultiQC table and violin plot with DMC styling
"""

import argparse
import collections
import re
import sys

import dash_mantine_components as dmc
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import polars as pl
from dash import Dash, Input, Output, dash_table, dcc
from dash.dash_table.Format import Format, Symbol
from multiqc_metadata_loader import MultiQCMetadataLoader, resolve_config_expressions

# Fix matplotlib deprecation warning
try:
    # Try new API first (matplotlib >= 3.7)
    from matplotlib import colormaps

    def get_colormap(name):
        return colormaps[name]
except ImportError:
    # Fallback to old API
    from matplotlib.cm import get_cmap

    def get_colormap(name):
        return get_cmap(name)


def sanitize_column_name(name):
    """Sanitize column names for DataTable JavaScript compatibility"""
    # Remove problematic characters for JavaScript
    sanitized = re.sub(r"[{}\'\"]", "", name)  # Remove braces and quotes
    sanitized = re.sub(r"f\'[^\']*\'", "Config_Value", sanitized)  # Replace f-strings
    sanitized = re.sub(
        r"config\.[a-zA-Z_]+", "Config_Value", sanitized
    )  # Replace config references
    sanitized = re.sub(r"[^a-zA-Z0-9\s\(\)_\-\.\%]", "_", sanitized)  # Replace other special chars
    sanitized = re.sub(r"\s+", " ", sanitized).strip()  # Clean up whitespace
    return sanitized


def process_multiqc_data(parquet_path, metadata_path):
    """Process MultiQC parquet data and return formatted DataFrames."""
    # Load MultiQC metadata
    metadata_loader = MultiQCMetadataLoader(metadata_path)
    column_metadata = metadata_loader.get_all_column_mappings()

    # Load the parquet file
    df_raw = pl.read_parquet(parquet_path)

    # Filter for general stats table data and convert to pandas
    df_general_stats = df_raw.filter(pl.col("anchor") == "general_stats_table")
    df_explore = df_general_stats.to_pandas()

    # Filter to just the data rows (not metadata rows)
    df_metrics = df_explore[df_explore["type"] == "plot_input_row"].copy()

    # Pivot the data to get samples as rows and metrics as columns
    df_pivot = df_metrics.pivot_table(
        index="sample", columns="metric", values="val_raw", aggfunc="first"
    ).reset_index()

    tools = df_metrics["section_key"].unique()

    # Create unified column mapping using metadata
    column_mapping = {}
    percentage_columns = []

    # Process each column in the pivoted data
    for col in df_pivot.columns:
        if col == "sample":
            column_mapping[col] = "Sample Name"
            continue

        # Find metadata for this column across all tools
        display_name = None
        config = None

        for tool in tools:
            if tool in column_metadata and col in column_metadata[tool]:
                config = column_metadata[tool][col]
                display_name = config["title"]
                # Apply suffix from metadata
                if config["suffix"] and not display_name.endswith(f" ({config['suffix']})"):
                    display_name = f"{display_name} ({config['suffix']})"
                break

        # Fallback for columns not in metadata
        if display_name is None:
            display_name = col.replace("_", " ").title()
            # Auto-detect percentage columns by name patterns
            if "pct_" in col or "rate" in col.lower() or "content" in col.lower():
                if not display_name.endswith(" (%))"):
                    display_name = display_name.replace("Pct ", "") + " (%)"

        column_mapping[col] = display_name

        # Track percentage columns based on metadata suffix
        if config and config["suffix"] == "%":
            percentage_columns.append(display_name)
        elif display_name.endswith(" (%)"):
            percentage_columns.append(display_name)

    # Apply column mapping
    df_multiqc_real = df_pivot.rename(columns=column_mapping)

    # Selectively convert 0-1 percentage columns to 0-100 for consistent display
    # Only convert specific columns that are known to be in 0-1 format
    for orig_col, display_name in column_mapping.items():
        if display_name in percentage_columns and display_name in df_multiqc_real.columns:
            # Check if this specific column needs conversion (0-1 to 0-100)
            # These specific fastp columns are known to be in 0-1 format
            if orig_col in ['after_filtering_gc_content', 'after_filtering_q30_rate']:
                df_multiqc_real[display_name] = df_multiqc_real[display_name] * 100

    # Auto-format large numbers (>1M) to millions using metadata
    for col in df_multiqc_real.columns:
        if col != "Sample Name" and df_multiqc_real[col].dtype in ["int64", "float64"]:
            if df_multiqc_real[col].mean() > 1_000_000:
                # Remove existing suffix and add millions suffix
                if "(" in col and col.endswith(")"):
                    base_name = col[:col.rfind("(")].strip()
                    millions_col = f"{base_name} (M)"
                else:
                    millions_col = f"{col} (M)"

                df_multiqc_real[millions_col] = (df_multiqc_real[col] / 1_000_000).round(2)
                df_multiqc_real = df_multiqc_real.drop(columns=[col])

                # Update percentage columns list if needed
                if col in percentage_columns:
                    percentage_columns.remove(col)
                    percentage_columns.append(millions_col)

    # Sanitize column names for DataTable JavaScript compatibility
    sanitized_columns = {}
    display_to_internal = {}

    for col in df_multiqc_real.columns:
        if col == "Sample Name":
            sanitized_columns[col] = col
            display_to_internal[col] = col
        else:
            sanitized = sanitize_column_name(col)
            counter = 1
            original_sanitized = sanitized
            while sanitized in sanitized_columns.values():
                sanitized = f"{original_sanitized}_{counter}"
                counter += 1
            sanitized_columns[col] = sanitized
            display_to_internal[col] = sanitized

    internal_to_display = {v: k for k, v in display_to_internal.items()}
    df_multiqc_real = df_multiqc_real.rename(columns=sanitized_columns)

    # Prepare display DataFrame - no conversion needed, just copy
    df_for_display = df_multiqc_real.copy()

    return df_multiqc_real, df_for_display, metadata_loader, internal_to_display, tools, column_metadata, percentage_columns


# =============================================================================
# DATA BARS FUNCTION
# =============================================================================


def multiqc_data_bars_colormap(
    df, column, cmap_name="RdYlGn", opacity=0.4, fixed_scale=None, reverse_colors=False
):
    """Create data bars with matplotlib colormap

    Args:
        fixed_scale: tuple of (min, max) to use instead of data min/max (e.g., (0, 100) for percentages)
        reverse_colors: If True, high values get low colormap values (for reversed scales like RdYlGn-rev)
    """
    n_bins = 100
    bounds = [i * (1.0 / n_bins) for i in range(n_bins + 1)]

    col_data = pd.to_numeric(df[column], errors="coerce")

    # Use fixed scale if provided (e.g., 0-100 for percentages), otherwise use data range
    if fixed_scale:
        col_min, col_max = fixed_scale
    else:
        col_max = col_data.max()
        col_min = col_data.min()

    if pd.isna(col_max) or pd.isna(col_min):
        return []

    # Get the colormap (updated for newer matplotlib versions)
    try:
        cmap = plt.colormaps[cmap_name]
    except KeyError:
        cmap = get_colormap(cmap_name)  # Use our compatibility function

    ranges = [((col_max - col_min) * i) + col_min for i in bounds]

    # Escape column name for filter query
    col_id = column.replace("(", "\\(").replace(")", "\\)").replace("%", "\\%")

    styles = []
    for i in range(1, len(bounds)):
        min_bound = ranges[i - 1]
        max_bound = ranges[i]
        # Calculate bar width percentage
        # For data normalized to the scale range, use the normalized position
        if fixed_scale:
            # For fixed scales, max_bound is actual data value, normalize to percentage
            max_bound_percentage = ((max_bound - col_min) / (col_max - col_min)) * 100
        else:
            # For auto scales, use bounds directly
            max_bound_percentage = bounds[i] * 100

        # Normalize the value to 0-1 for colormap
        mid_value = (min_bound + max_bound) / 2
        norm_value = (mid_value - col_min) / (col_max - col_min) if col_max != col_min else 0.5

        # For reversed scales (like RdYlGn-rev), high data values should get low colormap values
        if reverse_colors:
            norm_value = 1.0 - norm_value

        # Use the full colormap range for proper color scaling
        scaled_norm = norm_value

        # Get color from colormap and apply opacity for dimmer appearance
        rgba = cmap(scaled_norm)
        # Apply opacity by blending with white background
        r, g, b, _ = rgba
        # Blend with white background using opacity
        r = r * opacity + (1 - opacity) * 1.0  # 1.0 = white
        g = g * opacity + (1 - opacity) * 1.0
        b = b * opacity + (1 - opacity) * 1.0
        bar_color = mcolors.to_hex((r, g, b, 1.0))

        styles.append(
            {
                "if": {
                    "filter_query": (
                        "{{{column}}} >= {min_bound}"
                        + (" && {{{column}}} < {max_bound}" if (i < len(bounds) - 1) else "")
                    ).format(column=col_id, min_bound=min_bound, max_bound=max_bound),
                    "column_id": column,
                },
                "background": f"""
                linear-gradient(90deg,
                {bar_color} 0%,
                {bar_color} {max_bound_percentage}%,
                white {max_bound_percentage}%,
                white 100%)
            """,
                "paddingBottom": 4,
                "paddingTop": 4,
                "color": "black",
                "fontWeight": "normal",
            }
        )

    return styles


# =============================================================================
# 3. CREATE VIOLIN PLOT FUNCTION
# =============================================================================


def create_multiqc_violin_plot(df_general_stats, metadata_loader):
    """
    Create MultiQC-style violin plot from general stats DataFrame.

    Args:
        df_general_stats: DataFrame from parquet with general_stats_table anchor
        metadata_loader: MultiQCMetadataLoader instance

    Returns:
        Plotly figure object
    """
    # Constants from MultiQC
    VIOLIN_HEIGHT = 70  # Exact from MultiQC
    EXTRA_HEIGHT = 63  # Exact from MultiQC

    # Get unique metrics (column names) - excluding Sample Name
    metrics = [col for col in df_general_stats.columns if col != "Sample Name"]

    # Handle case where no metrics are available
    if not metrics:
        return (
            go.Figure()
            .add_annotation(
                text="No metrics available for violin plot",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                xanchor="center",
                yanchor="middle",
                showarrow=False,
                font_size=16,
            )
            .update_layout(
                title="General Statistics - No Data", template="plotly_white", height=200
            )
        )

    # Get metadata for each metric
    metric_info = []
    for metric in metrics:
        # Get original metric name from metadata
        original_metric = None

        is_percentage = "percent" in (original_metric or metric).lower() or "%" in metric

        metric_info.append(
            {
                "display_name": metric,
                "original_name": original_metric,
                "is_percentage": is_percentage,
            }
        )

    # Count number of samples
    num_samples = len(df_general_stats)

    # Create layout - EXACT MultiQC styling
    layout = go.Layout(
        title={
            "text": f"General Statistics<br><span style='font-size: 12px; color: #666;'>{num_samples} samples</span>",
            "x": 0.5,  # Center the title
            "xanchor": "center",
            "font": {"size": 16, "color": "#333"},
        },
        showlegend=False,
        template="plotly_white",  # Clean white background
        margin=dict(pad=0, b=40, t=70, l=120, r=20),  # Increased left margin for labels
        grid={
            "rows": len(metrics),
            "columns": 1,
            "roworder": "top to bottom",
            "pattern": "independent",
            "ygap": 0.4,  # Reduced padding between violins
            "subplots": [[(f"x{i + 1}y{i + 1}" if i > 0 else "xy")] for i in range(len(metrics))],
        },
        height=VIOLIN_HEIGHT * len(metrics) + EXTRA_HEIGHT,
        xaxis={
            "automargin": False,  # MultiQC specific
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},  # Grey small font
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
        },
        yaxis={
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},  # Grey small font
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
        },
        violingap=0,  # No gap between violins
    )

    # Create figure
    fig = go.Figure(layout=layout)

    # Process each metric
    for metric_idx, metric_data in enumerate(metric_info):
        metric = metric_data["display_name"]

        # Get values for this metric (convert from display format back to numeric)
        values = []
        samples = []
        for _, row in df_general_stats.iterrows():
            sample_name = row["Sample Name"]
            value = row[metric]
            values.append(value)
            samples.append(sample_name)

        # Set up axes for this metric
        axis_key = "" if metric_idx == 0 else str(metric_idx + 1)

        # Configure X-axis with proper limits
        x_axis_config = {
            "automargin": False,
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
            "title": "",
            "hoverformat": ".2f",
        }

        # Set range based on metric type
        if metric_data["is_percentage"]:
            x_axis_config["range"] = [0, 100]  # 0-100% for percentage distributions
            x_axis_config["ticksuffix"] = "%"
        else:
            # Set min to 0 for non-percentage metrics
            min_val = min(0, min(values))
            max_val = max(values)
            # Add 5% padding
            padding = (max_val - min_val) * 0.05 if max_val != min_val else 1
            x_axis_config["range"] = [min_val - padding, max_val + padding]

        layout[f"xaxis{metric_idx + 1}"] = x_axis_config

        # Configure Y-axis with metric label (Module name from data)
        # Use generic module name since we don't have access to raw metrics data
        module_name = "MultiQC"

        # Create label with module name and metric on separate lines
        label_text = f"{module_name}<br>{metric}"

        layout[f"yaxis{metric_idx + 1}"] = {
            "automargin": True,
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},  # Grey small font
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
            "tickmode": "array",
            "tickvals": [metric_idx],
            "ticktext": [label_text],
            "range": [metric_idx - 0.4, metric_idx + 0.4],
        }

        # Add violin trace - grey color as per MultiQC
        fig.add_trace(
            go.Violin(
                x=values,
                y=[metric_idx] * len(values),
                name=metric,
                text=samples,
                xaxis=f"x{axis_key}",
                yaxis=f"y{axis_key}",
                orientation="h",
                side="both",
                box={"visible": True},  # Show box plot
                meanline={"visible": True},  # Show mean line
                fillcolor="#b5b5b5",  # Grey color - EXACT MultiQC
                line={"width": 2, "color": "#b5b5b5"},  # Grey line
                opacity=0.5,
                points=False,  # Don't show points from violin
                hoveron="points",  # Only hover on scatter points
                showlegend=False,
            )
        )

        # Add scatter points - blue color as per MultiQC when all violins are grey
        fig.add_trace(
            go.Scatter(
                x=values,
                y=[metric_idx] * len(values),
                mode="markers",
                text=samples,
                xaxis=f"x{axis_key}",
                yaxis=f"y{axis_key}",
                marker={
                    "size": 4,
                    "color": "#0b79e6",  # Blue - EXACT MultiQC color when violins are grey
                },
                showlegend=False,
                hovertemplate="<b>%{text}</b><br>%{x:.2f}<extra></extra>",
                hoverlabel={"bgcolor": "white"},
            )
        )

    # Update final layout
    fig.update_layout(layout)

    return fig


def generate_data_bar_styles(df_for_display, tools, column_metadata, internal_to_display, percentage_columns):
    """Generate colormap-based data bar styles for columns using metadata."""
    # Map MultiQC scale names to matplotlib colormap names and reverse flags
    scale_mapping = {
        "RdYlGn-rev": ("RdYlGn_r", False),  # Use reversed colormap directly
        "RdYlGn": ("RdYlGn", False),  # Red-Yellow-Green
        "PuRd": ("PuRd", False),  # Purple-Red
        "Reds": ("Reds", False),  # Red scale
        "Blues": ("Blues", False),  # Blue scale
        "Greens": ("Greens", False),  # Green scale
        "Oranges": ("Oranges", False),  # Orange scale
    }

    column_formats = {}
    all_styles = []

    # Process each column in the display dataframe
    for internal_col in df_for_display.columns:
        if internal_col == "Sample Name":
            continue

        # Get display name for this column
        display_name = internal_to_display.get(internal_col, internal_col)

        # Find metadata for this column by searching original data column names
        config = None
        for tool in tools:
            if tool in column_metadata:
                for orig_key, meta_config in column_metadata[tool].items():
                    # Match by original key name or by title from metadata
                    if (orig_key in display_name or
                        display_name.startswith(meta_config.get("title", ""))):
                        config = meta_config
                        break
            if config:
                break

        # Set defaults if no metadata found
        if config is None:
            config = {
                "scale": "Blues",
                "format": "{:,.1f}",
                "suffix": "",
                "min": None,
                "max": None
            }

        # Set colormap and reverse flag from metadata
        scale_name = config.get("scale", "Blues")
        if scale_name in scale_mapping:
            colormap, reverse_flag = scale_mapping[scale_name]
        else:
            colormap = scale_name
            reverse_flag = False

        # Set fixed scale based on metadata and column type
        fixed_scale = None
        if display_name in percentage_columns:
            # For percentage columns, use 0-100 range (raw values)
            min_val = config.get("min")
            max_val = config.get("max")
            if min_val is not None and max_val is not None:
                fixed_scale = (min_val, max_val)
            # else:
            #     fixed_scale = (0, 100)
        elif config.get("min") is not None and config.get("max") is not None:
            fixed_scale = (config["min"], config["max"])

        # Store format information for later use
        column_formats[display_name] = {
            "format": config.get("format", "{:,.1f}"),
            "suffix": config.get("suffix", "")
        }

        # Generate styles for this column
        all_styles.extend(
            multiqc_data_bars_colormap(
                df_for_display,
                internal_col,
                colormap,
                opacity=0.3,
                fixed_scale=fixed_scale,
                reverse_colors=reverse_flag,
            )
        )

    return all_styles, column_formats


# Define column format function based on metadata
def get_column_format(column_name, percentage_columns, column_formats):
    """Get appropriate Dash DataTable format for a column based on metadata."""
    if column_name == "Sample Name":
        return None

    # Check if it's a percentage column (raw values 0-100)
    if column_name in percentage_columns:
        # Format as numbers with % suffix, 1 decimal place
        return Format(symbol=Symbol.yes, symbol_suffix="%").precision(1).scheme("f")

    # Handle millions column with M suffix BEFORE checking column_formats
    if "(M)" in column_name:
        return Format(symbol=Symbol.yes, symbol_suffix=" M").precision(2).scheme("f")

    # Handle bp columns BEFORE checking column_formats
    if "bp" in column_name:
        return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(0).scheme("f")

    # Check for specific format from metadata and add suffixes
    if column_name in column_formats:
        format_info = column_formats[column_name]
        format_str = format_info["format"]
        suffix = format_info.get("suffix", "")

        # Use Format with symbol_suffix for bp suffix, no scientific notation
        if "bp" in suffix:
            if ".0f" in format_str:
                return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(0).scheme("f")
            elif ".1f" in format_str:
                return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(1).scheme("f")

        # Regular numeric formats without suffix - use comma separators
        if ".0f" in format_str:
            return Format(precision=0, scheme="f", group=True)
        elif ".1f" in format_str:
            return Format(precision=1, scheme="f", group=True)
        elif ".2f" in format_str:
            return Format(precision=2, scheme="f", group=True)

    # Default length columns
    if "len" in column_name.lower():
        return Format(precision=0, scheme="f", group=True)

    return Format(precision=1, scheme="f", group=True)  # Default numeric format


# =============================================================================
# 4. COMPONENT CREATION FUNCTIONS
# =============================================================================


def create_multiqc_table_component(df_data, all_styles, column_display_mapping=None, percentage_columns=None, column_formats=None):
    """Create MultiQC table component with data bars."""
    # Use display names for headers if mapping is provided
    if column_display_mapping is None:
        column_display_mapping = {}
    if percentage_columns is None:
        percentage_columns = []
    if column_formats is None:
        column_formats = {}

    return dash_table.DataTable(
        id="multiqc-table",
        data=df_data.to_dict("records"),
        columns=[
            {
                "name": column_display_mapping.get(col, col),  # Use display name for header
                "id": col,  # Use internal name for data reference
                "type": "numeric" if col != "Sample Name" else "text",
                "format": get_column_format(column_display_mapping.get(col, col), percentage_columns, column_formats),
            }
            for col in df_data.columns
        ],
        style_data_conditional=all_styles
        + [
            {
                "if": {"state": "active"},
                "backgroundColor": "rgba(0, 116, 217, 0.05)",
                "border": "1px solid rgba(0, 116, 217, 0.3)",
            }
        ],
        style_cell={
            "textAlign": "left",
            "padding": "6px 8px",
            "fontFamily": "Arial, Helvetica, sans-serif",
            "fontSize": "12px",
            "border": "none",
            "borderBottom": "1px solid #e8e8e8",
            "whiteSpace": "nowrap",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": "Sample Name"},
                "minWidth": "200px",
                "fontWeight": "normal",
                "backgroundColor": "white",
            }
        ],
        style_header={
            "backgroundColor": "#f5f5f5",
            "fontWeight": "bold",
            "borderBottom": "2px solid #ddd",
            "borderTop": "none",
            "borderLeft": "none",
            "borderRight": "none",
            "textAlign": "center",
            "fontSize": "12px",
            "fontFamily": "Arial, Helvetica, sans-serif",
            "padding": "8px",
        },
        style_data={"border": "none", "borderBottom": "1px solid #f0f0f0"},
        style_table={
            "border": "none",
            "borderTop": "1px solid #ddd",
            "borderBottom": "1px solid #ddd",
            "overflow": "auto",
            "maxHeight": "600px",
        },
        sort_action="native",
        filter_action="none",
        page_size=50,
    )


def create_multiqc_violin_component(df_data, metadata_loader):
    """Create MultiQC violin plot component."""
    violin_fig = create_multiqc_violin_plot(df_data, metadata_loader)
    return dcc.Graph(figure=violin_fig, config={"displayModeBar": False})


def create_multiqc_dashboard(df_display_data, df_numeric_data, metadata_loader, all_styles, internal_to_display):
    """Create complete MultiQC dashboard with toggle."""
    table_component = create_multiqc_table_component(df_display_data, all_styles, internal_to_display)
    violin_component = create_multiqc_violin_component(df_numeric_data, metadata_loader)

    return dmc.Stack(
        [
            dmc.Group(
                [
                    dmc.Title("General Statistics", order=2),
                    dmc.SegmentedControl(
                        id="view-toggle",
                        value="table",
                        data=[
                            {"label": "📊 Table", "value": "table"},
                            {"label": "🎻 Violin", "value": "violin"},
                        ],
                    ),
                ],
                justify="space-between",
                align="center",
            ),
            dmc.Box(table_component, id="table-container"),
            dmc.Box(violin_component, id="violin-container", style={"display": "none"}),
        ],
        gap="md",
    )


def create_app(parquet_path, metadata_path, port=8052):
    """Create and configure the Dash app with MultiQC data."""
    # Process data
    df_multiqc_real, df_for_display, metadata_loader, internal_to_display, tools, column_metadata, percentage_columns = process_multiqc_data(parquet_path, metadata_path)

    # Generate styles and formats
    all_styles, column_formats = generate_data_bar_styles(df_for_display, tools, column_metadata, internal_to_display, percentage_columns)

    # Create Dash app
    app = Dash(__name__)

    # Create components (use column identity mapping)
    table_component = create_multiqc_table_component(df_for_display, all_styles, {}, percentage_columns, column_formats)
    violin_component = create_multiqc_violin_component(df_for_display, metadata_loader)
    dashboard = create_multiqc_dashboard(df_for_display, df_for_display, metadata_loader, all_styles, internal_to_display)

    # Set app layout
    app.layout = dmc.MantineProvider(dmc.Container(dashboard, p="md"))

    # Add callback for view toggle
    @app.callback(
        [Output("table-container", "style"), Output("violin-container", "style")],
        [Input("view-toggle", "value")],
    )
    def toggle_view(view_type):
        """Toggle between table and violin plot view."""
        if view_type == "table":
            return {"display": "block"}, {"display": "none"}
        else:
            return {"display": "none"}, {"display": "block"}

    return app

# =============================================================================
# 5. STANDALONE COMPONENT FUNCTIONS (NO DASH APP REQUIRED)
# =============================================================================


def get_multiqc_table_component(df_data, metadata_loader, internal_to_display=None):
    """Get standalone MultiQC table component (no app required)."""
    if internal_to_display is None:
        internal_to_display = {}

    # Process data and generate styles
    column_metadata = metadata_loader.get_all_column_mappings()
    all_styles = []
    percentage_columns = []

    for column in df_data.columns:
        if column != "Sample Name":
            cmap_name = "Blues"  # Default colormap
            fixed_scale = None
            reverse_colors = False

            # Find matching metadata from any tool
            for tool_name, tool_metadata in column_metadata.items():
                for key, config in tool_metadata.items():
                    if key in column or config.get("title", "") in column:
                        if config["suffix"] == "%":
                            fixed_scale = (0, 1)
                            percentage_columns.append(column)
                        break

            all_styles.extend(
                multiqc_data_bars_colormap(
                    df_data,
                    column,
                    cmap_name,
                    opacity=0.3,
                    fixed_scale=fixed_scale,
                    reverse_colors=reverse_colors,
                )
            )

    return create_multiqc_table_component(df_data, all_styles, internal_to_display, percentage_columns, {})


def get_multiqc_violin_component(df_data, metadata_loader):
    """Get standalone MultiQC violin plot component (no app required)."""
    return create_multiqc_violin_component(df_data, metadata_loader)


def get_multiqc_dashboard_component(df_data, metadata_loader):
    """Get complete MultiQC dashboard component with toggle (no app required)."""
    # Process data and generate styles
    column_metadata = metadata_loader.get_all_column_mappings()
    all_styles = []

    for column in df_data.columns:
        if column != "Sample Name":
            cmap_name = "Blues"
            fixed_scale = None
            reverse_colors = False

            # Find matching metadata from any tool
            for tool_name, tool_metadata in column_metadata.items():
                for key, config in tool_metadata.items():
                    if key in column or config.get("title", "") in column:
                        if config["suffix"] == "%":
                            fixed_scale = (0, 1)
                        break

            all_styles.extend(
                multiqc_data_bars_colormap(
                    df_data,
                    column,
                    cmap_name,
                    opacity=0.3,
                    fixed_scale=fixed_scale,
                    reverse_colors=reverse_colors,
                )
            )

    # Create internal_to_display mapping
    internal_to_display = {col: col for col in df_data.columns}
    return create_multiqc_dashboard(df_data, df_data, metadata_loader, all_styles, internal_to_display)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="MultiQC Components - Clean DMC Implementation")
    parser.add_argument("parquet_path", help="Path to MultiQC parquet file")
    parser.add_argument("metadata_path", help="Path to MultiQC metadata JSON file")
    parser.add_argument("--port", type=int, default=8052, help="Port to run the dashboard on (default: 8052)")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    return parser.parse_args()


def main():
    """Main function to run the MultiQC dashboard."""
    args = parse_arguments()

    try:
        # Create and run the app
        app = create_app(args.parquet_path, args.metadata_path, args.port)
        print(f"🚀 Starting MultiQC Table Dashboard on http://localhost:{args.port}")
        app.run(debug=args.debug, port=args.port)
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        if args.debug:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
