"""Callbacks for the single-gene deep-dive explorer.

Single main callback triggered by gene selection and metadata sort column.
Updates violin plot, heatmap row, rank badges, co-expression table,
and external links simultaneously.
"""

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, no_update
from dash_iconify import DashIconify

from data import get_top_correlated


def register_callbacks(
    app: Dash,
    expression_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    de_results_df: pd.DataFrame,
    correlation_df: pd.DataFrame,
) -> None:
    """Register all callbacks on the given app."""

    @app.callback(
        Output("violin-plot", "figure"),
        Output("heatmap-row", "figure"),
        Output("rank-badges", "children"),
        Output("coexpression-table", "rowData"),
        Output("external-links", "children"),
        Input("gene-select", "value"),
        Input("sort-by-meta", "value"),
    )
    def update_all(
        gene: str | None,
        sort_by: str,
    ):
        if not gene or gene not in expression_df.columns:
            empty = _empty_figure("Select a gene")
            return (
                empty,
                empty,
                [dmc.Text("Select a gene", size="sm", c="dimmed")],
                [],
                [dmc.Text("Select a gene", size="sm", c="dimmed")],
            )

        # ── Violin / strip plot ───────────────────────────────────
        violin_fig = _build_violin(gene, expression_df, metadata_df)

        # ── Heatmap row ───────────────────────────────────────────
        heatmap_fig = _build_heatmap_row(gene, expression_df, metadata_df, sort_by)

        # ── Rank badges ───────────────────────────────────────────
        badges = _build_rank_badges(gene, de_results_df)

        # ── Co-expression table ───────────────────────────────────
        coexpr_df = get_top_correlated(gene, correlation_df, expression_df, n=10)
        coexpr_data = coexpr_df.to_dict("records")

        # ── External links ────────────────────────────────────────
        links = _build_external_links(gene)

        return violin_fig, heatmap_fig, badges, coexpr_data, links


def _build_violin(
    gene: str,
    expression_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> go.Figure:
    """Build a violin + jittered strip plot for the gene across conditions."""
    plot_df = metadata_df.copy()
    plot_df["expression"] = expression_df[gene].values

    fig = px.violin(
        plot_df,
        x="condition",
        y="expression",
        color="condition",
        box=True,
        points="all",
        hover_data=["sample_id", "batch", "cell_type"],
        title=f"Expression of {gene} across conditions",
        labels={"expression": "Expression (log2)", "condition": "Condition"},
    )
    fig.update_traces(
        pointpos=0,
        jitter=0.4,
        marker=dict(size=5, opacity=0.7),
    )
    fig.update_layout(
        template="plotly_white",
        showlegend=False,
        margin=dict(l=60, r=20, t=50, b=60),
    )
    return fig


def _build_heatmap_row(
    gene: str,
    expression_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    sort_by: str,
) -> go.Figure:
    """Build a single-row heatmap of gene expression across sorted samples."""
    sorted_meta = metadata_df.sort_values(sort_by)
    sample_order = sorted_meta["sample_id"].tolist()
    values = expression_df.loc[sample_order, gene].values

    # Build hover text with metadata
    hover_text = []
    for _, row in sorted_meta.iterrows():
        expr_val = expression_df.loc[row["sample_id"], gene]
        hover_text.append(
            f"{row['sample_id']}<br>"
            f"Condition: {row['condition']}<br>"
            f"Batch: {row['batch']}<br>"
            f"Cell type: {row['cell_type']}<br>"
            f"Expression: {expr_val:.3f}"
        )

    fig = go.Figure(
        go.Heatmap(
            z=[values],
            x=sample_order,
            y=[gene],
            colorscale="Viridis",
            colorbar=dict(title="Expr", thickness=15, len=0.9),
            hovertext=[hover_text],
            hoverinfo="text",
        )
    )
    fig.update_layout(
        title=f"{gene} expression across samples (sorted by {sort_by})",
        template="plotly_white",
        xaxis=dict(tickangle=45, tickfont=dict(size=8)),
        yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=40, b=80),
        height=160,
    )
    return fig


def _build_rank_badges(gene: str, de_results_df: pd.DataFrame) -> list:
    """Build DMC Badge components showing DE stats for the gene."""
    match = de_results_df[de_results_df["gene_name"] == gene]
    if match.empty:
        return [dmc.Text("Gene not found in DE results", size="sm", c="dimmed")]

    row = match.iloc[0]
    log2fc = row["log2fc"]
    pvalue = row["pvalue"]
    padj = row["padj"]
    rank = int(row["rank"])
    total = len(de_results_df)

    # Color log2fc badge by direction
    fc_color = "red" if log2fc > 0 else "blue"

    # Color rank badge by percentile
    percentile = rank / total
    if percentile <= 0.05:
        rank_color = "red"
    elif percentile <= 0.20:
        rank_color = "orange"
    else:
        rank_color = "gray"

    # Color p-value badge
    if padj < 0.001:
        p_color = "red"
    elif padj < 0.05:
        p_color = "orange"
    else:
        p_color = "gray"

    return [
        dmc.Badge(
            f"log2FC: {log2fc:+.3f}",
            color=fc_color,
            variant="light",
            size="lg",
            leftSection=DashIconify(icon="mdi:arrow-up-down", width=14),
        ),
        dmc.Badge(
            f"p-value: {pvalue:.2e}",
            color=p_color,
            variant="light",
            size="lg",
            leftSection=DashIconify(icon="mdi:chart-bell-curve", width=14),
        ),
        dmc.Badge(
            f"p-adj: {padj:.2e}",
            color=p_color,
            variant="outline",
            size="lg",
        ),
        dmc.Badge(
            f"Rank: {rank} / {total}",
            color=rank_color,
            variant="light",
            size="lg",
            leftSection=DashIconify(icon="mdi:podium", width=14),
        ),
        dmc.Badge(
            f"Mean expr: {row['mean_expression']:.2f}",
            color="teal",
            variant="outline",
            size="lg",
        ),
    ]


def _build_external_links(gene: str) -> list:
    """Build auto-generated external links for a gene."""
    links = [
        {
            "label": "Ensembl",
            "url": f"https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={gene}",
            "icon": "mdi:database-search",
        },
        {
            "label": "NCBI Gene",
            "url": f"https://www.ncbi.nlm.nih.gov/gene/?term={gene}",
            "icon": "mdi:database",
        },
        {
            "label": "UniProt",
            "url": f"https://www.uniprot.org/uniprot/?query={gene}+AND+organism_id:9606",
            "icon": "mdi:protein",
        },
        {
            "label": "GeneCards",
            "url": f"https://www.genecards.org/cgi-bin/carddisp.pl?gene={gene}",
            "icon": "mdi:card-text",
        },
    ]

    return [
        dmc.Anchor(
            dmc.Group(
                [
                    DashIconify(icon=link["icon"], width=16),
                    link["label"],
                ],
                gap=4,
            ),
            href=link["url"],
            target="_blank",
            underline="hover",
            size="sm",
        )
        for link in links
    ]


def _empty_figure(title: str) -> go.Figure:
    """Return an empty placeholder figure."""
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        title=title,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text="Select a gene to view data",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color="gray"),
            )
        ],
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig
