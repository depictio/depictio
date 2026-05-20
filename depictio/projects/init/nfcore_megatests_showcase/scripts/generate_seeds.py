"""Generate .db_seeds/ dashboard JSONs for the nf-core megatests showcase.

Each dashboard mirrors one in advanced_viz_showcase/.db_seeds/ but rewires
the workflow / dc / project IDs to the nfcore_megatests_showcase ones, and
swaps the role column names to match the actual columns emitted by the
nf-core canonical producer (e.g. volcano binds `feature_id_col` to
`gene_id` instead of the synthetic `feature_id`).

Five dashboards land:
    1. volcano       (deseq2_results.tsv)
    2. ma            (deseq2_results.tsv — same DC, different column roles)
    3. qq            (deseq2_results.tsv — same DC, just pvalue)
    4. coverage_track (mosdepth_coverage.tsv)
    5. embedding     (rnaseq_pca.tsv)

Hierarchical heatmap is deferred — its ComplexHeatmapConfig needs
matrix_wf_id + matrix_dc_id wiring that doesn't simplify cleanly.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SEEDS_DIR = PROJECT_DIR / ".db_seeds"
SEEDS_DIR.mkdir(parents=True, exist_ok=True)

# Project + workflow scaffold ids (kept in sync with project.yaml).
PROJECT_ID = "646b0f3c1e4a2d7f8e5b8e00"
WF_ID = "646b0f3c1e4a2d7f8e5b8e01"
WF_TAG = "nf-core/nfcore_megatests"
ADMIN_USER_ID = "67658ba033c8b59ad489d7c7"

# DC ids — match project.yaml exactly.
DC = {
    "deseq2_results": "646b0f3c1e4a2d7f8e5b8e10",
    "deseq2_vst": "646b0f3c1e4a2d7f8e5b8e11",
    "mosdepth_coverage": "646b0f3c1e4a2d7f8e5b8e12",
    "rnaseq_pca": "646b0f3c1e4a2d7f8e5b8e13",
    "deseq2_vst_top100": "646b0f3c1e4a2d7f8e5b8e14",
    "qiime2_rarefaction": "646b0f3c1e4a2d7f8e5b8e15",
    "qiime2_stacked_taxonomy": "646b0f3c1e4a2d7f8e5b8e16",
    "ancombc_da_barplot": "646b0f3c1e4a2d7f8e5b8e17",
    "bracken_taxonomy": "646b0f3c1e4a2d7f8e5b8e18",
}

# Dashboard ids per viz_kind.
DASHBOARD_ID = {
    "volcano": "646b0f3c1e4a2d7f8e5b8e20",
    "ma": "646b0f3c1e4a2d7f8e5b8e21",
    "qq": "646b0f3c1e4a2d7f8e5b8e22",
    "coverage_track": "646b0f3c1e4a2d7f8e5b8e23",
    "embedding": "646b0f3c1e4a2d7f8e5b8e24",
    "complex_heatmap": "646b0f3c1e4a2d7f8e5b8e25",
    "rarefaction": "646b0f3c1e4a2d7f8e5b8e26",
    "stacked_taxonomy": "646b0f3c1e4a2d7f8e5b8e27",
    "da_barplot": "646b0f3c1e4a2d7f8e5b8e28",
    "sunburst": "646b0f3c1e4a2d7f8e5b8e29",
}

_NOW = "2026-05-18T00:00:00.000000"


def _owners() -> list[dict]:
    return [
        {
            "_id": {"$oid": ADMIN_USER_ID},
            "description": None,
            "flexible_metadata": None,
            "hash": None,
            "email": "admin@example.com",
            "is_admin": True,
            "is_anonymous": False,
            "is_temporary": False,
            "expiration_time": None,
        }
    ]


def _shell(
    dashboard_id: str,
    viz_kind: str,
    dc_tag: str,
    dc_id: str,
    title: str,
    subtitle: str,
    icon: str,
    icon_color: str,
    config: dict,
    component_title: str,
    description: str,
    tab_order: int,
) -> dict:
    """The common envelope around a single advanced_viz component."""
    component_index = f"nfcore-{viz_kind}"
    return {
        "_id": {"$oid": dashboard_id},
        "description": None,
        "flexible_metadata": None,
        "hash": None,
        "dashboard_id": {"$oid": dashboard_id},
        "version": 1,
        "tmp_children_data": [],
        "stored_layout_data": [],
        "stored_children_data": [],
        "stored_metadata": [
            {
                "index": component_index,
                "component_type": "advanced_viz",
                "title": component_title,
                "workflow_tag": "nfcore_megatests",
                "data_collection_tag": dc_tag,
                "wf_id": {"$oid": WF_ID},
                "dc_id": {"$oid": dc_id},
                "dc_config": {
                    "type": None,
                    "metatype": None,
                    "description": f"nf-core fixture: {dc_tag}",
                    "data_collection_tag": dc_tag,
                    "dc_specific_properties": None,
                    "_id": {"$oid": dc_id},
                },
                "cols_json": {},
                "parent_index": None,
                "last_updated": _NOW,
                "viz_kind": viz_kind,
                "config": config,
                "wf_tag": WF_TAG,
                "description": description,
            }
        ],
        "stored_edit_dashboard_mode_button": [],
        "left_panel_layout_data": [],
        "right_panel_layout_data": [
            {
                "i": f"box-{component_index}",
                "x": 0,
                "y": 0,
                "w": 12,
                "h": 8,
                "static": False,
                "resizeHandles": ["se", "s", "e", "sw", "w"],
            }
        ],
        "buttons_data": {"unified_edit_mode": True, "add_components_button": {"count": 0}},
        "stored_add_button": {"count": 0},
        "title": title,
        "subtitle": subtitle,
        "icon": icon,
        "icon_color": icon_color,
        "icon_variant": "filled",
        "workflow_system": "nf-core",
        "notes_content": "",
        "permissions": {"owners": _owners(), "editors": [], "viewers": []},
        "is_public": True,
        "last_saved_ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_id": {"$oid": PROJECT_ID},
        "is_main_tab": False,
        "parent_dashboard_id": {"$oid": PROJECT_ID},
        "tab_order": tab_order,
        "main_tab_name": None,
        "tab_icon": icon,
        "tab_icon_color": icon_color,
        "parent_dashboard_title": None,
    }


# -----------------------------------------------------------------------------
# Per-viz dashboards. Column-role bindings reflect the actual nf-core column
# names, not the synthetic showcase's pretty role names.
# -----------------------------------------------------------------------------

DASHBOARDS = [
    _shell(
        dashboard_id=DASHBOARD_ID["volcano"],
        viz_kind="volcano",
        dc_tag="deseq2_results",
        dc_id=DC["deseq2_results"],
        title="Volcano (DESeq2)",
        subtitle="DE results from nf-core/differentialabundance",
        icon="mdi:chart-scatter-plot",
        icon_color="red",
        component_title="Volcano — DESeq2 differential expression",
        description=(
            "Effect size vs significance scatter, bound to nf-core/differentialabundance's "
            "Condition_treatment-Control-Treated.deseq2.results.tsv."
        ),
        config={
            "viz_kind": "volcano",
            "feature_id_col": "gene_id",
            "effect_size_col": "log2FoldChange",
            "significance_col": "padj",
            # Don't bind label_col to the same column as feature_id_col —
            # polars complains "the name 'gene_id' is duplicate" when the
            # loader selects both. Leave label_col unset; viz falls back
            # to feature_id for hover labels.
            "significance_is_neg_log10": False,
            "significance_threshold": 0.05,
            # nf-core/differentialabundance's megatest dataset is a tiny
            # mouse RNA-seq with max |log2FC| ~0.9 (pipeline-validation
            # data, not biology). Default threshold 1.0 → 0 DE genes;
            # 0.5 → 20 hits, enough to colour the plot meaningfully.
            "effect_threshold": 0.5,
            "top_n_labels": 15,
        },
        tab_order=1,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["ma"],
        viz_kind="ma",
        dc_tag="deseq2_results",
        dc_id=DC["deseq2_results"],
        title="MA (DESeq2)",
        subtitle="DESeq2 MA plot",
        icon="mdi:chart-bell-curve-cumulative",
        icon_color="blue",
        component_title="MA — DESeq2 baseMean × log2FoldChange",
        description=(
            "Bland-Altman view of the same DESeq2 results: baseMean on x, log2FoldChange on y."
        ),
        config={
            "viz_kind": "ma",
            "feature_id_col": "gene_id",
            "avg_log_intensity_col": "baseMean",
            "log2_fold_change_col": "log2FoldChange",
            "significance_col": "padj",
            # See note on volcano: don't bind label_col to feature_id_col,
            # polars rejects the duplicate column select.
            "log_intensity_is_log": False,
            "significance_threshold": 0.05,
            # nf-core/differentialabundance's megatest dataset is a tiny
            # mouse RNA-seq with max |log2FC| ~0.9 (pipeline-validation
            # data, not biology). Default threshold 1.0 → 0 DE genes;
            # 0.5 → 20 hits, enough to colour the plot meaningfully.
            "effect_threshold": 0.5,
            "top_n_labels": 15,
        },
        tab_order=2,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["qq"],
        viz_kind="qq",
        dc_tag="deseq2_results",
        dc_id=DC["deseq2_results"],
        title="QQ (DESeq2)",
        subtitle="p-value distribution QC",
        icon="mdi:chart-line-stacked",
        icon_color="violet",
        component_title="QQ — DESeq2 p-value distribution",
        description=(
            "Quantile-quantile plot of DESeq2 raw p-values vs. uniform null. "
            "Inflation / deflation flag QC."
        ),
        config={
            "viz_kind": "qq",
            "p_value_col": "pvalue",
            "feature_id_col": "gene_id",
            "p_is_neg_log10": False,
        },
        tab_order=3,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["coverage_track"],
        viz_kind="coverage_track",
        dc_tag="mosdepth_coverage",
        dc_id=DC["mosdepth_coverage"],
        title="Coverage track (mosdepth)",
        subtitle="Per-region read depth from viralrecon",
        icon="mdi:chart-areaspline",
        icon_color="teal",
        component_title="Coverage — mosdepth per-region",
        description=(
            "Read depth along the MN908947.3 reference, mosdepth output from nf-core/viralrecon."
        ),
        config={
            "viz_kind": "coverage_track",
            "chromosome_col": "chrom",
            "position_col": "start",
            "end_col": "end",
            "value_col": "coverage",
            "sample_col": "sample",
            "y_scale": "linear",
            "smoothing_window": 0,
        },
        tab_order=4,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["embedding"],
        viz_kind="embedding",
        dc_tag="rnaseq_pca",
        dc_id=DC["rnaseq_pca"],
        title="Embedding (rnaseq PCA)",
        subtitle="DESeq2 PCA from nf-core/rnaseq, coloured by condition",
        icon="mdi:atom",
        icon_color="grape",
        component_title="Embedding — nf-core/rnaseq DESeq2 PCA",
        description=(
            "Sample projection from DESeq2 vst() PCA (5 samples × 3 conditions). "
            "The condition column is derived from the sample naming convention "
            "(WT / RAP1_UNINDUCED / RAP1_IAA_30M) to drive cluster colouring."
        ),
        config={
            "viz_kind": "embedding",
            "mode": "precomputed",
            "sample_id_col": "Sample",
            "dim_1_col": "x",
            "dim_2_col": "y",
            "cluster_col": "condition",
            "color_col": "condition",
        },
        tab_order=5,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["complex_heatmap"],
        viz_kind="complex_heatmap",
        dc_tag="deseq2_vst_top100",
        dc_id=DC["deseq2_vst_top100"],
        title="Hierarchical Heatmap (DESeq2 vst)",
        subtitle="Top-100 most-variable genes",
        icon="mdi:grid",
        icon_color="orange",
        component_title="Hierarchical Heatmap — DESeq2 vst()",
        description=(
            "Clustered heatmap of the top-100 most-variable genes from the "
            "DESeq2 vst() matrix (24 samples × 100 genes)."
        ),
        config={
            "viz_kind": "complex_heatmap",
            "matrix_wf_id": WF_ID,
            "matrix_dc_id": DC["deseq2_vst_top100"],
            "index_column": "gene_id",
            "cluster_rows": True,
            "cluster_cols": True,
            "cluster_method": "ward",
            "cluster_metric": "euclidean",
            "normalize": "row_z",
        },
        tab_order=6,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["rarefaction"],
        viz_kind="rarefaction",
        dc_tag="qiime2_rarefaction",
        dc_id=DC["qiime2_rarefaction"],
        title="Rarefaction (QIIME2 Shannon)",
        subtitle="Alpha-diversity vs sequencing depth",
        icon="mdi:chart-line",
        icon_color="cyan",
        component_title="Rarefaction — QIIME2 Shannon alpha-diversity",
        description=(
            "Shannon diversity vs subsampling depth (5 samples × 30 depths × 10 iterations), "
            "pre-melted from QIIME2's wide alpha-rarefaction output."
        ),
        config={
            "viz_kind": "rarefaction",
            "sample_id_col": "sample_id",
            "depth_col": "depth",
            "metric_col": "metric",
            "iter_col": "iter",
            "show_ci": True,
        },
        tab_order=7,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["stacked_taxonomy"],
        viz_kind="stacked_taxonomy",
        dc_tag="qiime2_stacked_taxonomy",
        dc_id=DC["qiime2_stacked_taxonomy"],
        title="Stacked taxonomy (QIIME2)",
        subtitle="Per-sample ASV composition",
        icon="mdi:chart-bar-stacked",
        icon_color="indigo",
        component_title="Stacked taxonomy — QIIME2 feature-table",
        description=(
            "Per-sample ASV abundances from nf-core/ampliseq. Single-rank stub "
            "(real multi-rank lineage would need a taxonkit join)."
        ),
        config={
            "viz_kind": "stacked_taxonomy",
            "sample_id_col": "sample_id",
            "taxon_col": "taxon",
            "rank_col": "rank",
            "abundance_col": "abundance",
        },
        tab_order=8,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["da_barplot"],
        viz_kind="da_barplot",
        dc_tag="ancombc_da_barplot",
        dc_id=DC["ancombc_da_barplot"],
        title="DA barplot (ANCOM-BC)",
        subtitle="Differential abundance from QIIME2 ANCOM-BC",
        icon="mdi:view-grid-plus-outline",
        icon_color="lime",
        component_title="DA barplot — ANCOM-BC differentials",
        description=(
            "Per-contrast log-fold-change bars from nf-core/ampliseq ANCOM-BC "
            "(Category-mix8-ASV). Two contrasts: (Intercept) + mix8a."
        ),
        config={
            "viz_kind": "da_barplot",
            "feature_id_col": "feature_id",
            "contrast_col": "contrast",
            "lfc_col": "lfc",
            "significance_col": "significance",
            "contrast_view": "all",
            "top_n": 20,
        },
        tab_order=9,
    ),
    _shell(
        dashboard_id=DASHBOARD_ID["sunburst"],
        viz_kind="sunburst",
        dc_tag="bracken_taxonomy",
        dc_id=DC["bracken_taxonomy"],
        title="Sunburst (Bracken)",
        subtitle="Per-sample taxonomy abundance",
        icon="mdi:sun-wireless",
        icon_color="yellow",
        component_title="Sunburst — Bracken per-sample taxonomy",
        description=(
            "Bracken per-sample taxonomy from nf-core/taxprofiler. Single-rank "
            "(taxonomy_lvl) sunburst — multi-rank lineage needs a taxonkit join."
        ),
        config={
            "viz_kind": "sunburst",
            "rank_cols": ["taxonomy_lvl", "name"],
            "abundance_col": "new_est_reads",
        },
        tab_order=10,
    ),
]


def main() -> None:
    for dash in DASHBOARDS:
        viz = dash["stored_metadata"][0]["viz_kind"]
        out = SEEDS_DIR / f"dashboard_{viz}.json"
        out.write_text(json.dumps(dash, indent=2) + "\n")
        print(f"wrote {out.relative_to(PROJECT_DIR.parent.parent.parent)}")
    print(f"\n{len(DASHBOARDS)} dashboards in {SEEDS_DIR}")


if __name__ == "__main__":
    main()
