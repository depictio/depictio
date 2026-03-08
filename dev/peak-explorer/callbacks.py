"""Callbacks for the Peak Explorer analysis module.

Architecture
------------
1. Add-filter callback: appends a new filter card to the sidebar and updates stores.
2. Main update callback: reads all filter controls via pattern-matching (ALL),
   applies filters sequentially, and updates scatter, funnel, enrichment curve,
   annotation pie, summary badges, and AG Grid table.

The scatter plot shows fold_enrichment vs -log10(pvalue) with dynamic threshold
lines (hline + vline) derived from the first matching numeric filters. Points
passing all filters are colored by annotation; excluded points are gray.

The enrichment curve shows how % Promoter changes as you sweep the score
threshold. A vertical line marks the current score threshold.
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
    no_update,
)
from data import ANNOTATION_CATEGORIES, CATEGORICAL_COLS, COLUMN_LABELS, NUMERIC_COLS

# ── Annotation color palette ────────────────────────────────────────────────

ANNOTATION_COLORS: dict[str, str] = {
    "Promoter": "#e63946",
    "5' UTR": "#f4a261",
    "3' UTR": "#e9c46a",
    "Exon": "#2a9d8f",
    "Intron": "#264653",
    "Intergenic": "#a8dadc",
    "TTS": "#457b9d",
}

# ── Table column definitions ────────────────────────────────────────────────

TABLE_COLUMN_DEFS: list[dict] = [
    {
        "field": "peak_id",
        "headerName": "Peak ID",
        "filter": "agTextColumnFilter",
        "pinned": "left",
        "minWidth": 110,
    },
    {
        "field": "chr",
        "headerName": "Chr",
        "filter": "agTextColumnFilter",
        "maxWidth": 80,
    },
    {
        "field": "start",
        "headerName": "Start",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format(',')(params.value)"},
    },
    {
        "field": "end",
        "headerName": "End",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format(',')(params.value)"},
    },
    {
        "field": "width",
        "headerName": "Width",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format(',')(params.value)"},
    },
    {
        "field": "score",
        "headerName": "Score",
        "filter": "agNumberColumnFilter",
    },
    {
        "field": "neg_log10_pvalue",
        "headerName": "-log10(p)",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.2f')(params.value)"},
    },
    {
        "field": "fold_enrichment",
        "headerName": "Fold Enrich.",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.2f')(params.value)"},
    },
    {
        "field": "annotation",
        "headerName": "Annotation",
        "filter": "agTextColumnFilter",
    },
    {
        "field": "nearest_gene",
        "headerName": "Nearest Gene",
        "filter": "agTextColumnFilter",
    },
    {
        "field": "distance_to_tss",
        "headerName": "Dist. to TSS",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format(',')(params.value)"},
    },
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


# ── Chart builders ───────────────────────────────────────────────────────────


def _build_scatter(
    df: pd.DataFrame,
    mask: pd.Series,
    fe_threshold: float | None,
    pval_threshold: float | None,
) -> go.Figure:
    """Scatter plot: fold_enrichment vs -log10(pvalue).

    Points passing the filter chain are colored by annotation category.
    Dynamic hline/vline show the fold_enrichment and -log10(pvalue) thresholds.
    """
    fig = go.Figure()

    # All peaks as gray background
    fig.add_trace(
        go.Scatter(
            x=df["fold_enrichment"],
            y=df["neg_log10_pvalue"],
            mode="markers",
            marker=dict(color="lightgrey", opacity=0.3, size=4),
            name="Excluded",
            text=df["peak_id"],
            hovertemplate=("%{text}<br>Fold=%{x:.2f}<br>-log10(p)=%{y:.2f}<extra></extra>"),
        )
    )

    # Filtered peaks colored by annotation
    filtered = df[mask]
    if not filtered.empty:
        for cat in ANNOTATION_CATEGORIES:
            sub = filtered[filtered["annotation"] == cat]
            if sub.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=sub["fold_enrichment"],
                    y=sub["neg_log10_pvalue"],
                    mode="markers",
                    marker=dict(
                        color=ANNOTATION_COLORS.get(cat, "#888"),
                        opacity=0.8,
                        size=6,
                        line=dict(width=0.5, color="white"),
                    ),
                    name=cat,
                    text=sub["peak_id"],
                    hovertemplate=(
                        "%{text}<br>Fold=%{x:.2f}<br>-log10(p)=%{y:.2f}"
                        f"<br>{cat}<extra></extra>"
                    ),
                )
            )

    # Dynamic threshold lines
    if fe_threshold is not None:
        fig.add_vline(
            x=fe_threshold,
            line_dash="dash",
            line_color="#e64980",
            line_width=1.5,
            annotation_text=f"Fold >= {fe_threshold}",
            annotation_position="top right",
        )
    if pval_threshold is not None:
        fig.add_hline(
            y=pval_threshold,
            line_dash="dash",
            line_color="#7950f2",
            line_width=1.5,
            annotation_text=f"-log10(p) >= {pval_threshold}",
            annotation_position="top left",
        )

    fig.update_layout(
        title="Peak Significance vs Fold Enrichment",
        xaxis_title="Fold Enrichment",
        yaxis_title="-log10(p-value)",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="closest",
    )
    return fig


def _build_funnel(step_data: list[dict[str, Any]]) -> go.Figure:
    """Funnel chart showing sequential filter attrition."""
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
                ][: len(labels)],
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


def _build_enrichment_curve(
    df: pd.DataFrame,
    current_score_threshold: float | None,
) -> go.Figure:
    """Line chart: % Promoter as a function of score threshold.

    Sweeps score from min to max and at each point computes the fraction
    of peaks with score >= threshold that are annotated as Promoter.
    A vertical line shows the current score threshold.
    """
    score_min = int(df["score"].min())
    score_max = int(df["score"].max())
    thresholds = np.linspace(score_min, score_max, 80)

    pct_promoter = []
    for t in thresholds:
        above = df[df["score"] >= t]
        if len(above) == 0:
            pct_promoter.append(0.0)
        else:
            pct_promoter.append((above["annotation"] == "Promoter").sum() / len(above) * 100)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=thresholds,
            y=pct_promoter,
            mode="lines",
            line=dict(color="#e63946", width=2.5),
            name="% Promoter",
            hovertemplate="Score >= %{x:.0f}<br>%Promoter = %{y:.1f}%<extra></extra>",
        )
    )

    if current_score_threshold is not None:
        fig.add_vline(
            x=current_score_threshold,
            line_dash="dash",
            line_color="#228be6",
            line_width=2,
            annotation_text=f"Current: {current_score_threshold}",
            annotation_position="top right",
        )

    fig.update_layout(
        title="Promoter Enrichment Curve (by Score Threshold)",
        xaxis_title="Score Threshold (>=)",
        yaxis_title="% Promoter",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=60),
        yaxis=dict(range=[0, max(pct_promoter) * 1.15 if pct_promoter else 100]),
    )
    return fig


def _build_annotation_pie(df: pd.DataFrame) -> go.Figure:
    """Donut chart of annotation distribution for filtered peaks."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="Annotation Distribution (no peaks)",
            template="plotly_white",
            margin=dict(l=20, r=20, t=50, b=20),
        )
        return fig

    counts = df["annotation"].value_counts()
    colors = [ANNOTATION_COLORS.get(cat, "#ccc") for cat in counts.index]

    fig = go.Figure(
        go.Pie(
            labels=counts.index.tolist(),
            values=counts.values.tolist(),
            marker=dict(colors=colors),
            textinfo="percent+label",
            hole=0.35,
        )
    )
    fig.update_layout(
        title="Annotation Distribution",
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
        showlegend=False,
    )
    return fig


