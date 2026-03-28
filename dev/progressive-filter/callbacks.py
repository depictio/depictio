"""Callbacks for the progressive filter prototype.

Architecture
------------
1. Add-filter callback: appends a new filter card to the sidebar and updates stores.
2. Main update callback: reads all filter controls via pattern-matching (ALL),
   applies filters sequentially, and updates volcano, funnel, badges, and table.
"""

from typing import Any

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import (
    ALL,
    Dash,
    Input,
    Output,
    State,
    callback_context,
    html,
    no_update,
)
from data import CATEGORICAL_COLS, COLUMN_LABELS, NUMERIC_COLS

# ── Table column definitions ─────────────────────────────────────────────────

TABLE_COLUMN_DEFS: list[dict] = [
    {
        "field": "gene_name",
        "headerName": "Gene",
        "filter": "agTextColumnFilter",
        "pinned": "left",
        "minWidth": 120,
    },
    {
        "field": "log2fc",
        "headerName": "log2(FC)",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
    },
    {
        "field": "pvalue",
        "headerName": "p-value",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.2e')(params.value)"},
    },
    {
        "field": "padj",
        "headerName": "padj",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.2e')(params.value)"},
    },
    {
        "field": "neg_log10_pvalue",
        "headerName": "-log10(p)",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
    },
    {
        "field": "mean_expression",
        "headerName": "Mean Expr",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
    },
    {"field": "cluster", "headerName": "Cluster", "filter": "agTextColumnFilter"},
    {"field": "significance", "headerName": "Significance", "filter": "agTextColumnFilter"},
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_col_type(col: str) -> str:
    """Determine if a column is numeric or categorical."""
    if col in NUMERIC_COLS:
        return "numeric"
    return "categorical"


def _apply_single_filter(
    series: pd.Series,
    col_type: str,
    operator: str,
    threshold: float,
    use_abs: bool,
    cat_values: list[str],
) -> pd.Series:
    """Apply one filter and return a boolean mask."""
    if col_type == "categorical":
        if not cat_values:
            return pd.Series(True, index=series.index)
        return series.isin(cat_values)

    values = series.abs() if use_abs else series
    ops = {">": values.gt, "<": values.lt, ">=": values.ge, "<=": values.le}
    return ops.get(operator, values.gt)(threshold)


def _build_volcano(
    df: pd.DataFrame,
    mask: pd.Series,
) -> go.Figure:
    """Build volcano plot with gray background and colored filtered genes."""
    fig = go.Figure()

    # All genes as gray background
    fig.add_trace(
        go.Scatter(
            x=df["log2fc"],
            y=df["neg_log10_pvalue"],
            mode="markers",
            marker=dict(color="lightgrey", opacity=0.4, size=5),
            name="Excluded",
            text=df["gene_name"],
            hovertemplate="%{text}<br>log2FC=%{x:.3f}<br>-log10(p)=%{y:.3f}<extra></extra>",
        )
    )

    # Filtered genes overlaid with color by significance
    filtered = df[mask]
    if not filtered.empty:
        color_map = {"Up": "#e63946", "Down": "#457b9d", "NS": "#a8dadc"}
        for sig_label, color in color_map.items():
            sub = filtered[filtered["significance"] == sig_label]
            if sub.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=sub["log2fc"],
                    y=sub["neg_log10_pvalue"],
                    mode="markers",
                    marker=dict(
                        color=color,
                        opacity=0.85,
                        size=7,
                        line=dict(width=0.5, color="white"),
                    ),
                    name=sig_label,
                    text=sub["gene_name"],
                    hovertemplate="%{text}<br>log2FC=%{x:.3f}<br>-log10(p)=%{y:.3f}<extra></extra>",
                )
            )

    fig.update_layout(
        title="Volcano Plot",
        xaxis_title="log2(FC)",
        yaxis_title="-log10(p-value)",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="closest",
    )
    return fig


def _build_funnel(step_data: list[dict[str, Any]]) -> go.Figure:
    """Build a funnel chart from sequential filter step data."""
    fig = go.Figure()

    if not step_data:
        fig.update_layout(
            title="Filter Funnel",
            template="plotly_white",
            margin=dict(l=20, r=20, t=50, b=20),
        )
        return fig

    labels = [s["label"] for s in step_data]
    values = [s["count"] for s in step_data]

    fig.add_trace(
        go.Funnel(
            y=labels,
            x=values,
            textinfo="value+percent initial",
            marker=dict(
                color=[
                    "#228be6",
                    "#40c057",
                    "#fab005",
                    "#e64980",
                    "#7950f2",
                    "#15aabf",
                    "#fd7e14",
                    "#be4bdb",
                ][:len(labels)],
            ),
            connector=dict(line=dict(color="royalblue", width=1)),
        )
    )

    fig.update_layout(
        title="Filter Funnel",
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
        funnelmode="stack",
    )
    return fig


def _build_summary_badges(n_total: int, n_remaining: int) -> list:
    """Build summary badge components."""
    pct = (n_remaining / n_total * 100) if n_total > 0 else 0
    return [
        dmc.Badge(f"Total: {n_total}", color="gray", variant="light", size="lg"),
        dmc.Badge(f"Remaining: {n_remaining}", color="blue", variant="light", size="lg"),
        dmc.Badge(f"Retained: {pct:.1f}%", color="green", variant="light", size="lg"),
    ]


