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
    effect_label: str | None = Field(
        default=None,
        max_length=40,
        description="Volcano x-axis title, e.g. 'Log fold change'. Null shows effect_size_col",
    )
    significance_label: str | None = Field(
        default=None,
        max_length=40,
        description=(
            "Volcano y-axis title, e.g. '-log10 q-value'. Null shows -log10(<significance_col>)"
        ),
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
    # An MA view from a table of its own, in the MA plot's canonical columns
    # (feature_id, avg_log_intensity, log2_fold_change, significance, label),
    # for a test whose table has no mean abundance.
    ma_wf_id: str | None = Field(default=None, description="Workflow id of the MA table DC")
    ma_dc_id: str | None = Field(default=None, description="Data-collection id of the MA table DC")
    ma_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the MA table DC (resolved to ids at import)",
    )
    # The name ``view`` had on this branch before the views were merged with
    # main's: still accepted, and read as ``view`` when that is not given.
    default_view: Literal["volcano", "ma", "qq"] = Field(
        default="volcano",
        description="The view drawn first: volcano, MA or QQ (an older name for `view`)",
    )

    @model_validator(mode="before")
    @classmethod
    def _default_view_is_view(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("default_view") and "view" not in data:
            data = {**data, "view": data["default_view"]}
        return data

    @model_validator(mode="after")
    def _views_are_bound(self) -> VolcanoConfig:
        if self.default_view == "qq" and not self.p_value_col:
            raise ValueError("default_view: qq reads the raw p-values: bind p_value_col")
        if self.default_view == "ma" and not (
            self.avg_log_intensity_col or self.ma_dc_id or self.ma_dc_tag
        ):
            raise ValueError(
                "default_view: ma needs the mean abundance: bind avg_log_intensity_col, "
                "or an MA table with ma_dc_tag (or ma_dc_id)"
            )
        return self


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

    axis_prefix: str | None = Field(
        default=None,
        max_length=12,
        description=(
            "Names the dimensions on the axes and in the hover: 'PCo' gives "
            "PCo1 / PCo2. Null takes the live method's (PC, PCo, UMAP, t-SNE), "
            "or keeps the column names in precomputed mode."
        ),
    )
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
    """Stacked composition bar: one bar per sample, one segment per category.

    Built for taxa, but stacks any per-sample composition (CCS outcomes per
    library, BUSCO classes per assembly, score parts per section). Categories
    stack largest-overall at the bottom, which is what lets ``y_zoom`` crop a
    near-identical base away.
    """

    viz_kind: Literal["stacked_taxonomy"] = "stacked_taxonomy"

    sample_id_col: str = Field(default="sample_id", description="Column with the sample identifier")
    taxon_col: str = Field(default="taxon", description="Column with taxon name")
    rank_col: str | None = Field(
        default="rank",
        description=(
            "Column with the taxonomic rank (or any level) label. Null, or a column "
            "the table does not carry, draws a single-level composition with no "
            "rank picker."
        ),
    )
    abundance_col: str = Field(
        default="abundance", description="Column with relative or absolute abundance"
    )

    # Wide tables: one row per sample, one numeric column per category
    # (orthofinder species stats, FCS-GX actions, AGAT feature counts). The
    # renderer melts them into the long form, so every option below applies.
    value_cols: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "Wide form: the numeric columns to stack, one category each (the "
            "column is the category, its value the abundance). When set, "
            "taxon_col, abundance_col and rank_col are not read; only "
            "sample_id_col and these columns are fetched. Null (default) reads "
            "the long form."
        ),
    )
    value_labels: dict[str, str] | None = Field(
        default=None,
        description=(
            "Wide form: column -> display name of its category, e.g. "
            "{unassigned_genes: Unassigned}. Unlisted columns show their name. "
            "Colours (`taxon_palette`, `sort_category`) are keyed by the "
            "display name."
        ),
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
    taxon_palette: dict[str, str] | None = Field(
        default=None,
        description=(
            "Taxon -> hex colour overrides for the bars. Unlisted taxa keep the "
            "default cycle, which repeats past twelve taxa."
        ),
    )
    sample_sort: Literal["input", "name", "total_abundance", "first_taxon", "category"] = Field(
        default="input",
        description=(
            "Order of the bars. ``input``: as the table lists them. ``name``: "
            "natural alphabetical order (S2 before S10). ``total_abundance``: "
            "largest raw total first. ``first_taxon``: largest raw value of the "
            "overall most abundant category first. ``category``: largest plotted "
            "value (the share, when normalised) of ``sort_category`` first."
        ),
    )
    sort_category: str | None = Field(
        default=None,
        description=(
            "Category whose value orders the bars under ``sample_sort: category``. "
            "Null, or a category not shown, uses the most abundant one."
        ),
    )
    group_col: str | None = Field(
        default=None,
        description=(
            "Per-sample column that groups the bars (multi-level sort): bars are "
            "grouped by its value, each group labelled and set apart by a gap, "
            "and ``sample_sort`` orders the bars within each group. Groups follow "
            "their first appearance in the table, or natural name order under "
            "``sample_sort: name``. The viewer can also group by any "
            "``annotation_strips`` column."
        ),
    )
    y_zoom: Literal["off", "auto"] = Field(
        default="off",
        description=(
            "``auto`` crops the value axis to start just below the smallest "
            "bottom segment, so a composition that is near-identical across "
            "bars (every bar 95 % one class) shows the part that varies. The "
            "cropped axis carries a // break marker and says where it starts. "
            "No effect when the crop would gain little, or on a log axis."
        ),
    )
    orientation: Literal["v", "h"] = Field(
        default="v",
        description=(
            "``v`` (default): vertical bars, samples along x. ``h``: horizontal "
            "bars, one row per sample, which reads better for a few samples "
            "with long names."
        ),
    )
    value_title: str | None = Field(
        default=None,
        description=(
            "Value axis title. Unset shows 'Relative abundance' when normalised, "
            "else the abundance column; an empty string shows none."
        ),
    )
    show_legend: bool = Field(default=True, description="Show the taxon colour legend")
    log_y: bool = Field(default=False, description="Log-scale the abundance axis")

    # The kind stacks any per-sample composition, not only taxa: CCS outcomes
    # per library, structural categories per sample. The fields below let such
    # a tile drop the taxonomy wording and the controls that mean nothing for
    # it. All optional, so every taxonomy tile keeps its look. Colours stay with
    # `category_colors` (keyed by `taxon_col`, or by the rank shown), then
    # `taxon_palette`.
    hidden_controls: (
        list[Literal["rank", "sample_sort", "top_n", "normalise", "group", "zoom"]] | None
    ) = Field(
        default=None,
        description=(
            "Controls the tile does not offer. The config value still applies: "
            "hide `rank` when rank_col is constant, `top_n` when the categories "
            "are few and fixed, `sample_sort` when the input order is the point, "
            "`group` when the grouping is fixed, `zoom` when the full axis is the "
            "point. The rank picker also hides itself when there is one rank."
        ),
    )
    rank_label: str | None = Field(
        default=None,
        description="Label of the rank picker (default 'Rank'), e.g. 'Level' for a non-taxonomy split",
    )
    x_title: str | None = Field(
        default=None,
        description="Sample axis title. Unset shows 'Sample'; an empty string shows none.",
    )
    legend_pos: Literal["right", "bottom"] = Field(
        default="right",
        description=(
            "Legend in a column right of the bars (default), or in rows under the "
            "figure. Past 40 bars the sample labels are hidden (hover names each "
            "bar) and a bottom legend moves above the bars."
        ),
    )


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
    set_category_column: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The categorical column the sets are values of: the column the matrix "
            "was pivoted on (``locality``, ``habitat``). The set-size bars, the "
            "matrix dots and, with ``color_intersections_by='set'``, the bar of "
            "each single-set intersection take that column's dashboard "
            "``category_colors``, so a set is the same colour here as on every "
            "other tile. Null finds the column by value: the one "
            "``category_colors`` column that pins every set drawn. A set with no "
            "colour there keeps the plain look, and ``set_colors`` wins per set."
        ),
    )

    # --- Selection as a cross-filter ---------------------------------------
    # Off by default, same reasoning as EmbeddingConfig.
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a click on an intersection (its bar or its matrix column) emit "
            "a dashboard filter on the rows it counts, as a lasso does on a "
            "scatter. Clicking it again, or the tile's Reset selection, clears "
            "it. Requires ``selection_column``."
        ),
    )
    selection_column: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Column of the matrix whose values the selection emits: the values "
            "the intersection's rows hold there. The filter narrows every tile "
            "whose data has a column of that name (and those linked to it), so "
            "pick the identifier the other tiles share: a taxon's ``Phylum`` "
            "rather than a lineage string only the matrix carries."
        ),
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

    @model_validator(mode="after")
    def _selection_names_its_column(self) -> UpsetPlotConfig:
        # Nothing else in the config names the matrix's element column, so an
        # opt-in without one would validate, persist, and do nothing.
        if self.selection_enabled and not self.selection_column:
            raise ValueError(
                "selection_enabled needs selection_column: the column whose values "
                "a clicked intersection emits as the filter"
            )
        if self.selection_column and self.set_columns and self.selection_column in self.set_columns:
            raise ValueError(
                f"selection_column {self.selection_column!r} is one of the set columns; "
                "it must name the elements (a 0/1 membership column selects nothing)"
            )
        return self