def _build_summary_badges(
    n_total: int,
    n_remaining: int,
    pct_promoter: float,
    current_score: float | None,
) -> list:
    """Build summary badge components."""
    pct_retained = (n_remaining / n_total * 100) if n_total > 0 else 0
    badges = [
        dmc.Badge(f"Total: {n_total}", color="gray", variant="light", size="lg"),
        dmc.Badge(f"Remaining: {n_remaining}", color="blue", variant="light", size="lg"),
        dmc.Badge(
            f"Retained: {pct_retained:.1f}%",
            color="green",
            variant="light",
            size="lg",
        ),
        dmc.Badge(
            f"Promoter: {pct_promoter:.1f}%",
            color="red",
            variant="light",
            size="lg",
        ),
    ]
    if current_score is not None:
        badges.append(
            dmc.Badge(
                f"Score >= {current_score}",
                color="violet",
                variant="light",
                size="lg",
            )
        )
    return badges


# ── Callback registration ───────────────────────────────────────────────────


def register_callbacks(app: Dash, df: pd.DataFrame) -> None:
    """Register all Dash callbacks.

    Args:
        app: The Dash application instance.
        df: The source peak DataFrame (immutable reference).
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
            "column": "score",
            "col_type": "numeric",
            "operator": ">=",
            "threshold": 100,
            "use_abs": False,
            "cat_values": [],
            "enabled": True,
        }
        filters.append(new_filter)

        from layout import _create_filter_card

        new_card = _create_filter_card(new_filter)
        if current_cards is None:
            current_cards = []
        current_cards.append(new_card)

        return filters, next_id + 1, current_cards

    # ── Main update callback ─────────────────────────────────────────────────
    @app.callback(
        Output("scatter-plot", "figure"),
        Output("funnel-chart", "figure"),
        Output("enrichment-curve", "figure"),
        Output("annotation-pie", "figure"),
        Output("summary-badges", "children"),
        Output("peak-table", "rowData"),
        Output("peak-table", "columnDefs"),
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
        step_data: list[dict[str, Any]] = [{"label": "Total peaks", "count": n_total}]
        per_filter_counts: list[str] = []

        # Visibility outputs
        cat_styles: list[dict] = []
        numeric_styles: list[dict] = []
        threshold_styles: list[dict] = []
        cat_data_options: list[list] = []

        # Track thresholds for scatter plot lines
        fe_threshold: float | None = None
        pval_threshold: float | None = None
        score_threshold: float | None = None

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
                cat_data_options.append([{"value": v, "label": v} for v in cat_unique[col]])
            else:
                cat_data_options.append([])

            if enabled and col:
                step_mask = _apply_single_filter(
                    df[col],
                    col_type,
                    operator,
                    threshold or 0,
                    use_abs,
                    cat_vals,
                )
                cumulative_mask &= step_mask
                count = int(cumulative_mask.sum())
                label = COLUMN_LABELS.get(col, col)
                if is_numeric:
                    abs_prefix = "|" if use_abs else ""
                    abs_suffix = "|" if use_abs else ""
                    step_label = f"{abs_prefix}{label}{abs_suffix} {operator} {threshold}"
                else:
                    short_vals = ", ".join(cat_vals[:3])
                    ellipsis = "..." if len(cat_vals) > 3 else ""
                    step_label = f"{label} in [{short_vals}{ellipsis}]"
                step_data.append({"label": step_label, "count": count})
                per_filter_counts.append(f"{count} pass")

                # Capture thresholds for scatter dynamic lines
                if col == "fold_enrichment" and fe_threshold is None:
                    fe_threshold = threshold or 0
                if col == "neg_log10_pvalue" and pval_threshold is None:
                    pval_threshold = threshold or 0
                if col == "score" and score_threshold is None:
                    score_threshold = threshold or 0
            else:
                per_filter_counts.append("off")

        n_remaining = int(cumulative_mask.sum())
        filtered_df = df[cumulative_mask]

        # Compute promoter % of filtered set
        pct_promoter = 0.0
        if n_remaining > 0:
            pct_promoter = (filtered_df["annotation"] == "Promoter").sum() / n_remaining * 100

        # Build all outputs
        scatter_fig = _build_scatter(df, cumulative_mask, fe_threshold, pval_threshold)
        funnel_fig = _build_funnel(step_data)
        enrichment_fig = _build_enrichment_curve(df, score_threshold)
        pie_fig = _build_annotation_pie(filtered_df)
        summary = _build_summary_badges(n_total, n_remaining, pct_promoter, score_threshold)
        row_data = filtered_df.to_dict("records")

        return (
            scatter_fig,
            funnel_fig,
            enrichment_fig,
            pie_fig,
            summary,
            row_data,
            TABLE_COLUMN_DEFS,
            per_filter_counts,
            cat_styles,
            numeric_styles,
            threshold_styles,
            cat_data_options,
        )
