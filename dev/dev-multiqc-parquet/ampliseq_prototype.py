#!/usr/bin/env python
"""
MultiQC Ampliseq Prototype - Self-contained MultiQC general statistics dashboard.

Forked from multiqc_table_clean.py, adapted to extract metadata directly from
the parquet's column_meta field instead of requiring external JSON + AST-parsed
metadata files.

Features:
- Colorized DataTable with 100-bin gradient data bars
- Violin plot with scatter overlay
- Segmented control toggle (Table / Violin)
- Metadata-driven column formatting, scaling, and coloring

Usage:
    python ampliseq_prototype.py                          # default ampliseq reference
    python ampliseq_prototype.py --parquet-path /path/to/multiqc.parquet
    python ampliseq_prototype.py --show-hidden            # include hidden columns
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import dash_mantine_components as dmc
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import polars as pl
from dash import Dash, Input, Output, dash_table, dcc
from dash.dash_table.Format import Format, Symbol
from matplotlib import colormaps

# Default parquet path: ampliseq reference dataset
DEFAULT_PARQUET_PATH = str(
    Path(__file__).resolve().parent.parent.parent
    / "depictio"
    / "projects"
    / "reference"
    / "ampliseq"
    / "run_1"
    / "multiqc_data"
    / "multiqc.parquet"
)


def get_colormap(name):
    return colormaps[name]


def sanitize_column_name(name):
    """Sanitize column names for DataTable JavaScript compatibility"""
    sanitized = re.sub(r"[{}\'\"]", "", name)
    sanitized = re.sub(r"f\'[^\']*\'", "Config_Value", sanitized)
    sanitized = re.sub(r"config\.[a-zA-Z_]+", "Config_Value", sanitized)
    sanitized = re.sub(r"[^a-zA-Z0-9\s\(\)_\-\.\%]", "_", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


# =============================================================================
# METADATA EXTRACTION FROM PARQUET
# =============================================================================


def extract_metadata_from_parquet(
    df_general_stats: pl.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Extract per-metric metadata from parquet column_meta JSON.

    Parses the column_meta JSON field from each unique metric in the
    general_stats_table data and groups by section_key to produce a structure
    compatible with MultiQCMetadataLoader.get_all_column_mappings():

        {tool_name: {metric_key: {title, scale, suffix, min, max, hidden, ...}}}

    Args:
        df_general_stats: Polars DataFrame filtered to general_stats_table anchor,
            type == plot_input_row.

    Returns:
        Nested dict keyed by section_key (tool name), then metric key.
    """
    mappings: dict[str, dict[str, Any]] = {}

    # Get one row per metric to extract column_meta
    unique_metrics = df_general_stats.unique(subset=["metric"], keep="first")

    for row in unique_metrics.iter_rows(named=True):
        metric = row["metric"]
        section_key = row["section_key"]
        column_meta_str = row.get("column_meta")

        if not column_meta_str:
            # Provide sensible defaults when column_meta is missing
            if section_key not in mappings:
                mappings[section_key] = {}
            mappings[section_key][metric] = {
                "title": metric.replace("_", " ").title(),
                "description": "",
                "scale": "Blues",
                "format": "{:,.1f}",
                "suffix": "",
                "min": None,
                "max": None,
                "hidden": False,
            }
            continue

        try:
            meta = (
                json.loads(column_meta_str) if isinstance(column_meta_str, str) else column_meta_str
            )
        except (json.JSONDecodeError, TypeError):
            meta = {}

        if section_key not in mappings:
            mappings[section_key] = {}

        mappings[section_key][metric] = {
            "title": meta.get("title", metric.replace("_", " ").title()),
            "description": meta.get("description", ""),
            "scale": meta.get("scale", "Blues"),
            "format": meta.get("format", "{:,.1f}"),
            "suffix": meta.get("suffix", ""),
            "min": meta.get("min", None),
            "max": meta.get("max", None),
            "hidden": meta.get("hidden", False),
        }

    return mappings


