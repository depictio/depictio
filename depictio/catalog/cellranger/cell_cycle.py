"""Cell-cycle phase per cell, from the Tirosh S and G2/M gene sets.

Cell Ranger publishes no cell-cycle call, and a cluster that is really "the same
cell type, cycling" is one of the two readings a scRNA-seq reviewer asks for
after QC (the other is doublets, which needs a tool this pipeline does not run).
The scores here are the Seurat / Scanpy convention, simplified in one documented
way: a phase score is the mean log1p(CP10k) expression of the set's genes minus
the cell's mean over all measured genes, rather than minus the mean of expression-
matched control bins. The control-bin refinement changes the absolute scores, not
which of the two sets wins, which is what `phase` reports and what the dashboard
shows.

    s_score   = mean(expression over the S set)   - background
    g2m_score = mean(expression over the G2M set) - background
    background = the cell's mean log1p(CP10k) over EVERY feature of the reference
    phase     = "S" / "G2M" for the larger of the two when it is positive,
                "G1" when neither is

All three means count a gene the cell did not detect as 0 and divide by the
size of the set, never by the number of genes that happened to be detected.
Mixing the two conventions (a set mean over the whole set against a background
over the detected genes only) subtracts a number about ten times larger than
the one it corrects and calls every cell G1.

The matrix is read as the same streaming MatrixMarket triplet scan the rest of
the module uses, filtered to the cycle genes before anything is aggregated.

A template reusing this recipe declares four sources, all already shared by
`dc_ref` with `cellranger/cell_qc.py`::

    SOURCES = [
        RecipeSource(ref="matrix", dc_ref="cellranger_filtered_matrix_raw"),
        RecipeSource(ref="features", dc_ref="cellranger_filtered_features_raw"),
        RecipeSource(ref="barcode_index", dc_ref="cellranger_filtered_barcode_index_raw"),
        RecipeSource(ref="cell_qc", dc_ref="cellranger_cell_qc"),
    ]

Output schema:
    sample : Utf8
    barcode : Utf8           10x cell barcode, joins the cell hub
    cluster_label : Utf8      "C<n> top1/top2" graph-based cluster
    s_score : Float64          S-phase score
    g2m_score : Float64        G2/M score
    phase : Utf8               "G1" | "S" | "G2M"
    n_s_genes : Int64          S genes of the set this reference actually carries
    n_g2m_genes : Int64        G2/M genes of the set this reference actually carries
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cellranger_samples import with_sample_column
from depictio.recipes.lib.scrnaseq_panels import TIROSH_G2M_GENES, TIROSH_S_GENES

MATRIX_DC_TAG = "cellranger_filtered_matrix_raw"
FEATURES_DC_TAG = "cellranger_filtered_features_raw"
BARCODE_INDEX_DC_TAG = "cellranger_filtered_barcode_index_raw"
CELL_QC_DC_TAG = "cellranger_cell_qc"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="matrix", dc_ref=MATRIX_DC_TAG),
    RecipeSource(ref="features", dc_ref=FEATURES_DC_TAG),
    RecipeSource(ref="barcode_index", dc_ref=BARCODE_INDEX_DC_TAG),
    RecipeSource(ref="cell_qc", dc_ref=CELL_QC_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcode": pl.Utf8,
    "cluster_label": pl.Utf8,
    "s_score": pl.Float64,
    "g2m_score": pl.Float64,
    "phase": pl.Utf8,
    "n_s_genes": pl.Int64,
    "n_g2m_genes": pl.Int64,
}

_MATRIX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_FEATURES_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"
_BARCODE_INDEX_SAMPLE_RE = r"cellranger/count/([^/]+)/outs/filtered_feature_bc_matrix/"

_CP10K = 1e4

#: fewest genes of a set a reference must carry before the score is trusted;
#: below it the score is still emitted (the column has to exist) but every cell
#: lands in G1, which the dashboard text says to read as "not scored".
MIN_SET_GENES = 5


def _with_sample(df: pl.DataFrame, pattern: str, dc_name: str) -> pl.DataFrame:
    return with_sample_column(df, pattern, dc_name, "cellranger_cell_cycle")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    matrix = _with_sample(sources["matrix"], _MATRIX_SAMPLE_RE, "matrix")
    features = _with_sample(sources["features"], _FEATURES_SAMPLE_RE, "features")
    barcode_index = _with_sample(
        sources["barcode_index"], _BARCODE_INDEX_SAMPLE_RE, "barcode_index"
    )
    cell_qc = sources["cell_qc"]

    if missing := {"sample", "barcode", "cluster_label"} - set(cell_qc.columns):
        raise ValueError(f"cellranger_cell_cycle: cell_qc lacks columns {sorted(missing)}")

    s_set = set(TIROSH_S_GENES)
    g2m_set = set(TIROSH_G2M_GENES)
    gene_flags = features.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("feature_name").cast(pl.Utf8).alias("gene"),
    ).with_columns(
        pl.col("gene").is_in(s_set).alias("_is_s"),
        pl.col("gene").is_in(g2m_set).alias("_is_g2m"),
    )
    n_s = gene_flags.filter(pl.col("_is_s")).select("gene").unique().height
    n_g2m = gene_flags.filter(pl.col("_is_g2m")).select("gene").unique().height

    typed = matrix.select(
        "sample",
        pl.col("gene_idx").cast(pl.Int64),
        pl.col("barcode_idx").cast(pl.Int64),
        pl.col("count").cast(pl.Int64, strict=False),
    )
    per_cell_umi = typed.group_by(["sample", "barcode_idx"]).agg(
        pl.col("count").sum().alias("_n_umi")
    )
    normalised = typed.join(per_cell_umi, on=["sample", "barcode_idx"], how="inner").with_columns(
        (pl.col("count") / pl.col("_n_umi") * _CP10K).log1p().alias("_expression")
    )

    # Background: the cell's mean expression over EVERY feature of the
    # reference, undetected ones counted as 0, which is the convention the two
    # set means below use.
    n_features = features.group_by("sample").agg(
        pl.col("gene_idx").n_unique().cast(pl.Float64).alias("_n_features")
    )
    background = (
        normalised.group_by(["sample", "barcode_idx"])
        .agg(pl.col("_expression").sum().alias("_expression_sum"))
        .join(n_features, on="sample", how="left")
        .with_columns((pl.col("_expression_sum") / pl.col("_n_features")).alias("_background"))
        .select("sample", "barcode_idx", "_background")
    )

    cycle = normalised.join(
        gene_flags.filter(pl.col("_is_s") | pl.col("_is_g2m")),
        on=["sample", "gene_idx"],
        how="inner",
    )
    scores = cycle.group_by(["sample", "barcode_idx"]).agg(
        (pl.col("_expression") * pl.col("_is_s").cast(pl.Float64)).sum().alias("_s_sum"),
        (pl.col("_expression") * pl.col("_is_g2m").cast(pl.Float64)).sum().alias("_g2m_sum"),
    )

    bc_lookup = barcode_index.select(
        "sample", pl.col("barcode_idx").cast(pl.Int64), pl.col("barcode").cast(pl.Utf8)
    )
    cells = cell_qc.select("sample", "barcode", "cluster_label").join(
        bc_lookup, on=["sample", "barcode"], how="inner"
    )
    cells = (
        cells.join(scores, on=["sample", "barcode_idx"], how="left")
        .join(background, on=["sample", "barcode_idx"], how="left")
        .with_columns(
            pl.col("_s_sum").fill_null(0.0),
            pl.col("_g2m_sum").fill_null(0.0),
            pl.col("_background").fill_null(0.0),
        )
    )

    s_divisor = float(max(n_s, 1))
    g2m_divisor = float(max(n_g2m, 1))
    scored = cells.with_columns(
        (pl.col("_s_sum") / s_divisor - pl.col("_background")).alias("s_score"),
        (pl.col("_g2m_sum") / g2m_divisor - pl.col("_background")).alias("g2m_score"),
    )
    usable = n_s >= MIN_SET_GENES and n_g2m >= MIN_SET_GENES
    scored = scored.with_columns(
        pl.when(pl.lit(not usable))
        .then(pl.lit("G1"))
        .when((pl.col("s_score") <= 0) & (pl.col("g2m_score") <= 0))
        .then(pl.lit("G1"))
        .when(pl.col("g2m_score") >= pl.col("s_score"))
        .then(pl.lit("G2M"))
        .otherwise(pl.lit("S"))
        .alias("phase"),
        pl.lit(n_s, dtype=pl.Int64).alias("n_s_genes"),
        pl.lit(n_g2m, dtype=pl.Int64).alias("n_g2m_genes"),
    )

    return scored.select(list(EXPECTED_SCHEMA)).sort(["sample", "barcode"])
