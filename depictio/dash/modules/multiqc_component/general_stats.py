"""General Statistics table and violin for MultiQC component.

Ported from dev/dev-multiqc-parquet/ampliseq_prototype.py.
Provides functions to:
- Read a MultiQC parquet file and extract general_stats_table data
- Build a colorized DataTable with data bars
- Build a violin plot with scatter overlay
- Pre-compute all read modes for paired-end toggle (Mean/R1/R2/All)
- Produce empty DOM placeholders for non-general-stats instances
"""

import json
import re
from typing import Any

import dash_mantine_components as dmc
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import polars as pl
from dash import dash_table, dcc, html
from dash.dash_table.Format import Format, Symbol
from matplotlib import colormaps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_colormap(name: str):
    return colormaps[name]


def _sanitize_column_name(name: str) -> str:
    """Sanitize column names for DataTable JavaScript compatibility."""
    sanitized = re.sub(r"[{}\'\"]", "", name)
    sanitized = re.sub(r"f\'[^\']*\'", "Config_Value", sanitized)
    sanitized = re.sub(r"config\.[a-zA-Z_]+", "Config_Value", sanitized)
    sanitized = re.sub(r"[^a-zA-Z0-9\s\(\)_\-\.\%]", "_", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def _extract_metadata_from_parquet(
    df_general_stats: pl.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Extract per-metric metadata from parquet column_meta JSON."""
    mappings: dict[str, dict[str, Any]] = {}
    unique_metrics = df_general_stats.unique(subset=["metric"], keep="first")

    for row in unique_metrics.iter_rows(named=True):
        metric = row["metric"]
        section_key = row["section_key"]
        column_meta_str = row.get("column_meta")

        if not column_meta_str:
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


# ---------------------------------------------------------------------------
# Paired-end harmonization
# ---------------------------------------------------------------------------


def _detect_sample_groups(samples: list[str], df_metrics: pd.DataFrame) -> dict | None:
    """Detect paired-end sample groups (base, _1, _2)."""
    sample_set = set(samples)
    base_samples = []
    for s in samples:
        if not s.endswith("_1") and not s.endswith("_2"):
            if f"{s}_1" in sample_set and f"{s}_2" in sample_set:
                base_samples.append(s)

    if not base_samples:
        return None

    sample_level_metrics: list[str] = []
    read_level_metrics: list[str] = []

    for metric in df_metrics["metric"].unique():
        metric_samples = df_metrics[df_metrics["metric"] == metric]["sample"].tolist()
        has_bare = any(s in base_samples for s in metric_samples)
        has_suffixed = any(s.endswith("_1") or s.endswith("_2") for s in metric_samples)

        if has_bare and not has_suffixed:
            sample_level_metrics.append(metric)
        else:
            read_level_metrics.append(metric)

    return {
        "base_to_r1": {s: f"{s}_1" for s in base_samples},
        "base_to_r2": {s: f"{s}_2" for s in base_samples},
        "base_samples": sorted(base_samples),
        "sample_level_metrics": sample_level_metrics,
        "read_level_metrics": read_level_metrics,
    }


def _harmonize_samples(df_metrics: pd.DataFrame, groups: dict, read_mode: str) -> pd.DataFrame:
    """Build a pivoted DataFrame with harmonized samples."""
    base_samples = groups["base_samples"]
    sample_level_metrics = sorted(groups["sample_level_metrics"])
    read_level_metrics = sorted(groups["read_level_metrics"])
    canonical_order = ["sample"] + sample_level_metrics + read_level_metrics

    if read_mode == "all":
        df_pivot = df_metrics.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()
        ordered = [c for c in canonical_order if c in df_pivot.columns]
        remaining = [c for c in df_pivot.columns if c not in ordered]
        return df_pivot[ordered + remaining]

    base_to_r1 = groups["base_to_r1"]
    base_to_r2 = groups["base_to_r2"]

    df_sample = df_metrics[
        df_metrics["metric"].isin(sample_level_metrics) & df_metrics["sample"].isin(base_samples)
    ]
    if not df_sample.empty:
        df_sample_pivot = df_sample.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()
    else:
        df_sample_pivot = pd.DataFrame({"sample": base_samples})

    r1_names = list(base_to_r1.values())
    r2_names = list(base_to_r2.values())
    r1_to_base = {v: k for k, v in base_to_r1.items()}
    r2_to_base = {v: k for k, v in base_to_r2.items()}
    df_read = df_metrics[df_metrics["metric"].isin(read_level_metrics)]

    if read_mode == "mean":
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

    if not df_sample.empty and not df_read_pivot.empty:
        df_pivot = df_sample_pivot.merge(df_read_pivot, on="sample", how="outer")
    elif not df_read_pivot.empty:
        df_pivot = df_read_pivot
    else:
        df_pivot = df_sample_pivot

    ordered = [c for c in canonical_order if c in df_pivot.columns]
    remaining = [c for c in df_pivot.columns if c not in ordered]
    return df_pivot[ordered + remaining]


# ---------------------------------------------------------------------------
# Data processing
# ---------------------------------------------------------------------------


def _process_multiqc_data(
    parquet_path: str, show_hidden: bool = False, read_mode: str = "mean"
) -> tuple:
    """Process MultiQC parquet data and return formatted DataFrames."""
    df_raw = pl.read_parquet(parquet_path)
    df_general_stats = df_raw.filter(pl.col("anchor") == "general_stats_table")
    df_metrics_pl = df_general_stats.filter(pl.col("type") == "plot_input_row")

    if len(df_metrics_pl) == 0:
        msg = f"No general_stats_table data found in {parquet_path}"
        raise ValueError(msg)

    column_metadata = _extract_metadata_from_parquet(df_metrics_pl)

    if not show_hidden:
        hidden_metrics: set[str] = set()
        for _tool, tool_meta in column_metadata.items():
            for metric_key, config in tool_meta.items():
                if config.get("hidden", False):
                    hidden_metrics.add(metric_key)
        if hidden_metrics:
            df_metrics_pl = df_metrics_pl.filter(~pl.col("metric").is_in(list(hidden_metrics)))

    df_explore = df_metrics_pl.to_pandas()
    samples = df_explore["sample"].unique().tolist()
    sample_groups = _detect_sample_groups(samples, df_explore)

    if sample_groups:
        df_pivot = _harmonize_samples(df_explore, sample_groups, read_mode)
    else:
        df_pivot = df_explore.pivot_table(
            index="sample", columns="metric", values="val_mod", aggfunc="first"
        ).reset_index()

    tools = df_explore["section_key"].unique()

    column_mapping: dict[str, str] = {}
    percentage_columns: list[str] = []

    for col in df_pivot.columns:
        if col == "sample":
            column_mapping[col] = "Sample Name"
            continue

        display_name = None
        config = None
        for tool in tools:
            if tool in column_metadata and col in column_metadata[tool]:
                config = column_metadata[tool][col]
                display_name = config["title"]
                if config["suffix"] and not display_name.endswith(f" ({config['suffix'].strip()})"):
                    suffix = config["suffix"].strip()
                    display_name = f"{display_name} ({suffix})"
                break

        if display_name is None:
            display_name = col.replace("_", " ").title()
            if "pct_" in col or "rate" in col.lower() or "content" in col.lower():
                if not display_name.endswith(" (%)"):
                    display_name = display_name.replace("Pct ", "") + " (%)"

        column_mapping[col] = display_name

        if config and config["suffix"].strip() == "%":
            percentage_columns.append(display_name)
        elif display_name.endswith(" (%)"):
            percentage_columns.append(display_name)

    df_multiqc_real = df_pivot.rename(columns=column_mapping)

    sanitized_columns: dict[str, str] = {}
    display_to_internal: dict[str, str] = {}
    for col in df_multiqc_real.columns:
        if col == "Sample Name":
            sanitized_columns[col] = col
            display_to_internal[col] = col
        else:
            sanitized = _sanitize_column_name(col)
            counter = 1
            original_sanitized = sanitized
            while sanitized in sanitized_columns.values():
                sanitized = f"{original_sanitized}_{counter}"
                counter += 1
            sanitized_columns[col] = sanitized
            display_to_internal[col] = sanitized

    internal_to_display = {v: k for k, v in display_to_internal.items()}
    df_multiqc_real = df_multiqc_real.rename(columns=sanitized_columns)
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


# ---------------------------------------------------------------------------
# Data bars
# ---------------------------------------------------------------------------


def _multiqc_data_bars_colormap(
    df: pd.DataFrame,
    column: str,
    cmap_name: str = "RdYlGn",
    opacity: float = 0.4,
    fixed_scale: tuple | None = None,
    reverse_colors: bool = False,
) -> list[dict]:
    """Create data bars with matplotlib colormap."""
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
    col_id = column.replace("(", "\\(").replace(")", "\\)").replace("%", "\\%")

    try:
        cmap = plt.colormaps[cmap_name]
    except KeyError:
        cmap = _get_colormap(cmap_name)

    styles: list[dict] = []
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

        rgba = cmap(norm_value)
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
                "background": (
                    f"linear-gradient(90deg, "
                    f"{bar_color} 0%, "
                    f"{bar_color} {max_bound_percentage}%, "
                    f"white {max_bound_percentage}%, "
                    f"white 100%)"
                ),
                "paddingBottom": 4,
                "paddingTop": 4,
                "color": "black",
                "fontWeight": "normal",
            }
        )
    return styles


# ---------------------------------------------------------------------------
# Violin plot
# ---------------------------------------------------------------------------


def _create_violin_plot(
    df_general_stats: pd.DataFrame,
    reformatted_column_metadata: dict,
    display_to_original_mapping: dict | None = None,
) -> go.Figure:
    """Create MultiQC-style violin plot from general stats DataFrame."""
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
                title="General Statistics - No Data",
                template="plotly_white",
                height=200,
            )
        )

    metric_info = []
    for metric in metrics:
        is_percentage = "percent" in metric.lower() or "%" in metric
        metric_info.append(
            {
                "display_name": metric,
                "is_percentage": is_percentage,
            }
        )

    num_samples = len(df_general_stats)
    layout = go.Layout(
        title={
            "text": (
                f"General Statistics<br>"
                f"<span style='font-size: 12px; color: #666;'>{num_samples} samples</span>"
            ),
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
            values.append(row[metric])
            samples.append(row["Sample Name"])

        axis_key = "" if metric_idx == 0 else str(metric_idx + 1)
        x_axis_config: dict[str, Any] = {
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
            min_val = min(0, min(values)) if values else 0
            max_val = max(values) if values else 1
            padding = (max_val - min_val) * 0.05 if max_val != min_val else 1
            x_axis_config["range"] = [min_val - padding, max_val + padding]

        layout[f"xaxis{metric_idx + 1}"] = x_axis_config

        module_name = "Unknown Tool"
        if metric in reformatted_column_metadata:
            module_name = reformatted_column_metadata[metric]
        elif display_to_original_mapping and metric in display_to_original_mapping:
            original_name = display_to_original_mapping[metric]
            module_name = reformatted_column_metadata.get(original_name, "Unknown Tool")
        if module_name != "Unknown Tool":
            module_name = module_name.replace("_", " ").title()

        layout[f"yaxis{metric_idx + 1}"] = {
            "automargin": True,
            "tickfont": {"size": 9, "color": "rgba(0,0,0,0.5)"},
            "gridcolor": "rgba(0,0,0,0.1)",
            "zerolinecolor": "rgba(0,0,0,0.1)",
            "tickmode": "array",
            "tickvals": [metric_idx],
            "ticktext": [metric],
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
                marker={"size": 4, "color": "#0b79e6"},
                showlegend=False,
                hovertemplate="<b>%{text}</b><br>%{x:.2f}<extra></extra>",
                hoverlabel={"bgcolor": "white"},
            )
        )

    fig.update_layout(layout)
    return fig


# ---------------------------------------------------------------------------
# Scale resolution + style generation
# ---------------------------------------------------------------------------


def _resolve_scale_name(scale_name: str) -> tuple[str, bool]:
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
    if scale_name.endswith("-rev"):
        return (f"{scale_name[:-4]}_r", False)
    return (scale_name, False)


def _generate_data_bar_styles(
    df_for_display: pd.DataFrame,
    tools,
    column_metadata: dict,
    internal_to_display: dict,
    percentage_columns: list[str],
) -> tuple[list[dict], dict]:
    column_formats: dict[str, dict] = {}
    all_styles: list[dict] = []

    for internal_col in df_for_display.columns:
        if internal_col == "Sample Name":
            continue
        display_name = internal_to_display.get(internal_col, internal_col)

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
        colormap, reverse_flag = _resolve_scale_name(scale_name)

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
            _multiqc_data_bars_colormap(
                df_for_display,
                internal_col,
                colormap,
                opacity=0.3,
                fixed_scale=fixed_scale,
                reverse_colors=reverse_flag,
            )
        )

    return all_styles, column_formats


# ---------------------------------------------------------------------------
# Column format
# ---------------------------------------------------------------------------


def _get_column_format(
    column_name: str, percentage_columns: list[str], column_formats: dict
) -> Format | None:
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


# ---------------------------------------------------------------------------
# Build mode data (pre-compute one read mode)
# ---------------------------------------------------------------------------


def _build_mode_data(parquet_path: str, show_hidden: bool, read_mode: str) -> dict:
    """Build pre-computed table/violin data for a single read mode."""
    result = _process_multiqc_data(parquet_path, show_hidden=show_hidden, read_mode=read_mode)
    (
        _df_multiqc_real,
        df_for_display,
        internal_to_display,
        tools,
        column_metadata,
        percentage_columns,
        _sample_groups,
    ) = result

    all_styles, column_formats = _generate_data_bar_styles(
        df_for_display, tools, column_metadata, internal_to_display, percentage_columns
    )

    original_to_tool = {col: tool for tool, cols in column_metadata.items() for col in cols}
    display_to_original = (
        {v: k for k, v in internal_to_display.items()} if internal_to_display else None
    )

    # Format objects are not serialisable, so columns go in the DataTable, not the store
    columns = [
        {
            "name": internal_to_display.get(col, col),
            "id": col,
            "type": "numeric" if col != "Sample Name" else "text",
            "format": _get_column_format(
                internal_to_display.get(col, col), percentage_columns, column_formats
            ),
        }
        for col in df_for_display.columns
    ]

    violin_fig = _create_violin_plot(df_for_display, original_to_tool, display_to_original)

    active_cell_style = {
        "if": {"state": "active"},
        "backgroundColor": "rgba(0, 116, 217, 0.05)",
        "border": "1px solid rgba(0, 116, 217, 0.3)",
    }

    return {
        "table_data": df_for_display.to_dict("records"),
        "table_columns": columns,  # contains Format objects — NOT for dcc.Store
        "table_styles": all_styles + [active_cell_style],
        "violin_figure": violin_fig.to_dict(),  # JSON-safe
        "original_to_tool": original_to_tool,
        "display_to_original": display_to_original,
    }


# ---------------------------------------------------------------------------
# Shared layout styles
# ---------------------------------------------------------------------------

_HIDDEN_STYLE: dict[str, str] = {
    "position": "absolute",
    "visibility": "hidden",
    "overflow": "hidden",
    "height": "0",
    "width": "0",
    "pointerEvents": "none",
}

_TABLE_CELL_STYLE: dict[str, str] = {
    "textAlign": "left",
    "padding": "6px 8px",
    "fontFamily": "Arial, Helvetica, sans-serif",
    "fontSize": "12px",
    "border": "none",
    "borderBottom": "1px solid #e8e8e8",
    "whiteSpace": "nowrap",
    "overflow": "hidden",
    "textOverflow": "ellipsis",
}

_TABLE_HEADER_STYLE: dict[str, str] = {
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
}

_TABLE_DATA_STYLE: dict[str, str] = {
    "border": "none",
    "borderBottom": "1px solid #f0f0f0",
}

_TABLE_STYLE: dict[str, str] = {
    "border": "none",
    "borderTop": "1px solid #ddd",
    "borderBottom": "1px solid #ddd",
    "overflowX": "auto",
}


# ---------------------------------------------------------------------------
# Shared component tree builder
# ---------------------------------------------------------------------------


def _build_component_tree(
    component_id: str,
    is_paired_end: bool,
    table_data: list[dict],
    columns: list[dict],
    table_styles: list[dict],
    violin_figure: dict,
    store_data: dict,
) -> list:
    """Build the Dash component tree shared by both fresh build and cache rebuild."""
    controls: list = [dmc.Title("General Statistics", order=4)]
    if is_paired_end:
        controls.append(
            dmc.SegmentedControl(
                id={"type": "general-stats-read-toggle", "index": component_id},
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
            id={"type": "general-stats-view-toggle", "index": component_id},
            value="table",
            data=[
                {"label": "Table", "value": "table"},
                {"label": "Violin", "value": "violin"},
            ],
        )
    )

    return [
        html.Div(
            dmc.Group(controls, justify="space-between", align="center"),
            style={"flexShrink": "0", "padding": "4px 0"},
        ),
        html.Div(
            [
                dash_table.DataTable(
                    id={"type": "general-stats-table", "index": component_id},
                    data=table_data,
                    columns=columns,
                    style_data_conditional=table_styles,
                    style_cell=_TABLE_CELL_STYLE,
                    style_cell_conditional=[
                        {
                            "if": {"column_id": "Sample Name"},
                            "minWidth": "200px",
                            "fontWeight": "bold",
                            "backgroundColor": "white",
                        }
                    ],
                    style_header=_TABLE_HEADER_STYLE,
                    style_data=_TABLE_DATA_STYLE,
                    style_table=_TABLE_STYLE,
                    sort_action="native",
                    filter_action="none",
                    page_size=50,
                ),
                dcc.Graph(
                    id={"type": "general-stats-violin", "index": component_id},
                    figure=violin_figure,
                    config={"displayModeBar": False},
                    style=_HIDDEN_STYLE,
                ),
            ],
            style={
                "flex": "1",
                "minHeight": "0",
                "overflow": "auto",
            },
        ),
        dcc.Store(
            id={"type": "general-stats-store", "index": component_id},
            data=store_data,
        ),
    ]


# ---------------------------------------------------------------------------
# Public API: build general stats content
# ---------------------------------------------------------------------------


def build_general_stats_content(
    parquet_path: str,
    component_id: str,
    show_hidden: bool = True,
) -> tuple[list, dict, list]:
    """Build general stats children, store data, and column definitions."""
    result = _process_multiqc_data(parquet_path, show_hidden=show_hidden, read_mode="mean")
    sample_groups = result[6]
    is_paired_end = sample_groups is not None

    read_modes = ["mean", "r1", "r2", "all"] if is_paired_end else ["mean"]
    mode_data = {mode: _build_mode_data(parquet_path, show_hidden, mode) for mode in read_modes}

    default_data = mode_data["mean"]
    columns = default_data["table_columns"]

    store_data: dict[str, Any] = {}
    for mode, mdata in mode_data.items():
        store_data[mode] = {
            "table_data": mdata["table_data"],
            "table_styles": mdata["table_styles"],
            "violin_figure": mdata["violin_figure"],
            "original_to_tool": mdata["original_to_tool"],
            "display_to_original": mdata["display_to_original"],
        }
    store_data["is_paired_end"] = is_paired_end

    all_samples: set[str] = set()
    for mdata in mode_data.values():
        for rec in mdata["table_data"]:
            sample = rec.get("Sample Name")
            if sample:
                all_samples.add(sample)
    store_data["all_samples"] = sorted(all_samples)

    children = _build_component_tree(
        component_id=component_id,
        is_paired_end=is_paired_end,
        table_data=default_data["table_data"],
        columns=columns,
        table_styles=default_data["table_styles"],
        violin_figure=default_data["violin_figure"],
        store_data=store_data,
    )

    return children, store_data, columns


# ---------------------------------------------------------------------------
# Public API: rebuild from cached store data
# ---------------------------------------------------------------------------


def rebuild_general_stats_from_cache(
    store_data: dict,
    component_id: str,
) -> list:
    """Rebuild the Dash component tree from cached store_data (no parquet I/O)."""
    is_paired_end = store_data.get("is_paired_end", False)
    default_data = store_data.get("mean", {})

    if not default_data or "table_data" not in default_data:
        raise ValueError("Cached store_data missing 'mean' mode data")

    # Rebuild column definitions with Format objects from cached data
    percentage_columns: list[str] = []
    column_formats: dict[str, dict] = {}
    display_to_original = default_data.get("display_to_original", {})

    for col_name in display_to_original:
        if col_name.endswith(" (%)"):
            percentage_columns.append(col_name)

    sample_record = default_data["table_data"][0] if default_data["table_data"] else {}
    internal_cols = list(sample_record.keys())

    internal_to_display = (
        {v: k for k, v in display_to_original.items()} if display_to_original else {}
    )

    columns = [
        {
            "name": internal_to_display.get(col, col),
            "id": col,
            "type": "numeric" if col != "Sample Name" else "text",
            "format": _get_column_format(
                internal_to_display.get(col, col), percentage_columns, column_formats
            ),
        }
        for col in internal_cols
    ]

    return _build_component_tree(
        component_id=component_id,
        is_paired_end=is_paired_end,
        table_data=default_data["table_data"],
        columns=columns,
        table_styles=default_data.get("table_styles", []),
        violin_figure=default_data.get("violin_figure", {"data": [], "layout": {}}),
        store_data=store_data,
    )


# ---------------------------------------------------------------------------
# Public API: empty placeholders for non-general-stats instances
# ---------------------------------------------------------------------------


def build_empty_general_stats_elements(component_id: str) -> list:
    """Build hidden placeholder elements so MATCH callbacks never encounter missing outputs."""
    return [
        html.Div(
            [
                dmc.SegmentedControl(
                    id={"type": "general-stats-read-toggle", "index": component_id},
                    value="mean",
                    data=[{"label": "Mean", "value": "mean"}],
                    size="sm",
                ),
                dmc.SegmentedControl(
                    id={"type": "general-stats-view-toggle", "index": component_id},
                    value="table",
                    data=[{"label": "Table", "value": "table"}],
                ),
            ],
            style=_HIDDEN_STYLE,
        ),
        dash_table.DataTable(
            id={"type": "general-stats-table", "index": component_id},
            data=[],
            columns=[],
            style_data_conditional=[],
            style_table=_HIDDEN_STYLE,
        ),
        dcc.Graph(
            id={"type": "general-stats-violin", "index": component_id},
            figure={"data": [], "layout": {"height": 0, "width": 0}},
            style=_HIDDEN_STYLE,
        ),
        dcc.Store(
            id={"type": "general-stats-store", "index": component_id},
            data={},
        ),
    ]