# =============================================================================
# PAIRED-END SAMPLE HARMONIZATION
# =============================================================================


def detect_sample_groups(samples: list[str], df_metrics: pd.DataFrame) -> dict | None:
    """Detect paired-end sample groups using a 3-way match heuristic.

    For each sample, checks if {sample}_1 and {sample}_2 also exist.
    Only considers it paired-end when all three variants are present.

    Returns None if not paired-end, otherwise a dict with:
        - base_to_r1: mapping of base sample name to R1 name
        - base_to_r2: mapping of base sample name to R2 name
        - sample_level_metrics: metrics that only appear on bare samples
        - read_level_metrics: metrics that only appear on _1/_2 samples
    """
    sample_set = set(samples)
    base_samples = []
    for s in samples:
        if not s.endswith("_1") and not s.endswith("_2"):
            if f"{s}_1" in sample_set and f"{s}_2" in sample_set:
                base_samples.append(s)

    if not base_samples:
        return None

    # Classify metrics as sample-level or read-level
    sample_level_metrics = []
    read_level_metrics = []

    for metric in df_metrics["metric"].unique():
        metric_samples = df_metrics[df_metrics["metric"] == metric]["sample"].tolist()
        has_bare = any(s in base_samples for s in metric_samples)
        has_suffixed = any(s.endswith("_1") or s.endswith("_2") for s in metric_samples)

        if has_bare and not has_suffixed:
            sample_level_metrics.append(metric)
        elif has_suffixed and not has_bare:
            read_level_metrics.append(metric)
        else:
            # Metrics present on both — treat as read-level
            read_level_metrics.append(metric)

    return {
        "base_to_r1": {s: f"{s}_1" for s in base_samples},
        "base_to_r2": {s: f"{s}_2" for s in base_samples},
        "base_samples": sorted(base_samples),
        "sample_level_metrics": sample_level_metrics,
        "read_level_metrics": read_level_metrics,
    }


def harmonize_samples(df_metrics: pd.DataFrame, groups: dict, read_mode: str) -> pd.DataFrame:
    """Build a pivoted DataFrame with harmonized samples based on read_mode.

    Args:
        df_metrics: pandas DataFrame with columns [sample, metric, val_mod, ...]
        groups: dict from detect_sample_groups()
        read_mode: one of "mean", "r1", "r2", "all"

    Returns:
        Pivoted DataFrame with sample as index and metrics as columns.
    """
    base_samples = groups["base_samples"]
    # Sort metric lists to match pivot_table's alphabetical column ordering
    sample_level_metrics = sorted(groups["sample_level_metrics"])
    read_level_metrics = sorted(groups["read_level_metrics"])
    canonical_order = ["sample"] + sample_level_metrics + read_level_metrics

    if read_mode == "all":
        df_pivot = df_metrics.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()
        # Reorder columns to match harmonized modes: sample-level first, then read-level
        ordered = [c for c in canonical_order if c in df_pivot.columns]
        remaining = [c for c in df_pivot.columns if c not in ordered]
        return df_pivot[ordered + remaining]

    base_to_r1 = groups["base_to_r1"]
    base_to_r2 = groups["base_to_r2"]

    # Pivot sample-level metrics (bare sample names)
    df_sample = df_metrics[
        df_metrics["metric"].isin(sample_level_metrics) & df_metrics["sample"].isin(base_samples)
    ]
    if not df_sample.empty:
        df_sample_pivot = df_sample.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()
    else:
        df_sample_pivot = pd.DataFrame({"sample": base_samples})

    # Pivot read-level metrics
    r1_names = list(base_to_r1.values())
    r2_names = list(base_to_r2.values())
    r1_to_base = {v: k for k, v in base_to_r1.items()}
    r2_to_base = {v: k for k, v in base_to_r2.items()}

    df_read = df_metrics[df_metrics["metric"].isin(read_level_metrics)]

    if read_mode == "mean":
        # Pivot R1 and R2 separately, then average
        df_r1 = df_read[df_read["sample"].isin(r1_names)].copy()
        df_r1["sample"] = df_r1["sample"].map(r1_to_base)
        df_r1_pivot = df_r1.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        )

        df_r2 = df_read[df_read["sample"].isin(r2_names)].copy()
        df_r2["sample"] = df_r2["sample"].map(r2_to_base)
        df_r2_pivot = df_r2.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        )

        df_read_pivot = ((df_r1_pivot + df_r2_pivot) / 2).reset_index()

    elif read_mode == "r1":
        df_r1 = df_read[df_read["sample"].isin(r1_names)].copy()
        df_r1["sample"] = df_r1["sample"].map(r1_to_base)
        df_read_pivot = df_r1.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()

    elif read_mode == "r2":
        df_r2 = df_read[df_read["sample"].isin(r2_names)].copy()
        df_r2["sample"] = df_r2["sample"].map(r2_to_base)
        df_read_pivot = df_r2.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()

    else:
        msg = f"Unknown read_mode: {read_mode}"
        raise ValueError(msg)

    # Merge sample-level and read-level pivots
    if not df_sample.empty and not df_read_pivot.empty:
        df_pivot = df_sample_pivot.merge(df_read_pivot, on="sample", how="outer")
    elif not df_read_pivot.empty:
        df_pivot = df_read_pivot
    else:
        df_pivot = df_sample_pivot

    # Enforce canonical column order (same as "all" mode)
    ordered = [c for c in canonical_order if c in df_pivot.columns]
    remaining = [c for c in df_pivot.columns if c not in ordered]
    return df_pivot[ordered + remaining]


