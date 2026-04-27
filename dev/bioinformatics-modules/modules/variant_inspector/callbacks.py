"""Callbacks for the Variant Inspector module.

Architecture
------------
Single main callback reads all sidebar controls and updates:
- Summary badges row (total, passing, missense, high-confidence)
- AF-vs-Quality quadrant scatter with dynamic threshold lines
- Quadrant count badges
- Filter funnel chart (Total -> AF -> Quality -> Depth -> Effect -> Gene -> Final)
- Cross-sample variant sharing heatmap
- AG Grid variant table
- Sidebar summary badges

Cross-module communication:
- READS from ``highlighted-samples-store``: auto-selects a sample when highlighted.
- WRITES to ``filtered-feature-ids-store``: gene names with passing variants.

All component IDs are prefixed with ``vi-`` to avoid conflicts.
"""

from __future__ import annotations

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output
from shared_stores import FILTERED_FEATURE_IDS, HIGHLIGHTED_SAMPLES

# -- Table column definitions --------------------------------------------------

TABLE_COLUMN_DEFS: list[dict] = [
    {
        "field": "position",
        "headerName": "Position",
        "filter": "agNumberColumnFilter",
        "pinned": "left",
        "minWidth": 100,
        "valueFormatter": {"function": "d3.format(',')(params.value)"},
    },
    {"field": "ref", "headerName": "Ref", "filter": "agTextColumnFilter", "maxWidth": 60},
    {"field": "alt", "headerName": "Alt", "filter": "agTextColumnFilter", "maxWidth": 60},
    {
        "field": "alt_freq",
        "headerName": "AF",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format('.4f')(params.value)"},
    },
    {
        "field": "alt_depth",
        "headerName": "Alt DP",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format(',')(params.value)"},
    },
    {
        "field": "total_depth",
        "headerName": "Total DP",
        "filter": "agNumberColumnFilter",
        "valueFormatter": {"function": "d3.format(',')(params.value)"},
    },
    {"field": "alt_qual", "headerName": "Qual", "filter": "agNumberColumnFilter"},
    {"field": "gene", "headerName": "Gene", "filter": "agTextColumnFilter"},
    {"field": "effect", "headerName": "Effect", "filter": "agTextColumnFilter"},
    {"field": "aa_change", "headerName": "AA Change", "filter": "agTextColumnFilter"},
    {"field": "quadrant", "headerName": "Quadrant", "filter": "agTextColumnFilter"},
]


# -- Quadrant definitions ------------------------------------------------------

QUADRANT_CONFIG = {
    "Confident Fixed": {"color": "#2b8a3e", "symbol": "circle"},
    "Confident Minority": {"color": "#1971c2", "symbol": "diamond"},
    "Uncertain Fixed": {"color": "#e8590c", "symbol": "square"},
    "Noise": {"color": "#868e96", "symbol": "x"},
}


def _classify_quadrant(af: float, qual: float, af_thresh: float, qual_thresh: float) -> str:
    """Classify a variant into one of the four quadrants."""
    high_af = af >= af_thresh
    high_qual = qual >= qual_thresh
    if high_af and high_qual:
        return "Confident Fixed"
    if not high_af and high_qual:
        return "Confident Minority"
    if high_af and not high_qual:
        return "Uncertain Fixed"
    return "Noise"


# -- Chart builders ------------------------------------------------------------


