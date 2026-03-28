"""Callbacks for the DimRed Explorer module.

Handles method switching, parameter updates, linked plot generation,
summary badge updates, and cross-module communication via shared stores.

All component IDs are prefixed with ``dr-``.

Cross-module reads:
    - ``highlighted-samples-store``: highlight specific samples on the scatter
    - ``filtered-feature-ids-store``: use filtered features for dim. reduction
    - ``active-feature-store``: color samples by a specific feature's expression
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output
from shared_stores import ACTIVE_FEATURE, FILTERED_FEATURE_IDS, HIGHLIGHTED_SAMPLES

from .layout import COLUMN_LABELS

# Lazy-import UMAP to avoid slow import at startup
_umap_cls = None


def _get_umap_cls():
    global _umap_cls
    if _umap_cls is None:
        from umap import UMAP

        _umap_cls = UMAP
    return _umap_cls


def _get_top_variable_genes(expression_df: pd.DataFrame, n: int = 50) -> list[str]:
    """Return the top N most variable genes by standard deviation."""
    stds = expression_df.std(axis=0).sort_values(ascending=False)
    return stds.head(n).index.tolist()


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


def register_callbacks(app: Dash, data: dict) -> None:
    """Register all DimRed Explorer callbacks on the given app.

    Parameters
    ----------
    app : Dash
        The Dash application instance.
    data : dict
        Data dict from ``shared_data.load_all_data()``.
    """
    expression_df = data["expression_df"]
    metadata_df = data["metadata_df"]

    @app.callback(
        Output("dr-main-scatter", "figure"),
        Output("dr-variance-bar", "figure"),
        Output("dr-loadings-bar", "figure"),
        Output("dr-sample-table", "columnDefs"),
        Output("dr-sample-table", "rowData"),
        Output("dr-badge-samples", "children"),
        Output("dr-badge-genes", "children"),
        Output("dr-badge-method", "children"),
        Output("dr-badge-variance", "children"),
        Input("dr-method-select", "value"),
        Input("dr-n-top-genes", "value"),
        Input("dr-color-by", "value"),
        Input("dr-symbol-by", "value"),
        Input("dr-point-size", "value"),
        Input("dr-pc-x", "value"),
        Input("dr-pc-y", "value"),
        Input("dr-tsne-perplexity", "value"),
        Input("dr-umap-n-neighbors", "value"),
        Input("dr-umap-min-dist", "value"),
        Input(HIGHLIGHTED_SAMPLES, "data"),
        Input(FILTERED_FEATURE_IDS, "data"),
        Input(ACTIVE_FEATURE, "data"),
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
        highlighted_samples: list[str] | None,
        filtered_feature_ids: list[str] | None,
        active_feature: str | None,
    ):
        from sklearn.decomposition import PCA
        from sklearn.manifold import TSNE
        from sklearn.preprocessing import StandardScaler

        # ── Prep data ────────────────────────────────────────
        n_top_genes = max(10, min(n_top_genes or 200, expression_df.shape[1]))

        # Determine gene subset: use filtered features if available and fewer
        # than the current top-N setting, otherwise use top variable genes.
        if filtered_feature_ids:
            # Intersect with available genes in expression matrix
            available_filtered = [g for g in filtered_feature_ids if g in expression_df.columns]
            if available_filtered and len(available_filtered) < n_top_genes:
                gene_subset = available_filtered
            else:
                gene_subset = _get_top_variable_genes(expression_df, n=n_top_genes)
        else:
            gene_subset = _get_top_variable_genes(expression_df, n=n_top_genes)

        X = expression_df[gene_subset].values
        n_genes_used = len(gene_subset)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # ── Run dimensionality reduction ─────────────────────
        variance_fig = _empty_figure("Variance explained (PCA only)")
        loadings_fig = _empty_figure("Loadings (PCA only)")
        explained_variance = None
        loadings = None
        total_var_explained_str = "--"

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
            total_var_explained_str = (
                f"Var: {explained_variance[comp_x] + explained_variance[comp_y]:.1%}"
            )

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

        # Determine color: if active_feature is set and exists in expression,
        # color by that feature's expression instead of metadata
        use_feature_color = active_feature and active_feature in expression_df.columns

        if use_feature_color:
            plot_df["_feature_expr"] = expression_df[active_feature].values
            scatter_fig = px.scatter(
                plot_df,
                x="x",
                y="y",
                color="_feature_expr",
                symbol=symbol_by if symbol_by else None,
                hover_data=["sample_id", "condition", "batch", "cell_type"],
                labels={
                    "x": x_label,
                    "y": y_label,
                    "_feature_expr": active_feature,
                },
                title=f"{title} — colored by {active_feature}",
                color_continuous_scale="Viridis",
            )
        else:
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

        # ── Highlight samples from shared store ──────────────
        if highlighted_samples:
            hl_set = set(highlighted_samples)
            sample_ids = plot_df["sample_id"].tolist()

            # Build per-point marker properties
            sizes = []
            opacities = []
            line_widths = []
            for sid in sample_ids:
                if sid in hl_set:
                    sizes.append(point_size + 4)
                    opacities.append(1.0)
                    line_widths.append(2.0)
                else:
                    sizes.append(point_size)
                    opacities.append(0.3)
                    line_widths.append(0.5)

            # Apply to all traces
            for trace in scatter_fig.data:
                # Match trace points to the plot_df order via customdata
                # For simplicity, apply uniform highlight logic across traces
                # by updating the marker arrays per trace length
                n_pts = len(trace.x) if trace.x is not None else 0
                if n_pts == 0:
                    continue

                # Retrieve sample_ids from customdata (first column in
                # hover_data)
                if trace.customdata is not None and len(trace.customdata) > 0:
                    trace_sids = [row[0] for row in trace.customdata]
                    t_sizes = []
                    t_opacities = []
                    t_lw = []
                    for sid in trace_sids:
                        if sid in hl_set:
                            t_sizes.append(point_size + 4)
                            t_opacities.append(1.0)
                            t_lw.append(2.0)
                        else:
                            t_sizes.append(point_size)
                            t_opacities.append(0.3)
                            t_lw.append(0.5)
                    trace.marker.size = t_sizes
                    trace.marker.opacity = t_opacities
                    trace.marker.line.width = t_lw

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
            loading_genes = [gene_subset[i] for i in top_idx]
            loading_vals = loadings[comp_x_idx][top_idx]

            loadings_df = pd.DataFrame({"Gene": loading_genes, "Loading": loading_vals})
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

        # ── Summary badges ───────────────────────────────────
        n_samples = len(expression_df)
        badge_samples = f"{n_samples} samples"
        badge_genes = f"{n_genes_used} genes"
        badge_method = method.upper()
        badge_variance = total_var_explained_str

        return (
            scatter_fig,
            variance_fig,
            loadings_fig,
            col_defs,
            row_data,
            badge_samples,
            badge_genes,
            badge_method,
            badge_variance,
        )