# =============================================================================
# DATA PROCESSING
# =============================================================================


def process_multiqc_data(parquet_path, show_hidden=False, read_mode="mean"):
    """Process MultiQC parquet data and return formatted DataFrames.

    Uses val_mod (pre-transformed values) instead of val_raw + manual modify,
    and extracts metadata from the parquet's column_meta field.
    """
    # Load the parquet file
    df_raw = pl.read_parquet(parquet_path)

    # Filter for general stats table data
    df_general_stats = df_raw.filter(pl.col("anchor") == "general_stats_table")

    # Filter to data rows only
    df_metrics = df_general_stats.filter(pl.col("type") == "plot_input_row")

    if len(df_metrics) == 0:
        msg = f"No general_stats_table data found in {parquet_path}"
        raise ValueError(msg)

    # Extract metadata from column_meta
    column_metadata = extract_metadata_from_parquet(df_metrics)

    # Filter out hidden columns unless --show-hidden is set
    if not show_hidden:
        hidden_metrics = set()
        for _tool, tool_meta in column_metadata.items():
            for metric_key, config in tool_meta.items():
                if config.get("hidden", False):
                    hidden_metrics.add(metric_key)
        if hidden_metrics:
            df_metrics = df_metrics.filter(~pl.col("metric").is_in(list(hidden_metrics)))

    # Convert to pandas for pivoting
    df_explore = df_metrics.to_pandas()

    # Detect paired-end sample groups
    samples = df_explore["sample"].unique().tolist()
    sample_groups = detect_sample_groups(samples, df_explore)

    # Pivot based on read_mode (harmonized or flat)
    if sample_groups:
        df_pivot = harmonize_samples(df_explore, sample_groups, read_mode)
    else:
        df_pivot = df_explore.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()

    tools = df_explore["section_key"].unique()

    # Create unified column mapping using extracted metadata
    column_mapping = {}
    percentage_columns = []

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
                if config["suffix"] and not display_name.endswith(f" ({config['suffix'].strip()})"):
                    suffix = config["suffix"].strip()
                    display_name = f"{display_name} ({suffix})"
                break

        # Fallback for columns not in metadata
        if display_name is None:
            display_name = col.replace("_", " ").title()
            if "pct_" in col or "rate" in col.lower() or "content" in col.lower():
                if not display_name.endswith(" (%)"):
                    display_name = display_name.replace("Pct ", "") + " (%)"

        column_mapping[col] = display_name

        # Track percentage columns based on metadata suffix
        if config and config["suffix"].strip() == "%":
            percentage_columns.append(display_name)
        elif display_name.endswith(" (%)"):
            percentage_columns.append(display_name)

    # Apply column mapping
    df_multiqc_real = df_pivot.rename(columns=column_mapping)

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

    # Prepare display DataFrame
    df_for_display = df_multiqc_real.copy()

    return (
        df_multiqc_real,
        df_for_display,
        internal_to_display,
        tools,
        column_metadata,
        percentage_columns,
        sample_groups,
    )


