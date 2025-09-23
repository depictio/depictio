#!/usr/bin/env python
"""
MultiQC Table with Data Bars - Clean Implementation
Creates a MultiQC-style table with data bars using real parquet data and correct metadata
"""

import json

import dash_mantine_components as dmc
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import polars as pl
from dash import Dash, Input, Output, dash_table, dcc, html
from dash.dash_table.Format import Format, Symbol
from multiqc_metadata_loader import MultiQCMetadataLoader

# =============================================================================
# 1. LOAD METADATA AND PROCESS DATA FROM PARQUET
# =============================================================================

# Load MultiQC metadata
metadata_path = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/multiqc_metadata_extraction.json"
metadata_loader = MultiQCMetadataLoader(metadata_path)
column_metadata = metadata_loader.get_all_column_mappings()

print("=== MultiQC Metadata Loaded ===")
# Override hidden status for median_sequence_length - user wants it visible
if "median_sequence_length" in column_metadata:
    column_metadata["median_sequence_length"]["hidden"] = False

for key, config in column_metadata.items():
    if not config["hidden"]:  # Only show non-hidden columns
        print(f"{key}: {config['title']} | Scale: {config['scale']} | Format: {config['format']}")

# Load the parquet file
df_raw = pl.read_parquet(
    "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_fastqc_v1_31_0/multiqc_data/multiqc.parquet"
)

# Filter for general stats table data and convert to pandas
df_general_stats = df_raw.filter(pl.col("anchor") == "general_stats_table")
df_explore = df_general_stats.to_pandas()

# Filter to just the data rows (not metadata rows)
df_metrics = df_explore[df_explore["type"] == "plot_input_row"].copy()

# Pivot the data to get samples as rows and metrics as columns
df_pivot = df_metrics.pivot_table(
    index="sample", columns="metric", values="val_raw", aggfunc="first"
).reset_index()

# Create column mapping using metadata titles
column_mapping = {"sample": "Sample Name"}
for key, config in column_metadata.items():
    if key in df_pivot.columns and not config["hidden"]:
        # Use actual metadata title
        display_title = config["title"]
        # Add suffix to title if it exists
        if config["suffix"]:
            display_title += f" ({config['suffix'].strip()})"
        column_mapping[key] = display_title

df_multiqc_real = df_pivot.rename(columns=column_mapping)

# Convert total_sequences to millions with proper labeling
if "total_sequences" in df_pivot.columns:
    millions_col = f"{column_metadata['total_sequences']['title']} (M)"
    df_multiqc_real[millions_col] = (df_pivot["total_sequences"] / 1_000_000).round(2)
    # Remove the original Seqs column if it was renamed
    seqs_col = column_mapping.get("total_sequences", "total_sequences")
    if seqs_col in df_multiqc_real.columns and seqs_col != millions_col:
        df_multiqc_real = df_multiqc_real.drop(columns=[seqs_col])

# For columns with units in the title, the suffix is already included
# This is a workaround since Dash DataTable doesn't support suffix formatting

# Keep numeric data - formatting will be handled by FormatTemplate and metadata
# For percentage columns, convert to decimal (0-1 range) for percentage FormatTemplate
df_for_display = df_multiqc_real.copy()

# Identify percentage columns from metadata
percentage_columns = []
for orig_key, display_name in column_mapping.items():
    if orig_key in column_metadata and column_metadata[orig_key]["suffix"] == "%":
        percentage_columns.append(display_name)

for col in percentage_columns:
    if col in df_for_display.columns:
        # Convert percentage values to decimal for FormatTemplate.percentage
        df_for_display[col] = df_for_display[col] / 100

# Select only non-hidden columns
visible_columns = ["Sample Name"]
for key, config in column_metadata.items():
    if key in column_mapping and not config["hidden"]:
        visible_columns.append(column_mapping[key])

# Add the millions column if it exists
millions_col = f"{column_metadata.get('total_sequences', {}).get('title', 'Seqs')} (M)"
if millions_col in df_multiqc_real.columns:
    visible_columns.append(millions_col)

# Filter to available columns
available_columns = [col for col in visible_columns if col in df_multiqc_real.columns]
df_multiqc_real = df_multiqc_real[available_columns]  # Keep original for data bars
df_for_display = df_for_display[available_columns]  # Use for display with converted percentages

print(f"\nLoaded {len(df_multiqc_real)} samples from parquet")
print(f"Displaying columns: {available_columns}")