class PhylogeneticConfig(_BaseVizConfig):
    """Phylogenetic tree (Microreact-style) — Newick tree + tip metadata.

    The tree itself comes from a *separate* DC with `type: "phylogeny"` (see
    DCPhylogenyConfig). Tip annotations (group / habitat / clade label /
    clinical metadata) live in a regular Table DC and are joined to tip
    labels at render time via the `taxon_col` column.

    `collapse_rank` draws the same component as a summary instead: one tip per
    value of that tip-metadata column, the top `top_n` by share, optionally
    sized by reads from an abundance table that has a column named like the
    rank. The component builder writes the same keys (its "Tree and tip
    metadata" and "Read shares" sections, and the preview's View switch), so
    a summary built there and this one are the same config. Example YAML::

        - component_type: advanced_viz
          workflow_tag: ampliseq
          data_collection_tag: phylogenetic_tree_canonical
          viz_kind: phylogenetic
          config:
            viz_kind: phylogenetic
            tree_wf_id: 646b0f3c1e4a2d7f8e5b8ca3  # placeholders, rewritten from
            tree_dc_id: 646b0f3c1e4a2d7f8e5b8cdb  # tree_dc_tag at import
            tree_dc_tag: phylogenetic_tree_canonical
            metadata_dc_tag: phylogenetic_tree_metadata_canonical
            color_col: Kingdom
            extra_color_cols: [Phylum, Class, Order]  # what Collapse to offers
            collapse_rank: Phylum                     # unset: the full tree
            top_n: 10
            size_by: abundance                        # default: tips
            abundance_dc_tag: taxonomy_rel_abundance  # has a Phylum column
            abundance_split_col: locality             # one column of dots per site
            split_scale: shared                       # or row: each lineage's own spread

    The `*_dc_tag` keys name DCs of the component's own workflow and are
    resolved to the `*_wf_id` / `*_dc_id` pair at import, overwriting whatever
    ids the YAML carries; a DC of another workflow is bound by its ids alone.
    `tree_wf_id` / `tree_dc_id` are required even beside `tree_dc_tag`, which
    is why a template ships placeholder ids for the import to replace.
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

    # Summary mode: the tree collapsed to one tip per value of a rank, for a
    # landing tile. Unset, the component draws the full tree as before.
    collapse_rank: str | None = Field(
        default=None,
        description=(
            "Tip-metadata column to collapse the tree to (e.g. 'Phylum'): one tip per "
            "value, placed at the largest clade whose classified tips all carry it, "
            "drawn as a cladogram. Unset draws the full tree."
        ),
    )
    top_n: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Summary mode: how many values of collapse_rank to draw, by share",
    )
    size_by: Literal["tips", "abundance"] = Field(
        default="tips",
        description=(
            "Summary mode: what a tip's dot measures — its share of the tree's tips "
            "(ASVs), or its mean share of a sample's reads from the abundance table"
        ),
    )
    show_shares: bool | None = Field(
        default=None,
        description=(
            "Summary mode: print each lineage's share (%) beside it. Unset, shown "
            "only when sized by reads"
        ),
    )
    # Abundance source for size_by="abundance": a long table with one row per
    # (sample, taxon) carrying the collapse_rank column and a relative abundance.
    abundance_wf_id: str | None = Field(
        default=None, description="Workflow id of the abundance table DC"
    )
    abundance_dc_id: str | None = Field(
        default=None, description="Data-collection id of the abundance table DC"
    )
    abundance_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the abundance table DC (resolved to ids at import)",
    )
    abundance_col: str = Field(
        default="rel_abundance",
        description="Abundance column: a sample's relative abundance of the row's taxon",
    )
    abundance_sample_col: str = Field(
        default="sample",
        description=(
            "Sample column of the abundance table: a share is the mean over samples of "
            "a sample's share. A table without it has its abundance column summed instead"
        ),
    )
    abundance_split_col: str | None = Field(
        default=None,
        description=(
            "Abundance-table column (e.g. a site) to break each share down by, drawn as "
            "a strip of dots beside the tips"
        ),
    )
    show_split: bool = Field(
        default=True,
        description=(
            "Summary mode: draw the abundance_split_col strip. Off keeps the column for "
            "when the viewer switches it back on"
        ),
    )
    split_scale: Literal["shared", "row"] = Field(
        default="shared",
        description=(
            "Summary mode: the strip's dot area on the one scale every dot shares, or "
            "relative to each lineage's largest value, to show where it is concentrated"
        ),
    )
    show_tip_dots: bool = Field(
        default=True,
        description="Summary mode: draw a dot sized by the lineage's share at each tip",
    )

    @model_validator(mode="after")
    def _summary_is_coherent(self) -> PhylogeneticConfig:
        # The summary's own settings (`size_by`, `top_n`, `abundance_split_col`)
        # are allowed without `collapse_rank`: the full tree ignores them, and a
        # tree switched from its summary to the full tree keeps them, so that
        # switching back (the View control in the viz's settings) returns the
        # summary as it was. What is refused is a summary that cannot be drawn.
        if self.collapse_rank and not (self.metadata_dc_id or self.metadata_dc_tag):
            raise ValueError(
                "collapse_rank reads the rank from the tip metadata: bind it with "
                "metadata_dc_tag (or metadata_dc_id)"
            )
        if self.size_by == "abundance" and not (self.abundance_dc_id or self.abundance_dc_tag):
            raise ValueError(
                "size_by: abundance needs the abundance table: bind it with "
                "abundance_dc_tag (or abundance_dc_id)"
            )
        return self


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

    # --- Selection as a cross-filter ---------------------------------------
    # Off by default: an existing dashboard keeps a lollipop that only reads.
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a click on a stem emit a residue selection (the feature and "
            "the position, shift-click extends the range) that the protein "
            "tiles and tables of the same columns follow, plus a point "
            "selection on the selection column when one resolves."
        ),
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column the point selection values belong to. Null uses "
            "``label_col``; with neither, only the residue selection is emitted."
        ),
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
    link_opacity: float = Field(default=0.4, ge=0.05, le=1.0)
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
    # No per-tile palette: a categorical colour column takes the colours the
    # dashboard pins for that column, so one category keeps one colour across
    # the tiles of every tab.
    color_col: str | None = Field(
        default=None,
        description=(
            "Column driving the marker colour. A categorical column takes the "
            "dashboard's `category_colors` for it (the tab's over the main tab's), "
            "and the palette cycle for any value they do not pin."
        ),
    )
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
    reference_label: str | None = Field(
        default=None,
        description=(
            "Text naming the reference line on the plot (it has no legend entry); null "
            "writes ``x = y`` or the line's equation"
        ),
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
        default=0,
        ge=0,
        description=(
            "Label this many points: the smallest by ``label_order_col`` when bound, "
            "else the largest by size or by |y|"
        ),
    )
    label_order_col: str | None = Field(
        default=None,
        description=(
            "Optional numeric column ranking the labelled points, smallest first (a rank, "
            "a p-value): the top-N labels go to the points it puts first"
        ),
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
    aggregate: Literal["none", "median_iqr"] = Field(
        default="none",
        description=(
            "``none``: one row per series and x, drawn as is. ``median_iqr``: one row per "
            "feature, series and x; the tile draws each series' median with its "
            "interquartile band, computed from the rows the filters leave, so the curves "
            "follow them (a summary written by a recipe cannot)"
        ),
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
    residue_axis: bool | None = Field(
        default=None,
        description=(
            "Whether x is a residue number, so a residue hover or pick on the "
            "protein tiles draws a line on it. Null guesses from the x column "
            "name (`position`); true or false forces it"
        ),
    )

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
            "bare contig name opens the whole contig. ``first`` opens the whole "
            "first contig the data carries, for a template that serves any "
            "reference and so cannot name one."
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


class IdeogramConfig(_BaseVizConfig):
    """A karyotype browser: one bar per chromosome, glyphs or density bins on each.

    The overview draws every bar from the same origin to its chromosome's
    length, so the reader compares chromosomes, and genomes, by length first.
    On the bars go the features: in ``marks`` mode one glyph per row (a BUSCO
    gene coloured by its status), in ``density`` mode one bin per window (the
    rows' own ``value`` when bound, else a count of rows coloured by their
    dominant category or on the colour scale), and in ``auto`` mode marks while
    at most ``lod_threshold`` features are in view and bins above it.

    Clicking a chromosome opens it in a horizontal detail view with its own
    finer bins, a bp axis, zoom and pan; that is local to the tile. Narrowing
    the rest of the dashboard to the chromosome or the visible range is an
    explicit action of the detail view (see ``region_filter_enabled``).

    Chromosome lengths come from ``chrom_length_col`` when bound, else from the
    ``assembly`` table the genome chord ring uses, else from the furthest
    feature on each chromosome.
    """

    viz_kind: Literal["ideogram"] = "ideogram"

    chrom_col: str = Field(default="chrom", description="Chromosome the feature sits on")
    start_col: str = Field(default="start", description="Feature start (bp)")
    end_col: str = Field(default="end", description="Feature end (bp)")
    value_col: str | None = Field(
        default=None,
        description="Optional numeric value (a density, a count), drawn on a sequential colour scale",
    )
    category_col: str | None = Field(
        default=None,
        description="Optional feature class (BUSCO status, variant type), drawn in categorical colours",
    )
    sample_col: str | None = Field(
        default=None,
        description="Optional sample or genome column: one karyotype per value",
    )
    label_col: str | None = Field(
        default=None, description="Optional feature name, shown in the hover"
    )
    chrom_length_col: str | None = Field(
        default=None,
        description="Optional per-row chromosome length (bp); wins over the assembly table",
    )

    assembly: str | None = Field(
        default=None,
        description=(
            "Chromosome sizes to scale the bars on (hg38, hg19, mm10); null uses "
            "``chrom_length_col``, else the furthest feature on each chromosome"
        ),
    )
    mode: Literal["marks", "density", "auto"] = Field(
        default="marks",
        description=(
            "``marks``: one glyph per feature (density past ``max_features``). "
            "``density``: one bin per window, the mean ``value`` when bound, else "
            "the number of features per bin in their dominant category or on the "
            "colour scale. ``auto``: marks while at most ``lod_threshold`` features "
            "are in view, bins above it, so zooming in brings the marks back"
        ),
    )
    bin_size: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Density bin width in bp. Null keeps the rows as their own bins when "
            "``value_col`` is bound, else picks a width giving about 100 bins on the "
            "longest chromosome"
        ),
    )
    orientation: Literal["horizontal", "vertical"] = Field(
        default="horizontal", description="Bars along x (one row each) or along y"
    )
    chromosomes: list[str] | None = Field(
        default=None,
        description=(
            "Chromosomes to draw, in this order (``chr`` prefix and case ignored); "
            "null draws every chromosome in natural order"
        ),
    )
    colour_scale: ColourScale = Field(
        default="Viridis", description="Sequential colour scale for ``value`` and density bands"
    )
    facet_by_sample: bool = Field(
        default=True,
        description="One karyotype per sample (small multiples); off shows the selected sample only",
    )
    sample: str | None = Field(
        default=None, description="Sample shown when not faceting; null picks the first"
    )
    max_facets: int = Field(
        default=6, ge=1, le=24, description="Guard on the number of karyotypes drawn side by side"
    )
    max_chromosomes: int = Field(
        default=60,
        ge=1,
        le=500,
        description="Guard on the bars per karyotype; the longest are kept and the rest reported",
    )
    max_features: int = Field(
        default=20000,
        ge=1,
        le=500000,
        description=(
            "Guard on the glyphs drawn in ``marks`` mode. Above it the tile draws "
            "the density bands instead and says so, never a subset of the marks"
        ),
    )
    lod_threshold: int = Field(
        default=2000,
        ge=1,
        le=500000,
        description=(
            "Level of detail for ``auto`` mode: features in view above which the "
            "overview or the detail view draws density bins rather than marks"
        ),
    )
    feature_opacity: float = Field(
        default=0.85,
        ge=0.05,
        le=1.0,
        description="Opacity of the marks and bins drawn over the chromosomes",
    )
    hidden_categories: list[str] | None = Field(
        default=None,
        description=(
            "Values of ``category_col`` hidden from the karyotype (toggled from the "
            "legend); null shows every category"
        ),
    )

    # --- Region as a cross-filter ------------------------------------------
    # On by default, as for genome_view's brush: a chromosome and a range are
    # never ambiguous. Emitting is an explicit action of the detail view, not a
    # side effect of opening a chromosome.
    region_filter_enabled: bool = Field(
        default=True,
        description=(
            'Offer a "Filter dashboard" action in the detail view, which emits a '
            "chromosome multi-select (plus the visible position range, when zoomed) "
            "on this tile's own collection: the ``genome_selection`` pair a "
            "genome_view brush emits"
        ),
    )

    @field_validator("chromosomes")
    @classmethod
    def _drop_blank_chromosomes(cls, value: list[str] | None) -> list[str] | None:
        """An empty list or blank entries mean "no restriction", not "draw nothing"."""
        if value is None:
            return None
        cleaned = [c.strip() for c in value if isinstance(c, str) and c.strip()]
        return cleaned or None

    @field_validator("hidden_categories")
    @classmethod
    def _empty_hidden_is_none(cls, value: list[str] | None) -> list[str] | None:
        """Nothing hidden is stored as null; the values are kept exactly as the data spells them."""
        if value is None:
            return None
        return list(dict.fromkeys(value)) or None


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


#: The pre-aggregated box statistics `ranked_distribution` reads, by role. The
#: three quartiles are what make a box; the fences and the mean are optional.
RANKED_DISTRIBUTION_STAT_ROLES: tuple[str, ...] = ("q1", "median", "q3", "lower", "upper", "mean")
RANKED_DISTRIBUTION_QUARTILE_ROLES: tuple[str, ...] = ("q1", "median", "q3")


class RankedDistributionConfig(_BaseVizConfig):
    """Top-N features ranked by a score, each with its distribution across samples.

    Two panels share ONE ordered category axis: a box (or violin) per feature of
    its values across samples, and a lollipop of the score that put it there.
    The driving case is nf-core/stableexpression (a stability score per gene and
    the gene's normalised counts across thousands of samples), and the same
    picture serves housekeeping-gene panels, NanoString normalisers or any "rank
    features by a metric" view.

    The distribution comes in one of two shapes, told apart by which columns are
    bound (``validate_binding`` reports a config that binds neither):

    * long form, ``value_col``: one row per feature and sample; the renderer
      ranks the features and aggregates each one's values itself. The only shape
      a violin can be drawn from.
    * pre-aggregated, ``q1_col`` / ``median_col`` / ``q3_col`` (plus optional
      ``lower_col`` / ``upper_col`` fences and ``mean_col``): one row per
      feature, the statistics a recipe computed. What a cohort of thousands of
      samples ships as, since its raw values are far too large to send.
    """

    viz_kind: Literal["ranked_distribution"] = "ranked_distribution"

    feature_id_col: str = Field(
        default="feature_id", description="Column identifying each feature (gene id)"
    )
    score_col: str = Field(
        default="score", description="Score the features are ranked by (stability, variance)"
    )
    rank_col: str | None = Field(
        default=None,
        description=(
            "Optional precomputed rank (1 = best). Unset ranks by ``score_col`` "
            "in the direction ``ascending`` gives."
        ),
    )
    label_col: str | None = Field(
        default=None, description="Optional display name (gene symbol) for the category axis"
    )
    group_col: str | None = Field(
        default=None,
        description="Optional categorical column colouring each feature (a section, a gene class)",
    )
    value_col: str | None = Field(
        default=None,
        description="Long form: one value per feature and sample, aggregated by the renderer",
    )
    q1_col: str | None = Field(default=None, description="Pre-aggregated: first quartile")
    median_col: str | None = Field(default=None, description="Pre-aggregated: median")
    q3_col: str | None = Field(default=None, description="Pre-aggregated: third quartile")
    lower_col: str | None = Field(
        default=None,
        description="Pre-aggregated: lower whisker end; unset draws the whisker from Q1 - 1.5 IQR",
    )
    upper_col: str | None = Field(
        default=None,
        description="Pre-aggregated: upper whisker end; unset draws the whisker to Q3 + 1.5 IQR",
    )
    mean_col: str | None = Field(default=None, description="Pre-aggregated: optional mean")

    top_n: int = Field(
        default=25, ge=1, description="How many of the best-ranked features are drawn"
    )
    ascending: bool = Field(
        default=True,
        description=(
            "Rank the lowest score first. True suits a stability score or a "
            "coefficient of variation, where lower is more stable; false suits "
            "a variance or an expression level. Ignored when ``rank_col`` is bound."
        ),
    )
    distribution: Literal["box", "violin"] = Field(
        default="box",
        description="How each feature's values are drawn; ``violin`` needs the long form",
    )
    orientation: Literal["horizontal", "vertical"] = Field(
        default="horizontal",
        description=(
            "``horizontal``: features down the y axis, distribution on the left "
            "and score on the right. ``vertical``: features along the x axis, "
            "distribution above the score"
        ),
    )
    score_label: str | None = Field(
        default=None, description="Score axis title; null uses the score column's name"
    )
    value_label: str | None = Field(
        default=None, description="Distribution axis title; null says 'Value'"
    )
    log_value: bool = Field(
        default=False,
        description="Draw the distribution on log10(value + 1), for counts spanning decades",
    )
    max_features: int = Field(
        default=200,
        ge=1,
        le=2000,
        description=(
            "Guard on the features a tile may draw: ``top_n`` and its control "
            "are capped here, so a reader cannot ask for a category axis of "
            "ten thousand genes"
        ),
    )

    # --- Selection as a cross-filter ---------------------------------------
    # Off by default, same reasoning as EmbeddingConfig above.
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a click on a feature (its box or its lollipop) emit a dashboard "
            "filter on ``selection_column``, else on ``feature_id_col``"
        ),
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column the emitted selection values belong to. Null uses "
            "``feature_id_col``: a feature is what the reader picks, and its id "
            "is what the other tiles of the dashboard join on"
        ),
    )

    @model_validator(mode="after")
    def _one_coherent_shape(self) -> RankedDistributionConfig:
        """Refuse half a pre-aggregated shape, both shapes at once, and a violin of stats.

        A config binding neither shape is left to ``validate_binding``: the
        builder saves configs before every role is bound, and a stored
        component must stay loadable while it is being edited.
        """
        bound = [r for r in RANKED_DISTRIBUTION_QUARTILE_ROLES if getattr(self, f"{r}_col")]
        if bound and len(bound) < len(RANKED_DISTRIBUTION_QUARTILE_ROLES):
            missing = [f"{r}_col" for r in RANKED_DISTRIBUTION_QUARTILE_ROLES if r not in bound]
            raise ValueError(
                f"ranked_distribution: a pre-aggregated box needs q1_col, median_col and "
                f"q3_col together (missing {', '.join(missing)})"
            )
        if bound and self.value_col:
            raise ValueError(
                "ranked_distribution: bind either value_col (long form) or "
                "q1_col / median_col / q3_col (pre-aggregated), not both"
            )
        if self.distribution == "violin" and bound:
            raise ValueError(
                "ranked_distribution: a violin needs the raw values (value_col); "
                "pre-aggregated statistics can only draw a box"
            )
        return self


# ---------------------------------------------------------------------------
# Protein kinds (lot 3). The 3D structure, the MSA and the linear sequence
# track of one entity share the `residue_selection` cross-filter: the same
# entity / position column names on their collections, so a click in one
# narrows or moves the others.
# ---------------------------------------------------------------------------

#: Residue colouring schemes of the `msa` kind; the `hmm_logo` kind colours its
#: letters with the same ones, so a residue has one colour in both tiles.
MsaColorScheme = Literal["clustal", "zappo", "hydrophobicity", "identity", "none"]


def _check_resolve_source(
    structure_source: str,
    uniprot_col: str | None,
    gene_col: str | None,
    sequence_col: str | None,
) -> None:
    """Refuse `structure_source: resolve` with nothing to resolve the structure from.

    Shared by every kind that can fetch a predicted structure instead of
    reading one from a file (`molecule_3d`, `ramachandran`): the resolver is
    keyed by a UniProt accession, a gene symbol or a sequence, so one of the
    three columns must be bound. Raises ``ValueError`` for a model validator
    to surface.
    """
    if structure_source == "resolve" and not (uniprot_col or gene_col or sequence_col):
        raise ValueError(
            "structure_source 'resolve' needs one of uniprot_col, gene_col or sequence_col"
        )


class Molecule3DConfig(_BaseVizConfig):
    """A protein structure in 3D, coloured and annotated from a residue table.

    The structure comes from an `indexed_file` DC of `pdb` / `mmcif` objects
    (one per entity, `structure_source: file`) or is fetched on demand from a
    UniProt accession, gene name or sequence (`structure_source: resolve`,
    AlphaFold DB first, ESMFold as a fallback). The tile's bound collection is
    the residue or variant table that colours and marks it; it may be absent
    when only the structure is shown.
    """

    viz_kind: Literal["molecule_3d"] = "molecule_3d"

    structure_source: Literal["file", "resolve"] = Field(
        default="file",
        description=(
            "Where the structure comes from: `file` reads the indexed_file DC "
            "named by `structure_dc_id`, `resolve` asks the structure resolver "
            "from the uniprot, gene or sequence column"
        ),
    )
    structure_wf_id: str | None = Field(
        default=None, description="Workflow id of the structure indexed_file DC (pdb / mmcif)"
    )
    structure_dc_id: str | None = Field(
        default=None,
        description="Data-collection id of the structure indexed_file DC (pdb / mmcif)",
    )
    structure_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the structure DC (resolved to ids at import)",
    )
    entity_col: str | None = Field(
        default="entity",
        description=(
            "Column naming the entity (protein) a row belongs to; the entity "
            "picked by the dashboard filters on it is shown, else the first one"
        ),
    )
    uniprot_col: str | None = Field(
        default=None, description="Column holding a UniProt accession (resolve mode)"
    )
    gene_col: str | None = Field(
        default=None, description="Column holding a gene symbol (resolve mode)"
    )
    sequence_col: str | None = Field(
        default=None,
        description="Column holding a one-letter protein sequence, folded by ESMFold (resolve mode)",
    )
    taxon: int = Field(
        default=9606, description="NCBI taxon id used to resolve a gene symbol (resolve mode)"
    )
    position_col: str = Field(
        default="position",
        description="Residue number column, 1-based in the structure numbering",
    )
    chain_col: str | None = Field(default=None, description="Optional chain id column")
    value_col: str | None = Field(
        default=None, description="Numeric per-residue column used by `color_mode: value`"
    )
    category_col: str | None = Field(
        default=None,
        description="Categorical per-residue column (domain, consequence) used by `color_mode: category`",
    )
    ref_aa_col: str | None = Field(default=None, description="Reference amino acid column")
    alt_aa_col: str | None = Field(default=None, description="Alternate amino acid column")
    label_col: str | None = Field(
        default=None, description="Residue or variant label column (for example a protein change)"
    )
    color_mode: Literal[
        "plddt",
        "chain",
        "spectrum",
        "value",
        "category",
        "uniform",
        "secondary_structure",
        "residue_type",
        "hydrophobicity",
    ] = Field(
        default="plddt",
        description=(
            "How residues are coloured: `plddt` reads the structure's B-factor "
            "column, `value` / `category` read the bound collection, "
            "`secondary_structure`, `residue_type` and `hydrophobicity` read the "
            "structure itself"
        ),
    )
    colour_scale: ColourScale | None = Field(
        default=None,
        description="Continuous colour scale of `color_mode: value`; null uses Viridis",
    )
    representation: Literal["cartoon", "trace", "stick", "sphere", "surface"] = Field(
        default="cartoon", description="Molecular representation"
    )
    representations: list[Literal["cartoon", "trace", "stick", "sphere", "surface"]] | None = Field(
        default=None,
        description=(
            "Representations drawn together (for example cartoon and surface); "
            "when set it replaces `representation`"
        ),
    )
    highlight_site: bool = Field(
        default=True,
        description=(
            "Draw the picked residue or residue range as red ball and stick, "
            "and mark it in the written sequence"
        ),
    )
    spin: bool = Field(default=False, description="Start with the structure spinning")
    show_variants: bool = Field(
        default=True,
        description="Draw a sphere on the CA atom of every row carrying an alternate residue or a category",
    )
    show_labels: bool = Field(default=False, description="Label the marked residues")
    layout: Literal["structure", "structure_sequence", "structure_msa", "structure_text"] = Field(
        default="structure",
        description=(
            "What the tile holds: the structure alone, the structure over its "
            "sequence strip, the structure beside the alignment of `msa_dc_id`, "
            "or the structure over its written sequence, one clickable letter "
            "per residue"
        ),
    )
    msa_wf_id: str | None = Field(
        default=None, description="Workflow id of the MSA table (layout `structure_msa`)"
    )
    msa_dc_id: str | None = Field(
        default=None, description="Data-collection id of the MSA table (layout `structure_msa`)"
    )
    msa_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the MSA table (resolved to ids at import)",
    )
    selection_enabled: bool = Field(
        default=True, description="Clicking a residue emits a residue_selection filter"
    )
    follow_selection: bool = Field(
        default=True,
        description="Zoom onto and ring the residues of an incoming residue_selection or hover",
    )

    @model_validator(mode="after")
    def _check_sources(self) -> "Molecule3DConfig":
        _check_resolve_source(
            self.structure_source, self.uniprot_col, self.gene_col, self.sequence_col
        )
        if self.layout == "structure_msa" and not (self.msa_dc_id or self.msa_dc_tag):
            raise ValueError("layout 'structure_msa' needs msa_dc_id (or msa_dc_tag)")
        return self


class MsaConfig(_BaseVizConfig):
    """A multiple sequence alignment, one row per sequence, one column per aligned position.

    The bound collection holds one row per aligned sequence (`msa_id`,
    `seq_id`, `aligned_sequence`, all rows of one `msa_id` the same length).
    Clicking a row selects that sequence; brushing columns emits a
    `residue_selection` in the reference row's own numbering, so the
    structure and the sequence track of the same entity follow it.
    """

    viz_kind: Literal["msa"] = "msa"

    msa_id_col: str = Field(
        default="msa_id",
        description="Column naming the alignment (entity or family) a row belongs to",
    )
    seq_id_col: str = Field(default="seq_id", description="Column naming each aligned sequence")
    sequence_col: str = Field(
        default="aligned_sequence",
        description="Aligned sequence column, gaps as `-`, same length within one alignment",
    )
    rank_col: str | None = Field(
        default="rank", description="Row order column; rank 0 is the query / reference row"
    )
    identity_col: str | None = Field(
        default="identity", description="Identity to the reference row, 0 to 1"
    )
    color_scheme: MsaColorScheme = Field(default="clustal", description="Residue colouring scheme")
    max_rows: int = Field(
        default=200, ge=1, le=1000, description="How many aligned sequences the tile draws"
    )
    sort_by: Literal["rank", "identity", "input"] = Field(
        default="rank",
        description="Row order: rank column, identity to the reference, or input order",
    )
    show_consensus: bool = Field(default=True, description="Show the consensus sequence row")
    show_conservation: bool = Field(
        default=True, description="Show the per-column conservation bars"
    )
    entity_col_for_selection: str = Field(
        default="entity",
        description=(
            "Entity column NAME a column brush filters on, so the filter lands "
            "on the residue and variant tables of the same dashboard"
        ),
    )
    position_col_for_selection: str = Field(
        default="position",
        description="Position column NAME a column brush filters on, in reference coordinates",
    )
    chains_col: str | None = Field(
        default="chains",
        description=(
            "Chain layout column of a multi-chain reference row, for example "
            "`A:1-664,B:665-1004` (each chain's own first and last residue, in "
            "concatenation order). With a layout a column brush is translated to "
            "one chain's own numbering; absent or null means a single chain"
        ),
    )
    chain_col_for_selection: str | None = Field(
        default="chain",
        description=(
            "Chain column NAME a column brush on a multi-chain reference filters "
            "on, beside the entity and position columns"
        ),
    )
    selection_enabled: bool = Field(
        default=True,
        description="Row click selects a sequence; column brush emits a residue_selection",
    )
    follow_selection: bool = Field(
        default=True,
        description="Scroll to and highlight the columns of an incoming residue_selection or hover",
    )


class SequenceTrackConfig(_BaseVizConfig):
    """The linear sequence of one entity with per-residue lanes.

    A residue ruler with the one-letter sequence, an optional numeric lane
    (pLDDT or any per-residue score), a category lane (secondary structure,
    domain), and optional domain spans and variant ticks read from two further
    collections. Brushing emits a `residue_selection`.
    """

    viz_kind: Literal["sequence_track"] = "sequence_track"

    entity_col: str | None = Field(
        default="entity", description="Column naming the entity (protein) a row belongs to"
    )
    position_col: str = Field(default="position", description="Residue number column, 1-based")
    residue_col: str | None = Field(default="residue", description="One-letter residue column")
    value_col: str | None = Field(
        default=None, description="Numeric per-residue column drawn as a lane"
    )
    category_col: str | None = Field(
        default=None, description="Categorical per-residue column drawn as a coloured lane"
    )
    value_label: str | None = Field(default=None, description="Title of the numeric lane")
    domains_wf_id: str | None = Field(
        default=None, description="Workflow id of the domain spans table (optional)"
    )
    domains_dc_id: str | None = Field(
        default=None, description="Data-collection id of the domain spans table (optional)"
    )
    domains_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the domain spans table (resolved to ids at import)",
    )
    domain_start_col: str = Field(default="start", description="Domain start column")
    domain_end_col: str = Field(default="end", description="Domain end column")
    domain_label_col: str = Field(default="label", description="Domain label column")
    variants_wf_id: str | None = Field(
        default=None, description="Workflow id of the variant table (optional)"
    )
    variants_dc_id: str | None = Field(
        default=None, description="Data-collection id of the variant table (optional)"
    )
    variants_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the variant table (resolved to ids at import)",
    )
    variant_position_col: str = Field(
        default="position", description="Amino-acid position column of the variant table"
    )
    variant_label_col: str | None = Field(
        default="label", description="Variant label column of the variant table"
    )
    variant_category_col: str | None = Field(
        default="category", description="Variant consequence column of the variant table"
    )
    selection_enabled: bool = Field(
        default=True, description="Brushing the track emits a residue_selection"
    )
    follow_selection: bool = Field(
        default=True, description="Highlight the residues of an incoming residue_selection or hover"
    )


# ---------------------------------------------------------------------------
# Protein kinds, wave 2. The profile HMM as a logo, the predicted secondary
# structure, the domain architecture, the predicted aligned error and the
# backbone torsions of one entity. They join the three kinds above on the same
# two column names, `entity` and `position`: a pick in one narrows or moves the
# others through `residue_selection`. Tables joined in one dashboard share only
# those two names, so every other column keeps a kind-specific name.
# ---------------------------------------------------------------------------


HmmLogoTrack = Literal["consensus", "insert", "occupancy", "hits", "ruler"]
"""A lane group of the HMM logo panel that can be hidden or collapsed."""


class HmmLogoConfig(_BaseVizConfig):
    """The sequence logo of one profile HMM, with an optional lane of the hits it matched.

    Skylign and `hmmlogo` semantics: one stack per match state, letter heights
    from the state's emission probabilities (always recomputed in the browser
    from `emission_col`), insert probability and expected insert length beside
    the stack, and a consensus row. `profile_source: hmm` reads the long
    profile table of `recipes/lib/hmm.py` (one row per match state and
    letter); `profile_source: msa` derives the same logo from an alignment
    table (`recipes/lib/msa.py`). An optional second collection of domain hits
    draws, under the logo, which states each hit covers.
    """

    viz_kind: Literal["hmm_logo"] = "hmm_logo"

    profile_source: Literal["hmm", "msa"] = Field(
        default="hmm",
        description=(
            "Where the logo comes from: `hmm` reads one row per match state and "
            "letter of a profile HMM (emission probabilities), `msa` builds the "
            "profile from the rows of an alignment table"
        ),
    )
    entity_col: str = Field(
        default="entity",
        description=(
            "Column naming the entity (reference sequence) a state maps onto; "
            "the entity picked by the dashboard filters on it is shown, else the first one"
        ),
    )
    position_col: str = Field(
        default="position",
        description=(
            "Reference residue number of a match state (1-based); null where the "
            "state has no residue on the reference. A pick on a stack emits it"
        ),
    )
    model_col: str = Field(
        default="hmm_name",
        description="Column naming the profile HMM a row belongs to (one logo per model)",
    )
    state_col: str = Field(
        default="hmm_position",
        description="Match-state number along the HMM (1-based): the x axis of the logo",
    )
    letter_col: str = Field(
        default="hmm_letter", description="Residue letter the emission probability belongs to"
    )
    emission_col: str = Field(
        default="emission",
        description="Match emission probability of the letter at the state, from 0 to 1",
    )
    insert_prob_col: str | None = Field(
        default="insert_prob",
        description="Probability of an insert after the state, drawn as the insert-probability lane",
    )
    insert_length_col: str | None = Field(
        default="insert_length",
        description="Expected length of an insert after the state, drawn as the insert-length lane",
    )
    occupancy_col: str | None = Field(
        default="occupancy",
        description="Fraction of the family's sequences that visit the state (match occupancy)",
    )
    consensus_col: str | None = Field(
        default="consensus", description="Consensus residue of the state, for the consensus row"
    )
    rf_col: str | None = Field(
        default="rf", description="Reference annotation character of the state (the `RF` line)"
    )
    cs_col: str | None = Field(
        default="cs", description="Consensus structure character of the state (the `CS` line)"
    )
    msa_id_col: str = Field(
        default="msa_id",
        description="Column naming the alignment a row belongs to (`profile_source: msa`)",
    )
    seq_id_col: str = Field(
        default="seq_id",
        description="Column naming each aligned sequence (`profile_source: msa`)",
    )
    sequence_col: str = Field(
        default="aligned_sequence",
        description=(
            "Aligned sequence column, gaps as `-`, same length within one "
            "alignment (`profile_source: msa`)"
        ),
    )
    rank_col: str | None = Field(
        default="rank",
        description="Row order column; rank 0 is the reference row (`profile_source: msa`)",
    )
    height_mode: Literal["relent_abovebg", "relent_all", "probability"] = Field(
        default="relent_abovebg",
        description=(
            "Letter heights, as in HMMER's hmmlogo: `relent_abovebg` scales the "
            "letters more frequent than background by the state's relative "
            "entropy, `relent_all` scales every letter by it, `probability` "
            "stacks the plain emission probabilities"
        ),
    )
    color_scheme: MsaColorScheme = Field(
        default="clustal",
        description="Residue colouring scheme, the same set as the `msa` kind",
    )
    show_indel_rows: bool = Field(
        default=True,
        description="Show the insert probability, expected insert length and occupancy lanes",
    )
    show_consensus: bool = Field(default=True, description="Show the consensus residue row")
    window_start: int | None = Field(
        default=None,
        ge=1,
        description=(
            "First match state drawn (1-based); states before it are left out. "
            "null starts at the first state. Also a tile control"
        ),
    )
    window_end: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Last match state drawn (1-based); states after it are left out. "
            "null runs to the last state. Also a tile control"
        ),
    )
    collapse_below_ic: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Fold runs of states whose information content is under this many "
            "bits (relative entropy) into a narrow stub that a click opens; "
            "null folds nothing. Also a tile control"
        ),
    )
    collapse_min_run: int = Field(
        default=4,
        ge=1,
        description="Shortest run of low-information states that `collapse_below_ic` folds",
    )
    hidden_tracks: list[HmmLogoTrack] = Field(
        default_factory=list,
        description=(
            "Tracks (lanes) of the panel left out entirely so the logo takes the "
            "room: `consensus` (consensus, RF and CS rows), `insert` (insert "
            "probability and length), `occupancy` (occupancy or deletion bars), "
            "`hits` (coverage area and hit bars), `ruler`. The logo itself is "
            "never hidden. Also a tile control"
        ),
    )
    collapsed_tracks: list[HmmLogoTrack] = Field(
        default_factory=list,
        description=(
            "Tracks reduced to a thin named strip (the hits strip keeps a tiny "
            "density summary); a header button on each track opens it again. "
            "A track in `hidden_tracks` stays hidden. Also a tile control"
        ),
    )
    hits_wf_id: str | None = Field(
        default=None, description="Workflow id of the domain hits table (optional)"
    )
    hits_dc_id: str | None = Field(
        default=None,
        description="Data-collection id of the domain hits table drawn under the logo (optional)",
    )
    hits_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the domain hits table (resolved to ids at import)",
    )
    hits_model_col: str = Field(
        default="label",
        description=(
            "Hits table column naming the HMM a hit matched; the hits of the shown model are drawn"
        ),
    )
    hits_entity_col: str = Field(
        default="entity", description="Hits table column naming the protein a hit belongs to"
    )
    hits_from_col: str = Field(
        default="hmm_from", description="Hits table column: first HMM state the hit aligns to"
    )
    hits_to_col: str = Field(
        default="hmm_to", description="Hits table column: last HMM state the hit aligns to"
    )
    hits_length_col: str | None = Field(
        default="hmm_length",
        description="Hits table column holding the length of the HMM, to tell a partial hit",
    )
    hits_evalue_col: str | None = Field(
        default="i_evalue",
        description="Hits table column holding the independent E-value of a hit",
    )
    hits_score_col: str | None = Field(
        default="dom_score", description="Hits table column holding the bit score of a hit"
    )
    hits_ali_from_col: str | None = Field(
        default="ali_from",
        description="Hits table column: first residue of the hit on its protein (alignment start)",
    )
    hits_ali_to_col: str | None = Field(
        default="ali_to",
        description="Hits table column: last residue of the hit on its protein (alignment end)",
    )
    hits_evalue_max: float | None = Field(
        default=0.01,
        gt=0,
        description="Draw only the hits at or below this E-value; null draws every hit",
    )
    max_hits: int = Field(
        default=200, ge=1, le=2000, description="How many hits the lane under the logo draws"
    )
    selection_enabled: bool = Field(
        default=True,
        description="Clicking or brushing states emits a residue_selection on the reference residues",
    )
    follow_selection: bool = Field(
        default=True, description="Mark the states of an incoming residue_selection or hover"
    )

    @model_validator(mode="after")
    def _tracks_are_listed_once(self) -> HmmLogoConfig:
        for name in ("hidden_tracks", "collapsed_tracks"):
            tracks = getattr(self, name)
            if len(set(tracks)) != len(tracks):
                raise ValueError(f"{name} must not list a track twice")
        overlap = sorted(set(self.hidden_tracks) & set(self.collapsed_tracks))
        if overlap:
            raise ValueError(f"a track cannot be both hidden and collapsed: {', '.join(overlap)}")
        return self

    @model_validator(mode="after")
    def _window_is_ordered(self) -> HmmLogoConfig:
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_start > self.window_end
        ):
            raise ValueError("window_start must not come after window_end")
        return self


class SecondaryStructureConfig(_BaseVizConfig):
    """The secondary structure of one protein, from a per-residue prediction table.

    A topology ribbon (helix, strand arrow, coil, turn) shaded by confidence,
    stacked helix / strand / coil probability lanes (S4PRED `.ss2`), several
    prediction sources compared with an agreement lane, the composition in
    percent and the list of segments. The bound collection holds one row per
    residue (and per source when several are compared); brushing emits a
    `residue_selection`.
    """

    viz_kind: Literal["secondary_structure"] = "secondary_structure"

    entity_col: str | None = Field(
        default="entity",
        description=(
            "Column naming the entity (protein) a row belongs to; the entity "
            "picked by the dashboard filters on it is shown, else the first one"
        ),
    )
    position_col: str = Field(default="position", description="Residue number column, 1-based")
    residue_col: str | None = Field(
        default="residue", description="One-letter residue column, written under the ribbon"
    )
    state_col: str = Field(
        default="ss_code",
        description=(
            "Secondary-structure state of the residue: a DSSP or S4PRED code (H, E, C, ...)"
        ),
    )
    source_col: str | None = Field(
        default=None,
        description=(
            "Column naming the prediction source of a row (S4PRED, DSSP, a "
            "structure). When set, each source gets its own ribbon and an "
            "agreement lane compares them; null means a single source"
        ),
    )
    reference_source: str | None = Field(
        default=None,
        description=(
            "Value of `source_col` the other sources are compared with in the "
            "agreement lane, and the one drawn as the main ribbon; null takes the "
            "first source. Needs `source_col`"
        ),
    )
    p_helix_col: str | None = Field(
        default="p_helix", description="Probability of helix at the residue, from 0 to 1"
    )
    p_strand_col: str | None = Field(
        default="p_strand", description="Probability of strand at the residue, from 0 to 1"
    )
    p_coil_col: str | None = Field(
        default="p_coil", description="Probability of coil at the residue, from 0 to 1"
    )
    confidence_col: str | None = Field(
        default=None,
        description=(
            "Per-residue confidence shading the ribbon, from 0 to 1; null uses "
            "the largest of the three probabilities"
        ),
    )
    show_probabilities: bool = Field(
        default=True, description="Show the stacked helix / strand / coil probability lanes"
    )
    show_agreement: bool = Field(
        default=True,
        description="Show the lane marking where the sources agree (several sources only)",
    )
    show_segments: bool = Field(
        default=True, description="Show the list of helix and strand segments with their span"
    )
    show_composition: bool = Field(
        default=True, description="Show the percentage of helix, strand and coil residues"
    )
    show_letters: bool = Field(
        default=True,
        description="Write the one-letter sequence under the ruler once the cells are wide enough",
    )
    shade_confidence: bool = Field(
        default=True, description="Shade each residue of the ribbon by its confidence"
    )
    show_coil_segments: bool = Field(
        default=False,
        description="List the coil stretches in the segment list, not only helices and strands",
    )
    residue_width: int = Field(
        default=0,
        ge=0,
        le=24,
        description="Pixels per residue; 0 fits the whole protein to the tile width",
    )
    ribbon_height: int | None = Field(
        default=None,
        ge=16,
        le=64,
        description=(
            "Height in pixels of the main ribbon lane, drawn exactly. Null keeps "
            "the default 30 px lane, which grows to fill spare room up to 52 px"
        ),
    )
    min_segment_length: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Leave out of the segment list the segments shorter than this many residues",
    )
    state_colors: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "CSS colour per secondary-structure class (Helix, Strand, Turn, Coil; "
            "state codes such as H or E read as their class). Over the colours the "
            "dashboard pins for the state column; a class left out keeps the "
            "pinned or default colour. The viewer can recolour on the tile"
        ),
    )
    selection_enabled: bool = Field(
        default=True, description="Brushing the ribbon emits a residue_selection"
    )
    follow_selection: bool = Field(
        default=True, description="Mark the residues of an incoming residue_selection or hover"
    )

    @field_validator("state_colors")
    @classmethod
    def _state_colors_non_empty(cls, v: dict[str, str]) -> dict[str, str]:
        for key, colour in v.items():
            if not key.strip():
                raise ValueError("state_colors keys must be non-empty class names")
            if not colour.strip():
                raise ValueError(f"state_colors[{key!r}] must be a non-empty colour string")
        return v

    @model_validator(mode="after")
    def _check_reference(self) -> "SecondaryStructureConfig":
        if self.reference_source and not self.source_col:
            raise ValueError("reference_source needs source_col (the column naming each source)")
        return self


class DomainArchitectureConfig(_BaseVizConfig):
    """The domain architecture of proteins, from a table of domain hits.

    `view: proteins` draws one backbone per protein with its domains coloured
    by label. Where the HMM match is partial the domain's edge is zigzagged, as
    Pfam graphics does: `hmm_from_col` above 1 marks the left edge,
    `hmm_to_col` below `hmm_length_col` the right edge, and a coverage under
    `partial_coverage` marks the domain partial on a side that is not known.
    `view: architectures` groups the proteins by their ordered list of labels
    and counts each architecture. The bound collection is a domain hit table
    (lot 3 `hmmsearch_domtbl`) or a plain `entity, start, end, label` table.
    """

    viz_kind: Literal["domain_architecture"] = "domain_architecture"

    entity_col: str = Field(
        default="entity", description="Column naming the protein a domain belongs to"
    )
    start_col: str = Field(
        default="start", description="First residue of the domain on its protein (1-based)"
    )
    end_col: str = Field(
        default="end", description="Last residue of the domain on its protein (inclusive)"
    )
    label_col: str = Field(
        default="label",
        description=(
            "Domain label (family name) that colours the domain and names it in the legend"
        ),
    )
    protein_length_col: str | None = Field(
        default="protein_length",
        description=(
            "Length of the protein, to draw the backbone to scale; null uses the last domain end"
        ),
    )
    hmm_from_col: str | None = Field(
        default="hmm_from",
        description="First HMM state the domain aligns to; above 1 the left edge is drawn zigzag",
    )
    hmm_to_col: str | None = Field(
        default="hmm_to",
        description=(
            "Last HMM state the domain aligns to; below the HMM length the right "
            "edge is drawn zigzag"
        ),
    )
    hmm_length_col: str | None = Field(
        default="hmm_length", description="Length of the HMM the domain matched"
    )
    hmm_coverage_col: str | None = Field(
        default="hmm_coverage",
        description=(
            "Fraction of the HMM the domain covers, from 0 to 1; the fallback "
            "for a partial match when the HMM states are not bound"
        ),
    )
    evalue_col: str | None = Field(
        default="i_evalue", description="E-value of the domain hit, shown in the tooltip"
    )
    source_col: str | None = Field(
        default="source",
        description=(
            "Annotation database of the hit (Pfam, SMART, ...), for "
            "`color_by: source` and the source filter"
        ),
    )
    description_col: str | None = Field(
        default="description",
        description="Free-text description of the family, shown in the tooltip",
    )
    accession_col: str | None = Field(
        default="accession", description="Accession of the family (for example PF00069)"
    )
    view: Literal["proteins", "architectures"] = Field(
        default="proteins",
        description=(
            "`proteins` draws one backbone per protein, `architectures` groups "
            "proteins that share the same ordered labels and counts them"
        ),
    )
    max_architectures: int = Field(
        default=15,
        ge=1,
        le=100,
        description="How many of the most frequent architectures the architectures view draws",
    )
    max_proteins: int = Field(
        default=2000, ge=1, le=20000, description="How many proteins the tile draws"
    )
    evalue_threshold: float | None = Field(
        default=None,
        gt=0,
        description="Draw only the domains at or below this E-value; null draws every hit",
    )
    sources: list[str] | None = Field(
        default=None,
        description="Annotation databases to keep, matched on `source_col`; null keeps them all",
    )
    scale: Literal["shared", "per_protein"] = Field(
        default="shared",
        description=(
            "`shared` draws every backbone on the longest protein's scale, "
            "`per_protein` stretches each backbone to the full width"
        ),
    )
    residue_width: int = Field(
        default=0,
        ge=0,
        le=24,
        description=(
            "Pixels per residue of the longest protein; 0 fits the tracks to the tile "
            "width, a larger value makes the tile scroll sideways under a fixed label "
            "column. With `scale: per_protein` every backbone is that long in total "
            "(the width of the longest protein at this many pixels per residue)"
        ),
    )
    color_by: Literal["label", "source"] = Field(
        default="label", description="What the domain colour encodes"
    )
    partial_coverage: float = Field(
        default=0.9,
        ge=0,
        le=1,
        description="HMM coverage below which a domain counts as a partial match",
    )
    position_col_for_selection: str = Field(
        default="position",
        description=(
            "Position column NAME a domain pick filters on (with the entity "
            "column), so the filter lands on the residue tables of the same dashboard"
        ),
    )
    label_selection: bool = Field(
        default=True,
        description="A domain pick also emits a point selection, on `selection_column` or `label_col`",
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column the point selection of a domain pick is made on, and the one a "
            "linked record card keys on. Null uses `label_col`, which several hits "
            "of a protein can share; name a per-hit key to pick exactly one domain"
        ),
    )
    selection_enabled: bool = Field(
        default=True, description="Clicking a domain emits a residue_selection over its span"
    )
    follow_selection: bool = Field(
        default=True, description="Mark the domains under an incoming residue_selection or hover"
    )


class PaeMatrixConfig(_BaseVizConfig):
    """The predicted aligned error of a structure, as a residue-by-residue heatmap.

    A square N x N matrix on residue axes (x the scored residue, y the aligned
    residue), read from the structure predictor's PAE file: a companion
    `indexed_file` collection of format `pae` (one object per entity, the
    sample id being the entity), fetched by the browser like a structure file.
    The bound collection is the residue table (`entity`, `position`, and
    optionally pLDDT for the strips along the axes).
    """

    viz_kind: Literal["pae_matrix"] = "pae_matrix"

    entity_col: str | None = Field(
        default="entity",
        description=(
            "Column naming the entity (protein) a row belongs to; the entity "
            "picked by the dashboard filters on it selects the PAE file shown"
        ),
    )
    position_col: str = Field(
        default="position", description="Residue number column, 1-based, in the matrix order"
    )
    value_col: str | None = Field(
        default=None,
        description="Numeric per-residue column (pLDDT) drawn as a strip along the axes",
    )
    chain_col: str | None = Field(
        default=None, description="Optional chain id column, to mark chain boundaries on a complex"
    )
    pae_wf_id: str | None = Field(
        default=None, description="Workflow id of the PAE indexed_file DC (format `pae`)"
    )
    pae_dc_id: str | None = Field(
        default=None, description="Data-collection id of the PAE indexed_file DC (format `pae`)"
    )
    pae_dc_tag: str | None = Field(
        default=None, description="Data-collection tag of the PAE DC (resolved to ids at import)"
    )
    max_pae: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Upper bound of the colour scale in angstroms; null takes the "
            "file's own maximum, else 31.75"
        ),
    )
    colour_scale: ColourScale | None = Field(
        default=None,
        description=(
            "Continuous colour scale of the matrix; null uses the AlphaFold-like "
            "ramp derived from the theme"
        ),
    )
    brush: Literal["diagonal", "rectangle"] = Field(
        default="diagonal",
        description=(
            "How a drag selects: `diagonal` takes the square [a, b] x [a, b] "
            "and emits [a, b]; `rectangle` (or shift-drag) emits the scored "
            "range and keeps the aligned range as a local outline"
        ),
    )
    show_plddt: bool = Field(
        default=True, description="Draw the pLDDT strips along the axes when `value_col` is bound"
    )
    selection_enabled: bool = Field(
        default=True, description="Brushing the matrix emits a residue_selection"
    )
    follow_selection: bool = Field(
        default=True, description="Mark the residues of an incoming residue_selection or hover"
    )

    @model_validator(mode="after")
    def _check_pae_source(self) -> "PaeMatrixConfig":
        if not (self.pae_dc_id or self.pae_dc_tag):
            raise ValueError("pae_matrix needs pae_dc_id (or pae_dc_tag)")
        return self


class RamachandranConfig(_BaseVizConfig):
    """The phi / psi backbone torsions of a structure, as a Ramachandran plot.

    The angles of every residue are computed in the browser from the backbone
    (N, CA, C) of the structure, which comes from the same sources as
    `molecule_3d` (an `indexed_file` DC of pdb / mmcif objects, or the
    structure resolver). Glycine and proline are drawn with their own symbols,
    and the schematic favoured regions are labelled as approximate, not as
    MolProbity contours. The bound collection is the residue table that
    colours the points.
    """

    viz_kind: Literal["ramachandran"] = "ramachandran"

    structure_source: Literal["file", "resolve"] = Field(
        default="file",
        description=(
            "Where the structure comes from: `file` reads the indexed_file DC "
            "named by `structure_dc_id`, `resolve` asks the structure resolver "
            "from the uniprot, gene or sequence column"
        ),
    )
    structure_wf_id: str | None = Field(
        default=None, description="Workflow id of the structure indexed_file DC (pdb / mmcif)"
    )
    structure_dc_id: str | None = Field(
        default=None,
        description="Data-collection id of the structure indexed_file DC (pdb / mmcif)",
    )
    structure_dc_tag: str | None = Field(
        default=None,
        description="Data-collection tag of the structure DC (resolved to ids at import)",
    )
    uniprot_col: str | None = Field(
        default=None, description="Column holding a UniProt accession (resolve mode)"
    )
    gene_col: str | None = Field(
        default=None, description="Column holding a gene symbol (resolve mode)"
    )
    sequence_col: str | None = Field(
        default=None,
        description=(
            "Column holding a one-letter protein sequence, folded by ESMFold (resolve mode)"
        ),
    )
    taxon: int = Field(
        default=9606, gt=0, description="NCBI taxon id used to resolve a gene symbol (resolve mode)"
    )
    entity_col: str = Field(
        default="entity",
        description=(
            "Column naming the entity (protein) a row belongs to; the entity "
            "picked by the dashboard filters on it is shown, else the first one"
        ),
    )
    position_col: str = Field(
        default="position",
        description="Residue number column, 1-based in the structure numbering",
    )
    chain_col: str | None = Field(default=None, description="Optional chain id column")
    value_col: str | None = Field(
        default=None, description="Numeric per-residue column used by `color_mode: value`"
    )
    category_col: str | None = Field(
        default=None,
        description=(
            "Categorical per-residue column (domain, consequence) used by `color_mode: category`"
        ),
    )
    color_mode: Literal[
        "plddt", "residue_class", "secondary_structure", "value", "category", "chain"
    ] = Field(
        default="plddt",
        description=(
            "How points are coloured: `plddt` reads the structure's B-factor "
            "column, `residue_class` the general / glycine / proline / "
            "pre-proline class, `secondary_structure` the helix / strand state of "
            "`category_col` when it holds one, else the phi/psi region each point "
            "falls in, `value` / `category` the bound collection, `chain` the chain"
        ),
    )
    show_regions: bool = Field(
        default=True,
        description="Draw the schematic favoured regions (approximate, not MolProbity contours)",
    )
    residue_classes: list[Literal["general", "glycine", "proline", "pre_proline"]] | None = Field(
        default=None, description="Residue classes to plot; null plots all four"
    )
    marker_size: int = Field(default=6, ge=2, le=20, description="Point diameter in pixels")
    selection_enabled: bool = Field(
        default=True, description="Clicking or lassoing points emits a residue_selection"
    )
    follow_selection: bool = Field(
        default=True, description="Ring the residues of an incoming residue_selection or hover"
    )

    @model_validator(mode="after")
    def _check_sources(self) -> "RamachandranConfig":
        _check_resolve_source(
            self.structure_source, self.uniprot_col, self.gene_col, self.sequence_col
        )
        return self


class SpatialCellsConfig(_BaseVizConfig):
    """Segmented cells drawn where they sit in the image.

    One marker per cell at its centroid, in the coordinate frame of the image
    the cells were segmented from: origin top-left, y growing downwards
    (``y_axis: image``, the default), equal aspect always, marker area taken
    from the cell's own area so the picture reads as tissue rather than as a
    scatter. The driving table is a single-cell quantification such as
    nf-core/mcmicro's mcquant output (``CellID``, ``X_centroid``,
    ``Y_centroid``, ``Area`` and one mean-intensity column per marker), which
    is WIDE: the colouring marker is switched from a control over
    ``value_columns`` (or the numeric columns matching
    ``value_columns_pattern``), never by rebinding.

    A sample is one image, so two samples are never drawn in one frame:
    ``sample_display: select`` shows one at a time behind a picker,
    ``facet`` puts up to ``max_facets`` of them side by side, each in its own
    frame. Cells of different segmenters on the same image share its frame
    and are told apart by ``category_col``.
    """

    viz_kind: Literal["spatial_cells"] = "spatial_cells"

    cell_id_col: str = Field(
        default="cell_id",
        description=(
            "Column identifying each cell. A selection emits its values, so it "
            "should be unique across samples (mcquant's CellID restarts at 1 "
            "per image: bind a sample-qualified id when several images share "
            "the table)"
        ),
    )
    x_col: str = Field(default="x", description="Centroid x, in image pixels (or microns)")
    y_col: str = Field(default="y", description="Centroid y, in image pixels (or microns)")
    value_col: str | None = Field(
        default=None,
        description=(
            "Numeric column the cells are coloured by first (one marker's "
            "intensity). The marker picker writes it back"
        ),
    )
    category_col: str | None = Field(
        default=None,
        description=(
            "Categorical column (cell type, phenotype, segmenter) for the "
            "categorical colouring; takes the dashboard's `category_colors`"
        ),
    )
    sample_col: str | None = Field(
        default=None,
        description="Column naming the image (sample, ROI, core) a cell belongs to",
    )
    area_col: str | None = Field(
        default=None,
        description="Cell area in squared coordinate units, which sizes the markers",
    )
    value_columns: list[str] | None = Field(
        default=None,
        description=(
            "Marker columns the colour picker offers. Null offers `value_col` "
            "alone, or the columns `value_columns_pattern` matches"
        ),
    )
    value_columns_pattern: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Regular expression naming the marker columns, for a table whose "
            "markers are only known at ingest (one column per channel of the "
            "panel). Matched with a search against the numeric columns, less "
            "the bound coordinate, id and area columns, in table order. "
            "Mutually exclusive with `value_columns`"
        ),
    )
    color_by: Literal["value", "category"] | None = Field(
        default=None,
        description=(
            "Colour the cells by the marker (continuous) or by `category_col`. "
            "Null takes the marker when one is bound, else the category"
        ),
    )
    sample_display: Literal["select", "facet"] = Field(
        default="select",
        description=(
            "One image at a time behind a picker (`select`), or up to "
            "`max_facets` images side by side, each in its own frame (`facet`)"
        ),
    )
    default_sample: str | None = Field(
        default=None, description="Sample shown first in `select` mode; null takes the first"
    )
    max_facets: int = Field(default=4, ge=1, le=12, description="Images drawn in `facet` mode")
    y_axis: Literal["image", "cartesian"] = Field(
        default="image",
        description=(
            "`image`: origin top-left, y downwards, as the pixels of the image "
            "(mcquant, Xenium, MERFISH). `cartesian`: y upwards"
        ),
    )
    colour_scale: ColourScale = Field(
        default="Viridis", description="Continuous colour scale of the marker colouring"
    )
    reverse_scale: bool = Field(default=False, description="Reverse the continuous colour scale")
    transform: Literal["none", "asinh", "log1p"] = Field(
        default="none",
        description=(
            "Transform applied to the marker before colouring: `asinh` is "
            "asinh(x / cofactor), the cytometry convention; `log1p` is log(1 + x)"
        ),
    )
    asinh_cofactor: float = Field(
        default=150.0,
        gt=0.0,
        description="Cofactor of the asinh transform (5 for mass cytometry, about 150 for flow)",
    )
    clip_low_pct: float = Field(
        default=1.0,
        ge=0.0,
        le=50.0,
        description="Lower percentile of the colour range; cells under it take the lowest colour",
    )
    clip_high_pct: float = Field(
        default=99.0,
        ge=50.0,
        le=100.0,
        description="Upper percentile of the colour range; cells over it take the highest colour",
    )
    size_by_area: bool = Field(
        default=True,
        description=(
            "Draw each cell at the diameter its area implies at the current "
            "zoom, so cells look like cells; off draws every cell at `point_size`"
        ),
    )
    point_size: float = Field(
        default=4.0,
        gt=0.0,
        le=40.0,
        description="Marker diameter in px without an area, and the floor with one",
    )
    max_point_size: float = Field(
        default=40.0, gt=0.0, le=200.0, description="Ceiling of an area-sized marker, in px"
    )
    opacity: float = Field(default=0.9, ge=0.05, le=1.0, description="Marker opacity")
    legend_pos: Literal["right", "bottom", "none"] = Field(
        default="right", description="Where the category legend sits"
    )
    hover_cols: list[str] = Field(
        default_factory=list, description="Extra columns shown in the hover tooltip"
    )
    max_cells: int = Field(
        default=100_000,
        ge=1_000,
        le=1_000_000,
        description=(
            "Most cells drawn per tile. The server already samples a large "
            "table to the figure point budget; past this, a full load is "
            "thinned evenly in the browser and the badge says so"
        ),
    )

    # --- Image underlay ------------------------------------------------------
    # An image of the same sample under the cells, placed on the coordinate
    # frame with Plotly's `layout.images`: pixel (0, 0) at the origin, the
    # image `width x height` pixels wide times `background_image_scale`.
    background_wf_id: str | None = Field(
        default=None, description="Workflow id of the Image DC holding the underlay previews"
    )
    background_dc_id: str | None = Field(
        default=None, description="Data-collection id of the Image DC holding the underlay previews"
    )
    background_dc_tag: str | None = Field(
        default=None, description="Data-collection tag of the Image DC (resolved to ids at import)"
    )
    background_image_col: str | None = Field(
        default=None,
        description="Column of the Image DC naming each preview; null takes its `image_column`",
    )
    background_sample_col: str = Field(
        default="sample",
        description="Column of the Image DC matching `sample_col`, one preview per sample",
    )
    background_width_col: str = Field(
        default="width", description="Column of the Image DC with the preview's width in pixels"
    )
    background_height_col: str = Field(
        default="height", description="Column of the Image DC with the preview's height in pixels"
    )
    background_url: str | None = Field(
        default=None,
        description=(
            "Direct URL of the underlay instead of an Image DC; `{sample}` is "
            "replaced by the sample shown. Needs `background_width` and "
            "`background_height`"
        ),
    )
    background_width: int | None = Field(
        default=None, ge=1, description="Width in pixels of the image at `background_url`"
    )
    background_height: int | None = Field(
        default=None, ge=1, description="Height in pixels of the image at `background_url`"
    )
    background_image_scale: float = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Coordinate units per image pixel: 1 when the centroids are in "
            "pixels of that image, the downscale factor of a preview, or the "
            "pixel size in microns for micron coordinates"
        ),
    )
    background_opacity: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Opacity of the image underlay"
    )
    show_background: bool = Field(
        default=True, description="Draw the underlay when one is configured"
    )

    # --- Selection as a cross-filter ---------------------------------------
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a lasso / box / click on cells emit a dashboard filter on the "
            "selection column. Off by default, like every scatter kind"
        ),
    )
    selection_column: str | None = Field(
        default=None, description="Column the selection values belong to; null uses `cell_id_col`"
    )

    @field_validator("value_columns_pattern")
    @classmethod
    def _value_columns_pattern_compiles(cls, v: str | None) -> str | None:
        return _pattern_compiles("value_columns_pattern", v)

    @model_validator(mode="after")
    def _check_spatial_cells(self) -> SpatialCellsConfig:
        # An empty list is what the builder writes when the picker is cleared,
        # and it lists nothing, so it does not compete with a pattern.
        if self.value_columns and self.value_columns_pattern is not None:
            raise ValueError(
                "value_columns and value_columns_pattern are mutually exclusive: list the "
                "markers or name them by pattern, not both"
            )
        if self.clip_low_pct >= self.clip_high_pct:
            raise ValueError("clip_low_pct must be below clip_high_pct")
        if self.background_url and not (self.background_width and self.background_height):
            raise ValueError(
                "background_url needs background_width and background_height: the "
                "underlay is placed on the coordinate frame by its pixel size"
            )
        if self.color_by == "category" and not self.category_col:
            raise ValueError("color_by: category needs category_col")
        return self


# ---------------------------------------------------------------------------
# Immunogenetics
# ---------------------------------------------------------------------------

#: How many nomenclature fields an allele keeps on screen: 1 is the allele
#: group ("A*02"), 2 the protein ("A*02:01", OptiType's resolution), 3 the
#: synonymous coding change, 4 the non-coding one.
AlleleResolution = Literal[1, 2, 3, 4]

#: The per-sample bars an allele grid can draw beside it.
AlleleSideBar = Literal["value", "reads"]


def _default_allele_side_bars() -> list[AlleleSideBar]:
    """Both bars; the renderer draws only those whose column is bound."""
    return ["value", "reads"]


class AlleleGridConfig(_BaseVizConfig):
    """Sample x locus grid of diploid genotypes (HLA typing).

    One row per allele call: OptiType's A1 / A2 / B1 / ... columns melted long,
    or LILAC and arcasHLA as they are written. Each cell is split in two
    halves, one per haplotype, coloured by allele: the allele group (first
    field) picks a hue family and the full allele a shade inside it, so every
    A*02 reads as one family across the cohort. A homozygous locus draws as
    one merged cell with a marker. The colours are the dashboard's
    ``category_colors`` for the allele column first.
    """

    viz_kind: Literal["allele_grid"] = "allele_grid"

    sample_id_col: str = Field(default="sample_id", description="Sample column (one grid row each)")
    locus_col: str = Field(default="locus", description="Locus column (one grid column each)")
    allele_col: str = Field(default="allele", description="Allele call, in HLA nomenclature")
    haplotype_col: str | None = Field(
        default=None,
        description="Optional haplotype (1 / 2) of the call; null pairs a locus's rows in table order",
    )
    category_col: str | None = Field(
        default=None,
        description="Optional locus class (HLA class I / II), grouping the columns under a header",
    )
    value_col: str | None = Field(
        default=None,
        description="Optional per-sample score (OptiType objective), drawn as a side bar",
    )
    reads_col: str | None = Field(
        default=None,
        description="Optional per-sample read support, drawn as a side bar or as cell opacity",
    )

    resolution: AlleleResolution = Field(
        default=2,
        description=(
            "Nomenclature fields kept on screen: 1 (A*02), 2 (A*02:01), 3 or 4. "
            "Two calls that agree at this resolution are drawn as homozygous."
        ),
    )
    locus_order: list[str] | None = Field(
        default=None,
        description=(
            "Loci in column order, with or without the HLA- prefix. Unlisted "
            "loci follow, in the conventional order (A, B, C, then class II)."
        ),
    )
    sample_order: Literal["alphabetical", "value", "allele"] = Field(
        default="alphabetical",
        description=(
            "Row order: sample name, the value column (highest first), or the "
            "alleles at `order_locus`, which lines carriers of one allele up"
        ),
    )
    order_locus: str | None = Field(
        default=None,
        description="Locus whose alleles order the rows when `sample_order` is `allele`; null uses the first column",
    )
    show_labels: bool = Field(
        default=True, description="Write the allele in each half when it fits"
    )
    side_bars: list[AlleleSideBar] = Field(
        default_factory=_default_allele_side_bars,
        description="Per-sample bars drawn beside the grid, among the bound value and reads columns",
    )
    reads_as_opacity: bool = Field(
        default=False,
        description="Fade a sample's cells by its read support instead of (or as well as) a bar",
    )
    value_label: str | None = Field(
        default=None, description="Header of the value bar; null uses the column name"
    )
    reads_label: str | None = Field(
        default=None, description="Header of the reads bar; null uses the column name"
    )
    max_samples: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Guard on the grid rows drawn; the rest are counted, never sampled",
    )
    max_loci: int = Field(default=24, ge=1, le=60, description="Guard on the grid columns drawn")

    # --- Selection as a cross-filter ---------------------------------------
    # Off by default, as for the other non-protein kinds.
    selection_enabled: bool = Field(
        default=False,
        description=(
            "Let a click on an allele filter the dashboard to the rows carrying "
            "it, and a click on a sample label to that sample"
        ),
    )
    selection_column: str | None = Field(
        default=None,
        description=(
            "Column an allele click selects on. Null uses ``allele_col``, which "
            "is what a peptide-by-allele prediction table (epitopeprediction) "
            "joins on. A sample-label click always selects on ``sample_id_col``."
        ),
    )


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
    | IdeogramConfig
    | RecordCardConfig
    | ParallelCoordinatesConfig
    | RankedDistributionConfig
    | Molecule3DConfig
    | MsaConfig
    | SequenceTrackConfig
    | HmmLogoConfig
    | SecondaryStructureConfig
    | DomainArchitectureConfig
    | PaeMatrixConfig
    | RamachandranConfig
    | SpatialCellsConfig
    | AlleleGridConfig,
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
