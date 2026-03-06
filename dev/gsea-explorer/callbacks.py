"""Callbacks for the GSEA explorer.

Handles contrast/source filtering, enrichment table updates, running ES plot,
dot plot summary, and leading edge heatmap.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, no_update


def _empty_figure(msg: str = "Select a pathway") -> go.Figure:
    """Return a placeholder figure with a centered message."""
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=msg,
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


def _compute_running_es(
    ranked_genes_df: pd.DataFrame,
    gene_set: list[str],
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Compute the running enrichment score.

    Walk through the ranked gene list. When a gene is in the set,
    increment proportional to its |rank_metric|. Otherwise decrement.

    Returns:
        positions: array of rank positions (x-axis)
        running_es: array of running ES values (y-axis)
        hit_indices: indices where the gene is in the set (for barcode)
    """
    genes = ranked_genes_df["gene_name"].values
    metrics = np.abs(ranked_genes_df["log2fc"].values)
    n = len(genes)

    gene_set_lookup = set(gene_set)
    is_hit = np.array([g in gene_set_lookup for g in genes])

    # Weighted increment for hits
    hit_weights = metrics * is_hit
    total_hit_weight = hit_weights.sum()
    if total_hit_weight == 0:
        total_hit_weight = 1.0

    # Decrement for misses
    n_miss = (~is_hit).sum()
    if n_miss == 0:
        n_miss = 1

    running_es = np.zeros(n)
    for i in range(n):
        if is_hit[i]:
            running_es[i] = (running_es[i - 1] if i > 0 else 0) + hit_weights[i] / total_hit_weight
        else:
            running_es[i] = (running_es[i - 1] if i > 0 else 0) - 1.0 / n_miss

    positions = np.arange(1, n + 1)
    hit_indices = np.where(is_hit)[0].tolist()

    return positions, running_es, hit_indices


