"""Per-viz_kind Pydantic configs for advanced visualisation components.

Each config owns the role→column mapping (e.g. role ``effect_size`` →
column ``lfc``) plus per-kind display defaults (thresholds, top-N, sort
order). The union below is what the AdvancedViz component stores under
its ``config`` field; Pydantic discriminates by ``viz_kind``.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# The continuous colour scales every viz kind that exposes one offers. Single
# definition on the Python side; its React twin lives in
# packages/depictio-react-core/src/components/advanced_viz/colourScales.ts and
# must list the same names in the same order.
ColourScale = Literal["Viridis", "Plasma", "Inferno", "Magma", "Cividis", "RdBu", "Spectral"]


#: Assembly aliases a template's ``GENOME`` variable may carry, mapped onto
#: the bundled gene tables. Anything else (another organism, an unresolved
#: ``{GENOME}`` placeholder in a raw YAML) draws no gene lane.
_GENE_LANE_ALIASES: dict[str, str] = {
    "none": "none",
    "hg38": "hg38",
    "grch38": "hg38",
    "mm10": "mm10",
    "grcm38": "mm10",
}


def _coerce_gene_lane(value: Any) -> Any:
    """Map a free assembly string onto a bundled gene lane, else ``none``."""
    if value is None:
        return "none"
    if isinstance(value, str):
        return _GENE_LANE_ALIASES.get(value.strip().lower(), "none")
    return value


GeneLaneAssembly = Annotated[Literal["none", "hg38", "mm10"], BeforeValidator(_coerce_gene_lane)]


class _BaseVizConfig(BaseModel):
    """Common base for all viz-kind configs."""

    model_config = ConfigDict(extra="forbid")

    # Where the tile puts its encoding controls. ``popover`` is what every tile
    # did before this field existed: everything behind the Settings icon.
    # ``header`` lifts the primary controls (axes, colour-by, view switch, gene
    # picker) into the tile header, ``rail`` into a strip beside the plot. The
    # cosmetic tier stays in the popover either way. Declared on the base so
    # every kind carries it without one copy of the field per kind.
    controls_placement: Literal["popover", "rail", "header"] = Field(
        default="popover",
        description=(
            "Where the primary (encoding) controls live: the settings popover, "
            "a side rail, or the tile header"
        ),
    )


class VolcanoConfig(_BaseVizConfig):
    """Volcano plot: effect size (x) vs significance (y, usually -log10)."""

    viz_kind: Literal["volcano"] = "volcano"

    # Column bindings (role -> column name in the bound DC).
    feature_id_col: str = Field(
        default="feature_id", description="Column with the feature identifier"
    )
    effect_size_col: str = Field(
        default="effect_size", description="Column with effect size (e.g. log2FC, lfc)"
    )
    significance_col: str = Field(
        default="significance", description="Column with p-value or padj/q-value"
    )
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
    show_labels: bool = Field(
        default=True, description="Draw text labels on the highlighted points"
    )

    # --- Switchable views ---------------------------------------------------
    # The same differential-expression table drawn three ways (volcano, MA, QQ),
    # picked from a control in the tile header. The fields below are the extra
    # bindings the MA and QQ views need. All optional, so a volcano authored
    # before they existed keeps validating and keeps its look. They deliberately
    # carry the field names the retired ``ma`` and ``qq`` configs used, so a
    # stored config of either kind maps onto this one without a rename.
    avg_log_intensity_col: str | None = Field(
        default=None,
        description=(
            "MA view: column with the average log intensity (the A axis). Null "
            "means the MA view has nothing to put on x and is not offered."
        ),
    )
    log2_fold_change_col: str | None = Field(
        default=None,
        description=(
            "MA view: column with the log2 fold change (the M axis). Null falls "
            "back to effect_size_col, which is the same quantity in most tables."
        ),
    )
    fold_change_threshold: float = Field(
        default=1.0, ge=0.0, description="MA view: absolute fold-change cutoff"
    )
    p_value_col: str | None = Field(
        default=None,
        description=(
            "QQ view: raw p-value column. Null falls back to significance_col, "
            "which holds raw p-values unless significance_is_neg_log10 is set."
        ),
    )
    view: Literal["volcano", "ma", "qq"] = Field(
        default="volcano",
        description="Which of the three differential-expression views the tile opens on",
    )
    views: list[Literal["volcano", "ma", "qq"]] | None = Field(
        default=None,
        description="Views offered in the tile's switch; null offers every view the bindings allow",
    )
    show_ci: bool = Field(default=True, description="QQ view: shade the 95% null CI band")
    show_identity: bool = Field(default=True, description="QQ view: draw the y = x line")
    point_size: int = Field(default=5, ge=1, le=30, description="QQ view: marker size")


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

    sample_id_col: str = Field(default="sample_id", description="Column with the sample identifier")
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
    category_palette: dict[str, str] | None = Field(
        default=None,
        description=(
            "Explicit value→colour overrides for the categorical colour column. "
            "Wins over the default palette-index assignment so dashboards can "
            "pin domain-specific colours (e.g. habitat → Set1 palette) without "
            "forking the renderer per project."
        ),
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
    marker_outline_width: float = Field(
        default=1.5,
        ge=0.5,
        le=4,
        description="Point outline thickness in px, when the outline is enabled",
    )
    plot_style: Literal["default", "grid", "clean"] = Field(
        default="default",
        description=(
            "Axis decoration: 'default' keeps axis lines only, 'grid' adds "
            "gridlines and ticks, 'clean' drops the axes entirely."
        ),
    )
    default_color_by: str | None = Field(
        default=None,
        description=(
            "Initial value for the Colour-by dropdown. Falls back to "
            "``color_col`` then ``cluster_col`` when unset."
        ),
    )
    show_centroids: bool = Field(default=False, description="Mark each colour group's centroid")
    marker_outline: bool = Field(default=False, description="Draw a thin outline around each point")
    legend_pos: Literal["right", "bottom", "in-tr", "hidden"] = Field(
        default="right", description="Where the colour legend sits"
    )
    ncontours: int = Field(default=14, ge=1, description="Contour count for the density overlay")
    density_opacity: float = Field(
        default=0.45, ge=0, le=1, description="Opacity of the density overlay"
    )
    view_3d: bool = Field(
        default=False,
        description="Plot the third dimension; only available when dim_3_col is bound",
    )
    reverse_scale: bool = Field(default=True, description="Reverse the continuous colour scale")
    hover_cols: list[str] = Field(
        default_factory=list, description="Extra columns to show in the hover tooltip"
    )

    # --- Selection as a cross-filter ---------------------------------------
    # Off by default so a shipped dashboard keeps the lasso-free drag it has
    # today and no deployment inherits a cross-filter nobody asked for.
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a lasso / box / click selection emit a dashboard filter the "
            "Analysis panel can turn into a group. Draws a lasso-capable "
            "dragmode and stops the component from filtering itself."
        ),
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column the emitted selection values belong to. Null uses "
            "``sample_id_col``, which is what every point already carries as "
            "its identifier; name another column to select on something the "
            "other tiles join on instead."
        ),
    )


class ManhattanConfig(_BaseVizConfig):
    """Generic chr/pos/score plot.

    Covers true GWAS (variants), peak significance (ATAC/ChIP narrowPeak),
    and viral variant tracks. ``score_kind`` labels the y-axis honestly.
    """

    viz_kind: Literal["manhattan"] = "manhattan"

    chr_col: str = Field(default="chr", description="Column with chromosome label")
    pos_col: str = Field(default="pos", description="Column with genomic position (1-based)")
    score_col: str = Field(default="score", description="Column with the y-axis score")
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
    marker_size_above: int = Field(
        default=6,
        ge=1,
        le=30,
        description=(
            "Marker size (px) for points at or above ``score_threshold``. "
            "Only used when a threshold is set."
        ),
    )
    marker_size_below: int = Field(
        default=4,
        ge=1,
        le=30,
        description=(
            "Marker size (px) for points below ``score_threshold``. Lower than "
            "``marker_size_above`` by default so the eye lands on the hits, but "
            "tunable when the sub-threshold population is the interesting one "
            "(e.g. minority-allele variant discovery)."
        ),
    )
    marker_size_uniform: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Marker size when no threshold is set (uniform sizing).",
    )
    highlight: Literal["above", "below", "none"] = Field(
        default="above",
        description=(
            "Which side of ``score_threshold`` gets emphasised. ``above`` (default) "
            "colours and enlarges points at/above the threshold and dims those "
            "below — the GWAS / consensus-variant default. ``below`` inverts it "
            "(useful when minority alleles or sub-threshold candidates are the "
            "interesting population). ``none`` colours both sides equally; the "
            "threshold line is still drawn for reference. No effect when "
            "``score_threshold`` is None."
        ),
    )
    color_by_columns: list[str] = Field(
        default_factory=list,
        description=(
            "Extra columns to fetch alongside the required ones, exposed in the "
            "viz controls' Colour-by dropdown. The renderer auto-detects numeric "
            "vs categorical (continuous colorscale vs palette). ``Chromosome`` "
            "(default) and ``Score`` (the y-axis column) are always available "
            "without listing them here. Typical viralrecon usage: "
            "``['effect', 'lineage', 'sample']``."
        ),
    )
    default_color_by: str | None = Field(
        default=None,
        description=(
            "Initial value for the Colour-by dropdown. Either ``Chromosome``, "
            "``Score``, or one of ``color_by_columns``. Defaults to ``Chromosome``."
        ),
    )
    top_n_labels: int = Field(
        default=8,
        ge=0,
        description=(
            "How many of the most extreme points carry a text label. The catalog "
            "payload builder has always emitted this and the renderer has always "
            "read it; the field was simply missing, so every catalog-added "
            "Manhattan wrote a config that no longer validated on re-import."
        ),
    )

    # --- Selection as a cross-filter ---------------------------------------
    # Off by default, same reasoning as EmbeddingConfig above.
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a lasso / box / click selection emit a dashboard filter the "
            "Analysis panel can turn into a group. Requires "
            "``selection_column``; without one the renderer stays inert."
        ),
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column the emitted selection values belong to. There is no safe "
            "default: a point here is one row of a long variant table keyed by "
            "(sample, chromosome, position), so selecting on the sample column "
            "pulls every variant of the picked samples while selecting on a "
            "per-variant label narrows to those variants alone. The dashboard "
            "has to say which of the two it means. The column is fetched "
            "automatically; it does not also have to appear in "
            "``color_by_columns``."
        ),
    )

    # --- Rainfall mode ------------------------------------------------------
    # The mutation-density figure of every cancer-genome paper: the same
    # chr / pos rows, but y is the distance to the previous variant on the same
    # chromosome, so clustered events (kataegis) fall to the bottom of the plot
    # and the eye reads density rather than significance. Opt-in, so a Manhattan
    # authored before this existed keeps drawing its score.
    mode: Literal["manhattan", "rainfall"] = Field(
        default="manhattan",
        description=(
            "``manhattan`` (default) puts score_col on y. ``rainfall`` puts "
            "log10 of the distance to the previous variant on the same "
            "chromosome on y and ignores score_col."
        ),
    )
    rainfall_class_col: str | None = Field(
        default=None,
        description=(
            "Rainfall mode: column whose values colour each point (mutation "
            "class, consequence, caller). Null colours by chromosome as usual."
        ),
    )


class StackedTaxonomyConfig(_BaseVizConfig):
    """Stacked composition bar (per-sample relative abundance by taxon)."""

    viz_kind: Literal["stacked_taxonomy"] = "stacked_taxonomy"

    sample_id_col: str = Field(default="sample_id", description="Column with the sample identifier")
    taxon_col: str = Field(default="taxon", description="Column with taxon name")
    rank_col: str = Field(default="rank", description="Column with taxonomic rank label")
    abundance_col: str = Field(
        default="abundance", description="Column with relative or absolute abundance"
    )

    default_rank: str | None = Field(
        default=None,
        description="If rank_col carries multiple ranks, default-filter to this one",
    )
    top_n: int = Field(default=20, ge=1, description="Show top-N taxa, lump rest into 'Other'")
    sort_by: Literal["abundance", "alphabetical"] = Field(default="abundance")
    normalise_to_one: bool = Field(
        default=True, description="Force each sample's bars to sum to 1 (true % composition)"
    )
    annotation_strips: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Generic per-sample categorical annotation strips drawn above or "
            "below the stacked bars. Each entry is a dict with keys: "
            "``column`` (str, required — DC column to read per-sample value), "
            "``label`` (str, optional — strip label; defaults to column name), "
            "``position`` ('top' | 'bottom', default 'bottom'), "
            "``palette`` ({value: hex}, optional — overrides default cycling). "
            "Reusable across any per-sample categorical metadata (habitat, "
            "batch, treatment, timepoint). Renderer pulls the required columns "
            "automatically — no recipe change needed beyond emitting the column."
        ),
    )
    sample_sort: Literal["input", "total_abundance", "first_taxon"] = Field(
        default="input", description="Order of samples along the x axis"
    )
    show_legend: bool = Field(default=True, description="Show the taxon colour legend")
    log_y: bool = Field(default=False, description="Log-scale the abundance axis")


class RarefactionConfig(_BaseVizConfig):
    """Multi-sample alpha-rarefaction curve.

    Input: a long-format table with one row per (sample, depth, iter) where
    `metric_col` holds the alpha-diversity value at that subsampling depth.
    The renderer aggregates over iter (mean ± CI) and draws one line per
    sample, optionally coloured by a metadata `group_col`.
    """

    viz_kind: Literal["rarefaction"] = "rarefaction"

    sample_id_col: str = Field(default="sample_id", description="Sample identifier column")
    depth_col: str = Field(default="depth", description="Subsampling depth (x axis)")
    metric_col: str = Field(default="metric", description="Alpha-diversity metric value (y axis)")
    metric_options: list[str] | None = Field(
        default=None,
        description=(
            "Metric columns the renderer's tab-strip lets the user switch between "
            "(each an alternative y-axis, e.g. shannon / observed_features / faith_pd). "
            "Omit to show only metric_col."
        ),
    )
    iter_col: str | None = Field(
        default=None,
        description="Iteration column to aggregate over (mean / CI). Omit if already averaged.",
    )
    group_col: str | None = Field(
        default=None, description="Optional categorical column for line colour grouping"
    )
    category_palette: dict[str, str] | None = Field(
        default=None,
        description=(
            "Explicit value→colour overrides for the group_col categories. "
            "Pins domain palettes (e.g. habitat → Set1) across PCoA + UpSet + "
            "heatmap + rarefaction for cross-tab consistency."
        ),
    )
    show_ci: bool = Field(default=True, description="Shade ±1 SE band around each sample's curve")
    top_n: int = Field(default=60, ge=1, description="How many samples to draw before truncating")


class DaBarplotConfig(_BaseVizConfig):
    """Differential-abundance barplot — single panel or faceted across contrasts.

    Long-format input: one row per (feature, contrast) with lfc + optional
    significance. Renders top-N features by |lfc|. ``contrast_view`` controls
    layout: ``"all"`` = faceted small-multiples (one panel per contrast); any
    specific contrast value = single panel drilling into that contrast.

    Previously split into ``ancombc_differentials`` (single-panel + contrast
    dropdown) and ``da_barplot`` (faceted). Both collapsed here — the legacy
    ``viz_kind: ancombc_differentials`` string is rewritten to ``da_barplot``
    at deserialisation by AdvancedVizLiteComponent's pre-validator.
    """

    viz_kind: Literal["da_barplot"] = "da_barplot"

    feature_id_col: str = Field(default="feature_id", description="Feature / taxon identifier")
    contrast_col: str = Field(
        default="contrast", description="Contrast name (faceting + single-panel filter)"
    )
    lfc_col: str = Field(default="lfc", description="Log-fold-change (signed)")
    significance_col: str | None = Field(
        default=None, description="FDR-adjusted p-value (for highlighting significant bars)"
    )
    label_col: str | None = Field(default=None, description="Optional display label")
    significance_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    top_n: int = Field(default=15, ge=1, description="Top features (by |lfc|) shown per panel")
    contrast_view: str = Field(
        default="all",
        description=(
            "'all' → faceted view (one panel per contrast); any specific contrast value → "
            "single-panel drill-in. Used as the initial active tab in the React renderer."
        ),
    )


class EnrichmentConfig(_BaseVizConfig):
    """GSEA / GO / KEGG / Reactome pathway-enrichment dot plot.

    Canonical layout: pathway/term name on the y-axis, NES (or signed
    enrichment score) on the x-axis, dot size encoding gene-set size,
    dot colour encoding -log10(padj). Filters: source MultiSelect
    (GO_BP / KEGG / ...), padj threshold, top-N pathways shown.
    """

    viz_kind: Literal["enrichment"] = "enrichment"

    term_col: str = Field(default="term", description="Pathway / GO-term name column")
    nes_col: str = Field(default="nes", description="Normalised enrichment score (signed) — x axis")
    padj_col: str = Field(default="padj", description="FDR-adjusted p-value")
    gene_count_col: str = Field(default="gene_count", description="Gene-set size column — dot size")
    source_col: str | None = Field(
        default=None,
        description="Optional ontology / source column (GO_BP / KEGG / Reactome / Hallmark / ...).",
    )

    padj_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    top_n: int = Field(default=20, ge=1)
    default_colour_by: Literal["neg_log10_padj", "abs_nes", "nes_sign", "gene_count"] = Field(
        default="neg_log10_padj", description="Which quantity drives the point colour"
    )

    # Display options, shared vocabulary with DotPlotConfig below. Every default
    # here reproduces what the renderer drew before they existed, so a dashboard
    # that never set them keeps its appearance.
    colour_scale: Literal["Auto"] | ColourScale = Field(
        default="Auto",
        description=(
            "Continuous colour scale. 'Auto' picks per colour-by mode and theme "
            "(a discrete blue/red palette for NES sign); any named scale overrides all modes."
        ),
    )
    reverse_scale: bool = Field(default=False, description="Reverse the colour scale")
    max_dot_size: int = Field(default=30, ge=4, le=60, description="Max marker size in pixels")
    min_dot_size: int = Field(
        default=6, ge=0, le=20, description="Marker size at the smallest gene set"
    )
    term_sort: Literal["nes", "significance", "gene_count", "name"] = Field(
        default="nes", description="Ordering of the term axis, most notable at the top"
    )
    annotate_top_n: int = Field(
        default=0,
        ge=0,
        description="Label this many most-significant dots with their gene count; 0 draws none",
    )
    marker_outline: bool = Field(default=False, description="Draw an outline around each dot")


def _pattern_compiles(field: str, v: str | None) -> str | None:
    """Reject a column-name pattern that is not a valid regular expression."""
    if v is not None:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"{field} is not a valid regular expression: {exc}") from exc
    return v


class ComplexHeatmapConfig(_BaseVizConfig):
    """ComplexHeatmap-style clustered heatmap with dendrograms + annotations.

    Wraps the in-tree ``packages/plotly-complexheatmap`` library. The Celery
    worker calls ``ComplexHeatmap.from_dataframe(...).to_plotly()`` and the
    React renderer hands the resulting Plotly figure dict to react-plotly.js.
    Heavy compute (clustering, dendrogram, layout) stays on the server;
    cached by (DC, params hash) like the live-clustering path.
    """

    viz_kind: Literal["complex_heatmap"] = "complex_heatmap"

    matrix_wf_id: str | None = Field(
        default=None,
        description=(
            "Deprecated/unused: the renderer loads data from the component's "
            "resolved dc_id (data_collection_tag), not from this field. Kept "
            "optional for backward compatibility with older seeds."
        ),
    )
    matrix_dc_id: str | None = Field(
        default=None,
        description="Deprecated/unused (see matrix_wf_id). Kept optional for back-compat.",
    )
    index_column: str = Field(default="sample_id", description="Row-label column in the DC")
    value_columns: list[str] | None = Field(
        default=None,
        description="Subset of numeric columns to include in the heatmap. None → all numeric.",
    )
    value_columns_pattern: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Regular expression naming the value columns, for a matrix whose columns "
            "are only known at ingest (one per sample of the run). Matched with "
            "``re.search`` against the numeric columns of the loaded frame, less "
            "``index_column`` and ``row_annotation_cols``, and kept in frame order. "
            "Mutually exclusive with ``value_columns``."
        ),
    )
    row_annotation_cols: list[str] = Field(
        default_factory=list,
        description="Categorical columns from the DC rendered as a right-side annotation strip",
    )
    col_annotations: dict[str, dict[str, str]] | None = Field(
        default=None,
        description=(
            "Per-column categorical annotations rendered as a top strip. Shape: "
            "``{annotation_name: {column_label: category_value}}``. E.g. "
            "``{'habitat': {'SRR10070130': 'Riverwater', 'SRR10070131': 'Riverwater', ...}}``. "
            "The renderer aligns the values to the matrix's column order. Use when "
            "per-sample metadata (treatment / habitat / batch) needs to live on the "
            "column axis without joining a second DC."
        ),
    )
    col_annotation_cols: list[str] = Field(
        default_factory=list,
        description=(
            "Columns of the LINKED METADATA DC to draw as a top strip, named "
            "declaratively instead of baked into ``col_annotations``. E.g. "
            "``[condition, replicate, read_type]`` on an rnaseq expression matrix "
            "pulls those three off the samplesheet. Opt-in: an empty list resolves "
            "no link and issues no extra query, which is why this is safe to leave "
            "unset everywhere. The server resolves the single enabled link whose "
            "TARGET is this matrix and whose SOURCE DC carries ``metatype: "
            "Metadata``, then joins on that link's ``source_column``. Restricting "
            "to metadata sources is what keeps a matrix-to-matrix link (a derived "
            "stats table, say) from ever becoming an annotation source. When the "
            "gate leaves zero or several candidates nothing is drawn and the "
            "dispatcher logs why, rather than guessing; name "
            "``annotation_source_dc_tag`` to settle it."
        ),
    )
    annotation_source_dc_tag: str | None = Field(
        default=None,
        description=(
            "Which linked metadata DC ``col_annotation_cols`` reads from, for the "
            "case where a matrix has more than one. Only consulted when "
            "``col_annotation_cols`` is non-empty, and the named DC still has to be "
            "a linked ``metatype: Metadata`` source: this picks among candidates, "
            "it does not widen what may become one."
        ),
    )
    col_annotation_colors: dict[str, dict[str, str]] | None = Field(
        default=None,
        description=(
            "Optional per-annotation colour overrides for the column-annotation "
            "track. Shape: ``{annotation_name: {category_value: hex}}``. When "
            "unset the server picks colours from a Dark2 palette (chosen to "
            "contrast with the row-track's Set2 pastels so the two tracks "
            "read as distinct families). Use to pin domain palettes (e.g. "
            "habitat → Set1) across PCoA + UpSet + heatmap. Applies to both "
            "``col_annotations`` and ``col_annotation_cols`` strips."
        ),
    )
    cluster_rows: bool = Field(default=True)
    cluster_cols: bool = Field(default=True)
    cluster_method: Literal["ward", "single", "complete", "average"] = Field(default="ward")
    cluster_metric: Literal["euclidean", "correlation", "cosine"] = Field(default="euclidean")
    normalize: Literal["none", "row_z", "col_z", "log1p"] = Field(default="none")
    colorscale: str | None = Field(default=None, description="Plotly colorscale name override")

    @field_validator("value_columns_pattern")
    @classmethod
    def _value_columns_pattern_compiles(cls, v: str | None) -> str | None:
        return _pattern_compiles("value_columns_pattern", v)

    @model_validator(mode="after")
    def _value_columns_named_one_way(self) -> ComplexHeatmapConfig:
        if self.value_columns is not None and self.value_columns_pattern is not None:
            raise ValueError(
                "value_columns and value_columns_pattern are mutually exclusive: list the "
                "columns or name them by pattern, not both"
            )
        return self


class UpsetPlotConfig(_BaseVizConfig):
    """UpSet plot for set-intersection visualisation.

    Wraps the in-tree ``packages/plotly-upset`` library. The Celery worker
    calls ``UpSetPlot(df, set_columns=..., ...).to_plotly()`` and the React
    renderer hands the resulting Plotly figure dict to react-plotly.js.
    Input DC: a binary table where each row is an element and each set_col
    is a 0/1 membership indicator.
    """

    viz_kind: Literal["upset_plot"] = "upset_plot"

    matrix_wf_id: str | None = Field(
        default=None,
        description=(
            "Deprecated/unused: the renderer loads data from the component's "
            "resolved dc_id (data_collection_tag), not from this field. Kept "
            "optional for backward compatibility with older seeds."
        ),
    )
    matrix_dc_id: str | None = Field(
        default=None,
        description="Deprecated/unused (see matrix_wf_id). Kept optional for back-compat.",
    )
    set_columns: list[str] | None = Field(
        default=None,
        description="Explicit list of set columns. None → auto-detect binary columns.",
    )
    set_columns_pattern: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Regular expression naming the set columns, for a matrix whose set "
            "columns are only known at ingest (one per sample of the run). Matched "
            "with ``re.search`` against the binary columns of the loaded frame and "
            "kept in frame order. Mutually exclusive with ``set_columns``."
        ),
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
    set_colors: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional per-set colour overrides (set name → hex). Drives set-size "
            "bars + matrix dots + intersection bars when color_intersections_by='set'. "
            "Use to pin domain palettes (e.g. habitat → Set1) consistently across tiles."
        ),
    )
    default_annotation_cols: list[str] | None = Field(
        default=None,
        description=(
            "Columns shown as annotation rows under the intersection matrix on "
            "first paint. Read by the renderer since the annotation strip was "
            "added; the field was missing here, so the value could be rendered "
            "but never validated."
        ),
    )
    show_values: bool = Field(
        default=False, description="Print the count above each intersection bar"
    )
    show_annotations: bool = Field(
        default=True,
        description="Master toggle for the set-size bars and annotation tracks",
    )

    @field_validator("set_columns_pattern")
    @classmethod
    def _set_columns_pattern_compiles(cls, v: str | None) -> str | None:
        return _pattern_compiles("set_columns_pattern", v)

    @model_validator(mode="after")
    def _sets_named_one_way(self) -> UpsetPlotConfig:
        if self.set_columns is not None and self.set_columns_pattern is not None:
            raise ValueError(
                "set_columns and set_columns_pattern are mutually exclusive: list the "
                "sets or name them by pattern, not both"
            )
        return self


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
    # Portable alternative to the raw ids: a dashboard YAML shipped with a
    # template cannot know the ObjectIds a fresh project will mint, so it names
    # the DCs by tag and `_resolve_workflow_tags` rewrites the *_id fields at
    # import time (same contract as the map's `geojson_dc_tag`).
    tree_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the phylogeny DC (resolved to ids at import)",
    )

    # Tip-metadata source — a table DC keyed by taxon name.
    metadata_wf_id: str | None = Field(
        default=None, description="Workflow id of the metadata table DC (optional)"
    )
    metadata_dc_id: str | None = Field(
        default=None, description="Data-collection id of the metadata table DC (optional)"
    )
    metadata_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the metadata table DC (resolved to ids at import)",
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
    extra_color_cols: list[str] | None = Field(
        default=None,
        description=(
            "Extra metadata columns to pre-fetch so they appear in the viz "
            "'Colour by' Select. Typical use: taxonomic ranks on ASV trees "
            "(Kingdom/Phylum/Class/Order/Family/Genus/Species) so the user can "
            "re-colour tips at a different rank without reloading."
        ),
    )
    category_palettes: dict[str, dict[str, str]] | None = Field(
        default=None,
        description=(
            "Per-column palette overrides for the 'Colour by' selector. Shape: "
            "``{column_name: {category_value: hex}}``. Use to pin domain "
            "palettes — e.g. ``dominant_habitat → Set1`` — so the same category "
            "lands on the same colour across PCoA, UpSet, heatmap and phylogeny "
            "tiles."
        ),
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

    feature_id_col: str = Field(default="feature_id", description="Feature identifier column")
    avg_log_intensity_col: str = Field(
        default="avg_log_intensity",
        description="Column with average log intensity (x-axis, A in MA)",
    )
    log2_fold_change_col: str = Field(
        default="log2_fold_change", description="Column with log2 fold change (y-axis, M in MA)"
    )
    significance_col: str | None = Field(
        default=None, description="Optional p/padj column for tier colouring"
    )
    label_col: str | None = Field(default=None, description="Optional hover label column")

    significance_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    fold_change_threshold: float = Field(default=1.0, ge=0.0)
    top_n_labels: int = Field(default=15, ge=0)
    show_labels: bool = Field(
        default=True, description="Draw text labels on the highlighted points"
    )


class DotPlotConfig(_BaseVizConfig):
    """Single-cell marker-gene dot plot.

    Rows = genes, columns = clusters. Each dot's colour encodes mean
    expression in that (gene, cluster) cell; dot size encodes the
    fraction of cells in the cluster expressing the gene above a cut-off.
    Canonical scanpy / Seurat ``dotplot`` layout.
    """

    viz_kind: Literal["dot_plot"] = "dot_plot"

    cluster_col: str = Field(default="cluster", description="Cluster / group column (x axis)")
    gene_col: str = Field(default="gene", description="Gene / feature column (y axis)")
    mean_expression_col: str = Field(
        default="mean_expression", description="Mean expression value (dot colour)"
    )
    frac_expressing_col: str = Field(
        default="frac_expressing",
        description="Fraction of cells expressing the gene in the cluster (dot size)",
    )

    max_dot_size: int = Field(default=22, ge=4, le=60, description="Max marker size in pixels")
    min_dot_size: int = Field(default=2, ge=0, le=20)
    colour_scale: Literal["Auto"] | ColourScale = Field(
        default="Viridis",
        description=(
            "Continuous colour scale for mean expression. 'Auto' lets the "
            "enrichment view pick per colour-by mode and theme."
        ),
    )
    reverse_scale: bool = Field(default=False, description="Reverse the colour scale")
    log_transform: bool = Field(
        default=False, description="Log-transform mean expression before colouring"
    )
    gene_sort: Literal["name", "mean", "frac"] = Field(
        default="name", description="Ordering of the gene axis"
    )
    cluster_sort: Literal["name", "mean", "frac"] = Field(
        default="name", description="Ordering of the cluster axis"
    )
    annotate_top_n: int = Field(
        default=0, ge=0, description="Label this many highest-mean dots; 0 draws none"
    )
    marker_outline: bool = Field(default=True, description="Draw an outline around each dot")
    max_genes: int = Field(default=50, ge=1, description="How many genes to draw before truncating")

    # --- Switchable views ---------------------------------------------------
    # Same marks, same size and colour channels, a different table: the
    # enrichment view puts a pathway on the y axis, its NES on x, the gene-set
    # size in the dot area and the adjusted p-value in the colour. The fields
    # below carry the names the retired ``enrichment`` config used, so a stored
    # config of that kind maps onto this one without a rename. All optional:
    # a marker dot plot authored before they existed is untouched.
    term_col: str | None = Field(
        default=None, description="Enrichment view: pathway / GO-term name column (y axis)"
    )
    nes_col: str | None = Field(
        default=None, description="Enrichment view: normalised enrichment score column (x axis)"
    )
    padj_col: str | None = Field(
        default=None, description="Enrichment view: FDR-adjusted p-value column (dot colour)"
    )
    gene_count_col: str | None = Field(
        default=None, description="Enrichment view: gene-set size column (dot size)"
    )
    source_col: str | None = Field(
        default=None,
        description="Enrichment view: optional ontology / source column (GO_BP, KEGG, ...)",
    )
    padj_threshold: float = Field(
        default=0.05, ge=0.0, le=1.0, description="Enrichment view: significance cutoff"
    )
    top_n: int = Field(default=20, ge=1, description="Enrichment view: how many terms to draw")
    default_colour_by: Literal["neg_log10_padj", "abs_nes", "nes_sign", "gene_count"] = Field(
        default="neg_log10_padj",
        description="Enrichment view: which quantity drives the point colour",
    )
    term_sort: Literal["nes", "significance", "gene_count", "name"] = Field(
        default="nes", description="Enrichment view: ordering of the term axis"
    )
    view: Literal["dotplot", "enrichment"] = Field(
        default="dotplot", description="Which of the two dot-plot views the tile opens on"
    )
    views: list[Literal["dotplot", "enrichment"]] | None = Field(
        default=None,
        description="Views offered in the tile's switch; null offers every view the bindings allow",
    )


class LollipopConfig(_BaseVizConfig):
    """Lollipop / needle plot for variant / mutation tracks along a gene.

    Each gene's body is drawn as a horizontal line; each variant is a
    vertical stem with a marker on top, coloured by consequence category
    (``category_col``). Optional ``effect_col`` modulates marker size.
    """

    viz_kind: Literal["lollipop"] = "lollipop"

    feature_id_col: str = Field(
        default="feature_id", description="Gene / feature the variant is on"
    )
    position_col: str = Field(
        default="position", description="Position along the feature (integer)"
    )
    category_col: str = Field(
        default="category", description="Variant consequence category (colour)"
    )
    effect_col: str | None = Field(
        default=None, description="Optional numeric effect column (marker size)"
    )
    label_col: str | None = Field(
        default=None,
        description=(
            "Optional column naming each stem (gene symbol, variant id). "
            "``feature_id_col`` is the TRACK the stems are drawn on (one "
            "subplot lane per distinct value), so without this the hover and "
            "the ``top_n_labels`` text can only name the lane and the raw "
            "position. Unset leaves both exactly as they were."
        ),
    )

    max_subplot_genes: int = Field(
        default=6,
        ge=1,
        description="When the gene universe exceeds this, switch to a single-gene picker",
    )
    point_size: int = Field(default=8, ge=1, le=40, description="Head size of each lollipop")
    stem_width: float = Field(
        default=1.2, ge=0, le=10, description="Line width of the lollipop stems"
    )
    scale_points_by_effect: bool = Field(
        default=True, description="Scale head size by the effect column"
    )
    show_stems: bool = Field(default=True, description="Draw the stems under the heads")
    marker_outline: bool = Field(default=False, description="Draw an outline around each head")
    palette: Literal["tab10", "tab20"] = Field(
        default="tab10", description="Categorical palette for the effect categories"
    )
    gene_sort: Literal["name", "count", "effect"] = Field(
        default="count", description="Ordering of the gene subplots"
    )
    top_n_labels: int = Field(
        default=0, ge=0, description="Label this many most extreme points; 0 draws none"
    )


class QQConfig(_BaseVizConfig):
    """Quantile-quantile plot for p-value distributions (GWAS / DE / eQTL QC).

    Sorts p-values, plots ``-log10(observed)`` against the theoretical
    ``-log10(expected)`` under a uniform null. Y = x reference line + 95%
    null CI band are drawn client-side. Optional ``category_col`` produces
    one trace per stratum.
    """

    viz_kind: Literal["qq"] = "qq"

    p_value_col: str = Field(default="p_value", description="Raw p-value column (0–1)")
    feature_id_col: str | None = Field(default=None, description="Optional id column for hover")
    category_col: str | None = Field(
        default=None, description="Optional stratification column (one trace per value)"
    )
    show_ci: bool = Field(default=True, description="Shade the 95% null CI band")
    show_identity: bool = Field(default=True, description="Draw the y = x reference line")
    point_size: int = Field(default=5, ge=1, le=30, description="Marker size")
    top_n_labels: int = Field(
        default=0, ge=0, description="Label this many most extreme points; 0 draws none"
    )


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
    abundance_col: str = Field(default="abundance", description="Leaf abundance weight column")
    category_palette: dict[str, str] | None = Field(
        default=None,
        description=(
            "Explicit value→colour overrides for the colour-key categories "
            "(whichever rank the user's `Colour by` picker chooses). Use to pin "
            "domain palettes (e.g. Habitat → Set1) so the same category lands "
            "on the same colour as the matching PCoA / UpSet / heatmap tiles."
        ),
    )
    # Ring controls. The two rank pickers store a rank *name* rather than an
    # index into ``rank_cols``: re-binding the hierarchy would leave an index
    # pointing at a different rank, silently changing the chart someone saved.
    start_rank: str | None = Field(
        default=None,
        description=(
            "Which rank forms the innermost ring. Null starts at the root of "
            "``rank_cols``. A name no longer present falls back to the root."
        ),
    )
    colour_by_rank: str | None = Field(
        default=None,
        description=(
            "Which rank drives the colour key. Null, or a rank outside the "
            "visible window, colours by the innermost visible ring."
        ),
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        description="How many rings to draw from the start rank outwards",
    )
    palette: Literal["tab10", "tab20"] = Field(
        default="tab20",
        description="Categorical palette for the colour key; tab20 for wider hierarchies",
    )
    show_counts: bool = Field(default=True, description="Label each arc with its share of the root")
    min_percent: float = Field(
        default=0.5,
        ge=0,
        le=50,
        description="Hide arcs below this share of the root, as a percentage",
    )


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

    chromosome_col: str = Field(
        default="chromosome", description="Column with the chromosome / contig label"
    )
    position_col: str = Field(
        default="position",
        description="Column with the bin centre or single-base position (integer)",
    )
    value_col: str = Field(default="value", description="Column with the coverage / signal value")
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
        default=5,
        ge=0,
        le=200,
        description=(
            "Rolling-mean window in bins (0 disables smoothing). Default 5 ≈ 1 kb "
            "at 200-bp mosdepth bins — kills high-frequency wiggle without flattening "
            "amplicon-scale dropouts. Set to 0 explicitly to disable."
        ),
    )
    color_by: Literal["single", "category", "sample"] = Field(
        default="single", description="Trace colour assignment mode"
    )
    show_annotation_lane: bool = Field(
        default=True,
        description="Render a thin annotation strip below the coverage when category_col is bound",
    )
    annotation_id: str | None = Field(
        default=None,
        description=(
            "Optional bundled-annotation override. When null (default), the renderer "
            "auto-detects the assembly from the bound DC's chromosome value (e.g. "
            "``MN908947.3`` → SARS-CoV-2). Pin this when your data uses a non-standard "
            "chromosome name (e.g. internal isolate IDs) but corresponds to a known "
            "assembly. See depictio-react-core's genome_annotations registry for valid "
            "IDs (``sars_cov_2``, ``rsv_a``, ``hiv_1``, ``mpox``, ``hbv``)."
        ),
    )
    chromosomes_filter: list[str] | None = Field(
        default=None,
        description="Optional whitelist of chromosomes to display; null = all chromosomes",
    )
    samples_filter: list[str] | None = Field(
        default=None,
        description="Optional whitelist of samples to display; null = all samples",
    )
    view_mode: Literal["aggregate", "facet", "overlay"] | None = Field(
        default=None,
        description=(
            "How multiple samples share the track: one aggregate line, one lane "
            "each, or all overlaid. Null lets the renderer pick from the sample "
            "count once the data arrives. The builder has always written this key "
            "and the renderer has always read it; the field was missing, so the "
            "resulting config failed validation on export and re-import."
        ),
    )
    show_individuals: bool = Field(
        default=True, description="Draw the per-sample traces under the aggregate"
    )
    mark: Literal["line", "rect", "point"] = Field(
        default="line",
        description=(
            "Trace geometry: a continuous line (default, today's rendering), "
            "filled rects per bin, or discrete points. Recorded so a later "
            "GenomeSpy spec can bind the same rows to an equivalent mark."
        ),
    )
    facet_by_sample: bool = Field(
        default=False,
        description=(
            "Force one lane per sample regardless of view_mode / sample count. "
            "Optional, defaults keep today's rendering."
        ),
    )

    # --- Switchable views ---------------------------------------------------
    # The ``locus`` view hands the same rows to the GenomeSpy track the
    # genome_view kind draws, so a template that used to bind coverage_track and
    # genome_view on one data collection can bind one tile instead. Both fields
    # below only reach that view; the smoothed Plotly track ignores them.
    locus_annotation: GeneLaneAssembly = Field(
        default="none",
        description="Locus view: bundled gene lane drawn under the track",
    )
    locus_assembly: str | None = Field(
        default=None,
        description=(
            "Locus view: assembly whose contig lengths lay out the genome axis "
            "(hg38, mm10, ...). Null derives the axis from the rows themselves."
        ),
    )
    view: Literal["track", "locus"] = Field(
        default="track",
        description="``track`` draws the smoothed Plotly line; ``locus`` draws the zoomable genome track",
    )
    views: list[Literal["track", "locus"]] | None = Field(
        default=None,
        description="Views offered in the tile's switch; null offers every view the bindings allow",
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
    available_step_cols: list[str] | None = Field(
        default=None,
        description=(
            "Full ordered list of columns the user can wire as steps. When set, "
            "the renderer exposes a Depth slider that picks the first N columns "
            "from this list. ``step_cols`` is the initial prefix; leaving it "
            "unset locks the diagram to ``step_cols``."
        ),
    )
    value_col: str | None = Field(
        default=None,
        description="Optional numeric weight column; null → each row counts as 1",
    )
    value_label: str | None = Field(
        default=None,
        description=(
            "Human-readable label for the value column shown in hover tooltips. "
            "Defaults to ``value_col`` when unset (e.g. 'abundance')."
        ),
    )
    value_format: Literal["raw", "fraction", "count"] = Field(
        default="raw",
        description=(
            "Hover display mode: 'fraction' multiplies by 100 and appends '%'; "
            "'count' uses thousands separators; 'raw' adapts decimal precision "
            "to magnitude."
        ),
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

    depth: int | None = Field(
        default=None,
        ge=2,
        description=(
            "How many of ``available_step_cols`` to draw. Null uses the length of ``step_cols``."
        ),
    )


class OncoplotConfig(_BaseVizConfig):
    """Oncoplot / co-mutation matrix (sample × gene × mutation type).

    Discrete heatmap with one colour per mutation type (NA cells stay
    blank). Side strips show per-gene and per-sample mutation counts.
    """

    viz_kind: Literal["oncoplot"] = "oncoplot"

    sample_id_col: str = Field(default="sample_id", description="Sample identifier column (x axis)")
    gene_col: str = Field(default="gene", description="Gene identifier column (y axis)")
    mutation_type_col: str = Field(
        default="mutation_type", description="Categorical mutation-type column (cell colour)"
    )
    sort_by_freq: bool = Field(
        default=True, description="Order genes by mutation frequency rather than by name"
    )


# Discriminated union — the AdvancedViz component stores one of these.
class PrBenchmarkConfig(_BaseVizConfig):
    """Precision-recall benchmark scatter.

    Each point is a callset (tool / sample / caller) plotted at its
    (recall, precision). F1 iso-contours and the y=x diagonal are drawn as
    reference; optional ``f1_col`` colours points and ``support_col`` sizes
    them. The signature variant-benchmarking view — top-right is best.
    """

    viz_kind: Literal["pr_benchmark"] = "pr_benchmark"

    label_col: str = Field(
        default="label", description="Callset identifier (tool / sample / caller)"
    )
    recall_col: str = Field(default="recall", description="Recall / sensitivity column (x, 0-1)")
    precision_col: str = Field(default="precision", description="Precision column (y, 0-1)")
    f1_col: str = Field(default="f1", description="F1 column (point colour)")
    support_col: str | None = Field(
        default=None, description="Optional count column (e.g. TP) for point size"
    )
    category_col: str | None = Field(
        default=None, description="Optional column to colour points by category instead of F1"
    )

    show_iso_f1: bool = Field(default=True, description="Draw F1 iso-contours")
    show_diagonal: bool = Field(default=True, description="Draw the y=x reference line")
    show_labels: bool = Field(default=True, description="Annotate points with the label")
    colorscale: str = Field(
        default="Tealgrn", description="Continuous colour scale for the F1 point colour"
    )

    # --- Switchable views ---------------------------------------------------
    # One operating point per callset (the ``pr`` view) and the threshold sweep
    # that point sits on (the ``roc`` view) are the same benchmark read at two
    # zoom levels, so they share a tile and a control in its header. The fields
    # below carry the names the retired ``roc_pr_curve`` config used, so a
    # stored config of that kind maps onto this one without a rename. The sweep
    # views need a threshold column; without one only the ``pr`` view is
    # offered, which is what every benchmark authored so far draws.
    fpr_col: str | None = Field(
        default=None,
        description="ROC view: false-positive-rate column, which turns the curve into a true ROC",
    )
    threshold_col: str | None = Field(
        default=None, description="ROC view: quality-threshold column swept along the curve"
    )
    group_col: str | None = Field(
        default=None, description="ROC view: column that splits the sweep into one curve per group"
    )
    show_auc: bool = Field(
        default=True, description="ROC view: compute and show the area under the curve"
    )
    fill: bool = Field(default=False, description="ROC view: shade the area under each curve")
    view: Literal["pr", "roc", "both"] = Field(
        default="pr", description="Which of the benchmark views the tile opens on"
    )
    views: list[Literal["pr", "roc", "both"]] | None = Field(
        default=None,
        description="Views offered in the tile's switch; null offers every view the bindings allow",
    )


class RocPrCurveConfig(_BaseVizConfig):
    """Threshold-sweep precision-recall / ROC curve.

    Plots precision (y) against recall (x) across the quality-threshold sweep
    (e.g. hap.py ROC). Multiple curves are drawn when ``group_col`` is set
    (one line per tool / caller). Area under the curve is reported per group.
    """

    viz_kind: Literal["roc_pr_curve"] = "roc_pr_curve"

    recall_col: str = Field(default="recall", description="Recall / TPR column (0-1)")
    precision_col: str = Field(default="precision", description="Precision column (0-1)")
    fpr_col: str | None = Field(
        default=None,
        description="Optional false-positive-rate column — enables a true ROC (TPR vs FPR) case",
    )
    threshold_col: str | None = Field(
        default=None, description="Optional quality-threshold column (hover + sort order)"
    )
    group_col: str | None = Field(
        default=None, description="Optional column to split into one curve per group"
    )

    show_auc: bool = Field(default=True, description="Compute & show area under the curve")
    fill: bool = Field(default=False, description="Shade the area under each curve")


class ConfusionMatrixConfig(_BaseVizConfig):
    """Benchmark confusion matrix (TP / FP / FN, optionally TN) per callset.

    A compact heatmap of the exact counts that underlie precision/recall — one
    column block per callset (``label_col``), rows = TP / FP / FN (/ TN).
    Optionally row-normalised to fractions.
    """

    viz_kind: Literal["confusion_matrix"] = "confusion_matrix"

    label_col: str = Field(default="label", description="Callset identifier (tool / caller)")
    tp_col: str = Field(default="tp", description="True-positive count column")
    fp_col: str = Field(default="fp", description="False-positive count column")
    fn_col: str = Field(default="fn", description="False-negative count column")
    tn_col: str | None = Field(default=None, description="Optional true-negative count column")

    normalize: bool = Field(
        default=False, description="Show fractions instead of raw counts in cell labels"
    )
    normalize_mode: Literal["per_caller", "per_truth", "none"] = Field(
        default="per_caller", description="How cell colour is normalised"
    )
    colorscale: str = Field(default="Blues", description="Heatmap colour scale")


class MetricCiBarsConfig(_BaseVizConfig):
    """Metric bars with 95% confidence-interval whiskers.

    Horizontal bars of a single metric (precision / recall / F1) per callset
    with asymmetric error bars from ``lower_col`` / ``upper_col`` — surfaces
    the binomial CIs that som.py already emits but the plain bar charts drop.
    """

    viz_kind: Literal["metric_ci_bars"] = "metric_ci_bars"

    label_col: str = Field(default="label", description="Callset identifier (tool / caller)")
    value_col: str = Field(default="value", description="Metric value column (0-1)")
    lower_col: str = Field(default="lower", description="CI lower-bound column")
    upper_col: str = Field(default="upper", description="CI upper-bound column")
    metric_name: str = Field(default="F1", description="Display name of the metric (axis title)")
    sort_desc: bool = Field(default=True, description="Sort bars by value descending")
    colorscale: str = Field(default="Tealgrn", description="Continuous colour scale for the points")


class ScatterXyConfig(_BaseVizConfig):
    """Numeric against numeric: the plainest kind here, and the most asked for.

    Twenty-eight figures across ten nf-core templates drop into code mode to draw
    a scatter, and none of them does it for the shape. They do it for a marker
    size column, a `custom_data` selection key, a reference diagonal or a log
    axis, which is exactly the set below.
    """

    viz_kind: Literal["scatter_xy"] = "scatter_xy"

    x_col: str = Field(default="x", description="Numeric column on the x axis")
    y_col: str = Field(default="y", description="Numeric column on the y axis")
    label_col: str | None = Field(
        default=None, description="Column naming each point, used in hover and for labels"
    )
    color_col: str | None = Field(default=None, description="Column driving the marker colour")
    size_col: str | None = Field(default=None, description="Numeric column driving marker size")

    log_x: bool = Field(default=False, description="Log-scale the x axis")
    log_y: bool = Field(default=False, description="Log-scale the y axis")
    x_title: str | None = Field(default=None)
    y_title: str | None = Field(default=None)

    reference_line: Literal["none", "diagonal", "horizontal", "vertical"] = Field(
        default="none",
        description="Guide line: the identity diagonal, or a line at reference_value",
    )
    reference_value: float | None = Field(
        default=None, description="Where a horizontal or vertical reference line sits"
    )
    reference_highlight: Literal["none", "above", "below"] = Field(
        default="none",
        description=(
            "Which side of the reference line to look at: the other side is dimmed "
            "and the top-N labels rank the highlighted side only, as on the Manhattan "
            "plot. Above is y greater than a horizontal line, x greater than a "
            "vertical one, y greater than x against the diagonal."
        ),
    )

    min_size: float = Field(default=4.0, gt=0.0, description="Marker size at the smallest value")
    max_size: float = Field(default=22.0, gt=0.0, description="Marker size at the largest value")
    marker_size: float = Field(
        default=7.0, gt=0.0, description="Marker size when no size column is bound"
    )
    opacity: float = Field(default=0.8, ge=0.05, le=1.0)
    marker_outline: bool = Field(
        default=True, description="Draw a thin outline so overlapping points stay separable"
    )
    top_n_labels: int = Field(
        default=0, ge=0, description="Label this many points, the largest by size or by |y|"
    )
    color_scale: str = Field(
        default="Viridis", description="Colourscale used when the colour column is numeric"
    )
    legend_pos: Literal["right", "bottom", "none"] = Field(default="right")
    selection_enabled: bool = Field(default=False)
    selection_column: str | None = Field(default=None)

    # --- Density and quadrants ---------------------------------------------
    # Two modes the omics figures ask for and a marker cloud cannot give: a
    # binned density when the points overplot (read length vs quality, VAF vs
    # depth, GC vs coverage), and reference lines that cut the plane into the
    # four named regions a reader is looking for (MIMAG completeness vs
    # contamination). Both opt-in; defaults draw today's scatter.
    density: bool = Field(
        default=False,
        description=(
            "Draw a binned 2D histogram instead of one marker per row. Points "
            "are the default; the reader can flip the view from the tile."
        ),
    )
    density_threshold: int = Field(
        default=0,
        ge=0,
        description=(
            "Row count above which the renderer switches to the density view on "
            "its own, where a marker cloud is a solid blob. 0 (default) never "
            "switches: an author who wants the switch names the row count."
        ),
    )
    density_bins: int = Field(
        default=60, ge=5, le=400, description="Bins per axis in the density view"
    )
    quadrants: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Reference lines cutting the plane into four named regions, as "
            "``{x: number, y: number, labels: [top-left, top-right, "
            "bottom-left, bottom-right]}``. Labels are optional."
        ),
    )

    @field_validator("quadrants")
    @classmethod
    def _quadrants_are_two_numbers_and_four_labels(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Reject a quadrant block the renderer would silently half-draw."""
        if value is None:
            return value
        for axis in ("x", "y"):
            if not isinstance(value.get(axis), int | float) or isinstance(value.get(axis), bool):
                raise ValueError(f"quadrants.{axis} must be a number")
        labels = value.get("labels")
        if labels is not None:
            if not isinstance(labels, list) or len(labels) != 4:
                raise ValueError("quadrants.labels must be a list of exactly 4 strings")
            if not all(isinstance(label, str) for label in labels):
                raise ValueError("quadrants.labels must be a list of exactly 4 strings")
        unknown = sorted(set(value) - {"x", "y", "labels"})
        if unknown:
            raise ValueError(f"quadrants has unknown keys: {unknown}")
        return value


