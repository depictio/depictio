"""The curated half of `cellranger_cell_expression`, melted: one row per
(cell, gene), so a violin or a box can show the whole per-cell distribution of
one marker across clusters instead of the cluster mean a dot plot draws.

Two caps keep it a frame a plot can draw. Only the `CURATED_PBMC_PANEL` columns
are kept (the wide table's full panel is ~120 genes and melting all of it would
be ~1 M rows for a single sample), and at most `MAX_CELLS_PER_CLUSTER` cells of
each cluster are carried. Both matter because `box` is not in the figure
service's samplable plot types (`figure_builder._SAMPLABLE_PLOT_TYPES`): every
row it is handed is serialised into the trace, so the cap has to live here.

The cell cap is the first `MAX_CELLS_PER_CLUSTER` barcodes of the cluster in
barcode order, which is deterministic and, since a 10x barcode is a random
16-mer, independent of anything the plot shows. The wide table keeps every
cell; this one is for the shape of a distribution, not for counting.

Source: the already-transformed wide table (`dc_ref`), so nothing is re-read
from the matrix.

Output schema:
    sample : Utf8
    barcode : Utf8           10x cell barcode
    cluster_label : Utf8      "C<n> top1/top2" graph-based cluster
    qc_status : Utf8          pass | flagged
    gene : Utf8               marker gene symbol, the column to filter on
    expression : Float64      log1p(CP10k) for that (cell, gene); 0 when undetected
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.scrnaseq_panels import CURATED_PBMC_PANEL

CELL_EXPRESSION_DC_TAG = "cellranger_cell_expression"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="wide", dc_ref=CELL_EXPRESSION_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "barcode": pl.Utf8,
    "cluster_label": pl.Utf8,
    "qc_status": pl.Utf8,
    "gene": pl.Utf8,
    "expression": pl.Float64,
}

_INDEX_COLUMNS = ["sample", "barcode", "cluster_label", "qc_status"]

#: cells kept per (sample, cluster) before the melt, see the module docstring
MAX_CELLS_PER_CLUSTER = 150


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    wide = sources["wide"]
    if missing := set(_INDEX_COLUMNS) - set(wide.columns):
        raise ValueError(f"cellranger_cell_expression_long: input lacks {sorted(missing)}")

    genes = [gene for gene in CURATED_PBMC_PANEL if gene in wide.columns]
    if not genes:
        raise ValueError(
            "cellranger_cell_expression_long: none of the curated panel genes is a "
            "column of cellranger_cell_expression (a non-human reference?)"
        )

    wide = (
        wide.sort(["sample", "cluster_label", "barcode"])
        .with_columns(
            pl.int_range(pl.len()).over(["sample", "cluster_label"]).alias("_rank_in_cluster")
        )
        .filter(pl.col("_rank_in_cluster") < MAX_CELLS_PER_CLUSTER)
    )

    long = wide.select([*_INDEX_COLUMNS, *genes]).unpivot(
        on=genes,
        index=_INDEX_COLUMNS,
        variable_name="gene",
        value_name="expression",
    )
    long = long.with_columns(
        pl.col("gene").cast(pl.Utf8),
        pl.col("expression").cast(pl.Float64),
    )
    return long.select(list(EXPECTED_SCHEMA)).sort(["sample", "gene", "barcode"])