# =============================================================================
# DATA BARS FUNCTION
# =============================================================================


def multiqc_data_bars_colormap(
    df, column, cmap_name="RdYlGn", opacity=0.4, fixed_scale=None, reverse_colors=False
):
    """Create data bars with matplotlib colormap.

    Args:
        fixed_scale: tuple of (min, max) to use instead of data min/max
        reverse_colors: If True, high values get low colormap values
    """
    n_bins = 100
    bounds = [i * (1.0 / n_bins) for i in range(n_bins + 1)]

    col_data = pd.to_numeric(df[column], errors="coerce")

    if fixed_scale:
        col_min, col_max = fixed_scale
    else:
        col_max = col_data.max()
        col_min = col_data.min()

    if pd.isna(col_max) or pd.isna(col_min):
        return []

    ranges = [((col_max - col_min) * i) + col_min for i in bounds]

    # Escape column name for filter query
    col_id = column.replace("(", "\\(").replace(")", "\\)").replace("%", "\\%")

    try:
        cmap = plt.colormaps[cmap_name]
    except KeyError:
        cmap = get_colormap(cmap_name)

    styles = []
    for i in range(1, len(bounds)):
        min_bound = ranges[i - 1]
        max_bound = ranges[i]
        if fixed_scale:
            max_bound_percentage = ((max_bound - col_min) / (col_max - col_min)) * 100
        else:
            max_bound_percentage = bounds[i] * 100

        mid_value = (min_bound + max_bound) / 2
        norm_value = (mid_value - col_min) / (col_max - col_min) if col_max != col_min else 0.5

        if reverse_colors:
            norm_value = 1.0 - norm_value

        scaled_norm = norm_value

        rgba = cmap(scaled_norm)
        r, g, b, _ = rgba
        r = r * opacity + (1 - opacity) * 1.0
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
# VIOLIN PLOT FUNCTION
# =============================================================================