# ── Callback registration ───────────────────────────────────────────────────


def register_callbacks(app: Dash, df: pd.DataFrame) -> None:
    """Register all Dash callbacks.

    Args:
        app: The Dash application instance.
        df: The source DataFrame (immutable reference).
    """

    # Precompute categorical unique values for each column
    cat_unique: dict[str, list[str]] = {}
    for col in CATEGORICAL_COLS:
        cat_unique[col] = sorted(df[col].unique().tolist())

    # ── Add filter callback ──────────────────────────────────────────────────
    @app.callback(
        Output("filter-store", "data", allow_duplicate=True),
        Output("next-filter-id", "data", allow_duplicate=True),
        Output("filter-cards-container", "children", allow_duplicate=True),
        Input("add-filter-btn", "n_clicks"),
        State("filter-store", "data"),
        State("next-filter-id", "data"),
        State("filter-cards-container", "children"),
        prevent_initial_call=True,
    )
    def add_filter(n_clicks, filters, next_id, current_cards):
        if not n_clicks:
            return no_update, no_update, no_update

        new_filter = {
            "id": next_id,
            "column": "log2fc",
            "col_type": "numeric",
            "operator": ">",
            "threshold": 1.0,
            "use_abs": False,
            "cat_values": [],
            "enabled": True,
        }
        filters.append(new_filter)

        # Import here to avoid circular import
        from layout import _create_filter_card

        new_card = _create_filter_card(new_filter)
        if current_cards is None:
            current_cards = []
        current_cards.append(new_card)

        return filters, next_id + 1, current_cards

    # ── Main update callback ─────────────────────────────────────────────────
    @app.callback(
        Output("volcano-plot", "figure"),
        Output("funnel-chart", "figure"),
        Output("summary-badges", "children"),
        Output("gene-table", "rowData"),
        Output("gene-table", "columnDefs"),
        Output({"type": "filter-count-badge", "index": ALL}, "children"),
        Output({"type": "cat-controls", "index": ALL}, "style"),
        Output({"type": "numeric-controls", "index": ALL}, "style"),
        Output({"type": "threshold-container", "index": ALL}, "style"),
        Output({"type": "filter-cat-values", "index": ALL}, "data"),
        Input({"type": "filter-enabled", "index": ALL}, "checked"),
        Input({"type": "filter-column", "index": ALL}, "value"),
        Input({"type": "filter-operator", "index": ALL}, "value"),
        Input({"type": "filter-threshold", "index": ALL}, "value"),
        Input({"type": "filter-abs", "index": ALL}, "checked"),
        Input({"type": "filter-cat-values", "index": ALL}, "value"),
        State("filter-store", "data"),
    )
    def update_main(
        enabled_list,
        column_list,
        operator_list,
        threshold_list,
        abs_list,
        cat_values_list,
        filter_store,
    ):
        n_filters = len(enabled_list)
        n_total = len(df)

        # Build per-step survival counts and final mask
        cumulative_mask = pd.Series(True, index=df.index)
        step_data = [{"label": "All genes", "count": n_total}]
        per_filter_counts = []

        # Visibility outputs
        cat_styles = []
        numeric_styles = []
        threshold_styles = []
        cat_data_options = []

        for i in range(n_filters):
            col = column_list[i]
            enabled = enabled_list[i]
            operator = operator_list[i]
            threshold = threshold_list[i]
            use_abs = abs_list[i]
            cat_vals = cat_values_list[i] or []

            col_type = _get_col_type(col) if col else "numeric"
            is_numeric = col_type == "numeric"

            # Set visibility styles
            cat_styles.append({"display": "none" if is_numeric else "block"})
            numeric_styles.append({"display": "block" if is_numeric else "none"})
            threshold_styles.append({"display": "block" if is_numeric else "none"})

            # Set categorical options
            if col and col in cat_unique:
                cat_data_options.append(
                    [{"value": v, "label": v} for v in cat_unique[col]]
                )
            else:
                cat_data_options.append([])

            if enabled and col:
                step_mask = _apply_single_filter(
                    df[col], col_type, operator, threshold or 0, use_abs, cat_vals
                )
                cumulative_mask &= step_mask
                count = int(cumulative_mask.sum())
                label = COLUMN_LABELS.get(col, col)
                if is_numeric:
                    abs_prefix = "|" if use_abs else ""
                    abs_suffix = "|" if use_abs else ""
                    step_label = f"{abs_prefix}{label}{abs_suffix} {operator} {threshold}"
                else:
                    step_label = f"{label} in [{', '.join(cat_vals[:3])}{'...' if len(cat_vals) > 3 else ''}]"
                step_data.append({"label": step_label, "count": count})
                per_filter_counts.append(f"{count} pass")
            else:
                per_filter_counts.append("off")

        n_remaining = int(cumulative_mask.sum())

        # Build outputs
        volcano_fig = _build_volcano(df, cumulative_mask)
        funnel_fig = _build_funnel(step_data)
        summary = _build_summary_badges(n_total, n_remaining)

        # Table: show only filtered genes
        filtered_df = df[cumulative_mask]
        row_data = filtered_df.to_dict("records")

        return (
            volcano_fig,
            funnel_fig,
            summary,
            row_data,
            TABLE_COLUMN_DEFS,
            per_filter_counts,
            cat_styles,
            numeric_styles,
            threshold_styles,
            cat_data_options,
        )