class ProfileConfig(_BaseVizConfig):
    """One curve per series over an ordered numeric axis.

    Named for the shape rather than a domain, because a TSS enrichment profile, a
    fragment-length ladder, a Hill diversity curve and a rank-abundance curve are
    the same three columns with different axis labels.
    """

    viz_kind: Literal["profile"] = "profile"

    series_col: str = Field(default="series", description="Column that splits the curves")
    x_col: str = Field(default="x", description="Ordered numeric axis")
    y_col: str = Field(default="y", description="Value at each x")
    lower_col: str | None = Field(
        default=None, description="Optional lower edge of a confidence band"
    )
    upper_col: str | None = Field(
        default=None, description="Optional upper edge of a confidence band"
    )

    reference_x: float | None = Field(
        default=None,
        description="Draw a marker at this x, e.g. 0 for a transcription start site",
    )
    reference_label: str | None = Field(default=None, description="Label for the marker")
    shaded_bands: list[tuple[float, float, str]] = Field(
        default_factory=list,
        description="x ranges to shade, as (start, end, label); e.g. nucleosome windows",
    )

    @field_validator("shaded_bands", mode="before")
    @classmethod
    def _bands_from_yaml_lists(cls, value: Any) -> Any:
        """Accept the YAML spelling ``- [start, end, label]`` for a band.

        YAML has no tuple, so a band authored in a dashboard arrives as a list.
        That matters more than it looks: a lite component is validated through
        ``LiteComponent | dict[str, Any]``, and pydantic's smart union runs a
        strict pass first, where a list is not a tuple. The component then loses
        to the ``dict`` member, which matches anything, and is stored as a raw
        dict with no ``viz_kind`` at all. Nothing raises; the tile simply renders
        as `Unknown advanced viz kind: ""`.
        """
        if isinstance(value, list):
            return [tuple(band) if isinstance(band, list) else band for band in value]
        return value

    log_x: bool = Field(default=False, description="Log-scale the x axis")
    log_y: bool = Field(default=False, description="Log-scale the y axis")
    band_opacity: float = Field(default=0.2, ge=0.0, le=1.0)
    line_width: float = Field(default=2.0, gt=0.0)
    x_title: str | None = Field(default=None)
    y_title: str | None = Field(default=None)
    legend_pos: Literal["right", "bottom", "none"] = Field(default="right")
    selection_enabled: bool = Field(default=False)
    selection_column: str | None = Field(default=None)

    # --- Derivative panel ---------------------------------------------------
    # The Hi-C contact-probability convention: P(s) on log-log axes with its
    # local slope d log y / d log x underneath, because the slope is what
    # separates a polymer regime from a loop-extrusion one and it is unreadable
    # off the curve itself. Opt-in, and useful to any log-log profile.
    derivative: bool = Field(
        default=False,
        description=(
            "Draw a second panel under the curves with the local log-log slope "
            "d log y / d log x. Forces both axes to log in the upper panel."
        ),
    )
    derivative_window: int = Field(
        default=5,
        ge=1,
        le=51,
        description=(
            "Points either side used for the slope's least-squares fit. Larger "
            "windows trade resolution for a smoother slope."
        ),
    )