# =============================================================================
# 2. DATA BARS FUNCTION
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
        cmap = plt.cm.get_cmap(cmap_name)  # Fallback for older versions

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
            if column == "Dups (%)" and i <= 3:  # Debug first few values
                print(
                    f"DEBUG BAR: {column} max_bound={max_bound}, col_min={col_min}, col_max={col_max}, percentage={max_bound_percentage}"
                )
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

    # Get metadata for each metric
    metric_info = []
    for metric in metrics:
        # Get original metric name from metadata
        original_metric = None
        for key in [
            "percent_duplicates",
            "percent_gc",
            "median_sequence_length",
            "total_sequences",
            "percent_fails",
        ]:
            if metadata_loader.get_column_title(key) in metric or key in metric.lower().replace(
                " ", "_"
            ):
                original_metric = key
                break

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

            # Convert percentage display values (0-1) back to 0-100 for visualization
            if metric_data["is_percentage"] and value <= 1.0:
                value = value * 100

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

        # Configure Y-axis with metric label (Module name on two lines)
        # Create label with module name and metric on separate lines
        label_text = f"FastQC<br>{metric}"

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


# =============================================================================
# 4. CREATE DASH TABLE WITH DATA BARS
# =============================================================================

app = Dash(__name__)

# Generate column configurations from metadata
column_colormaps = {}
column_scales = {}
column_formats = {}

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

print("\n=== Column Configuration from Metadata ===")
column_reverse_flags = {}  # Store reverse flags for each column

for orig_key, config in column_metadata.items():
    if orig_key in column_mapping and not config["hidden"]:
        display_name = column_mapping[orig_key]

        # Set colormap and reverse flag
        scale_name = config["scale"]
        if scale_name in scale_mapping:
            colormap, reverse_flag = scale_mapping[scale_name]
            column_colormaps[display_name] = colormap
            column_reverse_flags[display_name] = reverse_flag
        else:
            # Use original scale name as fallback
            column_colormaps[display_name] = scale_name
            column_reverse_flags[display_name] = False

        # Set fixed scale for percentages - use 0-1 for data bars to match display values
        if config["suffix"] == "%":
            column_scales[display_name] = (0, 1)  # 0-1 for display data bars
        elif config["min"] is not None and config["max"] is not None:
            column_scales[display_name] = (config["min"], config["max"])
        else:
            column_scales[display_name] = None  # Use data range

        # Store format information
        column_formats[display_name] = {"format": config["format"], "suffix": config["suffix"]}

        print(
            f"{display_name}: {colormap} | Scale: {column_scales[display_name]} | Format: {config['format']}"
        )

# Add the millions column configuration
millions_col = f"{column_metadata.get('total_sequences', {}).get('title', 'Seqs')} (M)"
if millions_col in available_columns:
    column_colormaps[millions_col] = "Blues"
    column_reverse_flags[millions_col] = False  # No reverse for Blues
    column_scales[millions_col] = None  # Use data range
    column_formats[millions_col] = {"format": "{:,.2f}", "suffix": "M"}

# Generate colormap-based data bar styles for each column using original numeric data (0-100 scale)
# But the styles need to target the display data values (0-1 scale for percentages)
all_styles = []


# Create a mapping function to convert display values back to original scale for color calculation
def get_color_calculation_value(column_name, display_df, original_df):
    """Convert display values back to original scale for color calculations"""
    if column_name in ["Dups (%)", "GC (%)", "Failed (%)"]:
        # Display is 0-1, original is 0-100, so multiply by 100 for color calculation
        return original_df[column_name]  # Use original 0-100 values
    else:
        return display_df[column_name]  # Use display values as-is


# Generate styles using original data for calculations but targeting display column names
for column in df_for_display.columns:
    if column != "Sample Name":
        cmap_name = column_colormaps.get(column, "Blues")  # Default to Blues
        fixed_scale = column_scales.get(column, None)

        # For percentages, use display data (0-1) for both calculation and targeting
        if column in percentage_columns:
            color_data_df = df_for_display  # Use 0-1 scale for both calculation and targeting
        else:
            color_data_df = df_for_display  # Use display scale

        # Get reverse flag for this column
        reverse_colors = column_reverse_flags.get(column, False)

        all_styles.extend(
            multiqc_data_bars_colormap(
                color_data_df,
                column,
                cmap_name,
                opacity=0.3,
                fixed_scale=fixed_scale,
                reverse_colors=reverse_colors,
            )
        )


