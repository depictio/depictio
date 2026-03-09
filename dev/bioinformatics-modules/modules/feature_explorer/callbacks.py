"""Callbacks for the Feature Explorer module.

Single main callback triggered by gene selection and metadata sort column.
Updates violin plot, heatmap row, rank badges, co-expression table,
and external links simultaneously.

Cross-module communication:
- READS from filtered-feature-ids-store: limits gene dropdown to filtered genes
- READS from active-contrast-store: shows DE results for active contrast
- WRITES to active-feature-store: when user selects a gene
- WRITES to selected-features-store: co-expressed genes as selected features
"""

from __future__ import annotations

import dash_mantine_components as dmc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output
from dash_iconify import DashIconify
from scipy import stats
from shared_stores import ACTIVE_CONTRAST, ACTIVE_FEATURE, FILTERED_FEATURE_IDS, SELECTED_FEATURES


def _get_top_correlated(
    gene: str,
    correlation_matrix: pd.DataFrame,
    expression_df: pd.DataFrame,
    n: int = 10,
) -> pd.DataFrame:
    """Return top N most correlated genes for a given gene.

    Returns DataFrame with columns: gene_name, pearson_r, pvalue.
    """
    if gene not in correlation_matrix.index:
        return pd.DataFrame(columns=["gene_name", "pearson_r", "pvalue"])

    corr_series = correlation_matrix[gene].drop(gene).abs().sort_values(ascending=False)
    top_genes = corr_series.head(n).index.tolist()

    rows = []
    gene_vals = expression_df[gene].values
    for other in top_genes:
        r_val = correlation_matrix.loc[gene, other]
        _, p_val = stats.pearsonr(gene_vals, expression_df[other].values)
        rows.append(
            {
                "gene_name": other,
                "pearson_r": round(float(r_val), 4),
                "pvalue": float(p_val),
            }
        )

    return pd.DataFrame(rows)


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


def _build_rank_badges(gene: str, de_results_df: pd.DataFrame, contrast_label: str) -> list:
    """Build DMC Badge components showing DE stats for the gene."""
    match = de_results_df[de_results_df["gene_name"] == gene]
    if match.empty:
        return [dmc.Text("Gene not found in DE results", size="sm", c="dimmed")]

    row = match.iloc[0]
    log2fc = row["log2fc"]
    pvalue = row["pvalue"]
    padj = row["padj"]

    # Compute rank from absolute log2fc
    rank_series = de_results_df["log2fc"].abs().rank(ascending=False, method="min").astype(int)
    gene_idx = match.index[0]
    rank = int(rank_series.loc[gene_idx])
    total = len(de_results_df)

    mean_expr = row.get("mean_expression", None)

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

    badges = [
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
    ]

    if mean_expr is not None:
        badges.append(
            dmc.Badge(
                f"Mean expr: {mean_expr:.2f}",
                color="teal",
                variant="outline",
                size="lg",
            )
        )

    return badges


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


# ── Callback registration ───────────────────────────────────────────────────


def register_callbacks(app: Dash, data: dict) -> None:
    """Register all callbacks for the Feature Explorer module.

    Args:
        app: The Dash application instance.
        data: The data dict from ``shared_data.load_all_data()``.
              Uses ``data["expression_df"]``, ``data["metadata_df"]``,
              ``data["de_results"]``, ``data["correlation_matrix"]``.
    """
    expression_df = data["expression_df"]
    metadata_df = data["metadata_df"]
    de_results = data["de_results"]
    correlation_matrix = data["correlation_matrix"]
    all_gene_names = sorted(data["gene_names"])

    # Default to the first available contrast
    contrast_names = list(de_results.keys())
    default_contrast = contrast_names[0] if contrast_names else None

    # ── Update gene dropdown based on filtered feature IDs ───────────────────
    @app.callback(
        Output("fe-gene-select", "data"),
        Input(FILTERED_FEATURE_IDS, "data"),
    )
    def update_gene_options(filtered_ids):
        if filtered_ids:
            # Limit to genes that pass the progressive filter
            available = [g for g in all_gene_names if g in set(filtered_ids)]
        else:
            # No filter active or empty list: show all genes
            available = all_gene_names
        return [{"value": g, "label": g} for g in sorted(available)]

    # ── Gene selection -> active-feature-store ───────────────────────────────
    @app.callback(
        Output(ACTIVE_FEATURE, "data"),
        Input("fe-gene-select", "value"),
        prevent_initial_call=True,
    )
    def update_active_feature(gene):
        return gene

    # ── Main update callback ─────────────────────────────────────────────────
    @app.callback(
        Output("fe-violin-plot", "figure"),
        Output("fe-heatmap-row", "figure"),
        Output("fe-rank-badges", "children"),
        Output("fe-de-results-title", "children"),
        Output("fe-coexpression-table", "rowData"),
        Output("fe-external-links", "children"),
        # Shared store output: co-expressed genes as selected features
        Output(SELECTED_FEATURES, "data", allow_duplicate=True),
        Input("fe-gene-select", "value"),
        Input("fe-sort-by-meta", "value"),
        Input(ACTIVE_CONTRAST, "data"),
        prevent_initial_call=True,
    )
    def update_all(
        gene: str | None,
        sort_by: str,
        active_contrast: str | None,
    ):
        if not gene or gene not in expression_df.columns:
            empty = _empty_figure("Select a gene")
            return (
                empty,
                empty,
                [dmc.Text("Select a gene", size="sm", c="dimmed")],
                "DE Results",
                [],
                [dmc.Text("Select a gene", size="sm", c="dimmed")],
                [],
            )

        # Determine which contrast's DE data to use
        contrast_key = active_contrast if active_contrast in de_results else default_contrast
        contrast_label = contrast_key.replace("_", " ") if contrast_key else "N/A"

        # ── Violin / strip plot ───────────────────────────────────
        violin_fig = _build_violin(gene, expression_df, metadata_df)

        # ── Heatmap row ───────────────────────────────────────────
        heatmap_fig = _build_heatmap_row(gene, expression_df, metadata_df, sort_by)

        # ── Rank badges ───────────────────────────────────────────
        if contrast_key and contrast_key in de_results:
            de_df = de_results[contrast_key]
            badges = _build_rank_badges(gene, de_df, contrast_label)
        else:
            badges = [dmc.Text("No DE data available", size="sm", c="dimmed")]

        de_title = f"DE Results ({contrast_label})"

        # ── Co-expression table ───────────────────────────────────
        # Only compute for genes present in the correlation matrix
        if gene in correlation_matrix.index:
            coexpr_df = _get_top_correlated(gene, correlation_matrix, expression_df, n=10)
        else:
            coexpr_df = pd.DataFrame(columns=["gene_name", "pearson_r", "pvalue"])
        coexpr_data = coexpr_df.to_dict("records")

        # Write co-expressed gene names to the shared selected-features-store
        coexpr_gene_names = coexpr_df["gene_name"].tolist() if not coexpr_df.empty else []

        # ── External links ────────────────────────────────────────
        links = _build_external_links(gene)

        return violin_fig, heatmap_fig, badges, de_title, coexpr_data, links, coexpr_gene_names