class SignalMatrixConfig(_BaseVizConfig):
    """Metagene heatmap: regions down, position offsets across, ordered by signal."""

    viz_kind: Literal["signal_matrix"] = "signal_matrix"

    region_id_col: str = Field(default="region_id", description="One row per region")
    position_col: str = Field(
        default="position", description="Signed offset from the reference point"
    )
    value_col: str = Field(default="value", description="Signal at that offset")
    group_col: str | None = Field(
        default=None, description="Optional column that splits the matrix into panels"
    )

    reference_position: float = Field(
        default=0.0, description="Where the reference point sits on the position axis"
    )
    reference_label: str | None = Field(default=None)
    sort_by: Literal["signal", "none"] = Field(
        default="signal", description="Row order; positional columns are never reordered"
    )
    max_rows: int = Field(
        default=2000,
        ge=1,
        description="Rows are binned to at most this many; a real matrix runs to 10^5",
    )
    colour_scale: ColourScale = Field(default="Viridis")
    show_profile: bool = Field(
        default=True, description="Draw the mean profile curve above the matrix"
    )


class FusionStructureConfig(_BaseVizConfig):
    """A fusion drawn as its two partners with the protein domains laid along them."""

    viz_kind: Literal["fusion_structure"] = "fusion_structure"

    fusion_id_col: str = Field(default="fusion_id", description="One fusion per facet")
    partner_col: str = Field(default="partner", description="Which side of the fusion")
    feature_col: str = Field(default="feature", description="Domain or exon name")
    start_col: str = Field(default="start", description="Feature start along the partner")
    end_col: str = Field(default="end", description="Feature end along the partner")

    breakpoint_col: str | None = Field(
        default=None, description="Offset of the breakpoint along each partner"
    )
    retained_col: str | None = Field(
        default=None, description="Fraction of the domain retained after the fusion"
    )
    colour_by_col: str | None = Field(default=None, description="Column driving the feature colour")
    top_n: int = Field(default=6, ge=1, description="How many fusions to draw")
    show_breakpoint: bool = Field(default=True)


