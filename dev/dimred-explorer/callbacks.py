"""Callbacks for the dimensionality reduction explorer.

Handles method switching, parameter updates, and linked plot generation.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, callback_context
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.preprocessing import StandardScaler

from data import COLUMN_LABELS, get_top_variable_genes

# Lazy-import UMAP to avoid slow import at startup
_umap_cls = None


def _get_umap_cls():
    global _umap_cls
    if _umap_cls is None:
        from umap import UMAP

        _umap_cls = UMAP
    return _umap_cls


def register_callbacks(
    app: Dash,
    expression_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> None:
    """Register all callbacks on the given app."""

    @app.callback(
        Output("main-scatter", "figure"),
        Output("variance-bar", "figure"),
        Output("loadings-bar", "figure"),
        Output("sample-table", "columnDefs"),
        Output("sample-table", "rowData"),
        Input("method-select", "value"),
        Input("n-top-genes", "value"),
        Input("color-by", "value"),
        Input("symbol-by", "value"),
        Input("point-size", "value"),
        Input("pc-x", "value"),
        Input("pc-y", "value"),
        Input("tsne-perplexity", "value"),
        Input("umap-n-neighbors", "value"),
        Input("umap-min-dist", "value"),
    )
    def update_all(
        method: str,
        n_top_genes: int,
        color_by: str,
        symbol_by: str | None,
        point_size: int,
        pc_x: int,
        pc_y: int,
        tsne_perplexity: int,
        umap_n_neighbors: int,
        umap_min_dist: float,
    ):
        # ── Prep data ────────────────────────────────────────
        n_top_genes = max(10, min(n_top_genes or 200, expression_df.shape[1]))
        top_genes = get_top_variable_genes(expression_df, n=n_top_genes)
        X = expression_df[top_genes].values

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # ── Run dimensionality reduction ─────────────────────
        variance_fig = _empty_figure("Variance explained (PCA only)")
        loadings_fig = _empty_figure("Loadings (PCA only)")
        explained_variance = None
        loadings = None

        if method == "pca":
            n_components = max(pc_x, pc_y, 2)
            n_components = min(n_components, min(X_scaled.shape) - 1, 10)
            pca = PCA(n_components=n_components)
            coords = pca.fit_transform(X_scaled)
            explained_variance = pca.explained_variance_ratio_
            loadings = pca.components_
            comp_x = min(pc_x, n_components) - 1
            comp_y = min(pc_y, n_components) - 1
            x_vals = coords[:, comp_x]
            y_vals = coords[:, comp_y]
            x_label = f"PC{comp_x + 1} ({explained_variance[comp_x]:.1%})"
            y_label = f"PC{comp_y + 1} ({explained_variance[comp_y]:.1%})"
            title = "PCA"

        elif method == "umap":
            UMAP = _get_umap_cls()
            n_neighbors = max(2, min(umap_n_neighbors or 15, X_scaled.shape[0] - 1))
            min_dist = max(0.0, min(umap_min_dist or 0.1, 1.0))
            reducer = UMAP(
                n_components=2,
                n_neighbors=n_neighbors,
                min_dist=min_dist,
                random_state=42,
            )
            coords = reducer.fit_transform(X_scaled)
            x_vals = coords[:, 0]
            y_vals = coords[:, 1]
            x_label = "UMAP 1"
            y_label = "UMAP 2"
            title = f"UMAP (n_neighbors={n_neighbors}, min_dist={min_dist})"

        else:  # tsne
            perp = max(5, min(tsne_perplexity or 30, X_scaled.shape[0] // 3))
            tsne = TSNE(
                n_components=2,
                perplexity=perp,
                random_state=42,
                init="pca",
                learning_rate="auto",
            )
            coords = tsne.fit_transform(X_scaled)
            x_vals = coords[:, 0]
            y_vals = coords[:, 1]
            x_label = "t-SNE 1"
            y_label = "t-SNE 2"
            title = f"t-SNE (perplexity={perp})"

        # ── Build scatter ────────────────────────────────────
        plot_df = metadata_df.copy()
        plot_df["x"] = x_vals
        plot_df["y"] = y_vals

        symbol_col = symbol_by if symbol_by else None
        color_label = COLUMN_LABELS.get(color_by, color_by)

        scatter_fig = px.scatter(
            plot_df,
            x="x",
            y="y",
            color=color_by,
            symbol=symbol_col,
            hover_data=["sample_id", "condition", "batch", "cell_type"],
            labels={"x": x_label, "y": y_label, color_by: color_label},
            title=title,
        )
        scatter_fig.update_traces(
            marker=dict(size=point_size, line=dict(width=0.5, color="white")),
        )
        scatter_fig.update_layout(
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=-0.25),
            margin=dict(l=60, r=20, t=50, b=80),
        )

        # ── Variance explained (PCA only) ────────────────────
        if explained_variance is not None:
            n_bars = min(len(explained_variance), 10)
            var_df = pd.DataFrame(
                {
                    "Component": [f"PC{i + 1}" for i in range(n_bars)],
                    "Variance Explained": explained_variance[:n_bars],
                    "Cumulative": np.cumsum(explained_variance[:n_bars]),
                }
            )
            variance_fig = px.bar(
                var_df,
                x="Component",
                y="Variance Explained",
                title="Variance Explained per PC",
                text_auto=".1%",
            )
            variance_fig.add_trace(
                go.Scatter(
                    x=var_df["Component"],
                    y=var_df["Cumulative"],
                    mode="lines+markers",
                    name="Cumulative",
                    yaxis="y",
                    line=dict(color="firebrick", width=2),
                    marker=dict(size=6),
                )
            )
            variance_fig.update_layout(
                template="plotly_white",
                yaxis_tickformat=".0%",
                showlegend=True,
                margin=dict(l=50, r=20, t=40, b=40),
                legend=dict(orientation="h", yanchor="bottom", y=-0.35),
            )

        # ── Loadings (PCA only) ──────────────────────────────
        if loadings is not None:
            comp_x_idx = min(pc_x, loadings.shape[0]) - 1
            abs_loadings = np.abs(loadings[comp_x_idx])
            top_idx = np.argsort(abs_loadings)[-15:][::-1]
            loading_genes = [top_genes[i] for i in top_idx]
            loading_vals = loadings[comp_x_idx][top_idx]

            loadings_df = pd.DataFrame(
                {"Gene": loading_genes, "Loading": loading_vals}
            )
            loadings_fig = px.bar(
                loadings_df,
                x="Loading",
                y="Gene",
                orientation="h",
                title=f"Top 15 Loadings — PC{comp_x_idx + 1}",
                color="Loading",
                color_continuous_scale="RdBu_r",
                color_continuous_midpoint=0,
            )
            loadings_fig.update_layout(
                template="plotly_white",
                yaxis=dict(autorange="reversed"),
                margin=dict(l=80, r=20, t=40, b=40),
                coloraxis_showscale=False,
            )

        # ── Table data ───────────────────────────────────────
        table_df = plot_df[["sample_id", "condition", "batch", "cell_type", "x", "y"]].copy()
        table_df = table_df.rename(columns={"x": x_label, "y": y_label})
        table_df[x_label] = table_df[x_label].round(3)
        table_df[y_label] = table_df[y_label].round(3)

        col_defs = [{"field": c, "headerName": COLUMN_LABELS.get(c, c)} for c in table_df.columns]
        row_data = table_df.to_dict("records")

        return scatter_fig, variance_fig, loadings_fig, col_defs, row_data


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
                text="Not available for this method",
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
