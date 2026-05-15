"""Per-viz_kind Pydantic configs for advanced visualisation components.

Each config owns the role→column mapping (e.g. role ``effect_size`` →
column ``lfc``) plus per-kind display defaults (thresholds, top-N, sort
order). The union below is what the AdvancedViz component stores under
its ``config`` field; Pydantic discriminates by ``viz_kind``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    dim_1_col: str = Field(
        default="dim_1", description="Column with first embedding dim (precomputed mode)"
    )
    dim_2_col: str = Field(
        default="dim_2", description="Column with second embedding dim (precomputed mode)"
    )
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
    significance_col: str = Field(
        ..., description="FDR-adjusted p-value (used to bold significant bars)"
    )
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
    label_col: str | None = Field(default=None, description="Optional display label")
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


class ComplexHeatmapConfig(_BaseVizConfig):
    """ComplexHeatmap-style clustered heatmap with dendrograms + annotations.

    Wraps the in-tree ``packages/plotly-complexheatmap`` library. The Celery
    worker calls ``ComplexHeatmap.from_dataframe(...).to_plotly()`` and the
    React renderer hands the resulting Plotly figure dict to react-plotly.js.
    Heavy compute (clustering, dendrogram, layout) stays on the server;
    cached by (DC, params hash) like the live-clustering path.
    """

    viz_kind: Literal["complex_heatmap"] = "complex_heatmap"

    matrix_wf_id: str = Field(..., description="Workflow id of the matrix DC")
    matrix_dc_id: str = Field(..., description="DC id — wide matrix (row id + numeric cols)")
    index_column: str = Field(default="sample_id", description="Row-label column in the DC")
    value_columns: list[str] | None = Field(
        default=None,
        description="Subset of numeric columns to include in the heatmap. None → all numeric.",
    )
    row_annotation_cols: list[str] = Field(
        default_factory=list,
        description="Categorical columns from the DC rendered as a right-side annotation strip",
    )
    cluster_rows: bool = Field(default=True)
    cluster_cols: bool = Field(default=True)
    cluster_method: Literal["ward", "single", "complete", "average"] = Field(default="ward")
    cluster_metric: Literal["euclidean", "correlation", "cosine"] = Field(default="euclidean")
    normalize: Literal["none", "row_z", "col_z", "log1p"] = Field(default="none")
    colorscale: str | None = Field(default=None, description="Plotly colorscale name override")


class UpsetPlotConfig(_BaseVizConfig):
    """UpSet plot for set-intersection visualisation.

    Wraps the in-tree ``packages/plotly-upset`` library. The Celery worker
    calls ``UpSetPlot(df, set_columns=..., ...).to_plotly()`` and the React
    renderer hands the resulting Plotly figure dict to react-plotly.js.
    Input DC: a binary table where each row is an element and each set_col
    is a 0/1 membership indicator.
    """

    viz_kind: Literal["upset_plot"] = "upset_plot"

    matrix_wf_id: str = Field(..., description="Workflow id of the membership DC")
    matrix_dc_id: str = Field(..., description="DC id — binary membership table")
    set_columns: list[str] | None = Field(
        default=None,
        description="Explicit list of set columns. None → auto-detect binary columns.",
    )
    sort_by: Literal["cardinality", "degree", "degree-cardinality", "input"] = Field(
        default="cardinality"
    )
    sort_order: Literal["descending", "ascending"] = Field(default="descending")
    min_size: int = Field(default=1, ge=0, description="Hide intersections smaller than this")
    max_degree: int | None = Field(
        default=None, description="Hide intersections involving more than N sets"
    )
    show_set_sizes: bool = Field(default=True, description="Show horizontal set-size bar chart")
    color_intersections_by: Literal["none", "set", "degree"] = Field(default="none")


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
    default_layout: Literal["rectangular", "circular", "radial", "diagonal", "hierarchical"] = (
        Field(default="rectangular")
    )
    ladderize: bool = Field(default=True, description="Ladderise the tree by default")
    show_metadata_strip: bool = Field(
        default=True,
        description="Render Microreact-style metadata strip next to each tip",
    )
    show_branch_lengths: bool = Field(default=True, description="Annotate branches with lengths")
    show_internal_labels: bool = Field(
        default=False, description="Annotate internal nodes with their labels"
    )


class MAConfig(_BaseVizConfig):
    """MA (Bland-Altman) plot: mean log intensity (x) vs log fold change (y).

    Canonical post-DE / post-proteomics view. Shares the tier-coloured
    UP / DN / NS scheme with VolcanoConfig — same `significance_col` knob
    drives the colour split. The labelling story is also identical
    (top-N by |y| × -log10(sig), free-text search).
    """

    viz_kind: Literal["ma"] = "ma"

    feature_id_col: str = Field(..., description="Feature identifier column")
    avg_log_intensity_col: str = Field(
        ..., description="Column with average log intensity (x-axis, A in MA)"
    )
    log2_fold_change_col: str = Field(
        ..., description="Column with log2 fold change (y-axis, M in MA)"
    )
    significance_col: str | None = Field(
        default=None, description="Optional p/padj column for tier colouring"
    )
    label_col: str | None = Field(default=None, description="Optional hover label column")

    significance_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    fold_change_threshold: float = Field(default=1.0, ge=0.0)
    top_n_labels: int = Field(default=15, ge=0)


class DotPlotConfig(_BaseVizConfig):
    """Single-cell marker-gene dot plot.

    Rows = genes, columns = clusters. Each dot's colour encodes mean
    expression in that (gene, cluster) cell; dot size encodes the
    fraction of cells in the cluster expressing the gene above a cut-off.
    Canonical scanpy / Seurat ``dotplot`` layout.
    """

    viz_kind: Literal["dot_plot"] = "dot_plot"

    cluster_col: str = Field(..., description="Cluster / group column (x axis)")
    gene_col: str = Field(..., description="Gene / feature column (y axis)")
    mean_expression_col: str = Field(..., description="Mean expression value (dot colour)")
    frac_expressing_col: str = Field(
        ..., description="Fraction of cells expressing the gene in the cluster (dot size)"
    )

    max_dot_size: int = Field(default=22, ge=4, le=60, description="Max marker size in pixels")
    min_dot_size: int = Field(default=2, ge=0, le=20)


class LollipopConfig(_BaseVizConfig):
    """Lollipop / needle plot for variant / mutation tracks along a gene.

    Each gene's body is drawn as a horizontal line; each variant is a
    vertical stem with a marker on top, coloured by consequence category
    (``category_col``). Optional ``effect_col`` modulates marker size.
    """

    viz_kind: Literal["lollipop"] = "lollipop"

    feature_id_col: str = Field(..., description="Gene / feature the variant is on")
    position_col: str = Field(..., description="Position along the feature (integer)")
    category_col: str = Field(..., description="Variant consequence category (colour)")
    effect_col: str | None = Field(
        default=None, description="Optional numeric effect column (marker size)"
    )

    max_subplot_genes: int = Field(
        default=6,
        ge=1,
        description="When the gene universe exceeds this, switch to a single-gene picker",
    )


class QQConfig(_BaseVizConfig):
    """Quantile-quantile plot for p-value distributions (GWAS / DE / eQTL QC).

    Sorts p-values, plots ``-log10(observed)`` against the theoretical
    ``-log10(expected)`` under a uniform null. Y = x reference line + 95%
    null CI band are drawn client-side. Optional ``category_col`` produces
    one trace per stratum.
    """

    viz_kind: Literal["qq"] = "qq"

    p_value_col: str = Field(..., description="Raw p-value column (0–1)")
    feature_id_col: str | None = Field(default=None, description="Optional id column for hover")
    category_col: str | None = Field(
        default=None, description="Optional stratification column (one trace per value)"
    )
    show_ci: bool = Field(default=True, description="Shade the 95% null CI band")


class SunburstConfig(_BaseVizConfig):
    """Sunburst for taxonomic / hierarchical abundance.

    ``rank_cols`` lists the columns that form the hierarchy from root to
    leaf (e.g. ``[Kingdom, Phylum, Class, Order, Family, Genus]``).
    ``abundance_col`` is the leaf weight; intermediate arc sizes are
    reconstructed via Plotly's ``branchvalues='total'``.
    """

    viz_kind: Literal["sunburst"] = "sunburst"

    rank_cols: list[str] = Field(
        ..., min_length=2, description="Hierarchical rank columns from root to leaf"
    )
    abundance_col: str = Field(..., description="Leaf abundance weight column")


class CoverageTrackConfig(_BaseVizConfig):
    """Read-depth / signal coverage along a coordinate axis.

    Universal genomics primitive: nf-core viralrecon (mosdepth per-bin
    coverage), rnaseq (BigWig-derived transcript coverage), chipseq/atacseq
    (peak signal), methylseq (depth), mag/bacass (contig coverage), sarek QC.
    The renderer is a Plotly line/area plot; optional ``sample_col`` produces
    one subplot row per sample, optional ``category_col`` colour-segments
    the trace (annotation lane).
    """

    viz_kind: Literal["coverage_track"] = "coverage_track"

    chromosome_col: str = Field(..., description="Column with the chromosome / contig label")
    position_col: str = Field(
        ..., description="Column with the bin centre or single-base position (integer)"
    )
    value_col: str = Field(..., description="Column with the coverage / signal value")
    end_col: str | None = Field(
        default=None,
        description="Optional bin end column — when set with position_col, treated as interval",
    )
    sample_col: str | None = Field(
        default=None, description="Optional column for per-sample faceting (stacked subplots)"
    )
    category_col: str | None = Field(
        default=None,
        description="Optional categorical annotation column (gene region, peak class, …)",
    )

    # Display defaults — editable from the viz Settings popover.
    y_scale: Literal["linear", "log"] = Field(default="linear")
    smoothing_window: int = Field(
        default=0,
        ge=0,
        le=200,
        description="Rolling-mean window in bins (0 disables smoothing)",
    )
    color_by: Literal["single", "category", "sample"] = Field(
        default="single", description="Trace colour assignment mode"
    )
    show_annotation_lane: bool = Field(
        default=True,
        description="Render a thin annotation strip below the coverage when category_col is bound",
    )
    chromosomes_filter: list[str] | None = Field(
        default=None,
        description="Optional whitelist of chromosomes to display; null = all chromosomes",
    )
    samples_filter: list[str] | None = Field(
        default=None,
        description="Optional whitelist of samples to display; null = all samples",
    )


class SankeyConfig(_BaseVizConfig):
    """Sankey / categorical-flow diagram across N ordered categorical levels.

    Universal multi-step categorical flow: viralrecon (sample → lineage →
    clade), taxprofiler (sample → kingdom → phylum → genus), mag (sample →
    bin → taxonomy), airrflow (V → D → J gene), sarek (tissue → variant
    class → consequence). The Celery worker aggregates by ``step_cols`` and
    builds a Plotly ``sankey`` trace; the React renderer applies client-side
    sort / colour / opacity tweaks without re-dispatching.
    """

    viz_kind: Literal["sankey"] = "sankey"

    step_cols: list[str] = Field(
        ...,
        min_length=2,
        description="Ordered categorical columns from source to leaf (≥2 levels)",
    )
    value_col: str | None = Field(
        default=None,
        description="Optional numeric weight column; null → each row counts as 1",
    )

    # Display defaults — editable from the Settings popover.
    sort_mode: Literal["alphabetical", "total_flow", "input"] = Field(default="total_flow")
    color_mode: Literal["source", "target", "step"] = Field(default="source")
    link_opacity: float = Field(default=0.5, ge=0.05, le=1.0)
    min_link_value: float = Field(
        default=0.0,
        ge=0.0,
        description="Hide links whose aggregated value is below this threshold",
    )
    show_node_labels: bool = Field(default=True)

    @field_validator("step_cols")
    @classmethod
    def _step_cols_unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("step_cols must not contain duplicate column names")
        return v


class OncoplotConfig(_BaseVizConfig):
    """Oncoplot / co-mutation matrix (sample × gene × mutation type).

    Discrete heatmap with one colour per mutation type (NA cells stay
    blank). Side strips show per-gene and per-sample mutation counts.
    """

    viz_kind: Literal["oncoplot"] = "oncoplot"

    sample_id_col: str = Field(..., description="Sample identifier column (x axis)")
    gene_col: str = Field(..., description="Gene identifier column (y axis)")
    mutation_type_col: str = Field(
        ..., description="Categorical mutation-type column (cell colour)"
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
    | EnrichmentConfig
    | ComplexHeatmapConfig
    | UpsetPlotConfig
    | MAConfig
    | DotPlotConfig
    | LollipopConfig
    | QQConfig
    | SunburstConfig
    | OncoplotConfig
    | CoverageTrackConfig
    | SankeyConfig,
    Field(discriminator="viz_kind"),
]