class GeneArrowTrackConfig(_BaseVizConfig):
    """A locus map: one arrow per coding sequence along a contig."""

    viz_kind: Literal["gene_arrow_track"] = "gene_arrow_track"

    contig_col: str = Field(default="contig", description="Contig or scaffold identifier")
    feature_id_col: str = Field(default="feature_id", description="Gene or CDS identifier")
    start_col: str = Field(default="start")
    end_col: str = Field(default="end")
    strand_col: str = Field(default="strand", description="'+' or '-'; sets the arrow direction")

    class_col: str | None = Field(default=None, description="Column driving the arrow colour")
    label_col: str | None = Field(default=None, description="Column drawn above each arrow")
    region_start_col: str | None = Field(
        default=None, description="Start of a highlighted region, e.g. a BGC boundary"
    )
    region_end_col: str | None = Field(default=None)
    show_labels: bool = Field(default=True)
    arrow_height: float = Field(default=0.5, gt=0.0)


class GseaRunningScoreConfig(_BaseVizConfig):
    """The GSEA running enrichment score along the ranked gene list."""

    viz_kind: Literal["gsea_running_score"] = "gsea_running_score"

    gene_set_col: str = Field(default="gene_set", description="One curve per gene set")
    rank_col: str = Field(default="rank", description="Position in the ranked list")
    running_es_col: str = Field(default="running_es", description="Running enrichment score")

    member_col: str | None = Field(
        default=None, description="Boolean column marking the ranks that are set members"
    )
    metric_col: str | None = Field(
        default=None, description="Ranking metric, drawn as a bar under the curve"
    )
    show_leading_edge: bool = Field(
        default=True, description="Shade the ranks up to the peak of the score"
    )
    top_n_sets: int = Field(default=5, ge=1)


