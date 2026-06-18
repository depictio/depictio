"""MultiQC General Statistics — JSON-safe payload builder.

Extracted from depictio.dash.modules.multiqc_component.general_stats, keeping
only the path that produces the JSON payload the React viewer fetches.
The Dash-side component-tree builders (`build_general_stats_content`,
`rebuild_general_stats_from_cache`, `build_empty_general_stats_elements`)
stay in the dash/ tree and die with it.
"""

import json
import re
from typing import Any

import pandas as pd
import plotly.colors as pc
import plotly.graph_objects as go
import polars as pl

# Plotly colorscales standing in for the matplotlib colormaps the general-stats
# table used before the Dash → React migration. matplotlib is no longer a
# dependency, and plotly (already required) provides equivalent scales with the
# same low→high orientation (Red→Green, Red→Blue, light→dark Blue).
_CMAP_ALIASES = {
    "RdYlGn": pc.diverging.RdYlGn,
    "RdYlBu": pc.diverging.RdYlBu,
    "Blues": pc.sequential.Blues,
}
_FALLBACK_CMAP = pc.diverging.RdYlGn


def _get_colormap(name: str):
    return _CMAP_ALIASES.get(name, _FALLBACK_CMAP)


def _sample_colormap(cmap, norm_value: float) -> tuple[float, float, float]:
    """Sample a plotly colorscale at a normalised value, returning (r, g, b) in 0-1.

    Mirrors the matplotlib ``cmap(norm_value)`` call this replaced, including the
    implicit clamping matplotlib applied to out-of-range values.
    """
    clamped = min(1.0, max(0.0, norm_value))
    r, g, b = pc.sample_colorscale(cmap, [clamped], colortype="tuple")[0]
    return r, g, b


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
    parquet_path: str | list[str], show_hidden: bool = False, read_mode: str = "mean"
) -> tuple:
    """Process MultiQC parquet data and return formatted DataFrames.

    ``parquet_path`` can be a single path (legacy single-report behaviour)
    or a list of paths — when given a list, every parquet is read and
    vertically concatenated *before* the pivot, so the GS table aggregates
    samples across the entire DC. Without this, a multi-report DC only
    surfaces samples from the first parquet (the historical bug that left
    appended runs invisible in the GS table).
    """
    if isinstance(parquet_path, str):
        df_raw = pl.read_parquet(parquet_path)
    else:
        if not parquet_path:
            raise ValueError("_process_multiqc_data requires at least one parquet path")
        # `how="diagonal_relaxed"` so reports with extra columns / different
        # dtypes don't crash the concat — they just contribute nulls / get
        # cast to a common dtype, mirroring the CLI aggregator's behaviour.
        df_raw = pl.concat([pl.read_parquet(p) for p in parquet_path], how="diagonal_relaxed")
    df_general_stats = df_raw.filter(pl.col("anchor") == "general_stats_table")
    df_metrics_pl = df_general_stats.filter(pl.col("type") == "plot_input_row")

    # Fallback: try summary_variants_metrics_plot (nf-core/viralrecon style). The
    # illumina route emits the bare `..._plot` anchor; the nanopore/ARTIC route emits
    # the same table under a `..._plot_table` anchor — accept both.
    if len(df_metrics_pl) == 0:
        for fallback_anchor in [
            "summary_variants_metrics_plot",
            "summary_assembly_metrics_plot",
            "summary_variants_metrics_plot_table",
            "summary_assembly_metrics_plot_table",
        ]:
            df_fallback = df_raw.filter(pl.col("anchor") == fallback_anchor)
            df_fallback_metrics = df_fallback.filter(pl.col("type") == "plot_input_row")
            if len(df_fallback_metrics) > 0:
                df_metrics_pl = df_fallback_metrics
                break

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
                display_name = config.get("title") or col.replace("_", " ").title()
                suffix = config.get("suffix")
                if suffix and not display_name.endswith(f" ({suffix.strip()})"):
                    display_name = f"{display_name} ({suffix.strip()})"
                break

        if display_name is None:
            display_name = col.replace("_", " ").title()
            if "pct_" in col or "rate" in col.lower() or "content" in col.lower():
                if not display_name.endswith(" (%)"):
                    display_name = display_name.replace("Pct ", "") + " (%)"

        column_mapping[col] = display_name

        suffix = config.get("suffix") if config else None
        if suffix and suffix.strip() == "%":
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
    """Create data bars coloured with a plotly colorscale."""
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

        r, g, b = _sample_colormap(cmap, norm_value)
        r = r * opacity + (1 - opacity) * 1.0
        g = g * opacity + (1 - opacity) * 1.0
        b = b * opacity + (1 - opacity) * 1.0
        bar_color = "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))

        styles.append(
            {
                "if": {
                    "filter_query": (
                        "{{{column}}} >= {min_bound}"
                        + (" && {{{column}}} < {max_bound}" if (i < len(bounds) - 1) else "")
                    ).format(column=col_id, min_bound=min_bound, max_bound=max_bound),
                    "column_id": column,
                },
                "backgroundImage": (
                    f"linear-gradient(90deg, "
                    f"{bar_color} 0%, "
                    f"{bar_color} {max_bound_percentage}%, "
                    f"transparent {max_bound_percentage}%, "
                    f"transparent 100%)"
                ),
                "paddingBottom": 4,
                "paddingTop": 4,
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
                template="mantine_light",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
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
            "text": f"General Statistics<br><span style='font-size: 12px;'>{num_samples} samples</span>",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 16},
        },
        showlegend=False,
        template="mantine_light",
        margin=dict(pad=0, b=40, t=70, l=120, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
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
            "tickfont": {"size": 9},
        },
        yaxis={
            "tickfont": {"size": 9},
        },
        violingap=0,
    )
    fig = go.Figure(layout=layout)

    for metric_idx, metric_data in enumerate(metric_info):
        metric = metric_data["display_name"]
        values = []
        samples = []
        for _, row in df_general_stats.iterrows():
            val = row[metric]
            if pd.isna(val):
                continue
            values.append(val)
            samples.append(row["Sample Name"])

        axis_key = "" if metric_idx == 0 else str(metric_idx + 1)
        x_axis_config: dict[str, Any] = {
            "automargin": False,
            "tickfont": {"size": 9},
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
            "tickfont": {"size": 9},
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
                opacity=0.5,
                fixed_scale=fixed_scale,
                reverse_colors=reverse_flag,
            )
        )

    return all_styles, column_formats


