"""Callbacks for the Taxonomy Browser analysis module.

Architecture
------------
Single cascading callback: rank selector, abundance threshold, top-N, and
condition filter drive all views. Differential abundance (volcano-style scatter)
is computed on the fly using Mann-Whitney U tests between conditions.
"""

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output
from data import (
    aggregate_by_rank,
    compute_alpha_diversity,
)
from scipy.stats import mannwhitneyu

# Qualitative color palette for taxa
TAXA_COLORS: list[str] = [
    "#e63946",
    "#457b9d",
    "#2a9d8f",
    "#e9c46a",
    "#f4a261",
    "#264653",
    "#a8dadc",
    "#d62828",
    "#023e8a",
    "#0077b6",
    "#00b4d8",
    "#90be6d",
    "#f9844a",
    "#577590",
    "#43aa8b",
    "#f8961e",
    "#f3722c",
    "#4d908e",
    "#277da1",
    "#9b5de5",
]

# Significance and fold-change thresholds for the volcano plot
PVALUE_THRESHOLD: float = 0.05
LOG2FC_THRESHOLD: float = 1.0


def _compute_differential_abundance(
    agg_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    conditions: list[str],
) -> pd.DataFrame:
    """Compute differential abundance statistics for each taxon.

    For each taxon, computes:
    - Mean relative abundance per condition
    - log2(fold change) between conditions
    - Mann-Whitney U p-value

    Requires exactly 2 conditions. Returns empty DataFrame otherwise.
    """
    if len(conditions) != 2:
        return pd.DataFrame(
            columns=["taxon", "mean_cond1", "mean_cond2", "log2fc", "pvalue", "neg_log10p"]
        )

    cond1, cond2 = conditions[0], conditions[1]
    samples_c1 = metadata_df[metadata_df["condition"] == cond1]["sample_id"].tolist()
    samples_c2 = metadata_df[metadata_df["condition"] == cond2]["sample_id"].tolist()

    # Filter to available samples
    samples_c1 = [s for s in samples_c1 if s in agg_df.columns]
    samples_c2 = [s for s in samples_c2 if s in agg_df.columns]

    if not samples_c1 or not samples_c2:
        return pd.DataFrame(
            columns=["taxon", "mean_cond1", "mean_cond2", "log2fc", "pvalue", "neg_log10p"]
        )

    # Compute relative abundance
    rel_df = agg_df.div(agg_df.sum(axis=0), axis=1)

    results = []
    for taxon in rel_df.index:
        vals_c1 = rel_df.loc[taxon, samples_c1].values.astype(float)
        vals_c2 = rel_df.loc[taxon, samples_c2].values.astype(float)

        mean_c1 = np.mean(vals_c1)
        mean_c2 = np.mean(vals_c2)

        # log2 fold change with pseudocount to avoid log(0)
        pseudocount = 1e-6
        log2fc = float(np.log2((mean_c2 + pseudocount) / (mean_c1 + pseudocount)))

        # Mann-Whitney U test
        try:
            _, pvalue = mannwhitneyu(vals_c1, vals_c2, alternative="two-sided")
        except ValueError:
            pvalue = 1.0

        neg_log10p = float(-np.log10(max(pvalue, 1e-300)))

        results.append(
            {
                "taxon": taxon,
                f"mean_{cond1}": round(mean_c1, 6),
                f"mean_{cond2}": round(mean_c2, 6),
                "log2fc": round(log2fc, 4),
                "pvalue": pvalue,
                "neg_log10p": round(neg_log10p, 4),
            }
        )

    return pd.DataFrame(results)