def register_callbacks(
    app: Dash,
    enrichment_df: pd.DataFrame,
    ranked_genes: dict[str, pd.DataFrame],
    expression_df: pd.DataFrame,
    sample_meta_df: pd.DataFrame,
) -> None:
    """Register all callbacks on the given app."""

    # ── 1. Filter enrichment table ────────────────────────────────
    @app.callback(
        Output("enrichment-table", "rowData"),
        Input("contrast-select", "value"),
        Input("source-filter", "value"),
    )
    def update_table(contrast: str, sources: list[str]):
        if not contrast or not sources:
            return []
        mask = (enrichment_df["contrast"] == contrast) & (enrichment_df["source"].isin(sources))
        filtered = enrichment_df.loc[mask].copy()
        filtered = filtered.sort_values("padj")
        # Drop columns not needed in the table
        display_cols = ["pathway_name", "NES", "padj", "leading_edge_size", "gene_set_size", "source"]
        return filtered[display_cols].to_dict("records")

    # ── 2. Running ES plot on row selection ────────────────────────
    @app.callback(
        Output("running-es-plot", "figure"),
        Input("enrichment-table", "selectedRows"),
        Input("contrast-select", "value"),
    )
    def update_running_es(selected_rows, contrast: str):
        if not selected_rows or not contrast:
            return _empty_figure("Click a row in the table to see the enrichment score plot")

        row = selected_rows[0]
        pathway_name = row["pathway_name"]

        # Find the full record
        rec = enrichment_df[
            (enrichment_df["contrast"] == contrast)
            & (enrichment_df["pathway_name"] == pathway_name)
        ]
        if rec.empty:
            return _empty_figure("Pathway not found for this contrast")

        rec = rec.iloc[0]
        gene_set = rec["gene_set"]
        ranked_df = ranked_genes[contrast]

        positions, running_es, hit_indices = _compute_running_es(ranked_df, gene_set)

        fig = go.Figure()

        # Running ES line
        fig.add_trace(
            go.Scatter(
                x=positions,
                y=running_es,
                mode="lines",
                name="Running ES",
                line=dict(color="#2563eb", width=2),
            )
        )

        # Zero line
        fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)

        # Mark the ES (max absolute value)
        es_idx = int(np.argmax(np.abs(running_es)))
        es_val = running_es[es_idx]
        fig.add_trace(
            go.Scatter(
                x=[positions[es_idx]],
                y=[es_val],
                mode="markers",
                name=f"ES = {es_val:.3f}",
                marker=dict(size=10, color="#dc2626", symbol="diamond"),
            )
        )

        # Barcode (gene hits) as vertical bars at bottom
        barcode_y_min = min(running_es.min(), 0) - 0.08
        barcode_y_max = barcode_y_min + 0.04
        for hi in hit_indices:
            fig.add_shape(
                type="line",
                x0=positions[hi],
                x1=positions[hi],
                y0=barcode_y_min,
                y1=barcode_y_max,
                line=dict(color="black", width=0.5),
            )

        nes_val = rec["NES"]
        padj_val = rec["padj"]
        fig.update_layout(
            template="plotly_white",
            title=f"{pathway_name}  (NES={nes_val:.2f}, p-adj={padj_val:.2e})",
            xaxis_title="Gene Rank",
            yaxis_title="Running Enrichment Score",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.25),
            margin=dict(l=60, r=20, t=50, b=80),
        )

        return fig

    # ── 3. Dot plot summary ────────────────────────────────────────
    @app.callback(
        Output("dot-plot", "figure"),
        Input("contrast-select", "value"),
        Input("source-filter", "value"),
        Input("top-n-slider", "value"),
    )
    def update_dot_plot(contrast: str, sources: list[str], top_n: int):
        if not contrast or not sources:
            return _empty_figure("No data to display")

        mask = (enrichment_df["contrast"] == contrast) & (enrichment_df["source"].isin(sources))
        filtered = enrichment_df.loc[mask].copy()
        # Top N by |NES|
        filtered["abs_NES"] = filtered["NES"].abs()
        filtered = filtered.nlargest(top_n, "abs_NES")
        filtered = filtered.sort_values("NES")

        # -log10(padj) for color, capped
        filtered["neg_log10_padj"] = -np.log10(filtered["padj"].clip(lower=1e-10))

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=filtered["NES"],
                y=filtered["pathway_name"],
                mode="markers",
                marker=dict(
                    size=filtered["gene_set_size"].clip(upper=300) / 10 + 4,
                    color=filtered["neg_log10_padj"],
                    colorscale="Viridis",
                    colorbar=dict(title="-log10(p-adj)", thickness=12, len=0.6),
                    line=dict(width=0.5, color="white"),
                ),
                text=[
                    f"NES: {nes:.2f}<br>p-adj: {p:.2e}<br>Size: {s}"
                    for nes, p, s in zip(
                        filtered["NES"], filtered["padj"], filtered["gene_set_size"], strict=False
                    )
                ],
                hoverinfo="text+y",
            )
        )

        fig.add_vline(x=0, line_dash="dash", line_color="gray", line_width=1)

        fig.update_layout(
            template="plotly_white",
            title=f"Top {top_n} Pathways by |NES|",
            xaxis_title="Normalized Enrichment Score (NES)",
            yaxis=dict(tickfont=dict(size=10)),
            margin=dict(l=200, r=30, t=50, b=60),
        )

        return fig

    # ── 4. Leading edge heatmap ────────────────────────────────────
    @app.callback(
        Output("le-heatmap", "figure"),
        Input("enrichment-table", "selectedRows"),
        Input("contrast-select", "value"),
    )
    def update_le_heatmap(selected_rows, contrast: str):
        if not selected_rows or not contrast:
            return _empty_figure("Click a row to see the leading edge heatmap")

        row = selected_rows[0]
        pathway_name = row["pathway_name"]

        rec = enrichment_df[
            (enrichment_df["contrast"] == contrast)
            & (enrichment_df["pathway_name"] == pathway_name)
        ]
        if rec.empty:
            return _empty_figure("Pathway not found")

        rec = rec.iloc[0]
        le_genes = rec["leading_edge_genes"]

        # Filter to genes present in expression matrix
        available = [g for g in le_genes if g in expression_df.index]
        if not available:
            return _empty_figure("No expression data for leading edge genes")

        # Cap at 40 genes for readability
        available = available[:40]

        heat_data = expression_df.loc[available]

        # Z-score across samples for each gene
        heat_z = heat_data.subtract(heat_data.mean(axis=1), axis=0).divide(
            heat_data.std(axis=1).replace(0, 1), axis=0
        )

        # Condition color annotation bar
        cond_colors = {"Control": "#4CAF50", "Treatment_A": "#2196F3", "Treatment_B": "#FF9800"}
        cond_bar = [cond_colors.get(c, "#999") for c in sample_meta_df["condition"]]

        fig = go.Figure()

        # Heatmap
        fig.add_trace(
            go.Heatmap(
                z=heat_z.values,
                x=heat_z.columns.tolist(),
                y=heat_z.index.tolist(),
                colorscale="RdBu_r",
                zmid=0,
                colorbar=dict(title="z-score", thickness=10, len=0.7),
            )
        )

        fig.update_layout(
            template="plotly_white",
            title=f"Leading Edge: {pathway_name} ({len(available)} genes)",
            xaxis=dict(
                title="Samples",
                tickfont=dict(size=7),
                tickangle=90,
            ),
            yaxis=dict(
                tickfont=dict(size=9),
                autorange="reversed",
            ),
            margin=dict(l=80, r=30, t=50, b=80),
            # Condition annotation as shapes at top
            shapes=[
                dict(
                    type="rect",
                    x0=i - 0.5,
                    x1=i + 0.5,
                    y0=-1.5,
                    y1=-0.5,
                    fillcolor=cond_bar[i],
                    line_width=0,
                    xref="x",
                    yref="y",
                )
                for i in range(len(cond_bar))
            ],
        )

        return fig