# ---------------------------------------------------------------------------
# Column format
# ---------------------------------------------------------------------------


def _column_format_to_json(
    column_name: str, percentage_columns: list[str], column_formats: dict
) -> dict | None:
    """JSON-safe mirror of `_get_column_format`.

    Returns a primitive dict the React side can consume (Intl.NumberFormat).
    Mirrors the same branching as the Dash `Format`-returning version.
    """
    if column_name == "Sample Name":
        return None
    if column_name in percentage_columns:
        return {"precision": 1, "suffix": "%", "group": True}
    if "(M)" in column_name:
        return {"precision": 2, "suffix": " M", "group": True}
    if "bp" in column_name:
        return {"precision": 0, "suffix": " bp", "group": True}
    if column_name in column_formats:
        format_info = column_formats[column_name]
        format_str = format_info.get("format") or "{:,.1f}"
        suffix = format_info.get("suffix") or ""
        if suffix and suffix.strip() == "M":
            return {"precision": 2, "suffix": " M", "group": True}
        if suffix and "bp" in suffix:
            if ".0f" in format_str:
                return {"precision": 0, "suffix": " bp", "group": True}
            if ".1f" in format_str:
                return {"precision": 1, "suffix": " bp", "group": True}
        if ".0f" in format_str:
            return {"precision": 0, "suffix": "", "group": True}
        if ".1f" in format_str:
            return {"precision": 1, "suffix": "", "group": True}
        if ".2f" in format_str:
            return {"precision": 2, "suffix": "", "group": True}
    if "len" in column_name.lower():
        return {"precision": 0, "suffix": "", "group": True}
    return {"precision": 1, "suffix": "", "group": True}


def _build_mode_payload(
    parquet_path: str | list[str],
    show_hidden: bool,
    read_mode: str,
    selected_samples: list[str] | None = None,
) -> dict:
    """Build a fully JSON-safe payload for one read mode (table + violin).

    When ``selected_samples`` is provided, the dataframe is filtered before
    style + violin generation so data bars span the filtered range only.
    """
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

    if selected_samples:
        df_for_display = df_for_display[
            df_for_display["Sample Name"].astype(str).isin([str(s) for s in selected_samples])
        ].reset_index(drop=True)

    all_styles, column_formats = _generate_data_bar_styles(
        df_for_display, tools, column_metadata, internal_to_display, percentage_columns
    )

    columns = [
        {
            "id": col,
            "name": internal_to_display.get(col, col),
            "type": "numeric" if col != "Sample Name" else "text",
            "format": _column_format_to_json(
                internal_to_display.get(col, col), percentage_columns, column_formats
            ),
        }
        for col in df_for_display.columns
    ]

    violin_fig = _create_violin_plot(
        df_for_display,
        {col: tool for tool, cols in column_metadata.items() for col in cols},
        {v: k for k, v in internal_to_display.items()} if internal_to_display else None,
    )

    return {
        "table_data": df_for_display.to_dict("records"),
        "table_columns": columns,
        "table_styles": all_styles,
        "violin_figure": violin_fig.to_dict(),
    }


def build_general_stats_payload(
    parquet_path: str | list[str],
    show_hidden: bool = True,
    selected_samples: list[str] | None = None,
) -> dict:
    """JSON-safe payload mirroring `build_general_stats_content` for the React viewer.

    ``parquet_path`` accepts a single path (legacy) or a list of paths to
    concatenate before pivoting — the React caller passes every parquet for
    the DC so the GS table aggregates samples across all reports.

    Returns:
        {
          "is_paired_end": bool,
          "all_samples": [str, ...],
          "modes": {
            "mean":  {table_data, table_columns, table_styles, violin_figure},
            "r1":    same shape — only when is_paired_end,
            "r2":    same shape — only when is_paired_end,
            "all":   same shape — only when is_paired_end,
          },
        }

    The Dash `Format` objects in `table_columns[].format` are replaced by plain
    `{precision, suffix, group}` dicts; everything else is already JSON-safe.

    When ``selected_samples`` is provided, the table is filtered to those
    samples (and the violin recomputed from the filtered slice). ``is_paired_end``
    and ``all_samples`` are still derived from the *unfiltered* probe so the
    React-side toggle remains coherent across filter changes.
    """
    probe = _process_multiqc_data(parquet_path, show_hidden=show_hidden, read_mode="mean")
    is_paired_end = probe[6] is not None

    read_modes = ["mean", "r1", "r2", "all"] if is_paired_end else ["mean"]
    modes = {
        mode: _build_mode_payload(parquet_path, show_hidden, mode, selected_samples)
        for mode in read_modes
    }

    all_samples: set[str] = set()
    for mdata in modes.values():
        for rec in mdata["table_data"]:
            sample = rec.get("Sample Name")
            if sample:
                all_samples.add(sample)

    return {
        "is_paired_end": is_paired_end,
        "all_samples": sorted(all_samples),
        "modes": modes,
    }


# ---------------------------------------------------------------------------
# Public API: rebuild from cached store data
# ---------------------------------------------------------------------------