def _build_differential_scatter(
    diff_df: pd.DataFrame,
    conditions: list[str],
    abundance_threshold: float,
) -> go.Figure:
    """Volcano-style scatter: x = log2FC, y = -log10(p-value)."""
    fig = go.Figure()

    if diff_df.empty:
        fig.update_layout(
            title="Differential Abundance (need exactly 2 conditions)",
            template="plotly_white",
        )
        return fig

    # Classify points: significant or not
    sig_mask = (diff_df["pvalue"] < PVALUE_THRESHOLD) & (diff_df["log2fc"].abs() > LOG2FC_THRESHOLD)

    # Non-significant points
    ns_df = diff_df[~sig_mask]
    if not ns_df.empty:
        fig.add_trace(
            go.Scatter(
                x=ns_df["log2fc"],
                y=ns_df["neg_log10p"],
                mode="markers+text",
                marker={"color": "#adb5bd", "size": 8, "opacity": 0.6},
                text=ns_df["taxon"],
                textposition="top center",
                textfont={"size": 9},
                name="Not significant",
                hovertemplate=(
                    "<b>%{text}</b><br>log2FC: %{x:.3f}<br>-log10(p): %{y:.2f}<br><extra></extra>"
                ),
            )
        )

    # Significant points
    sig_df = diff_df[sig_mask]
    if not sig_df.empty:
        colors = ["#e63946" if fc > 0 else "#457b9d" for fc in sig_df["log2fc"]]
        fig.add_trace(
            go.Scatter(
                x=sig_df["log2fc"],
                y=sig_df["neg_log10p"],
                mode="markers+text",
                marker={"color": colors, "size": 12, "line": {"width": 1, "color": "#333"}},
                text=sig_df["taxon"],
                textposition="top center",
                textfont={"size": 10, "color": "#333"},
                name="Significant",
                hovertemplate=(
                    "<b>%{text}</b><br>log2FC: %{x:.3f}<br>-log10(p): %{y:.2f}<br><extra></extra>"
                ),
            )
        )

    # Reference lines
    neg_log10_thresh = -np.log10(PVALUE_THRESHOLD)
    fig.add_hline(
        y=neg_log10_thresh,
        line_dash="dash",
        line_color="#868e96",
        annotation_text=f"p = {PVALUE_THRESHOLD}",
        annotation_position="top right",
    )
    fig.add_vline(
        x=LOG2FC_THRESHOLD,
        line_dash="dash",
        line_color="#868e96",
    )
    fig.add_vline(
        x=-LOG2FC_THRESHOLD,
        line_dash="dash",
        line_color="#868e96",
        annotation_text=f"|log2FC| = {LOG2FC_THRESHOLD}",
        annotation_position="top left",
    )

    cond_label = f"{conditions[1]} vs {conditions[0]}" if len(conditions) == 2 else ""
    fig.update_layout(
        title=f"Differential Abundance ({cond_label})",
        xaxis_title="log2(Fold Change)",
        yaxis_title="-log10(p-value)",
        template="plotly_white",
        margin={"l": 60, "r": 20, "t": 50, "b": 60},
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return fig


def _build_stacked_bar(
    agg_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    top_n: int,
    conditions: list[str],
    abundance_threshold: float,
) -> go.Figure:
    """Stacked bar chart of taxonomic relative abundance per sample.

    Includes a horizontal reference line at the abundance threshold.
    """
    valid_samples = metadata_df[metadata_df["condition"].isin(conditions)]["sample_id"].tolist()
    agg_df = agg_df[[c for c in agg_df.columns if c in valid_samples]]

    # Convert to relative abundance
    rel_df = agg_df.div(agg_df.sum(axis=0), axis=1)

    # Get top N taxa by mean abundance
    mean_abund = rel_df.mean(axis=1).sort_values(ascending=False)
    top_taxa = mean_abund.head(top_n).index.tolist()

    # Group the rest as "Other"
    plot_df = rel_df.loc[rel_df.index.isin(top_taxa)].copy()
    other = rel_df.loc[~rel_df.index.isin(top_taxa)].sum(axis=0)
    if other.sum() > 0:
        plot_df.loc["Other"] = other

    # Sort samples by condition
    sample_order = (
        metadata_df[metadata_df["sample_id"].isin(agg_df.columns)]
        .sort_values("condition")["sample_id"]
        .tolist()
    )
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
                marker={"color": color},
            )
        )

    # Abundance threshold reference line
    threshold_frac = abundance_threshold / 100.0
    if threshold_frac > 0:
        fig.add_hline(
            y=threshold_frac,
            line_dash="dot",
            line_color="#e63946",
            annotation_text=f"Threshold: {abundance_threshold}%",
            annotation_position="top right",
        )

    fig.update_layout(
        title=f"Taxonomic Composition (top {top_n})",
        barmode="stack",
        xaxis_title="Sample",
        yaxis_title="Relative Abundance",
        template="plotly_white",
        margin={"l": 60, "r": 20, "t": 50, "b": 80},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return fig


def _build_alpha_diversity(
    counts_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    conditions: list[str],
) -> go.Figure:
    """Box plot of Shannon diversity by condition."""
    diversity = compute_alpha_diversity(counts_df)
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
        margin={"l": 60, "r": 20, "t": 50, "b": 40},
        showlegend=False,
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
        Output("summary-badges", "children"),
        Output("differential-scatter", "figure"),
        Output("stacked-bar-chart", "figure"),
        Output("alpha-diversity-chart", "figure"),
        Output("abundance-table", "rowData"),
        Output("abundance-table", "columnDefs"),
        Output("sidebar-summary", "children"),
        Input("rank-selector", "value"),
        Input("abundance-threshold-slider", "value"),
        Input("top-n-input", "value"),
        Input("condition-filter", "value"),
    )
    def update_all(
        rank: str | None,
        abundance_threshold: float | None,
        top_n: int | None,
        conditions: list[str] | None,
    ) -> tuple:
        """Cascading update: all views respond to rank, threshold, top-N, conditions."""
        rank = rank or "phylum"
        abundance_threshold = abundance_threshold if abundance_threshold is not None else 0.5
        top_n = top_n or 10
        conditions = conditions or ["Healthy", "Disease"]

        # Aggregate counts by selected rank
        agg_df = aggregate_by_rank(abundance_df, taxonomy_df, rank)

        # Compute relative abundance and filter by threshold
        rel_df = agg_df.div(agg_df.sum(axis=0), axis=1)
        mean_rel = rel_df.mean(axis=1)
        threshold_frac = abundance_threshold / 100.0
        taxa_above = mean_rel[mean_rel >= threshold_frac].index
        filtered_agg = agg_df.loc[agg_df.index.isin(taxa_above)]

        n_total_taxa = len(agg_df)
        n_above_threshold = len(taxa_above)
        valid_samples = metadata_df[metadata_df["condition"].isin(conditions)]["sample_id"].tolist()
        n_samples = len(valid_samples)

        # -- Summary badges (main area) --
        summary_badges = [
            dmc.Badge(f"Rank: {rank.capitalize()}", color="blue", variant="light", size="lg"),
            dmc.Badge(f"{n_total_taxa} total taxa", color="gray", variant="light", size="lg"),
            dmc.Badge(
                f"{n_above_threshold} above {abundance_threshold}%",
                color="teal",
                variant="light",
                size="lg",
            ),
            dmc.Badge(f"{n_samples} samples", color="grape", variant="light", size="lg"),
        ]

        # -- Sidebar summary --
        sidebar_summary = [
            dmc.Badge(f"Rank: {rank.capitalize()}", color="blue", variant="outline", size="sm"),
            dmc.Badge(
                f"{n_above_threshold}/{n_total_taxa} taxa",
                color="teal",
                variant="outline",
                size="sm",
            ),
            dmc.Badge(f"{n_samples} samples", color="grape", variant="outline", size="sm"),
        ]

        # -- Differential abundance scatter --
        diff_df = _compute_differential_abundance(filtered_agg, metadata_df, conditions)
        scatter_fig = _build_differential_scatter(diff_df, conditions, abundance_threshold)

        # -- Stacked bar chart (uses filtered data) --
        bar_fig = _build_stacked_bar(
            filtered_agg, metadata_df, top_n, conditions, abundance_threshold
        )

        # -- Alpha diversity (uses raw counts, not filtered) --
        alpha_fig = _build_alpha_diversity(abundance_df, metadata_df, conditions)

        # -- AG Grid table: taxa with mean abundance per condition, FC, p-value --
        if diff_df.empty:
            row_data: list[dict] = []
            col_defs = [
                {
                    "field": "taxon",
                    "headerName": "Taxon",
                    "filter": "agTextColumnFilter",
                    "pinned": "left",
                    "minWidth": 150,
                }
            ]
        else:
            table_df = diff_df.copy()
            # Round for display
            for col in table_df.columns:
                if col not in ("taxon",):
                    table_df[col] = pd.to_numeric(table_df[col], errors="coerce")
            table_df = table_df.sort_values("pvalue")
            row_data = table_df.to_dict("records")

            cond1, cond2 = conditions[0], conditions[1]
            col_defs = [
                {
                    "field": "taxon",
                    "headerName": "Taxon",
                    "filter": "agTextColumnFilter",
                    "pinned": "left",
                    "minWidth": 150,
                },
                {
                    "field": f"mean_{cond1}",
                    "headerName": f"Mean {cond1}",
                    "filter": "agNumberColumnFilter",
                    "valueFormatter": {"function": "d3.format('.6f')(params.value)"},
                },
                {
                    "field": f"mean_{cond2}",
                    "headerName": f"Mean {cond2}",
                    "filter": "agNumberColumnFilter",
                    "valueFormatter": {"function": "d3.format('.6f')(params.value)"},
                },
                {
                    "field": "log2fc",
                    "headerName": "log2(FC)",
                    "filter": "agNumberColumnFilter",
                    "valueFormatter": {"function": "d3.format('.4f')(params.value)"},
                },
                {
                    "field": "pvalue",
                    "headerName": "p-value",
                    "filter": "agNumberColumnFilter",
                    "valueFormatter": {"function": "d3.format('.4e')(params.value)"},
                },
                {
                    "field": "neg_log10p",
                    "headerName": "-log10(p)",
                    "filter": "agNumberColumnFilter",
                    "valueFormatter": {"function": "d3.format('.2f')(params.value)"},
                },
            ]

        return (
            summary_badges,
            scatter_fig,
            bar_fig,
            alpha_fig,
            row_data,
            col_defs,
            sidebar_summary,
        )