class SashimiConfig(_BaseVizConfig):
    """Splice junctions as arcs over a genomic interval, weighted by read support."""

    viz_kind: Literal["sashimi"] = "sashimi"

    chr_col: str = Field(default="chr")
    start_col: str = Field(default="start", description="Donor coordinate")
    end_col: str = Field(default="end", description="Acceptor coordinate")
    count_col: str = Field(default="count", description="Reads supporting the junction")

    sample_col: str | None = Field(default=None, description="Optional column splitting panels")
    annotation_col: str | None = Field(
        default=None, description="Known or novel, used to style the arc"
    )
    min_count: int = Field(default=1, ge=0, description="Hide junctions under this support")
    top_n: int = Field(default=50, ge=1, description="Keep the strongest arcs")
    log_width: bool = Field(
        default=True, description="Scale arc width by log10(count) rather than count"
    )

    # The two derived tracks. Both are inferred from the junction ends in the
    # bound collection: an exon is the interval between an acceptor and the next
    # donor, and its support is the read count of the junctions touching it.
    # Neither is a coverage measurement, and no second collection is involved.
    show_support_track: bool = Field(
        default=True, description="Draw inferred exon support under the arcs of each lane"
    )
    show_gene_model: bool = Field(
        default=True, description="Draw the inferred exon model in a lane under the panel"
    )
    support_track_height: float = Field(
        default=0.3, gt=0, le=0.6, description="Share of each lane given to the support profile"
    )
    gene_model_height: float = Field(
        default=0.14, gt=0, le=0.4, description="Share of the panel given to the exon model lane"
    )
    arc_height: float = Field(
        default=1.0, gt=0, le=1.5, description="Scale factor on the arc apex height"
    )
    arc_colors: dict[str, str] | None = Field(
        default=None,
        description=(
            "Arc colour per annotation value, overriding the theme palette. "
            "Key '*' colours every arc when the binding has no annotation column."
        ),
    )

    # ------------------------------------------------------------------
    # Optional real coverage, from a SECOND data collection.
    #
    # A junction table counts spliced reads only, so the support track above
    # is an estimate and says so. Per-base or per-bin read depth is a
    # different measurement and lives in a different file (mosdepth regions,
    # a bedGraph, a BigWig export). Binding it here replaces the inferred
    # profile with the real thing, per lane, and leaves everything else alone.
    #
    # Same contract as the phylogenetic viz's `tree_dc_*`: the `_dc_tag` is
    # what a template YAML ships, and the dashboard import rewrites
    # `coverage_dc_id` / `coverage_wf_id` from it against the project it is
    # importing into. Unbound (the default) the component behaves exactly as
    # it did before this existed.
    # ------------------------------------------------------------------
    coverage_wf_id: str | None = Field(
        default=None, description="Workflow id of the coverage DC (optional)"
    )
    coverage_dc_id: str | None = Field(
        default=None, description="Data-collection id of the coverage DC (optional)"
    )
    coverage_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the coverage DC (resolved to ids at import)",
    )
    coverage_chr_col: str = Field(
        default="chromosome", description="Chromosome column in the coverage DC"
    )
    coverage_position_col: str = Field(
        default="position", description="Bin start / single-base position in the coverage DC"
    )
    coverage_end_col: str | None = Field(
        default=None,
        description="Optional bin end, so binned depth is drawn as intervals rather than points",
    )
    coverage_value_col: str = Field(
        default="value", description="Read depth / signal column in the coverage DC"
    )
    coverage_sample_col: str | None = Field(
        default=None,
        description=(
            "Sample column in the coverage DC. Its values must match the junction "
            "table's sample column so each lane gets its own depth profile."
        ),
    )
    show_coverage: bool = Field(
        default=True,
        description="Draw the bound coverage DC under the arcs (ignored when none is bound)",
    )
    coverage_height: float = Field(
        default=0.6,
        gt=0,
        le=0.8,
        description="Share of the room above the zero line given to the coverage profile",
    )
    coverage_color: str | None = Field(
        default=None,
        description="Fill colour of the coverage area; null uses the theme's grid colour",
    )
    coverage_log: bool = Field(
        default=False,
        description="Compress the depth axis with log10(1 + depth); tames one deep exon",
    )
    color_by: Literal["annotation", "sample"] = Field(
        default="annotation",
        description=(
            "What the arcs take their colour from. 'annotation' separates known "
            "from novel; 'sample' gives each lane one colour, the ggsashimi "
            "convention. The depth profile is always coloured per lane."
        ),
    )
    max_arc_width: int = Field(default=2, ge=1, le=18, description="Pixel width of an arc")
    arc_width_by_support: bool = Field(
        default=False,
        description=(
            "Scale arc width by read support. Off by default: the count is "
            "already printed at the apex, and scaling it makes a junction class "
            "that happens to be weaker look thinner as a class."
        ),
    )
    arc_split: Literal["annotation", "alternate"] = Field(
        default="annotation",
        description=(
            "Which side of the zero line an arc is drawn on. 'annotation' puts "
            "each class on its own side, so two junctions sharing a span never "
            "overlap; 'alternate' flips side along the locus instead, which is "
            "what a binding with no annotation column falls back to."
        ),
    )

    # --- Switchable views ---------------------------------------------------
    # ``plotly`` is the arc panel above; ``genomespy`` redraws the same
    # junctions and coverage as a zoomable GenomeSpy track: coverage bars per
    # lane, junctions as dome links whose width follows read support, and the
    # bundled gene lane when ``annotation`` names an assembly.
    view: Literal["plotly", "genomespy"] = Field(
        default="plotly",
        description="Which of the two sashimi views the tile opens on",
    )
    views: list[Literal["plotly", "genomespy"]] | None = Field(
        default=None,
        description="Views offered in the tile's switch; null offers both",
    )
    annotation: GeneLaneAssembly = Field(
        default="none",
        description=(
            "GenomeSpy view: bundled protein-coding gene lane drawn under the "
            "lanes, and the assembly whose contig lengths lay out the axis. "
            "none draws no gene lane and derives the axis from the rows."
        ),
    )


