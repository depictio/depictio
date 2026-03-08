"""Callbacks for the Variant Inspector prototype.

Architecture
------------
1. Main update callback: reads sample selector, AF range, depth/quality filters,
   effect/gene filters, then updates AF histogram, coverage track, lineage chart,
   and variant table.
"""

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output
from data import GENE_REGIONS, GENOME_LENGTH


TABLE_COLUMN_DEFS: list[dict] = [
    {"field": "position", "headerName": "Position", "filter": "agNumberColumnFilter", "pinned": "left", "minWidth": 100, "valueFormatter": {"function": "d3.format(',')(params.value)"}},
    {"field": "ref", "headerName": "Ref", "filter": "agTextColumnFilter", "maxWidth": 60},
    {"field": "alt", "headerName": "Alt", "filter": "agTextColumnFilter", "maxWidth": 60},
    {"field": "alt_freq", "headerName": "AF", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format('.4f')(params.value)"}},
    {"field": "alt_depth", "headerName": "Alt DP", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format(',')(params.value)"}},
    {"field": "total_depth", "headerName": "Total DP", "filter": "agNumberColumnFilter", "valueFormatter": {"function": "d3.format(',')(params.value)"}},
    {"field": "alt_qual", "headerName": "Qual", "filter": "agNumberColumnFilter"},
    {"field": "gene", "headerName": "Gene", "filter": "agTextColumnFilter"},
    {"field": "effect", "headerName": "Effect", "filter": "agTextColumnFilter"},
    {"field": "aa_change", "headerName": "AA Change", "filter": "agTextColumnFilter"},
]


def _build_af_histogram(df: pd.DataFrame) -> go.Figure:
    """Histogram of allele frequencies."""
    fig = go.Figure(
        go.Histogram(
            x=df["alt_freq"],
            nbinsx=40,
            marker=dict(color="#228be6", line=dict(color="white", width=0.5)),
        )
    )
    fig.update_layout(
        title="Allele Frequency Distribution",
        xaxis_title="Allele Frequency",
        yaxis_title="Count",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=60),
    )
    return fig


def _build_coverage_track(
    coverage_df: pd.DataFrame,
    variant_df: pd.DataFrame,
) -> go.Figure:
    """Coverage track with gene annotations and variant positions."""
    fig = go.Figure()

    # Coverage area
    fig.add_trace(
        go.Scatter(
            x=coverage_df["position"],
            y=coverage_df["depth"],
            mode="lines",
            fill="tozeroy",
            line=dict(color="#228be6", width=1),
            fillcolor="rgba(34, 139, 230, 0.2)",
            name="Coverage",
            hovertemplate="Pos: %{x:,}<br>Depth: %{y:,}<extra></extra>",
        )
    )

    # Variant markers on top
    if not variant_df.empty:
        fig.add_trace(
            go.Scatter(
                x=variant_df["position"],
                y=[coverage_df["depth"].max() * 1.05] * len(variant_df),
                mode="markers",
                marker=dict(
                    color=variant_df["alt_freq"],
                    colorscale="RdYlBu_r",
                    size=6,
                    cmin=0,
                    cmax=1,
                    colorbar=dict(title="AF", thickness=12, len=0.5),
                    line=dict(width=0.5, color="black"),
                    symbol="triangle-down",
                ),
                name="Variants",
                text=variant_df.apply(
                    lambda r: f"{r['ref']}>{r['alt']} AF={r['alt_freq']:.2f} {r['gene']}",
                    axis=1,
                ),
                hovertemplate="%{text}<br>Pos: %{x:,}<extra></extra>",
            )
        )

    # Gene region annotations
    max_depth = coverage_df["depth"].max()
    for region in GENE_REGIONS:
        fig.add_vrect(
            x0=region["start"],
            x1=region["end"],
            fillcolor="rgba(0,0,0,0.03)",
            line_width=0,
            annotation_text=str(region["gene"]),
            annotation_position="top left",
            annotation=dict(font_size=9, font_color="gray"),
        )

    fig.update_layout(
        title="Genome Coverage & Variant Positions",
        xaxis_title="Genomic Position",
        yaxis_title="Depth",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=60),
        showlegend=False,
        xaxis=dict(range=[0, GENOME_LENGTH]),
    )
    return fig


def _build_lineage_chart(lineage_df: pd.DataFrame) -> go.Figure:
    """Stacked bar chart of lineage composition per sample."""
    lineages = lineage_df["lineage"].unique().tolist()
    samples = lineage_df["sample"].unique().tolist()

    colors = ["#e63946", "#457b9d", "#2a9d8f", "#e9c46a", "#a8dadc"]

    fig = go.Figure()
    for i, lineage in enumerate(lineages):
        sub = lineage_df[lineage_df["lineage"] == lineage]
        fig.add_trace(
            go.Bar(
                x=sub["sample"],
                y=sub["abundance"],
                name=lineage,
                marker=dict(color=colors[i % len(colors)]),
            )
        )

    fig.update_layout(
        title="Lineage Composition",
        barmode="stack",
        xaxis_title="Sample",
        yaxis_title="Relative Abundance",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def register_callbacks(
    app: Dash,
    variant_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
    lineage_df: pd.DataFrame,
) -> None:
    """Register all Dash callbacks."""

    @app.callback(
        Output("af-histogram", "figure"),
        Output("coverage-track", "figure"),
        Output("lineage-chart", "figure"),
        Output("variant-table", "rowData"),
        Output("variant-table", "columnDefs"),
        Output("variant-summary", "children"),
        Input("sample-selector", "value"),
        Input("af-range-slider", "value"),
        Input("min-depth-input", "value"),
        Input("min-qual-input", "value"),
        Input("effect-filter", "value"),
        Input("gene-filter", "value"),
    )
    def update_main(sample, af_range, min_depth, min_qual, effects, gene):
        sample = sample or variant_df["sample"].iloc[0]
        af_range = af_range or [0, 1]
        min_depth = min_depth or 0
        min_qual = min_qual or 0
        effects = effects or []
        gene = gene or "all"

        # Filter to sample
        sample_df = variant_df[variant_df["sample"] == sample].copy()

        # Apply filters
        mask = (
            (sample_df["alt_freq"] >= af_range[0])
            & (sample_df["alt_freq"] <= af_range[1])
            & (sample_df["total_depth"] >= min_depth)
            & (sample_df["alt_qual"] >= min_qual)
            & (sample_df["effect"].isin(effects))
        )
        if gene != "all":
            mask &= sample_df["gene"] == gene

        filtered = sample_df[mask]

        # Build charts
        af_fig = _build_af_histogram(filtered)
        coverage_fig = _build_coverage_track(coverage_df, filtered)
        lineage_fig = _build_lineage_chart(lineage_df)

        # Table
        row_data = filtered.to_dict("records")

        # Summary
        n_total = len(sample_df)
        n_filtered = len(filtered)
        n_missense = (filtered["effect"] == "missense").sum() if not filtered.empty else 0
        median_af = round(filtered["alt_freq"].median(), 3) if not filtered.empty else 0

        summary = [
            dmc.Badge(f"Sample: {sample}", color="blue", variant="light", size="lg"),
            dmc.Badge(f"{n_filtered}/{n_total} variants", color="teal", variant="light", size="lg"),
            dmc.Badge(f"Missense: {n_missense}", color="red", variant="light", size="lg"),
            dmc.Badge(f"Median AF: {median_af}", color="grape", variant="light", size="lg"),
        ]

        return af_fig, coverage_fig, lineage_fig, row_data, TABLE_COLUMN_DEFS, summary