def create_multiqc_violin_plot(
    df_general_stats, reformatted_column_metadata, display_to_original_mapping=None
):
    """Create MultiQC-style violin plot from general stats DataFrame.

    Args:
        df_general_stats: DataFrame with Sample Name + metric columns
        reformatted_column_metadata: dict mapping display column names to tool names
        display_to_original_mapping: dict mapping display names to original column names
    """
    VIOLIN_HEIGHT = 70
    EXTRA_HEIGHT = 63

    metrics = [col for col in df_general_stats.columns if col != "Sample Name"]

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

    metric_info = []
    for metric in metrics:
        original_metric = None
        is_percentage = "percent" in (original_metric or metric).lower() or "%" in metric

        metric_info.append(
            {
                "display_name": metric,
                "original_name": original_metric,
                "is_percentage": is_percentage,
            }
        )

    num_samples = len(df_general_stats)

    layout = go.Layout(
        title={
            "text": f"General Statistics<br><span style='font-size: 12px; color: #666;'>{num_samples} samples</span>",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 16, "color": "#333"},
        },
        showlegend=False,
        template="plotly_white",
        margin=dict(pad=0, b=40, t=70, l=120, r=20),
        grid={
            "rows": len(metrics),
            "columns": 1,
            "roworder": "top to bottom",
            "pattern": "independent",
            "ygap": 0.4,
            "subplots": [[(f"x{i + 1}y{i + 1}" if i > 0 else "xy")] for i in range(len(metrics))],
        },
        height=VIOLIN_HEIGHT * len(metrics) + EXTRA_HEIGHT,
        xaxis={
            "automargin": False,
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
        },
        yaxis={
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
        },
        violingap=0,
    )

    fig = go.Figure(layout=layout)

    for metric_idx, metric_data in enumerate(metric_info):
        metric = metric_data["display_name"]

        values = []
        samples = []
        for _, row in df_general_stats.iterrows():
            sample_name = row["Sample Name"]
            value = row[metric]
            values.append(value)
            samples.append(sample_name)

        axis_key = "" if metric_idx == 0 else str(metric_idx + 1)

        x_axis_config = {
            "automargin": False,
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
            "title": "",
            "hoverformat": ".2f",
        }

        if metric_data["is_percentage"]:
            x_axis_config["range"] = [0, 100]
            x_axis_config["ticksuffix"] = "%"
        else:
            min_val = min(0, min(values))
            max_val = max(values)
            padding = (max_val - min_val) * 0.05 if max_val != min_val else 1
            x_axis_config["range"] = [min_val - padding, max_val + padding]

        layout[f"xaxis{metric_idx + 1}"] = x_axis_config

        # Get module name from metadata mapping
        module_name = "Unknown Tool"
        if metric in reformatted_column_metadata:
            module_name = reformatted_column_metadata[metric]
        elif display_to_original_mapping and metric in display_to_original_mapping:
            original_name = display_to_original_mapping[metric]
            module_name = reformatted_column_metadata.get(original_name, "Unknown Tool")

        if module_name != "Unknown Tool":
            module_name = module_name.replace("_", " ").title()

        label_text = f"{metric}"

        layout[f"yaxis{metric_idx + 1}"] = {
            "automargin": True,
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
            "tickmode": "array",
            "tickvals": [metric_idx],
            "ticktext": [label_text],
            "range": [metric_idx - 0.4, metric_idx + 0.4],
        }

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
                box={"visible": True},
                meanline={"visible": True},
                fillcolor="#b5b5b5",
                line={"width": 2, "color": "#b5b5b5"},
                opacity=0.5,
                points=False,
                hoveron="points",
                showlegend=False,
            )
        )

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
                    "color": "#0b79e6",
                },
                showlegend=False,
                hovertemplate="<b>%{text}</b><br>%{x:.2f}<extra></extra>",
                hoverlabel={"bgcolor": "white"},
            )
        )

    fig.update_layout(layout)
    return fig


# =============================================================================
# STYLE GENERATION
# =============================================================================


def resolve_scale_name(scale_name):
    """Resolve MultiQC scale name to matplotlib colormap name and reverse flag.

    Handles known scales and falls back to stripping '-rev' suffix and
    appending '_r' for reversed colormaps.
    """
    scale_mapping = {
        "RdYlGn-rev": ("RdYlGn_r", False),
        "RdYlGn": ("RdYlGn", False),
        "RdYlBu-rev": ("RdYlBu_r", False),
        "RdYlBu": ("RdYlBu", False),
        "PuRd": ("PuRd", False),
        "Reds": ("Reds", False),
        "Blues": ("Blues", False),
        "Greens": ("Greens", False),
        "Oranges": ("Oranges", False),
    }

    if scale_name in scale_mapping:
        return scale_mapping[scale_name]

    # Fallback: strip -rev suffix and append _r
    if scale_name.endswith("-rev"):
        base = scale_name[:-4]
        return (f"{base}_r", False)

    return (scale_name, False)


