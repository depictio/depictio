"""
Component Type Definitions.

Literal types for dashboard components, providing type safety and validation
for component configuration.
"""

from typing import Literal

# Component types
ComponentType = Literal[
    "card",
    "figure",
    "interactive",
    "table",
    "text",
    "jbrowse",
    "image",
    "map",
    "advanced_viz",
]

# Advanced visualisation kinds. Each kind has its own Pydantic config submodel
# in depictio/models/components/advanced_viz/configs.py and its own React
# renderer; the discriminated union over them lives inside the AdvancedViz
# component (not at the outer ComponentMetadata level), so the rest of the
# system sees one component type.
AdvancedVizKind = Literal[
    "volcano",
    "embedding",
    "manhattan",
    "stacked_taxonomy",
    "phylogenetic",
    "rarefaction",
    "da_barplot",
    "enrichment",
    "complex_heatmap",
    "upset_plot",
    "ma",
    "dot_plot",
    "lollipop",
    "qq",
    "sunburst",
    "oncoplot",
    "coverage_track",
    "sankey",
    # Variant-benchmarking kinds (precision/recall/F1 against truth sets).
    "pr_benchmark",
    "roc_pr_curve",
    "confusion_matrix",
    "metric_ci_bars",
    # Life-science kinds whose shape no existing kind can express. `profile` and
    # `signal_matrix` are the metagene pair, the rest are one figure each that a
    # pipeline in the nf-core lot had to fall back to code mode for.
    "profile",
    "signal_matrix",
    "fusion_structure",
    "gene_arrow_track",
    "gsea_running_score",
    "sashimi",
    # Numeric against numeric. Named `scatter_xy` rather than `scatter` because
    # `ChartType` below already owns that word for the figure component. It is
    # the plainest kind here and the most bound: 28 code-mode figures across ten
    # nf-core templates draw a scatter by hand, every one of them for a size
    # column, a selection key or a reference line rather than for the shape.
    "scatter_xy",
    # nf-core lot 2. Each one exists because a megatest output needed it and no
    # existing kind could bind it. `contact_map` is coordinate-bound like
    # `coverage_track`, and sits on the JBrowse boundary recorded in
    # depictio/projects/nf-core/TEMPLATE_BOTTLENECKS.md: it draws a binned
    # matrix, never per-base signal.
    "contact_map",
    "knee_plot",
    "damage_profile",
    # Declarative genome view rendered by GenomeSpy (issue #1083). The same
    # chr / pos / score roles as `manhattan`, drawn on a `locus` scale that
    # GenomeSpy concatenates and zooms itself. `end_col` turns points into
    # intervals, `sample_col` into stacked lanes, and a brush on the genome
    # axis into a chromosome + position filter the rest of the dashboard
    # reads. See docs/design/genomespy-eval.md.
    "genome_view",
    # Kinds from the 2026-09 nf-core audit, each the missing piece of a
    # reference app: a two-group test computed on demand (CELLxGENE / iSEE),
    # isoform structures (SQANTI / Swan), a copy-number profile (CNVkit /
    # cBioPortal) and a chord diagram of inter-locus links (circos).
    "group_compare",
    "transcript_structure",
    "cnv_profile",
    "genome_chord",
    # A reader-facing pair rather than a new chart family. `record_card` is the
    # detail half of a master/detail dashboard: it shows ONE row of a
    # collection, picked by a selection another tile emits, as labelled fields
    # and links instead of a mark. `parallel_coordinates` is the many-metric
    # view a scatter cannot give: one polyline per sample across N axes, which
    # is how a QC table with a dozen columns is read as a whole.
    "record_card",
    "parallel_coordinates",
    # Protein kinds (lot 3): a 3D structure, a multiple sequence alignment and
    # a linear per-residue track, linked by the `residue_selection` filter
    # (an entity column + a residue position range).
    "molecule_3d",
    "msa",
    "sequence_track",
    # Protein kinds (wave 2): the profile HMM as a logo, the predicted
    # secondary structure and the domain architecture of a protein, and the
    # two views of a structure that are not 3D (predicted aligned error,
    # backbone torsions). Same `residue_selection` link as the three above.
    "hmm_logo",
    "secondary_structure",
    "domain_architecture",
    "pae_matrix",
    "ramachandran",
    # A karyotype: one bar per chromosome from a common origin, scaled to its
    # length, with a glyph per feature (BUSCO genes coloured by status) or a
    # heat band per bin (variant density). The genomic kinds above all draw one
    # locus axis at a time; this is the whole genome as a set of bars.
    "ideogram",
    # Top-N features ranked by a score, each drawn with its distribution across
    # samples: a box (or violin) panel and a lollipop of the score on ONE
    # shared, ordered category axis. Gene stability (nf-core/stableexpression),
    # housekeeping candidates, any "rank features by a metric" view. Two panels
    # linked by order are a new set of marks: a box figure cannot sort by a
    # column it does not draw, nor hold the score beside it.
    "ranked_distribution",
    # Segmented cells drawn where they sit in the tissue: one marker per cell
    # at its centroid, in IMAGE coordinates (origin top-left, y down), at the
    # cell's own size, coloured by one marker of a wide single-cell table
    # (mcquant, Xenium, molkart) with an optional image underlay. Pending the
    # section 8 gate review against an `embedding` bound to the centroids;
    # see INCUBATING in advanced_viz/schemas.py.
    "spatial_cells",
    # Immunogenetics: a sample x locus grid of diploid genotypes, each cell
    # split into its two haplotypes and coloured by allele group (HLA typing
    # from nf-core/hlatyping, LILAC in oncoanalyser). Incubating against an
    # oncoplot view of the same table; see `INCUBATING` in schemas.py.
    "allele_grid",
    # Clinical genetics: a family tree from a PED-like table (one row per
    # individual, with its father, mother, sex and affected status), drawn with
    # the standard pedigree symbols (nf-core/raredisease, sarek germline).
    "pedigree",
    # A styled leaderboard: candidates ranked by a score, with medals on the
    # first three, badges and bars in the cells and a hover popover of the
    # fields behind a row (top variants of nf-core/raredisease, outlier genes
    # of DROP).
    "ranked_table",
]

