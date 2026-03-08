"""Callbacks for the Taxonomy Browser prototype.

Architecture
------------
1. Main update callback: reads rank selector, top-N, relative toggle, and condition
   filter, then updates stacked bar, alpha diversity, sunburst, and table.
"""

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output
from data import (
    RANK_ORDER,
    aggregate_by_rank,
    compute_alpha_diversity,
    compute_relative_abundance,
)

# Qualitative color palette for taxa
TAXA_COLORS: list[str] = [
    "#e63946", "#457b9d", "#2a9d8f", "#e9c46a", "#f4a261",
    "#264653", "#a8dadc", "#d62828", "#023e8a", "#0077b6",
    "#00b4d8", "#90be6d", "#f9844a", "#577590", "#43aa8b",
    "#f8961e", "#f3722c", "#4d908e", "#277da1", "#9b5de5",
]

TABLE_COLUMN_DEFS_BASE: list[dict] = [
    {"field": "taxon", "headerName": "Taxon", "filter": "agTextColumnFilter", "pinned": "left", "minWidth": 150},
]


def _build_stacked_bar(
    agg_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    top_n: int,
    relative: bool,
    conditions: list[str],
) -> go.Figure:
    """Stacked bar chart of taxonomic abundance per sample."""
    # Filter samples by condition
    valid_samples = metadata_df[metadata_df["condition"].isin(conditions)]["sample_id"].tolist()
    agg_df = agg_df[[c for c in agg_df.columns if c in valid_samples]]

    if relative:
        agg_df = agg_df.div(agg_df.sum(axis=0), axis=1)

    # Get top N taxa by mean abundance
    mean_abund = agg_df.mean(axis=1).sort_values(ascending=False)
    top_taxa = mean_abund.head(top_n).index.tolist()

    # Group the rest as "Other"
    plot_df = agg_df.loc[agg_df.index.isin(top_taxa)].copy()
    other = agg_df.loc[~agg_df.index.isin(top_taxa)].sum(axis=0)
    if other.sum() > 0:
        plot_df.loc["Other"] = other

    # Sort samples by condition
    sample_order = metadata_df[metadata_df["sample_id"].isin(agg_df.columns)].sort_values("condition")["sample_id"].tolist()
    plot_df = plot_df[[c for c in sample_order if c in plot_df.columns]]

    fig = go.Figure()
    taxa_list = plot_df.index.tolist()
    for i, taxon in enumerate(taxa_list):
        color = TAXA_COLORS[i % len(TAXA_COLORS)] if taxon != "Other" else "#cccccc"
        fig.add_trace(
            go.Bar(
                x=plot_df.columns.tolist(),
                y=plot_df.loc[taxon].values,
                name=taxon,
                marker=dict(color=color),
            )
        )

    yaxis_title = "Relative Abundance" if relative else "Read Count"
    fig.update_layout(
        title=f"Taxonomic Composition (top {top_n})",
        barmode="stack",
        xaxis_title="Sample",
        yaxis_title=yaxis_title,
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def _build_alpha_diversity(
    counts_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    conditions: list[str],
) -> go.Figure:
    """Box plot of Shannon diversity by condition."""
    diversity = compute_alpha_diversity(counts_df)
    # Merge with metadata
    merged = diversity.merge(metadata_df, left_on="sample", right_on="sample_id")
    merged = merged[merged["condition"].isin(conditions)]

    fig = go.Figure()
    for cond in conditions:
        sub = merged[merged["condition"] == cond]
        fig.add_trace(
            go.Box(
                y=sub["shannon"],
                name=cond,
                boxpoints="all",
                jitter=0.3,
                pointpos=-1.8,
            )
        )

    fig.update_layout(
        title="Alpha Diversity (Shannon Index)",
        yaxis_title="Shannon Index",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=40),
        showlegend=False,
    )
    return fig


def _build_sunburst(
    abundance_df: pd.DataFrame,
    taxonomy_df: pd.DataFrame,
) -> go.Figure:
    """Sunburst chart showing hierarchical taxonomy."""
    # Sum across samples for overall abundance
    total_counts = abundance_df.sum(axis=1)

    ids = []
    labels = []
    parents = []
    values = []

    # Build hierarchy from taxonomy
    for rank_idx, rank in enumerate(RANK_ORDER):
        groups = taxonomy_df.groupby(RANK_ORDER[:rank_idx + 1])
        for group_key, group_df in groups:
            if isinstance(group_key, str):
                group_key = (group_key,)
            taxon_name = group_key[-1]
            node_id = "/".join(group_key)

            if rank_idx == 0:
                parent_id = ""
            else:
                parent_id = "/".join(group_key[:-1])

            total = total_counts[group_df.index].sum()

            if node_id not in ids:
                ids.append(node_id)
                labels.append(taxon_name)
                parents.append(parent_id)
                values.append(int(total))

    fig = go.Figure(
        go.Sunburst(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            maxdepth=3,
        )
    )
    fig.update_layout(
        title="Taxonomic Hierarchy (Sunburst)",
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def register_callbacks(
    app: Dash,
    abundance_df: pd.DataFrame,
    taxonomy_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> None:
    """Register all Dash callbacks."""

    @app.callback(
        Output("stacked-bar-chart", "figure"),
        Output("alpha-diversity-chart", "figure"),
        Output("sunburst-chart", "figure"),
        Output("abundance-table", "rowData"),
        Output("abundance-table", "columnDefs"),
        Output("taxonomy-summary", "children"),
        Input("rank-selector", "value"),
        Input("top-n-input", "value"),
        Input("relative-toggle", "checked"),
        Input("condition-filter", "value"),
    )
    def update_main(rank, top_n, relative, conditions):
        rank = rank or "phylum"
        top_n = top_n or 10
        conditions = conditions or ["Healthy", "Disease"]

        # Aggregate by selected rank
        agg_df = aggregate_by_rank(abundance_df, taxonomy_df, rank)

        # Build charts
        bar_fig = _build_stacked_bar(agg_df, metadata_df, top_n, relative, conditions)
        alpha_fig = _build_alpha_diversity(abundance_df, metadata_df, conditions)
        sunburst_fig = _build_sunburst(abundance_df, taxonomy_df)

        # Table data
        valid_samples = metadata_df[metadata_df["condition"].isin(conditions)]["sample_id"].tolist()
        table_agg = agg_df[[c for c in agg_df.columns if c in valid_samples]]
        if relative:
            table_agg = table_agg.div(table_agg.sum(axis=0), axis=1)

        table_df = table_agg.reset_index()
        table_df = table_df.rename(columns={rank: "taxon"})
        # Round numeric columns
        for col in table_df.columns:
            if col != "taxon":
                table_df[col] = table_df[col].round(4)

        row_data = table_df.to_dict("records")
        col_defs = TABLE_COLUMN_DEFS_BASE.copy()
        for sample in [c for c in table_df.columns if c != "taxon"]:
            fmt = "d3.format('.4f')(params.value)" if relative else "d3.format(',')(params.value)"
            col_defs.append(
                {"field": sample, "headerName": sample, "filter": "agNumberColumnFilter", "valueFormatter": {"function": fmt}}
            )

        # Summary
        n_taxa = len(agg_df)
        n_samples = len(valid_samples)
        summary = [
            dmc.Badge(f"Rank: {rank}", color="blue", variant="light", size="lg"),
            dmc.Badge(f"{n_taxa} taxa", color="teal", variant="light", size="lg"),
            dmc.Badge(f"{n_samples} samples", color="grape", variant="light", size="lg"),
        ]

        return bar_fig, alpha_fig, sunburst_fig, row_data, col_defs, summary