def generate_data_bar_styles(
    df_for_display, tools, column_metadata, internal_to_display, percentage_columns
):
    """Generate colormap-based data bar styles for columns using metadata."""
    column_formats = {}
    all_styles = []

    for internal_col in df_for_display.columns:
        if internal_col == "Sample Name":
            continue

        display_name = internal_to_display.get(internal_col, internal_col)

        # Find metadata for this column
        config = None
        for tool in tools:
            if tool in column_metadata:
                for orig_key, meta_config in column_metadata[tool].items():
                    if orig_key in display_name or display_name.startswith(
                        meta_config.get("title", "")
                    ):
                        config = meta_config
                        break
            if config:
                break

        if config is None:
            config = {
                "scale": "Blues",
                "format": "{:,.1f}",
                "suffix": "",
                "min": None,
                "max": None,
            }

        scale_name = config.get("scale", "Blues")
        colormap, reverse_flag = resolve_scale_name(scale_name)

        fixed_scale = None
        if display_name in percentage_columns:
            min_val = config.get("min")
            max_val = config.get("max")
            if min_val is not None and max_val is not None:
                fixed_scale = (min_val, max_val)
        elif config.get("min") is not None and config.get("max") is not None:
            fixed_scale = (config["min"], config["max"])

        column_formats[display_name] = {
            "format": config.get("format", "{:,.1f}"),
            "suffix": config.get("suffix", ""),
        }

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


# =============================================================================
# COLUMN FORMAT
# =============================================================================


def get_column_format(column_name, percentage_columns, column_formats):
    """Get appropriate Dash DataTable format for a column based on metadata."""
    if column_name == "Sample Name":
        return None

    if column_name in percentage_columns:
        return Format(symbol=Symbol.yes, symbol_suffix="%").precision(1).scheme("f")

    if "(M)" in column_name:
        return Format(symbol=Symbol.yes, symbol_suffix=" M").precision(2).scheme("f")

    if "bp" in column_name:
        return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(0).scheme("f")

    if column_name in column_formats:
        format_info = column_formats[column_name]
        format_str = format_info["format"] or "{:,.1f}"
        suffix = format_info.get("suffix", "")

        if suffix and suffix.strip() == "M":
            return Format(symbol=Symbol.yes, symbol_suffix=" M").precision(2).scheme("f")

        if "bp" in suffix:
            if ".0f" in format_str:
                return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(0).scheme("f")
            elif ".1f" in format_str:
                return Format(symbol=Symbol.yes, symbol_suffix=" bp").precision(1).scheme("f")

        if ".0f" in format_str:
            return Format(precision=0, scheme="f", group=True)
        elif ".1f" in format_str:
            return Format(precision=1, scheme="f", group=True)
        elif ".2f" in format_str:
            return Format(precision=2, scheme="f", group=True)

    if "len" in column_name.lower():
        return Format(precision=0, scheme="f", group=True)

    return Format(precision=1, scheme="f", group=True)


# =============================================================================
# COMPONENT CREATION FUNCTIONS
# =============================================================================


def create_multiqc_table_component(
    df_data, all_styles, column_display_mapping=None, percentage_columns=None, column_formats=None
):
    """Create MultiQC table component with data bars."""
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
                "name": column_display_mapping.get(col, col),
                "id": col,
                "type": "numeric" if col != "Sample Name" else "text",
                "format": get_column_format(
                    column_display_mapping.get(col, col), percentage_columns, column_formats
                ),
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
                "fontWeight": "bold",
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
            "textAlign": "left",
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


def create_multiqc_violin_component(
    df_data, reformatted_column_metadata, display_to_original_mapping=None
):
    """Create MultiQC violin plot component."""
    violin_fig = create_multiqc_violin_plot(
        df_data, reformatted_column_metadata, display_to_original_mapping
    )
    return dcc.Graph(figure=violin_fig, config={"displayModeBar": False})


def create_multiqc_dashboard(
    df_display_data,
    df_numeric_data,
    reformatted_column_metadata,
    all_styles,
    internal_to_display,
    is_paired_end=False,
):
    """Create complete MultiQC dashboard with toggle and optional read selector."""
    table_component = create_multiqc_table_component(
        df_display_data, all_styles, internal_to_display
    )

    display_to_original_mapping = (
        {v: k for k, v in internal_to_display.items()} if internal_to_display else None
    )

    violin_component = create_multiqc_violin_component(
        df_numeric_data, reformatted_column_metadata, display_to_original_mapping
    )

    # Build control bar
    controls = [dmc.Title("General Statistics", order=2)]

    if is_paired_end:
        controls.append(
            dmc.SegmentedControl(
                id="read-toggle",
                value="mean",
                data=[
                    {"label": "Mean", "value": "mean"},
                    {"label": "R1", "value": "r1"},
                    {"label": "R2", "value": "r2"},
                    {"label": "All reads", "value": "all"},
                ],
                size="sm",
            )
        )

    controls.append(
        dmc.SegmentedControl(
            id="view-toggle",
            value="table",
            data=[
                {"label": "Table", "value": "table"},
                {"label": "Violin", "value": "violin"},
            ],
        )
    )

    return dmc.Stack(
        [
            dmc.Group(controls, justify="space-between", align="center"),
            dmc.Box(table_component, id="table-container"),
            dmc.Box(violin_component, id="violin-container", style={"display": "none"}),
        ],
        gap="md",
    )


# =============================================================================
# APP CREATION
# =============================================================================


def _build_mode_data(parquet_path, show_hidden, read_mode):
    """Build pre-computed table/violin data for a single read mode.

    Returns a dict with all the data needed to render that mode's table and violin.
    """
    result = process_multiqc_data(parquet_path, show_hidden=show_hidden, read_mode=read_mode)
    (
        df_multiqc_real,
        df_for_display,
        internal_to_display,
        tools,
        column_metadata,
        percentage_columns,
        _,
    ) = result

    all_styles, column_formats = generate_data_bar_styles(
        df_for_display, tools, column_metadata, internal_to_display, percentage_columns
    )

    original_to_tool_mapping = {col: tool for tool, cols in column_metadata.items() for col in cols}
    display_to_original = (
        {v: k for k, v in internal_to_display.items()} if internal_to_display else None
    )

    # Build column defs for the DataTable
    columns = [
        {
            "name": internal_to_display.get(col, col),
            "id": col,
            "type": "numeric" if col != "Sample Name" else "text",
            "format": get_column_format(
                internal_to_display.get(col, col), percentage_columns, column_formats
            ),
        }
        for col in df_for_display.columns
    ]

    # Build violin figure
    violin_fig = create_multiqc_violin_plot(
        df_for_display, original_to_tool_mapping, display_to_original
    )

    return {
        "table_data": df_for_display.to_dict("records"),
        "table_columns": columns,
        "table_styles": all_styles
        + [
            {
                "if": {"state": "active"},
                "backgroundColor": "rgba(0, 116, 217, 0.05)",
                "border": "1px solid rgba(0, 116, 217, 0.3)",
            }
        ],
        "violin_figure": violin_fig,
    }


def create_app(parquet_path, port=8053, show_hidden=False):
    """Create and configure the Dash app with MultiQC data."""
    # Process the default (mean) mode to detect paired-end
    result = process_multiqc_data(parquet_path, show_hidden=show_hidden, read_mode="mean")
    (
        _,
        df_for_display,
        internal_to_display,
        tools,
        column_metadata,
        percentage_columns,
        sample_groups,
    ) = result
    is_paired_end = sample_groups is not None

    # Pre-compute all read modes if paired-end, otherwise just one
    read_modes = ["mean", "r1", "r2", "all"] if is_paired_end else ["mean"]
    mode_data = {mode: _build_mode_data(parquet_path, show_hidden, mode) for mode in read_modes}

    app = Dash(__name__)

    # Map original column names to tool names for violin
    original_to_tool_mapping = {col: tool for tool, cols in column_metadata.items() for col in cols}

    all_styles, column_formats = generate_data_bar_styles(
        df_for_display, tools, column_metadata, internal_to_display, percentage_columns
    )

    dashboard = create_multiqc_dashboard(
        df_for_display,
        df_for_display,
        original_to_tool_mapping,
        all_styles,
        internal_to_display,
        is_paired_end=is_paired_end,
    )

    app.layout = dmc.MantineProvider(dmc.Container(dashboard, p="md"))

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

    if is_paired_end:

        @app.callback(
            [
                Output("multiqc-table", "data"),
                Output("multiqc-table", "style_data_conditional"),
                Output("violin-container", "children"),
            ],
            [Input("read-toggle", "value")],
        )
        def switch_read_mode(read_mode):
            """Switch table and violin data based on read mode selection."""
            data = mode_data[read_mode]
            return (
                data["table_data"],
                data["table_styles"],
                dcc.Graph(figure=data["violin_figure"], config={"displayModeBar": False}),
            )

    return app


