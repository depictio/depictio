"""Callbacks for the Contrast Manager module.

Handles contrast table, MA plot, PCA mini-view, contrast-vs-contrast scatter,
sample count previews, and cross-module communication via shared stores.

All component IDs are prefixed with ``cm-``.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from shared_stores import ACTIVE_CONTRAST, FILTERED_FEATURE_IDS, HIGHLIGHTED_SAMPLES


def _get_contrast_summary(
    metadata_df: pd.DataFrame, de_results: dict[str, pd.DataFrame]
) -> list[dict]:
    """Build summary rows for the contrast table.

    Returns list of dicts with: name, numerator, denominator,
    n_samples_num, n_samples_den, n_sig_genes, balance_warning.
    """
    rows = []
    for name, de_df in de_results.items():
        treatment = name.replace("_vs_Control", "")
        n_num = int((metadata_df["condition"] == treatment).sum())
        n_den = int((metadata_df["condition"] == "Control").sum())
        n_sig = int(de_df["significant"].sum())
        ratio = max(n_num, n_den) / max(min(n_num, n_den), 1)
        balance_warning = ratio > 2.0
        rows.append(
            {
                "name": name,
                "numerator": treatment,
                "denominator": "Control",
                "n_samples_num": n_num,
                "n_samples_den": n_den,
                "n_sig_genes": n_sig,
                "balance_warning": balance_warning,
            }
        )
    return rows


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
                text="No data to display",
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
    """Register all Contrast Manager callbacks on the given app.

    Parameters
    ----------
    app : Dash
        The Dash application instance.
    data : dict
        Data dict from ``shared_data.load_all_data()``.
    """
    expression_df = data["expression_df"]
    metadata_df = data["metadata_df"]
    de_results = data["de_results"]

    # Pre-compute PCA for the mini-view (done once)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(expression_df.values)
    pca = PCA(n_components=2)
    pca_coords = pca.fit_transform(X_scaled)
    pca_df = metadata_df.copy()
    pca_df["PC1"] = pca_coords[:, 0]
    pca_df["PC2"] = pca_coords[:, 1]

    # Pre-compute contrast summary
    contrast_summary = _get_contrast_summary(metadata_df, de_results)

    # ── Write active contrast to shared store ──────────────
    @app.callback(
        Output(ACTIVE_CONTRAST, "data"),
        Input("cm-active-contrast-select", "value"),
    )
    def sync_active_contrast(contrast_name: str | None):
        return contrast_name

    # ── Write highlighted samples to shared store ──────────
    @app.callback(
        Output(HIGHLIGHTED_SAMPLES, "data"),
        Input("cm-active-contrast-select", "value"),
    )
    def sync_highlighted_samples(contrast_name: str | None) -> list[str]:
        if not contrast_name or contrast_name not in de_results:
            return []
        treatment = contrast_name.replace("_vs_Control", "")
        num_samples = metadata_df.loc[
            metadata_df["condition"] == treatment, "sample_id"
        ].tolist()
        den_samples = metadata_df.loc[
            metadata_df["condition"] == "Control", "sample_id"
        ].tolist()
        return num_samples + den_samples

    # ── Update sig genes badge ─────────────────────────────
    @app.callback(
        Output("cm-badge-sig-genes", "children"),
        Input("cm-active-contrast-select", "value"),
    )
    def update_sig_badge(contrast_name: str | None) -> str:
        if not contrast_name or contrast_name not in de_results:
            return "0 sig. genes"
        n_sig = int(de_results[contrast_name]["significant"].sum())
        return f"{n_sig} sig. genes"

    # ── Numerator sample count preview ─────────────────────
    @app.callback(
        Output("cm-numerator-count", "children"),
        Input("cm-numerator-select", "value"),
    )
    def update_numerator_count(selected: list[str] | None) -> str:
        if not selected:
            return "0 samples selected"
        n = int(metadata_df["condition"].isin(selected).sum())
        return f"{n} samples selected"

    # ── Denominator sample count preview ───────────────────
    @app.callback(
        Output("cm-denominator-count", "children"),
        Input("cm-denominator-select", "value"),
    )
    def update_denominator_count(selected: list[str] | None) -> str:
        if not selected:
            return "0 samples selected"
        n = int(metadata_df["condition"].isin(selected).sum())
        return f"{n} samples selected"

    # ── Contrast table data ────────────────────────────────
    @app.callback(
        Output("cm-contrast-table", "rowData"),
        Input("cm-add-contrast-btn", "n_clicks"),
    )
    def update_contrast_table(n_clicks: int | None) -> list[dict]:
        return contrast_summary

    # ── MA plot ────────────────────────────────────────────
    @app.callback(
        Output("cm-ma-plot", "figure"),
        Input("cm-active-contrast-select", "value"),
        Input(FILTERED_FEATURE_IDS, "data"),
    )
    def update_ma_plot(
        contrast_name: str | None, filtered_ids: list[str] | None
    ) -> go.Figure:
        if not contrast_name or contrast_name not in de_results:
            return _empty_figure("Select a contrast")

        de_df = de_results[contrast_name].copy()

        # If filtered feature IDs are provided, mark them
        if filtered_ids:
            de_df["in_filter"] = de_df["gene_name"].isin(filtered_ids)
            de_df["status"] = np.where(
                de_df["in_filter"] & de_df["significant"],
                "Significant (filtered)",
                np.where(
                    de_df["significant"],
                    "Significant",
                    "Not significant",
                ),
            )
            color_map = {
                "Significant (filtered)": "#e63946",
                "Significant": "#f4a261",
                "Not significant": "#adb5bd",
            }
        else:
            de_df["status"] = de_df["significant"].map(
                {True: "Significant", False: "Not significant"}
            )
            color_map = {
                "Significant": "#e63946",
                "Not significant": "#adb5bd",
            }

        fig = px.scatter(
            de_df,
            x="mean_expression",
            y="log2fc",
            color="status",
            color_discrete_map=color_map,
            hover_data=["gene_name", "padj"],
            labels={
                "mean_expression": "Mean Expression (A)",
                "log2fc": "log2 Fold Change (M)",
                "status": "Status",
            },
            title=f"MA Plot — {contrast_name}",
        )
        fig.update_traces(marker=dict(size=5, opacity=0.7))
        fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
        fig.add_hline(y=1.0, line_dash="dot", line_color="#e63946", line_width=0.8)
        fig.add_hline(y=-1.0, line_dash="dot", line_color="#e63946", line_width=0.8)
        fig.update_layout(
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=-0.25),
            margin=dict(l=60, r=20, t=50, b=80),
        )
        return fig

    # ── PCA mini-view ──────────────────────────────────────
    @app.callback(
        Output("cm-pca-mini", "figure"),
        Input("cm-active-contrast-select", "value"),
    )
    def update_pca_mini(contrast_name: str | None) -> go.Figure:
        if not contrast_name or contrast_name not in de_results:
            return _empty_figure("Select a contrast")

        treatment = contrast_name.replace("_vs_Control", "")
        fig = go.Figure()

        # Other samples (gray)
        other_mask = ~pca_df["condition"].isin([treatment, "Control"])
        if other_mask.any():
            fig.add_trace(
                go.Scatter(
                    x=pca_df.loc[other_mask, "PC1"],
                    y=pca_df.loc[other_mask, "PC2"],
                    mode="markers",
                    name="Other",
                    marker=dict(
                        size=7,
                        color="#dee2e6",
                        line=dict(width=0.5, color="#adb5bd"),
                    ),
                    text=pca_df.loc[other_mask, "sample_id"],
                    hoverinfo="text",
                )
            )

        # Denominator samples (open markers)
        den_mask = pca_df["condition"] == "Control"
        fig.add_trace(
            go.Scatter(
                x=pca_df.loc[den_mask, "PC1"],
                y=pca_df.loc[den_mask, "PC2"],
                mode="markers",
                name="Control (den)",
                marker=dict(
                    size=9,
                    color="rgba(255,255,255,0)",
                    line=dict(width=2, color="#2196F3"),
                    symbol="circle-open",
                ),
                text=pca_df.loc[den_mask, "sample_id"],
                hoverinfo="text",
            )
        )

        # Numerator samples (filled markers)
        num_mask = pca_df["condition"] == treatment
        fig.add_trace(
            go.Scatter(
                x=pca_df.loc[num_mask, "PC1"],
                y=pca_df.loc[num_mask, "PC2"],
                mode="markers",
                name=f"{treatment} (num)",
                marker=dict(
                    size=9,
                    color="#e63946",
                    line=dict(width=0.5, color="white"),
                ),
                text=pca_df.loc[num_mask, "sample_id"],
                hoverinfo="text",
            )
        )

        var_x = pca.explained_variance_ratio_[0]
        var_y = pca.explained_variance_ratio_[1]
        fig.update_layout(
            template="plotly_white",
            title=f"PCA — {contrast_name}",
            xaxis_title=f"PC1 ({var_x:.1%})",
            yaxis_title=f"PC2 ({var_y:.1%})",
            legend=dict(orientation="h", yanchor="bottom", y=-0.3),
            margin=dict(l=60, r=20, t=50, b=80),
        )
        return fig

    # ── Contrast-vs-contrast scatter ───────────────────────
    @app.callback(
        Output("cm-contrast-scatter", "figure"),
        Input("cm-contrast-a-select", "value"),
        Input("cm-contrast-b-select", "value"),
    )
    def update_contrast_scatter(
        contrast_a: str | None, contrast_b: str | None
    ) -> go.Figure:
        if (
            not contrast_a
            or not contrast_b
            or contrast_a not in de_results
            or contrast_b not in de_results
        ):
            return _empty_figure("Select two contrasts")

        de_a = de_results[contrast_a][["gene_name", "log2fc", "significant"]].rename(
            columns={"log2fc": "log2fc_A", "significant": "sig_A"}
        )
        de_b = de_results[contrast_b][["gene_name", "log2fc", "significant"]].rename(
            columns={"log2fc": "log2fc_B", "significant": "sig_B"}
        )
        merged = de_a.merge(de_b, on="gene_name")

        # Concordant: same sign; Discordant: different sign
        same_sign = (merged["log2fc_A"] * merged["log2fc_B"]) > 0
        merged["direction"] = np.where(same_sign, "Concordant", "Discordant")

        fig = px.scatter(
            merged,
            x="log2fc_A",
            y="log2fc_B",
            color="direction",
            color_discrete_map={
                "Concordant": "#2a9d8f",
                "Discordant": "#e76f51",
            },
            hover_data=["gene_name"],
            labels={
                "log2fc_A": f"log2FC — {contrast_a}",
                "log2fc_B": f"log2FC — {contrast_b}",
                "direction": "Direction",
            },
            title=f"Contrast Comparison: {contrast_a} vs {contrast_b}",
        )
        fig.update_traces(marker=dict(size=5, opacity=0.7))
        fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=0.8)
        fig.add_vline(x=0, line_dash="dash", line_color="gray", line_width=0.8)

        # Identity line
        lim = max(
            abs(merged["log2fc_A"].min()),
            abs(merged["log2fc_A"].max()),
            abs(merged["log2fc_B"].min()),
            abs(merged["log2fc_B"].max()),
        )
        fig.add_trace(
            go.Scatter(
                x=[-lim, lim],
                y=[-lim, lim],
                mode="lines",
                line=dict(dash="dot", color="gray", width=1),
                showlegend=False,
                hoverinfo="skip",
            )
        )

        fig.update_layout(
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=-0.2),
            margin=dict(l=60, r=20, t=50, b=80),
        )
        return fig