class ContactMapConfig(_BaseVizConfig):
    """Binned Hi-C style contact matrix: one row per (bin1, bin2) pair.

    Coordinate-bound like ``coverage_track``, and on the same side of the
    JBrowse boundary: it draws a binned matrix of counts, never per-read
    pairs. Only one triangle of the matrix needs to be present in the data;
    the renderer mirrors it across the diagonal.
    """

    viz_kind: Literal["contact_map"] = "contact_map"

    chrom1_col: str = Field(default="chrom1", description="Chromosome of the first bin")
    start1_col: str = Field(default="start1", description="Start of the first bin")
    chrom2_col: str = Field(default="chrom2", description="Chromosome of the second bin")
    start2_col: str = Field(default="start2", description="Start of the second bin")
    count_col: str = Field(default="count", description="Contact count / interaction score")
    end1_col: str | None = Field(default=None, description="Optional end of the first bin")
    end2_col: str | None = Field(default=None, description="Optional end of the second bin")
    sample_col: str | None = Field(
        default=None, description="Optional column selecting a sample when a DC holds several"
    )
    resolution_col: str | None = Field(
        default=None,
        description=(
            "Optional column naming the bin size each row was counted at. A "
            "cooler holds every resolution, so one data collection can carry "
            "them all as partitions; the renderer then re-reads the resolution "
            "matching the visible span instead of one fixed matrix. Null means "
            "the collection holds a single resolution, which is how every "
            "contact map authored so far is stored."
        ),
    )

    chrom: str | None = Field(
        default=None,
        description="Chromosome to display (intra-chromosomal view); null picks the first seen",
    )
    log_scale: bool = Field(default=True, description="Log-transform counts before colouring")
    colour_scale: ColourScale = Field(default="Viridis")
    balance: bool = Field(
        default=False,
        description="Single-pass row/column coverage normalisation before display (not iterative ICE)",
    )
    display: Literal["square", "triangle"] | None = Field(
        default=None,
        description=(
            "Square puts genomic position on both axes. Triangle rotates the "
            "matrix 45 degrees so the diagonal becomes the horizontal axis: x "
            "is then genomic position on the same scale as a genome_view track "
            "stacked above it, and y is the separation between the two bins. "
            "Unset: triangle when a region filter reaches the tile, square otherwise"
        ),
    )
    max_separation_bins: int = Field(
        default=0,
        ge=0,
        le=5000,
        description=(
            "Triangle display only: how many bins of separation to draw before "
            "the apex is cut off. Hi-C signal decays with distance, so the far "
            "corner flattens the colour scale. 0 keeps every separation"
        ),
    )
    max_bins: int = Field(
        default=500,
        ge=10,
        le=5000,
        description="Guard on the matrix side length; larger requests are rejected client-side",
    )


class KneePlotConfig(_BaseVizConfig):
    """Barcode-rank ("knee") curve: UMI count vs rank, descending, per sample."""

    viz_kind: Literal["knee_plot"] = "knee_plot"

    sample_col: str = Field(default="sample", description="Column naming each curve / library")
    rank_col: str = Field(default="rank", description="Barcode rank, ascending from 1")
    umi_count_col: str = Field(default="umi_count", description="UMI count at that rank")
    is_cell_col: str | None = Field(
        default=None,
        description="Optional boolean column marking called cells; else the cutoff is estimated",
    )

    log_x: bool = Field(default=True, description="Log-scale the rank axis")
    log_y: bool = Field(default=True, description="Log-scale the UMI-count axis")
    show_cutoff: bool = Field(
        default=True, description="Draw the cell-calling threshold as a reference line"
    )


class DamageProfileConfig(_BaseVizConfig):
    """Ancient-DNA misincorporation profile: substitution frequency by read-end position."""

    viz_kind: Literal["damage_profile"] = "damage_profile"

    sample_col: str = Field(default="sample", description="Column naming each sample / library")
    end_col: str = Field(
        default="end", description="Read end the position is measured from: 5p or 3p"
    )
    position_col: str = Field(default="position", description="Distance from the read end")
    base_change_col: str = Field(
        default="base_change", description="Substitution, e.g. C>T, G>A, other"
    )
    frequency_col: str = Field(
        default="frequency", description="Substitution frequency at that position"
    )

    ends: Literal["both", "5p", "3p"] = Field(
        default="both", description="Which read end(s) to draw a panel for"
    )
    max_position: int = Field(
        default=25, ge=1, le=200, description="Furthest distance from the read end to display"
    )
    highlight: list[str] = Field(
        default_factory=lambda: ["C>T", "G>A"],
        description="Substitutions drawn in the deamination colours; others render muted",
    )

    # --- Read-length facet --------------------------------------------------
    # Authenticity is read off the interaction, not the marginal: short reads
    # should carry more deamination than long ones, and one curve per length
    # bin is how an aDNA paper shows it. Opt-in and inert unless the bound
    # collection actually carries the column.
    facet_by: Literal["none", "length_bin"] = Field(
        default="none",
        description=(
            "``length_bin`` draws one lane per read-length bin, using the "
            "``length_bin_col`` column. ``none`` (default) keeps one panel."
        ),
    )
    length_bin_col: str = Field(
        default="length_bin",
        description="Column holding the read-length bin, used when facet_by is length_bin",
    )
    max_facets: int = Field(
        default=6, ge=1, le=20, description="How many length-bin lanes to draw before truncating"
    )


# --- Locus grammar, mirrored from locusParse.ts -----------------------------
# The address bar of a locus section accepts one grammar and the YAML that
# pre-loads that address bar must accept the same one, or a dashboard would
# validate here and resolve to nothing in the browser. Kept beside the only
# field that uses it; the React twin is ``parseLocusText`` in
# ``packages/depictio-react-core/src/components/advanced_viz/genomespy/
# locusParse.ts``.
_LOCUS_COORD_RE = re.compile(r"^\d+(?:\.\d+)?(?:kb|mb|gb|k|m|g)?$", re.IGNORECASE)
_LOCUS_CONTIG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# ``..`` is the Ensembl separator; the two dashes are the ones a copy from a
# paper carries (en dash U+2013, em dash U+2014).
_LOCUS_RANGE_SEP_RE = re.compile(r"\.\.|[-– - ]")


def _is_locus_text(text: str) -> bool:
    """True when ``text`` is a locus the browser's address bar would resolve.

    Accepts ``chr7:55,000,000-56,000,000``, ``chr7:55.0Mb-56Mb``,
    ``chr7:55000000..56000000``, ``chr7:55000000`` (a window around one
    coordinate) and a bare contig name.
    """
    trimmed = text.strip()
    if not trimmed:
        return False
    colon = trimmed.rfind(":")
    if colon < 0:
        return bool(_LOCUS_CONTIG_RE.match(trimmed))
    chrom = trimmed[:colon].strip()
    rest = trimmed[colon + 1 :].strip()
    if not chrom:
        return False
    if not rest:
        return True
    parts = [p.strip() for p in _LOCUS_RANGE_SEP_RE.split(rest) if p.strip()]
    if len(parts) not in (1, 2):
        return False
    return all(_LOCUS_COORD_RE.match(re.sub(r"[,_\s]", "", p)) for p in parts)


