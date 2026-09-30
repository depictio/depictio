"""Baysor's per-cell statistics, as sopa stores them in the sample's cell table.

With ``--use_baysor``, sopa reads each patch's ``segmentation_counts.loom``
into ``tables/table`` of the SpatialData store: the table's ``obs`` then
carries Baysor's cell statistics next to sopa's columns (Baysor's own ``area``
renamed ``baysor_area``). The segmentation QC readings are the transcripts per
cell, their density, the cell's elongation, and the two confidences: how sure
Baysor is that the cell's molecules are real (``avg_confidence``) and that they
belong to this cell (``avg_assignment_confidence``). Baysor also clusters the
molecules by local gene composition (``cluster``, ``max_cluster_frac``).

Rows are kept only for cells whose region is a Baysor boundaries element, so a
run segmented with another method raises (the template declares the DC
optional, and ingestion then skips it). Columns absent from the run are null.

Input: the ``sopa_cells_raw`` data collection (see ``sopa/cells``).

Output schema:
    sample : Utf8                        store the cell belongs to
    cell_id : Utf8                       sopa's cell id (unique within a sample)
    cell_uid : Utf8                      "<sample>:<cell_id>", the key sopa/cells carries
    n_transcripts : Float64              molecules assigned to the cell
    density : Float64                    molecules per unit area
    elongation : Float64                 elongation of the cell shape
    baysor_area : Float64                area as Baysor computed it
    avg_confidence : Float64             mean molecule confidence (0-1)
    avg_assignment_confidence : Float64  mean assignment confidence (0-1)
    max_cluster_frac : Float64           share of the cell's molecules in its main cluster
    lifespan : Float64                   Baysor's cell lifespan (iterations it survived)
    cluster : Utf8                       Baysor's molecule cluster of the cell
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "sopa_cells_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="table", dc_ref=RAW_DC_TAG)]

NUMERIC = (
    "n_transcripts",
    "density",
    "elongation",
    "baysor_area",
    "avg_confidence",
    "avg_assignment_confidence",
    "max_cluster_frac",
    "lifespan",
)

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cell_id": pl.Utf8,
    "cell_uid": pl.Utf8,
    **{c: pl.Float64 for c in NUMERIC},
    "cluster": pl.Utf8,
}

REGION_PREFIX = "baysor"


def _col(df: pl.DataFrame, name: str, dtype: type[pl.DataType]) -> pl.Expr:
    if name in df.columns:
        return pl.col(name).cast(dtype, strict=False).alias(name)
    return pl.lit(None, dtype=dtype).alias(name)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["table"]
    if df is None or df.is_empty():
        raise ValueError("baysor cell_metadata: the cell table is empty")
    if "region" in df.columns:
        df = df.filter(pl.col("region").cast(pl.Utf8).str.starts_with(REGION_PREFIX))
    if df.is_empty() or "n_transcripts" not in df.columns:
        raise ValueError("baysor cell_metadata: no Baysor-segmented cell in the table")
    cell_id = "cell_id" if "cell_id" in df.columns else "obs_id"
    return (
        df.select(
            pl.col("sample").cast(pl.Utf8),
            pl.col(cell_id).cast(pl.Utf8).alias("cell_id"),
            pl.concat_str("sample", pl.col(cell_id).cast(pl.Utf8), separator=":").alias("cell_uid"),
            *[_col(df, c, pl.Float64) for c in NUMERIC],
            _col(df, "cluster", pl.Utf8),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort("sample", "cell_id")
    )