def _build_quadrant_scatter(
    df: pd.DataFrame,
    af_thresh: float,
    qual_thresh: float,
) -> go.Figure:
    """AF-vs-Quality scatter with dynamic threshold lines and quadrant coloring."""
    fig = go.Figure()

    if not df.empty:
        for quadrant_name, cfg in QUADRANT_CONFIG.items():
            subset = df[df["quadrant"] == quadrant_name]
            if subset.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=subset["alt_freq"],
                    y=subset["alt_qual"],
                    mode="markers",
                    name=quadrant_name,
                    marker=dict(
                        color=cfg["color"],
                        symbol=cfg["symbol"],
                        size=7,
                        opacity=0.7,
                        line=dict(width=0.5, color="white"),
                    ),
                    text=subset.apply(
                        lambda r: (
                            f"{r['gene']} {r['ref']}>{r['alt']}<br>"
                            f"AF={r['alt_freq']:.3f} Qual={r['alt_qual']}<br>"
                            f"Pos={r['position']:,}"
                        ),
                        axis=1,
                    ),
                    hovertemplate="%{text}<extra>%{fullData.name}</extra>",
                )
            )

    # Dynamic threshold lines
    fig.add_vline(
        x=af_thresh,
        line_dash="dash",
        line_color="red",
        line_width=1.5,
        annotation_text=f"AF={af_thresh}",
        annotation_position="top",
    )
    fig.add_hline(
        y=qual_thresh,
        line_dash="dash",
        line_color="red",
        line_width=1.5,
        annotation_text=f"Qual={qual_thresh}",
        annotation_position="right",
    )

    # Quadrant background shading
    max_qual = max(250, qual_thresh * 1.5)
    fig.add_shape(
        type="rect",
        x0=af_thresh,
        x1=1,
        y0=qual_thresh,
        y1=max_qual,
        fillcolor="rgba(43,138,62,0.05)",
        line_width=0,
        layer="below",
    )
    fig.add_shape(
        type="rect",
        x0=0,
        x1=af_thresh,
        y0=qual_thresh,
        y1=max_qual,
        fillcolor="rgba(25,113,194,0.05)",
        line_width=0,
        layer="below",
    )
    fig.add_shape(
        type="rect",
        x0=af_thresh,
        x1=1,
        y0=0,
        y1=qual_thresh,
        fillcolor="rgba(232,89,12,0.05)",
        line_width=0,
        layer="below",
    )
    fig.add_shape(
        type="rect",
        x0=0,
        x1=af_thresh,
        y0=0,
        y1=qual_thresh,
        fillcolor="rgba(134,142,150,0.05)",
        line_width=0,
        layer="below",
    )

    fig.update_layout(
        title="AF vs Quality — Quadrant Classification",
        xaxis_title="Allele Frequency",
        yaxis_title="Variant Quality",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=60),
        xaxis=dict(range=[-0.02, 1.02]),
        yaxis=dict(range=[0, max_qual]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def _build_filter_funnel(funnel_data: list[dict]) -> go.Figure:
    """Funnel chart showing the filter cascade."""
    labels = [d["stage"] for d in funnel_data]
    values = [d["count"] for d in funnel_data]

    fig = go.Figure(
        go.Funnel(
            y=labels,
            x=values,
            textinfo="value+percent initial",
            marker=dict(
                color=[
                    "#228be6",
                    "#12b886",
                    "#e8590c",
                    "#7048e8",
                    "#e63946",
                    "#1971c2",
                ],
            ),
            connector=dict(line=dict(color="lightgray", width=1)),
        )
    )
    fig.update_layout(
        title="Filter Funnel",
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def _build_sharing_heatmap(
    variant_df: pd.DataFrame,
    filtered_positions: set,
    all_samples: list[str],
) -> go.Figure:
    """Cross-sample variant sharing heatmap.

    For filtered variant positions, show which positions are present in each sample.
    Rows = positions, columns = samples, color = present/absent.
    """
    fig = go.Figure()

    if not filtered_positions:
        fig.update_layout(
            title="Cross-Sample Variant Sharing",
            template="plotly_white",
            margin=dict(l=60, r=20, t=50, b=60),
            annotations=[
                dict(
                    text="No variants to display",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=14, color="gray"),
                )
            ],
        )
        return fig

    # Build presence/absence matrix
    positions_sorted = sorted(filtered_positions)

    # Cap display at 80 positions for readability
    if len(positions_sorted) > 80:
        step = len(positions_sorted) // 80
        positions_sorted = positions_sorted[::step]

    # Subset the full dataframe to these positions across ALL samples
    pos_sample_df = variant_df[variant_df["position"].isin(positions_sorted)]

    # Use a pivot approach for efficiency
    presence = pos_sample_df.groupby(["position", "sample"]).size().reset_index(name="count")
    presence["present"] = 1

    matrix = []
    for pos in positions_sorted:
        row = []
        for sample in all_samples:
            hit = ((presence["position"] == pos) & (presence["sample"] == sample)).any()
            row.append(1 if hit else 0)
        matrix.append(row)

    matrix_arr = np.array(matrix)

    fig.add_trace(
        go.Heatmap(
            z=matrix_arr,
            x=all_samples,
            y=[str(p) for p in positions_sorted],
            colorscale=[[0, "#f1f3f5"], [1, "#228be6"]],
            showscale=False,
            hovertemplate="Sample: %{x}<br>Position: %{y}<br>Present: %{z}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Cross-Sample Variant Sharing (filtered positions)",
        xaxis_title="Sample",
        yaxis_title="Genomic Position",
        template="plotly_white",
        margin=dict(l=80, r=20, t=50, b=80),
        yaxis=dict(type="category", autorange="reversed"),
        xaxis=dict(tickangle=-45),
    )
    return fig


# -- Callback registration ----------------------------------------------------


def register_callbacks(app: Dash, data: dict) -> None:
    """Register all Dash callbacks.

    Args:
        app: The Dash application instance.
        data: The data dict from ``shared_data.load_all_data()``.
    """
    variant_df = data["variant_df"]
    all_samples = sorted(variant_df["sample"].unique().tolist())

    @app.callback(
        Output("vi-summary-badges", "children"),
        Output("vi-quadrant-scatter", "figure"),
        Output("vi-quadrant-badges", "children"),
        Output("vi-filter-funnel", "figure"),
        Output("vi-sharing-heatmap", "figure"),
        Output("vi-variant-table", "rowData"),
        Output("vi-variant-table", "columnDefs"),
        Output("vi-sidebar-summary", "children"),
        Output(FILTERED_FEATURE_IDS, "data", allow_duplicate=True),
        Input("vi-sample-selector", "value"),
        Input("vi-af-threshold-slider", "value"),
        Input("vi-qual-threshold-slider", "value"),
        Input("vi-depth-threshold-input", "value"),
        Input("vi-effect-filter", "value"),
        Input("vi-gene-filter", "value"),
        Input(HIGHLIGHTED_SAMPLES, "data"),
        prevent_initial_call="initial_duplicate",
    )
    def update_main(
        sample: str | None,
        af_thresh: float | None,
        qual_thresh: float | None,
        depth_thresh: int | None,
        effects: list[str] | None,
        gene: str | None,
        highlighted_samples: list[str] | None,
    ):
        # Auto-select sample from highlighted samples if available
        highlighted_samples = highlighted_samples or []
        if highlighted_samples and not sample:
            # Pick the first highlighted sample that exists in our data
            for hs in highlighted_samples:
                if hs in all_samples:
                    sample = hs
                    break

        sample = sample or variant_df["sample"].iloc[0]
        af_thresh = af_thresh if af_thresh is not None else 0.5
        qual_thresh = qual_thresh if qual_thresh is not None else 100
        depth_thresh = depth_thresh if depth_thresh is not None else 0
        effects = effects or []
        gene = gene or "all"

        # -- Filter cascade (track counts at each stage) -------------------
        sample_df = variant_df[variant_df["sample"] == sample].copy()
        n_total = len(sample_df)

        # Stage 1: AF filter
        af_mask = sample_df["alt_freq"] >= af_thresh
        n_after_af = int(af_mask.sum())

        # Stage 2: Quality filter
        qual_mask = sample_df["alt_qual"] >= qual_thresh
        n_after_qual = int((af_mask & qual_mask).sum())

        # Stage 3: Depth filter
        depth_mask = sample_df["total_depth"] >= depth_thresh
        n_after_depth = int((af_mask & qual_mask & depth_mask).sum())

        # Stage 4: Effect filter
        effect_mask = sample_df["effect"].isin(effects)
        n_after_effect = int((af_mask & qual_mask & depth_mask & effect_mask).sum())

        # Stage 5: Gene filter
        if gene != "all":
            gene_mask = sample_df["gene"] == gene
        else:
            gene_mask = pd.Series(True, index=sample_df.index)
        final_mask = af_mask & qual_mask & depth_mask & effect_mask & gene_mask
        filtered = sample_df[final_mask].copy()
        n_final = len(filtered)

        # -- Quadrant classification (on full sample_df for scatter) -------
        sample_df["quadrant"] = sample_df.apply(
            lambda r: _classify_quadrant(r["alt_freq"], r["alt_qual"], af_thresh, qual_thresh),
            axis=1,
        )
        filtered["quadrant"] = filtered.apply(
            lambda r: _classify_quadrant(r["alt_freq"], r["alt_qual"], af_thresh, qual_thresh),
            axis=1,
        )

        # Quadrant counts (on all sample variants for the scatter)
        q_counts = {}
        for qname in QUADRANT_CONFIG:
            q_counts[qname] = int((sample_df["quadrant"] == qname).sum())

        # High-confidence = Confident Fixed
        n_high_conf = q_counts.get("Confident Fixed", 0)
        n_missense = int((filtered["effect"] == "missense").sum()) if not filtered.empty else 0

        # -- Build outputs -------------------------------------------------

        # Summary badges row (main area top)
        summary_badges = [
            dmc.Badge(f"Total: {n_total}", color="blue", variant="light", size="lg"),
            dmc.Badge(f"Passing: {n_final}", color="teal", variant="light", size="lg"),
            dmc.Badge(f"Missense: {n_missense}", color="red", variant="light", size="lg"),
            dmc.Badge(
                f"High-Confidence: {n_high_conf}",
                color="green",
                variant="light",
                size="lg",
            ),
        ]

        # Quadrant scatter
        scatter_fig = _build_quadrant_scatter(sample_df, af_thresh, qual_thresh)

        # Quadrant count badges
        quadrant_badges = []
        for qname, cfg in QUADRANT_CONFIG.items():
            quadrant_badges.append(
                dmc.Badge(
                    f"{qname}: {q_counts.get(qname, 0)}",
                    color=cfg["color"],
                    variant="outline",
                    size="sm",
                    styles={"root": {"borderColor": cfg["color"], "color": cfg["color"]}},
                )
            )

        # Filter funnel (6 stages: Total -> AF -> Quality -> Depth -> Effect -> Gene)
        funnel_data = [
            {"stage": "Total", "count": n_total},
            {"stage": "AF Filter", "count": n_after_af},
            {"stage": "Quality", "count": n_after_qual},
            {"stage": "Depth", "count": n_after_depth},
            {"stage": "Effect Type", "count": n_after_effect},
            {"stage": "Gene", "count": n_final},
        ]
        funnel_fig = _build_filter_funnel(funnel_data)

        # Cross-sample sharing heatmap
        filtered_positions = set(filtered["position"].tolist()) if not filtered.empty else set()
        heatmap_fig = _build_sharing_heatmap(variant_df, filtered_positions, all_samples)

        # Table data
        row_data = filtered.to_dict("records")

        # Sidebar summary
        sidebar_summary = [
            dmc.Badge(f"Sample: {sample}", color="blue", variant="light", size="lg"),
            dmc.Badge(f"{n_final}/{n_total} variants", color="teal", variant="light", size="lg"),
            dmc.Badge(f"Missense: {n_missense}", color="red", variant="light", size="lg"),
            dmc.Badge(
                f"Confident Fixed: {n_high_conf}",
                color="green",
                variant="light",
                size="lg",
            ),
        ]

        # Cross-module: write gene names with passing variants
        filtered_gene_names = (
            filtered[filtered["gene"] != "intergenic"]["gene"].unique().tolist()
            if not filtered.empty
            else []
        )

        return (
            summary_badges,
            scatter_fig,
            quadrant_badges,
            funnel_fig,
            heatmap_fig,
            row_data,
            TABLE_COLUMN_DEFS,
            sidebar_summary,
            filtered_gene_names,
        )