class GenomeViewConfig(_BaseVizConfig):
    """A genome view drawn by GenomeSpy on a chromosome-aware ``locus`` axis.

    Binds the same ``chr / pos / score`` roles as ``manhattan`` so every DC a
    Manhattan reads renders here unchanged, but the genome axis, the locus
    zoom, the mark picking and the region brush are GenomeSpy's own rather than
    rebuilt from Plotly primitives. ``end_col`` turns each row into an interval
    (``rect`` mark), which covers coverage bins and peak calls; ``bar`` draws
    the score as a bar from a baseline, which is the coverage look GenomeSpy
    has no line mark for.

    An advanced_viz tile binds exactly one data collection, so "multi-track"
    here means several ``genome_view`` tiles stacked in one dashboard section
    that share a region filter, not one tile over several collections. The
    brush emits that region as an ordinary chromosome + position filter pair
    (see ``genomeRegionFilters`` in ``packages/depictio-react-core/src/
    selection.ts``) and ``follow_region_filter`` makes a tile zoom to an
    incoming one.
    """

    viz_kind: Literal["genome_view"] = "genome_view"

    source: Literal["table", "file"] = Field(
        default="table",
        description=(
            "Where the track's rows come from. ``table`` (default) reads the "
            "bound data collection through the advanced_viz data endpoint. "
            "``file`` hands GenomeSpy an indexed file (bigWig, tabix, VCF, "
            "GFF3) it range-loads itself, for tracks too dense to materialise."
        ),
    )

    chr_col: str = Field(default="chr", description="Column with chromosome / contig name")
    pos_col: str = Field(default="pos", description="Column with the genomic start position")
    score_col: str = Field(default="score", description="Column with the y-axis value")
    feature_col: str | None = Field(
        default=None, description="Optional column naming the row (SNP, peak, gene) for hover"
    )
    end_col: str | None = Field(
        default=None,
        description=(
            "Optional column with the interval end. When set the track draws one "
            "rectangle per row from pos to end instead of a point."
        ),
    )
    sample_col: str | None = Field(
        default=None,
        description=(
            "Optional column naming the sample a row belongs to. Enables "
            "``facet_by_sample``, which stacks one lane per sample on a shared "
            "genome axis."
        ),
    )
    category_col: str | None = Field(
        default=None,
        description=(
            "Optional per-row annotation (gene region, peak caller, cluster) used "
            "as the colour channel in place of the chromosome."
        ),
    )
    mark: Literal["point", "rect", "bar"] = Field(
        default="point",
        description=(
            "Mark type. ``rect`` needs ``end_col`` and draws one rectangle per "
            "interval; ``bar`` draws the score as a bar from a baseline (GenomeSpy "
            "has no line or area mark, so this is the coverage profile look); "
            "without ``end_col`` both degrade to points."
        ),
    )
    facet_by_sample: bool = Field(
        default=False,
        description=(
            "Stack one lane per value of ``sample_col``, vertically concatenated "
            "and sharing the genome axis. Needs ``sample_col``."
        ),
    )
    max_facets: int = Field(
        default=8,
        ge=1,
        le=40,
        description=(
            "Upper bound on stacked lanes. Beyond it the lanes would be a few "
            "pixels tall each, so the renderer keeps the first ``max_facets`` "
            "samples in genome order and says how many it dropped."
        ),
    )
    annotation: GeneLaneAssembly = Field(
        default="none",
        description=(
            "Gene annotation lane drawn under the data track, from the bundled "
            "protein-coding gene table for that assembly "
            "(``assets/genomes/<assembly>.genes.json``, lazily fetched). ``none`` "
            "draws no lane."
        ),
    )
    assembly: str | None = Field(
        default=None,
        description=(
            "GenomeSpy built-in assembly (hg38, hg19, hg18, mm10, mm9, dm6). Null derives "
            "the contig list and sizes from the data itself, which is what a viral "
            "reference or a draft assembly needs."
        ),
    )
    score_title: str = Field(default="score", description="Y-axis label")
    score_threshold: float | None = Field(
        default=None, description="Horizontal reference rule; None hides it"
    )
    point_size: int = Field(default=5, ge=1, le=30, description="Point diameter in pixels")
    opacity: float = Field(default=0.85, ge=0.05, le=1.0)

    # --- Region brush as a cross-filter ------------------------------------
    region_filter_enabled: bool = Field(
        default=True,
        description=(
            "Let a brush along the genome axis emit a chromosome multi-select plus "
            "a position range on this tile's own collection, so other tiles bound "
            "to the same columns (directly, or through a project link) narrow to "
            "the brushed region."
        ),
    )
    follow_region_filter: bool = Field(
        default=False,
        description=(
            "Zoom this tile to an incoming region filter instead of showing the "
            "whole genome. Off by default so a tile keeps its overview unless the "
            "dashboard asks it to follow."
        ),
    )
    default_region: str | None = Field(
        default=None,
        description=(
            "Region the section opens on, written the way the locus field takes "
            "it: ``chr1:10,000,000-12,000,000``. On its first render the tile "
            "emits the same chromosome and position filters the locus field "
            "emits, so every tile of the section starts on that region instead "
            "of on the whole genome or on nothing at all. Emitted once per "
            "session and only when no region is already in force, so a reader "
            "who moves or clears the region keeps their own choice. Needs "
            "``region_filter_enabled``. Coordinates may carry thousands "
            "separators and a kb / Mb / Gb suffix, ``..`` works as the "
            "separator, one coordinate opens a 10 kb window around it, and a "
            "bare contig name opens the whole contig."
        ),
    )

    @field_validator("default_region")
    @classmethod
    def _check_default_region(cls, value: str | None) -> str | None:
        """Refuse a region the browser's address bar could not resolve.

        The contig name is not checked against the data: which contigs exist is
        known only once the collection is read, and the renderer matches the
        name against them (with or without the ``chr`` prefix) at that point.
        """
        if value is None:
            return None
        if not _is_locus_text(value):
            raise ValueError(
                f"default_region {value!r} is not a locus. Write it as "
                "chr:start-end, for example chr1:10,000,000-12,000,000."
            )
        return value.strip()

    # --- Selection as a cross-filter (same contract as ManhattanConfig) -----
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a click on a mark emit a dashboard filter the Analysis panel can "
            "turn into a group. Requires ``selection_column``."
        ),
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column the emitted selection values belong to. No default, for the "
            "same reason as the Manhattan plot: a row here is one feature at one "
            "locus and the dashboard has to say what a pick means."
        ),
    )

    # --- source: file ------------------------------------------------------
    # Only read when ``source`` is ``file``. The bound DC is then an
    # ``indexed_file`` collection and the browser range-loads its objects
    # itself; nothing below applies to a table-backed tile.
    file_info_fields: list[str] | None = Field(
        default=None,
        description=(
            "VCF only. INFO keys promoted to columns before encoding, so a "
            "classification or an allele frequency can drive the y axis and the "
            "colour. Null promotes none."
        ),
    )
    file_category_field: str | None = Field(
        default=None,
        description=(
            "VCF only. Which promoted INFO field ranks the variants on the y "
            "axis and colours them. Null draws one row of marks instead."
        ),
    )
    file_categories: list[str] | None = Field(
        default=None,
        description=(
            "Ordered values of ``file_category_field``, bottom to top. Null "
            "lets the values order themselves as they arrive."
        ),
    )
    file_add_chr_prefix: bool = Field(
        default=False,
        description=(
            "Prepend 'chr' to the contig names read from the file, for a file "
            "called on an Ensembl-style reference shown on a UCSC assembly."
        ),
    )
    file_window_size: int | None = Field(
        default=None,
        ge=1000,
        description=(
            "Visible span, in bases, below which the browser starts fetching. "
            "Null uses the per-format default (1 Mb for VCF, 2 Mb for GFF3). "
            "Raising it fetches sooner and costs more bandwidth."
        ),
    )
    file_max_lanes: int = Field(
        default=8,
        ge=1,
        le=40,
        description="Upper bound on per-sample lanes drawn from the collection's files.",
    )
    file_tabix_columns: list[str] | None = Field(
        default=None,
        description=(
            "Field names of a bgzip and tabix indexed interval file, in column "
            "order. Null assumes BED order: chrom, chromStart, chromEnd, name, "
            "score, strand."
        ),
    )
    file_bam_view: Literal["coverage", "pileup"] = Field(
        default="coverage",
        description=(
            "BAM only. 'coverage' draws a depth profile; 'pileup' stacks the "
            "reads themselves, which is only legible over a few kilobases."
        ),
    )


class GroupCompareConfig(_BaseVizConfig):
    """Two saved selection groups compared feature by feature, on demand.

    The observations are the rows (``index_col`` names them) and the features
    are every other numeric column, as in ``complex_heatmap``. The two groups
    are not bound columns: they are the dashboard's saved selection groups
    (lasso on an embedding, ticked table rows), resolved to row ids when the
    ``compute_group_compare`` endpoint runs the test as a background job and
    caches the result, the same contract as ``compute_embedding``.
    """

    viz_kind: Literal["group_compare"] = "group_compare"

    index_col: str = Field(
        default="index", description="Column naming each observation (cell, sample)"
    )
    group_col: str | None = Field(
        default=None,
        description="Optional column with a precomputed group label, used when no saved groups are picked",
    )
    test: Literal["wilcoxon", "t_test"] = Field(
        default="wilcoxon", description="Per-feature test between the two groups"
    )
    log_transform: bool = Field(
        default=True, description="log1p the feature values before testing (raw counts / UMIs)"
    )
    max_features: int = Field(
        default=2000, ge=10, le=20000, description="Guard on the number of feature columns tested"
    )
    min_observations: int = Field(
        default=3, ge=2, description="Smallest group size the test accepts"
    )
    fdr_threshold: float = Field(
        default=0.05, gt=0, lt=1, description="Significance line on the volcano"
    )
    log2fc_threshold: float = Field(
        default=1.0, ge=0, description="Effect-size lines on the volcano"
    )
    top_n_labels: int = Field(
        default=20, ge=0, le=200, description="Features labelled on the volcano"
    )
    default_group_a: str | None = Field(
        default=None,
        description=(
            "Group A picked on open: a saved selection group name, or a value of group_col. "
            "Unknown names fall back to the first two groups offered"
        ),
    )
    default_group_b: str | None = Field(
        default=None,
        description="Group B picked on open, resolved like default_group_a",
    )
    auto_run: bool = Field(
        default=False,
        description=(
            "Run the comparison as soon as two groups are picked, once per distinct request; "
            "the server caches the result so reopening the tab reuses it"
        ),
    )

    @model_validator(mode="after")
    def _distinct_default_groups(self) -> "GroupCompareConfig":
        if self.default_group_a is not None and self.default_group_a == self.default_group_b:
            raise ValueError("default_group_a and default_group_b must name two different groups")
        return self


class TranscriptStructureConfig(_BaseVizConfig):
    """Isoforms of one gene on a base-pair axis, one lane per transcript."""

    viz_kind: Literal["transcript_structure"] = "transcript_structure"

    transcript_id_col: str = Field(
        default="transcript_id", description="Column naming each isoform"
    )
    gene_id_col: str = Field(
        default="gene_id", description="Column naming the gene an isoform belongs to"
    )
    chrom_col: str = Field(default="chrom", description="Chromosome / contig of the block")
    start_col: str = Field(default="start", description="Block start (bp)")
    end_col: str = Field(default="end", description="Block end (bp)")
    feature_col: str = Field(default="feature", description="Block type: exon, CDS, UTR")
    strand_col: str = Field(default="strand", description="Transcript strand: + or -")
    sample_col: str | None = Field(default=None, description="Optional column selecting a sample")
    gene_name_col: str | None = Field(default=None, description="Optional readable gene symbol")
    transcript_class_col: str | None = Field(
        default=None, description="Optional novelty / class label (known, novel, NIC, NNC)"
    )
    expression_col: str | None = Field(
        default=None, description="Optional per-transcript expression used for lane order or colour"
    )

    gene: str | None = Field(
        default=None, description="Gene to draw; null picks the gene with the most transcripts"
    )
    max_transcripts: int = Field(default=30, ge=1, le=200, description="Lanes drawn per gene")
    exon_feature: str = Field(default="exon", description="Feature value drawn as a block")
    cds_feature: str = Field(default="CDS", description="Feature value drawn as a taller block")
    colour_by: Literal["transcript_class", "expression", "none"] = Field(
        default="transcript_class", description="What the lane colour encodes"
    )
    colour_scale: ColourScale = Field(default="Viridis")


class CnvProfileConfig(_BaseVizConfig):
    """Copy-number profile: log2 ratio per bin, called segments over it, BAF below."""

    viz_kind: Literal["cnv_profile"] = "cnv_profile"

    sample_col: str = Field(default="sample", description="Column naming each sample")
    chrom_col: str = Field(default="chrom", description="Chromosome of the bin / segment")
    start_col: str = Field(default="start", description="Start of the bin / segment (bp)")
    end_col: str = Field(default="end", description="End of the bin / segment (bp)")
    log2_col: str = Field(default="log2", description="Log2 copy ratio")
    baf_col: str | None = Field(
        default=None, description="Optional B-allele frequency, drawn underneath"
    )
    copy_number_col: str | None = Field(
        default=None, description="Optional integer copy number, colours the segments"
    )
    segment_col: str | None = Field(
        default=None,
        description="Optional row-type column: rows whose value is ``segment`` draw as segments, the rest as bins",
    )
    label_col: str | None = Field(default=None, description="Optional hover label (gene, cytoband)")

    sample: str | None = Field(
        default=None, description="Sample to draw; null picks the first seen"
    )
    chrom: str | None = Field(
        default=None, description="Chromosome to zoom on; null draws the whole genome"
    )
    y_range: float = Field(default=3.0, gt=0, le=10, description="Symmetric log2 axis limit")
    show_baf: bool = Field(default=True, description="Draw the BAF panel when ``baf_col`` is bound")
    point_size: int = Field(default=3, ge=1, le=12, description="Bin marker size in pixels")
    gain_threshold: float = Field(
        default=0.3, description="Log2 above which a segment reads as a gain"
    )
    loss_threshold: float = Field(
        default=-0.3, description="Log2 below which a segment reads as a loss"
    )
    max_bins: int = Field(
        default=50000, ge=100, le=500000, description="Guard on the number of bin rows requested"
    )

    # --- Locus view (GenomeSpy, the ASCAT layout) ---------------------------
    view: Literal["plotly", "locus"] = Field(
        default="plotly",
        description=(
            "``plotly`` draws the genome-wide Plotly profile; ``locus`` draws the zoomable "
            "GenomeSpy tracks: allele-specific copy number, log2 ratio and mirrored BAF"
        ),
    )
    views: list[Literal["plotly", "locus"]] | None = Field(
        default=None,
        description="Views offered in the tile's switch; null offers every view",
    )
    minor_copy_number_col: str | None = Field(
        default=None,
        description=(
            "Optional minor-allele copy number (ASCAT nMinor). With ``copy_number_col`` bound, "
            "the locus view draws nMajor and nMinor as two rules per segment"
        ),
    )
    annotation: GeneLaneAssembly = Field(
        default="none",
        description="Locus view: bundled gene lane drawn under the tracks; labels appear on zoom",
    )
    facet_by_sample: bool = Field(
        default=False,
        description="Locus view: one set of tracks per sample instead of the selected sample only",
    )