# Map visualization types
MapType = Literal["scatter_map", "density_map", "choropleth_map"]

# Chart/visualization types (from figure_component/definitions.py).
# ``violin`` is the per-cluster distribution every single-cell tool draws beside
# its dot plot. The API has always been able to render it (``px.violin`` is in
# the plotly-express map, and the aggregation planner has a violin branch), but
# the model constant did not list it, so a template asking for one failed
# validation before it reached either.
ChartType = Literal[
    "scatter",
    "line",
    "bar",
    "box",
    "violin",
    "histogram",
    "ecdf",
    "strip",
    "area",
    "funnel",
    "density_heatmap",
    "density_contour",
    "heatmap",
]

# Aggregation functions (from card_component/utils.py AGGREGATION_MAPPING)
AggregationFunction = Literal[
    "count",
    "sum",
    "average",
    "median",
    "min",
    "max",
    "range",
    "variance",
    "std_dev",
    "skewness",
    "kurtosis",
    "percentile",
    "q1",
    "q3",
    "box_plot_stats",
    "nunique",
    "mode",
]

# Interactive component types (from interactive_component/utils.py)
InteractiveType = Literal[
    "Select",
    "MultiSelect",
    "SegmentedControl",
    "Slider",
    "RangeSlider",
    "DateRangePicker",
    "Timeline",
    "Switch",
]

# Column types for data columns
ColumnType = Literal[
    "int64",
    "float64",
    "bool",
    "datetime",
    "timedelta",
    "category",
    "object",
    "string",
]

# Figure mode (UI-based or code-based)
FigureMode = Literal["ui", "code"]

# How a metric card is drawn. Shared by a card's own `variant` and a grid
# section's `card_variant` (the style its cards take unless they set one), so
# the two can never drift apart. Mirrored by CARD_VARIANTS in
# packages/depictio-react-core/src/components/cardVariant.ts.
CardVariant = Literal["default", "headline", "compact", "minimal", "accent", "split"]

# How a figure tile is drawn. `minimal` is the landing-page look: the title in
# the card header with an icon badge and an inline subtitle, a transparent plot
# with faint dashed grid lines, the legend in one line under the plot, large
# markers. Shared by a figure's own `figure_style` and a grid section's
# `figure_style`, like CardVariant. Mirrored by FIGURE_STYLES in
# packages/depictio-react-core/src/components/figureStyle.ts and in
# depictio/api/v1/services/figure/style_presets.py.
FigureStyle = Literal["default", "minimal"]
