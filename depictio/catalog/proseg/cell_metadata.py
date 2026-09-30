"""Proseg's per-cell metadata, as sopa stores it in the sample's cell table.

With ``--use_proseg``, sopa reads Proseg's output (``proseg-output.zarr`` from
Proseg 3, ``cell-metadata.csv.gz`` before) into ``tables/table`` of the
SpatialData store, so the table's ``obs`` carries Proseg's own columns next to
sopa's (``cell_id``, ``region``, ``area``). Those are the segmentation QC
readings: the inferred ``volume`` and ``surface_area`` of each cell, the
``scale`` of its expression model and the connected ``component`` of the
transcript graph it came from. ``surface_to_volume`` is derived here: a cell
far above the run's typical ratio is thin or fragmented rather than round.

Rows are kept only for cells whose region is a Proseg boundaries element, so a
run segmented with another method raises (the template declares the DC
optional, and ingestion then skips it). Columns Proseg did not write in this
version are null.

Input: the ``sopa_cells_raw`` data collection (see ``sopa/cells``).

Output schema:
    sample : Utf8                store the cell belongs to
    cell_id : Utf8               sopa's cell id (unique within a sample)
    cell_uid : Utf8              "<sample>:<cell_id>", the run-wide key sopa/cells carries
    area : Float64               2D area of the cell polygon (microns)
    volume : Float64             Proseg's inferred cell volume
    surface_area : Float64       Proseg's inferred cell surface area
    surface_to_volume : Float64  surface_area / volume
    scale : Float64              Proseg's per-cell expression scale factor
    component : Int64            connected component of the transcript graph
    centroid_z : Float64         cell centroid depth
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "sopa_cells_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="table", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cell_id": pl.Utf8,
    "cell_uid": pl.Utf8,
    "area": pl.Float64,
    "volume": pl.Float64,
    "surface_area": pl.Float64,
    "surface_to_volume": pl.Float64,
    "scale": pl.Float64,
    "component": pl.Int64,
    "centroid_z": pl.Float64,
}

REGION_PREFIX = "proseg"


def _col(df: pl.DataFrame, name: str, dtype: type[pl.DataType]) -> pl.Expr:
    if name in df.columns:
        return pl.col(name).cast(dtype, strict=False).alias(name)
    return pl.lit(None, dtype=dtype).alias(name)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["table"]
    if df is None or df.is_empty():
        raise ValueError("proseg cell_metadata: the cell table is empty")
    if "region" in df.columns:
        df = df.filter(pl.col("region").cast(pl.Utf8).str.starts_with(REGION_PREFIX))
    if df.is_empty() or "volume" not in df.columns:
        raise ValueError("proseg cell_metadata: no Proseg-segmented cell in the table")
    cell_id = "cell_id" if "cell_id" in df.columns else "obs_id"
    out = df.select(
        pl.col("sample").cast(pl.Utf8),
        pl.col(cell_id).cast(pl.Utf8).alias("cell_id"),
        pl.concat_str("sample", pl.col(cell_id).cast(pl.Utf8), separator=":").alias("cell_uid"),
        *[_col(df, c, pl.Float64) for c in ("area", "volume", "surface_area", "scale")],
        _col(df, "component", pl.Int64),
        _col(df, "centroid_z", pl.Float64),
    ).with_columns(
        pl.when(pl.col("volume") > 0)
        .then(pl.col("surface_area") / pl.col("volume"))
        .otherwise(None)
        .alias("surface_to_volume")
    )
    return out.select(list(EXPECTED_SCHEMA)).sort("sample", "cell_id")