class GenomeChordConfig(_BaseVizConfig):
    """Chromosomes on a ring, one chord per link between two loci."""

    viz_kind: Literal["genome_chord"] = "genome_chord"

    chrom_a_col: str = Field(default="chrom_a", description="Chromosome of the first locus")
    pos_a_col: str = Field(default="pos_a", description="Position of the first locus (bp)")
    chrom_b_col: str = Field(default="chrom_b", description="Chromosome of the second locus")
    pos_b_col: str = Field(default="pos_b", description="Position of the second locus (bp)")
    label_col: str | None = Field(
        default=None, description="Optional link label (fusion name, SV id)"
    )
    weight_col: str | None = Field(
        default=None, description="Optional link weight (supporting reads), drives chord width"
    )
    category_col: str | None = Field(
        default=None, description="Optional link class (fusion type, SV type), drives chord colour"
    )
    sample_col: str | None = Field(default=None, description="Optional column selecting a sample")

    assembly: str | None = Field(
        default=None,
        description="Chromosome sizes to lay the ring out on (hg38, hg19, mm10); null derives them from the data",
    )
    max_links: int = Field(
        default=500, ge=1, le=5000, description="Guard on the number of chords drawn"
    )
    min_weight: float | None = Field(default=None, description="Drop links lighter than this")
    colour_by: Literal["category", "chrom_a", "none"] = Field(
        default="category", description="What the chord colour encodes"
    )
    show_labels: bool = Field(default=True, description="Label the chromosome arcs")
    intra_chromosomal: bool = Field(
        default=True, description="Draw links whose two loci share a chromosome"
    )

    # --- Selection as a cross-filter ---------------------------------------
    # Off by default, same reasoning as EmbeddingConfig above.
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a click on a chord emit a dashboard filter the Analysis panel "
            "can turn into a group. Falls back to ``label_col`` when "
            "``selection_column`` is unset; with neither bound the renderer "
            "stays inert."
        ),
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column the emitted selection values belong to. Null uses "
            "``label_col``, because a chord is one named link (a fusion, a pair "
            "of breakends) and its label is what the other tiles join on. Name "
            "the sample column instead to select every link of the samples the "
            "picked chords belong to."
        ),
    )


class RecordCardConfig(_BaseVizConfig):
    """One row of a collection, read as labelled fields rather than as a mark.

    The detail half of a master/detail dashboard: a scatter, a table or a
    genome view emits a selection, and this tile shows the record behind the
    picked point. It draws no marks at all, which is the whole point: the
    columns a reader wants once they have chosen a sample (run identifiers,
    QC verdicts, links out to a report) are text, and a chart of one row is a
    worse way to read them.

    With no selection reaching it the tile shows its empty state naming the
    source it is waiting on, never the first row of the collection: a card
    that silently shows row 0 reads as the record the reader picked. The one
    exception is an explicit `default_record`, which the echo line labels as
    the default so it never passes for a pick.
    """

    viz_kind: Literal["record_card"] = "record_card"

    id_col: str = Field(
        default="id",
        description="Column whose value identifies the record, matched against the incoming selection",
    )
    title_col: str | None = Field(
        default=None,
        description="Column shown as the card's heading; null uses the id column's value",
    )
    sections: dict[str, list[str]] | None = Field(
        default=None,
        description=(
            "Section title to the columns it holds, in order. Null groups the "
            "columns by the data collection's own `columns_description` groups, "
            "so a well-described collection needs no layout here."
        ),
    )
    labels: dict[str, str] | None = Field(
        default=None,
        description="Display label per column; unlisted columns fall back to a short column description, then the column name",
    )
    link_templates: dict[str, str] | None = Field(
        default=None,
        description=(
            "Column to a URL template containing `{value}`. A column listed "
            "here renders as a link instead of as text."
        ),
    )
    selection_source: Literal["scatter_selection", "table_selection", "any"] = Field(
        default="any",
        description=(
            "Which selection the card follows. `any` takes whichever arrives, "
            "which is what a dashboard with one selecting tile wants; name a "
            "source when several tiles select at once and only one of them "
            "should drive the card."
        ),
    )
    linked_component: str | None = Field(
        default=None,
        description=(
            "Tag of the component whose selection drives this card. When set, the "
            "card follows only that component's selection, and a card placed on "
            "the same row and section directly beside it is laid out as its "
            "collapsible side panel. The dashboard import resolves the tag to "
            "the component's index."
        ),
    )
    max_fields: int = Field(
        default=40,
        ge=1,
        description="How many columns to render before the card truncates and says so",
    )
    default_record: str | None = Field(
        default=None,
        description=(
            "Value of the id column shown when no selection reaches the tile, "
            "so the card opens filled. A real selection always wins, and "
            "clearing it brings this record back."
        ),
    )


class ParallelCoordinatesConfig(_BaseVizConfig):
    """One polyline per sample across N metric axes.

    The many-metric view a scatter cannot give: a QC table with a dozen
    columns is read as a whole here, where a scatter matrix would need
    N*(N-1)/2 panels. Plotly's `parcoords` also brushes each axis, so the
    reader narrows the cohort on the picture rather than in the filter panel.

    Axes are normalised by default because raw units put a read count and a
    duplication rate on the same axis range and flatten one of them.
    """

    viz_kind: Literal["parallel_coordinates"] = "parallel_coordinates"

    sample_col: str = Field(
        default="sample", description="Column naming each polyline (sample, library, run)"
    )
    metric_cols: list[str] | None = Field(
        default=None,
        description=(
            "Columns to draw as axes, in order. Null takes every numeric column "
            "of the bound collection, capped at `max_axes`, which is what a QC "
            "table wants and needs no per-pipeline list."
        ),
    )
    group_col: str | None = Field(
        default=None,
        description="Optional categorical column driving the line colour",
    )
    scale: Literal["raw", "zscore", "minmax"] = Field(
        default="minmax",
        description=(
            "How each axis is scaled. `minmax` (default) and `zscore` make "
            "axes in different units comparable; `raw` keeps the published "
            "values, which only reads well when every metric shares a unit."
        ),
    )
    max_rows: int = Field(
        default=2000,
        ge=1,
        description=(
            "How many rows the tile draws. Above a few thousand polylines the "
            "picture is a solid band, so the server hands over the first "
            "`max_rows` rather than a sample of them."
        ),
    )
    max_axes: int = Field(
        default=12,
        ge=2,
        le=30,
        description="Cap on the inferred axis count when `metric_cols` is null",
    )
    colour_scale: ColourScale = Field(
        default="Viridis", description="Continuous colour scale when the colour column is numeric"
    )
    line_opacity: float = Field(default=0.6, ge=0.05, le=1.0)


# ---------------------------------------------------------------------------
# Retired kinds, kept alive as views of the kind that survived
# ---------------------------------------------------------------------------

#: ``old kind -> (surviving kind, config overrides)``.
#:
#: Four kinds were the same marks on the same table as a neighbour, told apart
#: only by which column went on which axis: ``ma`` and ``qq`` are a volcano's
#: table read two other ways, ``enrichment`` is a dot plot of terms, and
#: ``roc_pr_curve`` is the threshold sweep the ``pr_benchmark`` point sits on.
#: Each survivor gained a ``view`` field and the retired kind's bindings, so
#: the merge costs a stored dashboard nothing: it is rewritten at READ time,
#: here, and only written back if the user saves.
#:
#: The old literals stay in ``AdvancedVizKind`` (and in ``KIND_METADATA``, with
#: ``legacy: True``) so every snapshot that enumerates kinds keeps validating.
_KIND_ALIASES: dict[str, tuple[str, dict[str, Any]]] = {
    "ma": ("volcano", {"view": "ma"}),
    "qq": ("volcano", {"view": "qq"}),
    "enrichment": ("dot_plot", {"view": "enrichment"}),
    "roc_pr_curve": ("pr_benchmark", {"view": "roc"}),
}

#: ``old kind -> {old field: surviving field}``, applied before the overrides.
#:
#: Empty for every alias, and that is the point rather than an oversight: each
#: survivor took the retired config's field NAMES verbatim when it gained the
#: view (``VolcanoConfig.avg_log_intensity_col`` is ``MAConfig``'s field,
#: ``DotPlotConfig.term_col`` is ``EnrichmentConfig``'s, ``PrBenchmarkConfig``
#: .``fpr_col`` is ``RocPrCurveConfig``'s), so the translation is the identity
#: and a stored config carries over key for key. A future merge whose names
#: collide puts its renames here instead of rewriting this function.
_ALIAS_FIELD_RENAMES: dict[str, dict[str, str]] = {
    "ma": {},
    "qq": {},
    "enrichment": {},
    "roc_pr_curve": {},
}

#: Bindings the survivor needs that the retired kind spelled under another
#: role. ``old kind -> {surviving field: the old field to copy it from}``,
#: applied only when the surviving field is absent, so an explicit binding
#: always wins. An MA plot's M axis IS a volcano's effect size and a QQ plot's
#: p-value IS a volcano's significance, so both views of a migrated tile draw
#: something rather than falling back to a column name that is not there.
_ALIAS_FIELD_SEEDS: dict[str, dict[str, str]] = {
    "ma": {"effect_size_col": "log2_fold_change_col"},
    "qq": {"significance_col": "p_value_col"},
    "enrichment": {},
    "roc_pr_curve": {},
}

#: Extra overrides applied only when the key is absent from the stored config.
#: A migrated ``enrichment`` tile offers the enrichment view alone: the marker
#: dot plot needs a cluster column the enrichment table never had, so offering
#: it would put an empty panel behind the switch.
_ALIAS_SOFT_OVERRIDES: dict[str, dict[str, Any]] = {
    "enrichment": {"views": ["enrichment"]},
}


def _accepts_none(model: type[BaseModel], field: str) -> bool:
    """Whether ``field`` on ``model`` is declared optional."""
    info = model.model_fields.get(field)
    if info is None:
        return True
    annotation = info.annotation
    return annotation is None or type(None) in get_args(annotation)


def apply_kind_aliases(data: Any) -> Any:
    """Rewrite a retired kind's config into the surviving kind's, in place of it.

    Runs as a ``BeforeValidator`` on the ``VizConfig`` union, i.e. everywhere a
    config is validated: a dashboard read out of Mongo, a shipped YAML, a
    ``use:`` expansion, the CLI validator and the API's save route. A config
    that is not a dict or does not name a retired kind is returned untouched,
    so the common path costs one dict lookup.

    Every other field is carried over unchanged. The one thing dropped is a
    null the survivor does not accept: ``MAConfig.significance_col`` was
    optional and ``VolcanoConfig``'s is not, so a stored null becomes "use the
    default" rather than a validation error on a dashboard that used to load.
    """
    if not isinstance(data, dict):
        return data
    alias = _KIND_ALIASES.get(data.get("viz_kind"))
    if alias is None:
        return data
    old_kind = data["viz_kind"]
    survivor, overrides = alias

    renames = _ALIAS_FIELD_RENAMES.get(old_kind, {})
    cfg: dict[str, Any] = {}
    for key, value in data.items():
        if key == "viz_kind":
            continue
        cfg[renames.get(key, key)] = value

    for target, source in _ALIAS_FIELD_SEEDS.get(old_kind, {}).items():
        if cfg.get(target) is None and cfg.get(source) is not None:
            cfg[target] = cfg[source]
    for key, value in _ALIAS_SOFT_OVERRIDES.get(old_kind, {}).items():
        cfg.setdefault(key, value)

    cfg["viz_kind"] = survivor
    cfg.update(overrides)

    model = _SURVIVOR_MODELS[survivor]
    return {k: v for k, v in cfg.items() if v is not None or _accepts_none(model, k)}


def resolve_viz_kind(viz_kind: str | None) -> str | None:
    """The kind a stored ``viz_kind`` string resolves to today.

    The top-level ``viz_kind`` on an advanced_viz component mirrors
    ``config.viz_kind``; this is what keeps the two agreeing once the config
    has been rewritten under it.
    """
    if viz_kind is None:
        return None
    alias = _KIND_ALIASES.get(viz_kind)
    return alias[0] if alias else viz_kind


_VizConfigUnion = Annotated[
    ScatterXyConfig
    | VolcanoConfig
    | EmbeddingConfig
    | ManhattanConfig
    | StackedTaxonomyConfig
    | PhylogeneticConfig
    | RarefactionConfig
    | DaBarplotConfig
    | ComplexHeatmapConfig
    | UpsetPlotConfig
    | DotPlotConfig
    | LollipopConfig
    | SunburstConfig
    | OncoplotConfig
    | CoverageTrackConfig
    | SankeyConfig
    | PrBenchmarkConfig
    | ConfusionMatrixConfig
    | MetricCiBarsConfig
    | ProfileConfig
    | SignalMatrixConfig
    | FusionStructureConfig
    | GeneArrowTrackConfig
    | GseaRunningScoreConfig
    | SashimiConfig
    | ContactMapConfig
    | KneePlotConfig
    | DamageProfileConfig
    | GenomeViewConfig
    | GroupCompareConfig
    | TranscriptStructureConfig
    | CnvProfileConfig
    | GenomeChordConfig
    | RecordCardConfig
    | ParallelCoordinatesConfig,
    Field(discriminator="viz_kind"),
]

#: The models a retired kind can be rewritten into, for the null-dropping above.
_SURVIVOR_MODELS: dict[str, type[BaseModel]] = {
    "volcano": VolcanoConfig,
    "dot_plot": DotPlotConfig,
    "pr_benchmark": PrBenchmarkConfig,
}

# The union as everything outside this module validates it: the alias rewrite
# first, discrimination second. Kept as a separate name above so the rewrite can
# be read (and tested) on its own.
VizConfig = Annotated[_VizConfigUnion, BeforeValidator(apply_kind_aliases)]
