"""Per-viz_kind Pydantic configs for advanced visualisation components.

Each config owns the role→column mapping (e.g. role ``effect_size`` →
column ``lfc``) plus per-kind display defaults (thresholds, top-N, sort
order). The union below is what the AdvancedViz component stores under
its ``config`` field; Pydantic discriminates by ``viz_kind``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _BaseVizConfig(BaseModel):
    """Common base for all viz-kind configs."""

    model_config = ConfigDict(extra="forbid")


class VolcanoConfig(_BaseVizConfig):
    """Volcano plot: effect size (x) vs significance (y, usually -log10)."""

    viz_kind: Literal["volcano"] = "volcano"

    # Column bindings (role -> column name in the bound DC).
    feature_id_col: str = Field(..., description="Column with the feature identifier")
    effect_size_col: str = Field(..., description="Column with effect size (e.g. log2FC, lfc)")
    significance_col: str = Field(..., description="Column with p-value or padj/q-value")
    label_col: str | None = Field(default=None, description="Optional column for hover labels")
    category_col: str | None = Field(
        default=None, description="Optional column for point colour/category"
    )

    # Display defaults — editable from the viz UI as Tier-2 (intra-viz) controls.
    significance_is_neg_log10: bool = Field(
        default=False,
        description="True if significance_col already contains -log10(p); else applied client-side",
    )
    significance_threshold: float = Field(default=0.05, description="Default p/padj cutoff")
    effect_threshold: float = Field(default=1.0, description="Default |effect_size| cutoff")
    top_n_labels: int = Field(default=20, ge=0, description="How many top features to label")


class EmbeddingConfig(_BaseVizConfig):
    """2D/3D embedding scatter — supports two modes:

    1. **Precomputed mode** (default): the bound DC already has ``dim_1_col``
       and ``dim_2_col`` (and optionally ``dim_3_col``). The renderer just
       plots those coordinates. Use this when clustering has been run
       offline (e.g. recipe-driven, scanpy notebook).

    2. **Live-compute mode**: set ``compute_method`` to one of ``"pca"`` /
       ``"umap"`` / ``"tsne"`` / ``"pcoa"`` and bind to a wide sample×feature
       matrix DC. The renderer dispatches a Celery task via
       ``POST /advanced_viz/compute_embedding`` and renders the coordinates
       returned by the worker. The user can tune the per-method parameters
       below in the viz controls; each change re-dispatches a fresh job
       (cached on the server keyed by (dc, method, params, filters)).
    """

    viz_kind: Literal["embedding"] = "embedding"

    sample_id_col: str = Field(..., description="Column with the sample identifier")
    dim_1_col: str = Field(default="dim_1", description="Column with first embedding dim (precomputed mode)")
    dim_2_col: str = Field(default="dim_2", description="Column with second embedding dim (precomputed mode)")
    dim_3_col: str | None = Field(default=None, description="Optional third dim (enables 3D)")
    cluster_col: str | None = Field(default=None, description="Optional cluster assignment column")
    color_col: str | None = Field(
        default=None, description="Optional column for point colouring (metadata or expression)"
    )

    # --- Live-compute mode -------------------------------------------------
    # When `compute_method` is set, the renderer ignores dim_1_col/dim_2_col
    # and dispatches a Celery task that runs the chosen dim-reduction on the
    # wide sample×feature matrix bound via the standard (wf_id, dc_id).
    compute_method: Literal["pca", "umap", "tsne", "pcoa"] | None = Field(
        default=None,
        description="Run dim-reduction live on the server. Null → precomputed mode.",
    )

    # Per-method tunables. Frontend exposes the ones relevant to the active
    # method as sliders; the values flow through to the Celery worker's
    # run_pca / run_umap / run_tsne / run_pcoa calls.
    umap_n_neighbors: int = Field(default=15, ge=2, le=100)
    umap_min_dist: float = Field(default=0.1, ge=0.0, le=1.0)
    tsne_perplexity: float = Field(default=30.0, ge=2.0, le=100.0)
    tsne_n_iter: int = Field(default=1000, ge=250, le=5000)
    pcoa_distance: Literal["bray_curtis"] = Field(default="bray_curtis")

    show_density: bool = Field(default=False, description="Overlay density contours")
    point_size: int = Field(default=6, ge=1, le=30)


class ManhattanConfig(_BaseVizConfig):
    """Generic chr/pos/score plot.

    Covers true GWAS (variants), peak significance (ATAC/ChIP narrowPeak),
    and viral variant tracks. ``score_kind`` labels the y-axis honestly.
    """

    viz_kind: Literal["manhattan"] = "manhattan"

    chr_col: str = Field(..., description="Column with chromosome label")
    pos_col: str = Field(..., description="Column with genomic position (1-based)")
    score_col: str = Field(..., description="Column with the y-axis score")
    feature_col: str | None = Field(
        default=None, description="Optional column with feature/locus id (gene, SNP, peak)"
    )
    effect_col: str | None = Field(
        default=None, description="Optional column with signed effect for point colouring"
    )

    score_kind: str = Field(
        default="-log10(padj)",
        description="Y-axis label, e.g. '-log10(padj)', 'peak qvalue', 'variant AF'",
    )
    score_threshold: float | None = Field(
        default=None, description="Horizontal threshold line; None hides it"
    )


class StackedTaxonomyConfig(_BaseVizConfig):
    """Stacked composition bar (per-sample relative abundance by taxon)."""

    viz_kind: Literal["stacked_taxonomy"] = "stacked_taxonomy"

    sample_id_col: str = Field(..., description="Column with the sample identifier")
    taxon_col: str = Field(..., description="Column with taxon name")
    rank_col: str = Field(..., description="Column with taxonomic rank label")
    abundance_col: str = Field(..., description="Column with relative or absolute abundance")

    default_rank: str | None = Field(
        default=None,
        description="If rank_col carries multiple ranks, default-filter to this one",
    )
    top_n: int = Field(default=20, ge=1, description="Show top-N taxa, lump rest into 'Other'")
    sort_by: Literal["abundance", "alphabetical"] = Field(default="abundance")
    normalise_to_one: bool = Field(
        default=True, description="Force each sample's bars to sum to 1 (true % composition)"
    )


class RarefactionConfig(_BaseVizConfig):
    """Multi-sample alpha-rarefaction curve.

    Input: a long-format table with one row per (sample, depth, iter) where
    `metric_col` holds the alpha-diversity value at that subsampling depth.
    The renderer aggregates over iter (mean ± CI) and draws one line per
    sample, optionally coloured by a metadata `group_col`.
    """

    viz_kind: Literal["rarefaction"] = "rarefaction"

    sample_id_col: str = Field(..., description="Sample identifier column")
    depth_col: str = Field(..., description="Subsampling depth (x axis)")
    metric_col: str = Field(..., description="Alpha-diversity metric value (y axis)")
    iter_col: str | None = Field(
        default=None,
        description="Iteration column to aggregate over (mean / CI). Omit if already averaged.",
    )
    group_col: str | None = Field(
        default=None, description="Optional categorical column for line colour grouping"
    )
    show_ci: bool = Field(default=True, description="Shade ±1 SE band around each sample's curve")


class ANCOMBCDifferentialsConfig(_BaseVizConfig):
    """Ranked horizontal bar of ANCOM-BC log-fold-changes.

    Long-format input: one row per (feature, contrast) with lfc + significance.
    Renders top-N features by |lfc| for the selected contrast as a signed
    horizontal bar (up = enriched in the contrast's numerator, down = depleted).
    Orthogonal to the volcano viz — same data, different question.
    """

    viz_kind: Literal["ancombc_differentials"] = "ancombc_differentials"

    feature_id_col: str = Field(..., description="Feature / taxon identifier")
    contrast_col: str = Field(..., description="Contrast name (used for the dropdown)")
    lfc_col: str = Field(..., description="Log-fold-change (signed)")
    significance_col: str = Field(..., description="FDR-adjusted p-value (used to bold significant bars)")
    label_col: str | None = Field(
        default=None, description="Optional column for the bar's display label"
    )
    significance_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    top_n: int = Field(default=25, ge=1)


class DaBarplotConfig(_BaseVizConfig):
    """Per-contrast differential-abundance barplot.

    Faceted variant of the ANCOM-BC differentials viz: one small-multiples
    panel per contrast, top-N features ordered by signed lfc within each
    panel. Useful for comparing multiple contrasts side by side.
    """

    viz_kind: Literal["da_barplot"] = "da_barplot"

    feature_id_col: str = Field(..., description="Feature / taxon identifier")
    contrast_col: str = Field(..., description="Faceting column (one panel per contrast)")
    lfc_col: str = Field(..., description="Log-fold-change (signed)")
    significance_col: str | None = Field(
        default=None, description="FDR-adjusted p-value (for highlighting significant bars)"
    )
    label_col: str | None = Field(
        default=None, description="Optional display label"
    )
    significance_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    top_n: int = Field(default=15, ge=1, description="Top features (by |lfc|) shown per contrast")


class EnrichmentConfig(_BaseVizConfig):
    """GSEA / GO / KEGG / Reactome pathway-enrichment dot plot.

    Canonical layout: pathway/term name on the y-axis, NES (or signed
    enrichment score) on the x-axis, dot size encoding gene-set size,
    dot colour encoding -log10(padj). Filters: source MultiSelect
    (GO_BP / KEGG / ...), padj threshold, top-N pathways shown.
    """

    viz_kind: Literal["enrichment"] = "enrichment"

    term_col: str = Field(..., description="Pathway / GO-term name column")
    nes_col: str = Field(..., description="Normalised enrichment score (signed) — x axis")
    padj_col: str = Field(..., description="FDR-adjusted p-value")
    gene_count_col: str = Field(..., description="Gene-set size column — dot size")
    source_col: str | None = Field(
        default=None,
        description="Optional ontology / source column (GO_BP / KEGG / Reactome / Hallmark / ...).",
    )

    padj_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    top_n: int = Field(default=20, ge=1)


class PhylogeneticConfig(_BaseVizConfig):
    """Phylogenetic tree (Microreact-style) — Newick tree + tip metadata.

    The tree itself comes from a *separate* DC with `type: "phylogeny"` (see
    DCPhylogenyConfig). Tip annotations (group / habitat / clade label /
    clinical metadata) live in a regular Table DC and are joined to tip
    labels at render time via the `taxon_col` column.
    """

    viz_kind: Literal["phylogenetic"] = "phylogenetic"

    # Tree source — a phylogeny DC (the .nwk file lives on disk, served via
    # the /advanced_viz/phylogeny/{dc_id}/newick endpoint).
    tree_wf_id: str = Field(..., description="Workflow id of the phylogeny DC")
    tree_dc_id: str = Field(..., description="Data-collection id of the phylogeny DC")

    # Tip-metadata source — a table DC keyed by taxon name.
    metadata_wf_id: str | None = Field(
        default=None, description="Workflow id of the metadata table DC (optional)"
    )
    metadata_dc_id: str | None = Field(
        default=None, description="Data-collection id of the metadata table DC (optional)"
    )
    taxon_col: str = Field(
        default="taxon",
        description="Column in the metadata DC matching tip labels in the tree",
    )
    color_col: str | None = Field(
        default=None, description="Metadata column for tip colouring (categorical or continuous)"
    )
    label_col: str | None = Field(
        default=None, description="Metadata column shown alongside the tip label (e.g. clade name)"
    )

    # Display defaults (all editable from the viz controls).
    default_layout: Literal[
        "rectangular", "circular", "radial", "diagonal", "hierarchical"
    ] = Field(default="rectangular")
    ladderize: bool = Field(default=True, description="Ladderise the tree by default")
    show_metadata_strip: bool = Field(
        default=True,
        description="Render Microreact-style metadata strip next to each tip",
    )
    show_branch_lengths: bool = Field(
        default=True, description="Annotate branches with lengths"
    )
    show_internal_labels: bool = Field(
        default=False, description="Annotate internal nodes with their labels"
    )


# Discriminated union — the AdvancedViz component stores one of these.
VizConfig = Annotated[
    VolcanoConfig
    | EmbeddingConfig
    | ManhattanConfig
    | StackedTaxonomyConfig
    | PhylogeneticConfig
    | RarefactionConfig
    | ANCOMBCDifferentialsConfig
    | DaBarplotConfig
    | EnrichmentConfig,
    Field(discriminator="viz_kind"),
]
