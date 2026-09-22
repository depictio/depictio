"""One row per called cell, one column per panel gene: the table that turns the
dashboard into a gene browser.

Everything else this module ships aggregates expression before it reaches the
reader (a dot plot is per cluster, a heatmap is per cluster). That answers "what
marks cluster 7" and never answers "where is CD3D on this UMAP", which is the
first question anyone opens a single-cell app with. This output is the wide
`cell x gene` matrix that answers it: the embedding renderer's Colour-by menu
lists every column of the bound data collection, so shipping ~120 gene columns
next to the UMAP coordinates gives a gene picker for free, with no new renderer
and no new dependency.

The panel is the union of three sources, deliberately: what the run itself found
(top `TOP_MARKERS_PER_CLUSTER` genes of every graph-based cluster), what a reader
of a PBMC run will look for whether or not the clustering surfaced it
(`CURATED_PBMC_PANEL`), and what varies most across cells regardless of the
clustering (the top `TOP_DISPERSION_GENES` by Cell Ranger's own normalised
dispersion). Capped at `MAX_PANEL_GENES` columns, because the width is what the
reader pays for: 8 767 cells x 120 Float64 columns is roughly 8 MB.

Values are log1p(CP10k): the count is divided by the cell's total UMI count,
scaled to 10 000, and log1p-ed, the normalisation every single-cell app plots.
A gene with no UMI in a cell is 0, not null, so the colour scale has a floor
rather than a hole.

The matrix is never densified: it is read as a streaming MatrixMarket triplet
scan (the pattern `cellranger/cell_qc.py` documents), filtered down to the panel
gene rows first, and only then pivoted.

A template reusing this recipe declares six sources, all already shared by
`dc_ref` with `cellranger/cell_qc.py`, `cellranger/diffexp.py` and
`cellranger/hvg_dispersion.py`::

    SOURCES = [
        RecipeSource(ref="diffexp", dc_ref="cellranger_diffexp"),
        RecipeSource(ref="dispersion", dc_ref="cellranger_dispersion_raw", optional=True),
        RecipeSource(ref="matrix", dc_ref="cellranger_filtered_matrix_raw"),
        RecipeSource(ref="features", dc_ref="cellranger_filtered_features_raw"),
        RecipeSource(ref="barcode_index", dc_ref="cellranger_filtered_barcode_index_raw"),
        RecipeSource(ref="cell_qc", dc_ref="cellranger_cell_qc"),
    ]

Output schema: the six fixed columns below, then one Float64 column per panel
gene (names are data-dependent, so they are not in `EXPECTED_SCHEMA`; the
`group_compare` kind infers its feature columns the same way `complex_heatmap`
infers its matrix, and `umap_1` / `umap_2` are numeric columns of the same
frame, see the note in VALIDATION_REPORT.md).

    sample : Utf8          sample the cell was sequenced in
    barcode : Utf8          10x cell barcode, the row id (`group_compare`'s index)
    cluster_label : Utf8    "C<n> top1/top2" graph-based cluster, the grouping column
    qc_status : Utf8        pass | flagged, from the cell hub's MAD rules
    umap_1 : Float64        first UMAP dimension, so one tile is both the embedding
    umap_2 : Float64        and the gene picker
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cellranger_samples import with_sample_column
from depictio.recipes.lib.scrnaseq_panels import CURATED_PBMC_PANEL

DIFFEXP_DC_TAG = "cellranger_diffexp"
DISPERSION_DC_TAG = "cellranger_dispersion_raw"
MATRIX_DC_TAG = "cellranger_filtered_matrix_raw"
FEATURES_DC_TAG = "cellranger_filtered_features_raw"
BARCODE_INDEX_DC_TAG = "cellranger_filtered_barcode_index_raw"
CELL_QC_DC_TAG = "cellranger_cell_qc"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="diffexp", dc_ref=DIFFEXP_DC_TAG),
    RecipeSource(ref="dispersion", dc_ref=DISPERSION_DC_TAG, optional=True),
    RecipeSource(ref="matrix", dc_ref=MATRIX_DC_TAG),
    RecipeSource(ref="features", dc_ref=FEATURES_DC_TAG),
    RecipeSource(ref="barcode_index", dc_ref=BARCODE_INDEX_DC_TAG),
    RecipeSource(ref="cell_qc", dc_ref=CELL_QC_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcode": pl.Utf8,
    "cluster_label": pl.Utf8,
    "qc_status": pl.Utf8,
    "umap_1": pl.Float64,
    "umap_2": pl.Float64,
}

#: markers per graph-based cluster contributed to the panel
TOP_MARKERS_PER_CLUSTER = 5
#: highest-dispersion genes contributed to the panel
TOP_DISPERSION_GENES = 30
#: hard cap on the gene columns, the width the reader pays for
MAX_PANEL_GENES = 150

#: the clustering the panel's marker half comes from (see `cellranger/diffexp.py`)
GRAPHCLUST_RESOLUTION = "graphclust"

_MATRIX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_FEATURES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_BARCODE_INDEX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"

_CP10K = 1e4


def _with_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> pl.DataFrame:
    return with_sample_column(df, pattern, dc_name, "cellranger_cell_expression")


def panel_genes(
    diffexp: pl.DataFrame,
    dispersion: pl.DataFrame | None,
    available: set[str],
) -> list[str]:
    """Markers, then the curated panel, then the most dispersed genes, deduplicated.

    Ordered by provenance rather than alphabetically so the cap, when it bites,
    drops the dispersion tail first: the run's own markers and the panel a reader
    types by hand are what the tile is for.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def _take(names) -> None:
        for name in names:
            if name and name in available and name not in seen:
                seen.add(name)
                ordered.append(name)

    markers = diffexp
    if "resolution" in markers.columns:
        markers = markers.filter(pl.col("resolution") == GRAPHCLUST_RESOLUTION)
    markers = markers.filter(pl.col("rank_in_cluster") <= TOP_MARKERS_PER_CLUSTER)
    _take(markers.sort(["cluster", "rank_in_cluster"])["gene"].to_list())
    _take(CURATED_PBMC_PANEL)

    if dispersion is not None and dispersion.height:
        cols = set(dispersion.columns)
        gene_col = "Feature" if "Feature" in cols else None
        disp_col = "Normalized.Dispersion" if "Normalized.Dispersion" in cols else None
        if gene_col and disp_col:
            top = (
                dispersion.select(
                    pl.col(gene_col).cast(pl.Utf8).alias("gene"),
                    pl.col(disp_col).cast(pl.Float64, strict=False).alias("dispersion"),
                )
                .drop_nulls()
                .sort("dispersion", descending=True)
                .head(TOP_DISPERSION_GENES)
            )
            _take(top["gene"].to_list())

    return ordered[:MAX_PANEL_GENES]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    diffexp = sources["diffexp"]
    dispersion = sources.get("dispersion")
    matrix = _with_sample(sources["matrix"], _MATRIX_SAMPLE_RE, "matrix")
    features = _with_sample(sources["features"], _FEATURES_SAMPLE_RE, "features")
    barcode_index = _with_sample(
        sources["barcode_index"], _BARCODE_INDEX_SAMPLE_RE, "barcode_index"
    )
    cell_qc = sources["cell_qc"]

    required_cell_qc = {"sample", "barcode", "cluster_label", "qc_status", "n_umi"}
    if missing := required_cell_qc - set(cell_qc.columns):
        raise ValueError(f"cellranger_cell_expression: cell_qc lacks columns {sorted(missing)}")
    if "gene" not in diffexp.columns or "rank_in_cluster" not in diffexp.columns:
        raise ValueError("cellranger_cell_expression: diffexp lacks 'gene' / 'rank_in_cluster'")

    feature_names = set(features["feature_name"].cast(pl.Utf8).drop_nulls().to_list())
    # A gene symbol that collides with one of the fixed columns would shadow it.
    feature_names -= set(EXPECTED_SCHEMA)
    genes = panel_genes(diffexp, dispersion, feature_names)
    if not genes:
        raise ValueError("cellranger_cell_expression: the gene panel is empty")

    # gene_idx of the panel genes only: an `is_in` on the 30k-row feature list,
    # so the 17M-row matrix scan below is an inner join on a tiny key set.
    panel_idx = features.filter(pl.col("feature_name").is_in(genes)).select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("feature_name").cast(pl.Utf8).alias("gene"),
    )
    # A symbol may appear on several feature rows (10x does not force unique
    # names); keep every row and sum them per (cell, gene) below.

    matrix_typed = matrix.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("barcode_idx").cast(pl.Int64),
        pl.col("count").cast(pl.Int64, strict=False),
    )
    panel_counts = matrix_typed.join(panel_idx, on=["sample", "gene_idx"], how="inner")

    bc_lookup = barcode_index.select(
        "sample", pl.col("barcode_idx").cast(pl.Int64), pl.col("barcode").cast(pl.Utf8)
    )
    panel_counts = panel_counts.join(bc_lookup, on=["sample", "barcode_idx"], how="inner")

    cell_meta = cell_qc.select("sample", "barcode", "cluster_label", "qc_status", "n_umi")
    panel_counts = panel_counts.join(cell_meta, on=["sample", "barcode"], how="inner")

    per_cell_gene = panel_counts.group_by(["sample", "barcode", "gene"]).agg(
        pl.col("count").sum().alias("_count"),
        pl.col("n_umi").first().alias("_n_umi"),
    )
    per_cell_gene = per_cell_gene.with_columns(
        (pl.col("_count") / pl.col("_n_umi") * _CP10K).log1p().alias("_expression")
    )

    wide = per_cell_gene.pivot(
        on="gene", index=["sample", "barcode"], values="_expression", aggregate_function="sum"
    )

    # Every cell of the hub, including the ones with no panel-gene UMI at all,
    # and 0 rather than null wherever a gene was not detected.
    cells = cell_qc.select("sample", "barcode", "cluster_label", "qc_status", "umap_1", "umap_2")
    result = cells.join(wide, on=["sample", "barcode"], how="left")
    present = [g for g in genes if g in result.columns]
    result = result.with_columns(
        [pl.col(g).cast(pl.Float64).fill_null(0.0).alias(g) for g in present]
    )
    for gene in genes:
        if gene not in result.columns:
            result = result.with_columns(pl.lit(0.0, dtype=pl.Float64).alias(gene))

    return result.select([*EXPECTED_SCHEMA, *genes]).sort(["sample", "barcode"])
