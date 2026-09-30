"""Per-cell expression of a chosen gene list, long: one row per (cell, gene).

A spatial panel holds hundreds of genes (a Visium HD run, the whole
transcriptome), far too many to carry one column each for every cell, and no
gene is a sensible default across tissues and technologies. The genes are
therefore chosen by the run: a template passes them as the ``genes`` param (a
comma-separated list, e.g. from a ``GENES`` variable) and reads the same list
out of the store with a second ``format: spatialdata`` DC whose
``spatialdata.genes`` names them. Values come from the table's ``X``, which is
log-normalised when ``--use_scanpy_preprocessing`` ran and raw counts
otherwise.

Each cell's cluster and cell type are joined from the normalised cell table,
so the distributions split by cluster and follow the dashboard's cell filters.

Inputs:
    ``sopa_cell_genes_raw``  spatialdata table DC with ``spatialdata.genes`` set
    ``sopa_cells``           the ``sopa/cells`` output (cluster, cell type)

Output schema:
    sample : Utf8          store the cell belongs to
    cell_id : Utf8         sopa's cell id (unique within a sample)
    cell_uid : Utf8        "<sample>:<cell_id>", the run-wide key sopa/cells carries
    cluster : Utf8         cluster of the cell (null when none was computed)
    cell_type : Utf8       cell type of the cell (null when not annotated)
    gene : Utf8            gene name, as in the table's var names
    expression : Float64   value in X for that cell and gene
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag of the gene-bearing spatialdata table DC.
RAW_DC_TAG = "sopa_cell_genes_raw"
CELLS_DC_TAG = "sopa_cells"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="genes", dc_ref=RAW_DC_TAG),
    RecipeSource(ref="cells", dc_ref=CELLS_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cell_id": pl.Utf8,
    "cell_uid": pl.Utf8,
    "cluster": pl.Utf8,
    "cell_type": pl.Utf8,
    "gene": pl.Utf8,
    "expression": pl.Float64,
}


def gene_list(params: dict[str, str] | None) -> list[str]:
    raw = (params or {}).get("genes") or ""
    return [g.strip() for g in raw.split(",") if g.strip()]


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    table = sources["genes"]
    if table is None or table.is_empty():
        raise ValueError("sopa gene_expression: the gene table is empty")
    genes = [g for g in gene_list(params) if g in table.columns]
    if not genes:
        raise ValueError(
            "sopa gene_expression: none of the requested genes is a column of the table "
            f"(params genes={(params or {}).get('genes')!r})"
        )
    cell_id = "cell_id" if "cell_id" in table.columns else "obs_id"
    long = table.select(
        pl.col("sample").cast(pl.Utf8),
        pl.col(cell_id).cast(pl.Utf8).alias("cell_id"),
        *[pl.col(g).cast(pl.Float64) for g in genes],
    ).unpivot(index=["sample", "cell_id"], variable_name="gene", value_name="expression")
    long = long.with_columns(pl.concat_str("sample", "cell_id", separator=":").alias("cell_uid"))
    cells = sources.get("cells")
    if cells is not None and not cells.is_empty():
        long = long.join(
            cells.select("sample", "cell_id", "cluster", "cell_type"),
            on=["sample", "cell_id"],
            how="left",
        )
    else:
        long = long.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("cluster"),
            pl.lit(None, dtype=pl.Utf8).alias("cell_type"),
        )
    return long.select(list(EXPECTED_SCHEMA)).sort("gene", "sample", "cell_id")