# =============================================================================
# STANDALONE COMPONENT FUNCTIONS (NO DASH APP REQUIRED)
# =============================================================================


def get_multiqc_table_component(df_data, column_metadata, internal_to_display=None):
    """Get standalone MultiQC table component (no app required)."""
    if internal_to_display is None:
        internal_to_display = {}

    all_styles = []
    percentage_columns = []

    for column in df_data.columns:
        if column != "Sample Name":
            cmap_name = "Blues"
            fixed_scale = None
            reverse_colors = False

            for tool_name, tool_metadata in column_metadata.items():
                for key, config in tool_metadata.items():
                    if key in column or config.get("title", "") in column:
                        if config["suffix"].strip() == "%":
                            fixed_scale = (0, 100)
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

    return create_multiqc_table_component(
        df_data, all_styles, internal_to_display, percentage_columns, {}
    )


def get_multiqc_violin_component(df_data, column_metadata):
    """Get standalone MultiQC violin plot component (no app required)."""
    original_to_tool_mapping = {col: tool for tool, cols in column_metadata.items() for col in cols}
    return create_multiqc_violin_component(df_data, original_to_tool_mapping)


def get_multiqc_dashboard_component(df_data, column_metadata):
    """Get complete MultiQC dashboard component with toggle (no app required)."""
    all_styles = []

    for column in df_data.columns:
        if column != "Sample Name":
            cmap_name = "Blues"
            fixed_scale = None
            reverse_colors = False

            for tool_name, tool_metadata in column_metadata.items():
                for key, config in tool_metadata.items():
                    if key in column or config.get("title", "") in column:
                        if config["suffix"].strip() == "%":
                            fixed_scale = (0, 100)
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

    internal_to_display = {col: col for col in df_data.columns}
    original_to_tool_mapping = {col: tool for tool, cols in column_metadata.items() for col in cols}

    return create_multiqc_dashboard(
        df_data, df_data, original_to_tool_mapping, all_styles, internal_to_display
    )


# =============================================================================
# CLI
# =============================================================================


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MultiQC Ampliseq Prototype - Self-contained general statistics dashboard"
    )
    parser.add_argument(
        "--parquet-path",
        default=DEFAULT_PARQUET_PATH,
        help=f"Path to MultiQC parquet file (default: ampliseq reference at {DEFAULT_PARQUET_PATH})",
    )
    parser.add_argument(
        "--port", type=int, default=8053, help="Port to run the dashboard on (default: 8053)"
    )
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    parser.add_argument(
        "--show-hidden", action="store_true", help="Show hidden columns (e.g. avg/median length)"
    )
    return parser.parse_args()


def main():
    """Main function to run the MultiQC dashboard."""
    args = parse_arguments()

    try:
        app = create_app(args.parquet_path, args.port, show_hidden=args.show_hidden)
        print(f"Starting MultiQC Ampliseq Dashboard on http://localhost:{args.port}")
        print(f"Parquet: {args.parquet_path}")
        print(f"Hidden columns: {'shown' if args.show_hidden else 'filtered out'}")
        app.run(debug=True, port=args.port)
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
