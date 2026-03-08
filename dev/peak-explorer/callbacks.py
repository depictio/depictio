"""Callbacks for the Peak Explorer prototype.

Architecture
------------
1. Main update callback: reads sidebar filters, applies to peak data,
   updates annotation pie, width histogram, FRiP bar, consensus heatmap, and table.
"""

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output

# Color palette for annotation categories
ANNOTATION_COLORS: dict[str, str] = {
    "Promoter": "#e63946",
    "5' UTR": "#f4a261",
    "3' UTR": "#e9c46a",
    "Exon": "#2a9d8f",
    "Intron": "#264653",
    "Intergenic": "#a8dadc",
    "TTS": "#457b9d",
}

TABLE_COLUMN_DEFS: list[dict] = [
    {"field": "peak_id", "headerName": "Peak ID", "filter": "agTextColumnFilter", "pinned": "left", "minWidth": 110},
    {"field": "chr", "headerName": "Chr", "filter": "agTextColumnFilter", "maxWidth": 80},
    {"field": "start", "headerName": "Start", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format(',')(params.value)"}},
    {"field": "end", "headerName": "End", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format(',')(params.value)"}},
    {"field": "width", "headerName": "Width", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format(',')(params.value)"}},
    {"field": "score", "headerName": "Score", "filter": "agNumberColumnFilter"},
    {"field": "neg_log10_pvalue", "headerName": "-log10(p)", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
    {"field": "fold_enrichment", "headerName": "Fold Enrich.", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format('.2f')(params.value)"}},
    {"field": "annotation", "headerName": "Annotation", "filter": "agTextColumnFilter"},
    {"field": "nearest_gene", "headerName": "Nearest Gene", "filter": "agTextColumnFilter"},
    {"field": "distance_to_tss", "headerName": "Dist. to TSS", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format(',')(params.value)"}},
]


def _build_annotation_chart(df: pd.DataFrame) -> go.Figure:
    """Pie chart of peak annotation categories."""
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
        title="Peak Annotation Distribution",
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
        showlegend=False,
    )
    return fig


def _build_width_histogram(df: pd.DataFrame) -> go.Figure:
    """Histogram of peak widths."""
    fig = go.Figure(
        go.Histogram(
            x=df["width"],
            nbinsx=50,
            marker=dict(color="#228be6", line=dict(color="white", width=0.5)),
        )
    )
    fig.update_layout(
        title="Peak Width Distribution",
        xaxis_title="Peak Width (bp)",
        yaxis_title="Count",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=60),
    )
    return fig


def _build_frip_chart(frip_df: pd.DataFrame) -> go.Figure:
    """Bar chart of FRiP scores per sample."""
    colors = ["#e63946" if f < 0.1 else "#228be6" for f in frip_df["frip"]]
    fig = go.Figure(
        go.Bar(
            x=frip_df["sample"],
            y=frip_df["frip"],
            marker=dict(color=colors),
            text=frip_df["frip"].apply(lambda x: f"{x:.1%}"),
            textposition="outside",
        )
    )
    fig.add_hline(y=0.1, line_dash="dash", line_color="red", annotation_text="FRiP = 0.1")
    fig.update_layout(
        title="Fraction of Reads in Peaks (FRiP)",
        xaxis_title="Sample",
        yaxis_title="FRiP",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=80),
        yaxis=dict(range=[0, max(frip_df["frip"]) * 1.3]),
    )
    return fig


def _build_consensus_heatmap(
    consensus_df: pd.DataFrame,
    filtered_peaks: list[str],
    min_samples: int,
) -> go.Figure:
    """Heatmap showing which peaks are found across samples."""
    # Filter to only peaks that pass filters
    sub = consensus_df.loc[consensus_df.index.isin(filtered_peaks)]
    # Filter by min samples
    row_sums = sub.sum(axis=1)
    sub = sub[row_sums >= min_samples]

    # Limit display to 100 peaks for performance
    if len(sub) > 100:
        sub = sub.head(100)

    if sub.empty:
        fig = go.Figure()
        fig.update_layout(
            title="Consensus Peaks (no peaks meet criteria)",
            template="plotly_white",
            margin=dict(l=20, r=20, t=50, b=20),
        )
        return fig

    fig = go.Figure(
        go.Heatmap(
            z=sub.values,
            x=sub.columns.tolist(),
            y=sub.index.tolist(),
            colorscale=[[0, "#f8f9fa"], [1, "#228be6"]],
            showscale=False,
        )
    )
    fig.update_layout(
        title=f"Consensus Peaks ({len(sub)} peaks in >= {min_samples} samples)",
        template="plotly_white",
        margin=dict(l=100, r=20, t=50, b=60),
        yaxis=dict(showticklabels=len(sub) <= 40),
    )
    return fig


def register_callbacks(
    app: Dash,
    peak_df: pd.DataFrame,
    consensus_df: pd.DataFrame,
    frip_df: pd.DataFrame,
) -> None:
    """Register all Dash callbacks."""

    @app.callback(
        Output("annotation-chart", "figure"),
        Output("width-histogram", "figure"),
        Output("frip-chart", "figure"),
        Output("consensus-heatmap", "figure"),
        Output("peak-table", "rowData"),
        Output("peak-table", "columnDefs"),
        Output("summary-stats", "children"),
        Input("min-score-input", "value"),
        Input("min-fold-input", "value"),
        Input("annotation-filter", "value"),
        Input("min-samples-input", "value"),
    )
    def update_main(min_score, min_fold, annotations, min_samples):
        min_score = min_score or 0
        min_fold = min_fold or 0
        annotations = annotations or []
        min_samples = min_samples or 1

        # Apply filters
        mask = (
            (peak_df["score"] >= min_score)
            & (peak_df["fold_enrichment"] >= min_fold)
            & (peak_df["annotation"].isin(annotations))
        )
        filtered = peak_df[mask]

        # Build charts
        annotation_fig = _build_annotation_chart(filtered)
        width_fig = _build_width_histogram(filtered)
        frip_fig = _build_frip_chart(frip_df)
        consensus_fig = _build_consensus_heatmap(
            consensus_df, filtered["peak_id"].tolist(), min_samples,
        )

        # Table data
        row_data = filtered.to_dict("records")

        # Summary stats
        n_total = len(peak_df)
        n_filtered = len(filtered)
        median_width = int(filtered["width"].median()) if not filtered.empty else 0
        pct_promoter = (
            (filtered["annotation"] == "Promoter").sum() / max(len(filtered), 1) * 100
        )

        summary = [
            dmc.Badge(f"Total: {n_total}", color="gray", variant="light", size="lg"),
            dmc.Badge(f"Filtered: {n_filtered}", color="blue", variant="light", size="lg"),
            dmc.Badge(f"Median width: {median_width} bp", color="teal", variant="light", size="lg"),
            dmc.Badge(f"Promoter: {pct_promoter:.1f}%", color="red", variant="light", size="lg"),
        ]

        return annotation_fig, width_fig, frip_fig, consensus_fig, row_data, TABLE_COLUMN_DEFS, summary