# Define column format function based on metadata
def get_column_format(column_name):
    """Get appropriate Dash DataTable format for a column based on metadata."""
    if column_name == "Sample Name":
        return None

    # Debug output
    print(f"DEBUG: Formatting column '{column_name}'")

    # Check if it's a percentage column (converted to 0-1 range)
    if column_name in percentage_columns:
        print(f"DEBUG: {column_name} is percentage column")
        # Always use 1 decimal place for percentage columns to match MultiQC
        return dash_table.FormatTemplate.percentage(1)  # 1 decimal place (e.g., 45.2%)

    # Handle millions column with M suffix BEFORE checking column_formats
    if "(M)" in column_name:
        print(f"DEBUG: {column_name} matches M suffix pattern")
        return Format(symbol=Symbol.yes, symbol_suffix=" M").precision(2).scheme("f")

    # Handle bp columns BEFORE checking column_formats
    if "bp" in column_name:
        print(f"DEBUG: {column_name} matches bp suffix pattern")
        return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(0).scheme("f")

    # Check for specific format from metadata and add suffixes
    if column_name in column_formats:
        print(f"DEBUG: {column_name} found in column_formats")
        format_info = column_formats[column_name]
        format_str = format_info["format"]
        suffix = format_info.get("suffix", "")

        # Use Format with symbol_suffix for bp suffix, no scientific notation
        if "bp" in suffix:
            if ".0f" in format_str:
                return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(0).scheme("f")
            elif ".1f" in format_str:
                return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(1).scheme("f")

        # Regular numeric formats without suffix
        if ".0f" in format_str:
            return {"specifier": ".0f"}
        elif ".1f" in format_str:
            return {"specifier": ".1f"}
        elif ".2f" in format_str:
            return {"specifier": ".2f"}
    else:
        print(f"DEBUG: {column_name} NOT found in column_formats")

    # Default length columns
    if "len" in column_name.lower():
        return {"specifier": ".0f"}

    return {"specifier": ".1f"}  # Default numeric format


# Create violin plot
violin_fig = create_multiqc_violin_plot(df_for_display, metadata_loader)

# Create the app layout with toggle
app.layout = dmc.MantineProvider(
    html.Div([
        html.Div(
            [
                html.H2(
                    "General Statistics",
                    style={
                        "fontSize": "20px",
                        "fontWeight": "bold",
                        "marginBottom": 15,
                        "color": "#333",
                        "fontFamily": "Arial, Helvetica, sans-serif",
                        "display": "inline-block",
                    },
                ),
                # DMC Segmented Control for toggle
                dmc.SegmentedControl(
                    id="view-toggle",
                    value="table",
                    data=[
                        {"label": "📊 Table", "value": "table"},
                        {"label": "🎻 Violin", "value": "violin"},
                    ],
                    style={"float": "right", "marginTop": 5},
                ),
            ],
            style={"marginBottom": 20, "overflow": "hidden"},
        ),  # Clear float
        # Table view container
        html.Div(
            [
                dash_table.DataTable(
                        id="multiqc-table",
                        data=df_for_display.to_dict("records"),
                        columns=[
                            {
                                "name": col,
                                "id": col,
                                "type": "numeric" if col != "Sample Name" else "text",
                                "format": get_column_format(col),
                            }
                            for col in df_for_display.columns
                        ],
                        # Apply data bar styles
                        style_data_conditional=all_styles
                        + [
                            {
                                "if": {"state": "active"},
                                "backgroundColor": "rgba(0, 116, 217, 0.05)",
                                "border": "1px solid rgba(0, 116, 217, 0.3)",
                            }
                        ],
                        # Cell styling - clean MultiQC style
                        style_cell={
                            "textAlign": "left",
                            "padding": "6px 8px",
                            "fontFamily": "Arial, Helvetica, sans-serif",
                            "fontSize": "12px",
                            "border": "none",  # No cell borders
                            "borderBottom": "1px solid #e8e8e8",  # Only bottom border for rows
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
                        style_data={
                            "border": "none",
                            "borderBottom": "1px solid #f0f0f0",
                        },
                        style_table={
                            "border": "none",
                            "borderTop": "1px solid #ddd",
                            "borderBottom": "1px solid #ddd",
                            "overflow": "hidden",
                        },
                        # Enable sorting only (no filtering)
                        sort_action="native",
                        filter_action="none",  # Disable filters
                        page_size=20,
                    )
                ],
                id="table-container",
                style={"display": "block"},
            ),  # Show table by default
        # Violin plot container
        html.Div(
            [dcc.Graph(figure=violin_fig, config={"displayModeBar": False})],
            id="violin-container",
            style={"display": "none"},
        ),  # Hide violin by default
    ],
    style={
        "margin": "10px",
        "padding": "10px",
        "backgroundColor": "#ffffff",
        "fontFamily": "Arial, Helvetica, sans-serif",
    })
)

# =============================================================================
# 4. ADD CALLBACK FOR VIEW TOGGLE
# =============================================================================


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


# =============================================================================
# 5. RUN THE APP
# =============================================================================

if __name__ == "__main__":
    print("🚀 Starting MultiQC Table Dashboard on http://localhost:8052")
    app.run(debug=True, port=8052)
