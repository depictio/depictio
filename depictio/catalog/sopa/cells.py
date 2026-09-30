"""The cells of a sopa run, one row per cell, on a schema that does not move.

nf-core/sopa writes one SpatialData store per sample, ``<sample>.zarr``, whose
``tables/table`` holds one row per segmented cell. What its ``obs`` carries
depends on the run, not on the data:

* always ``cell_id``, ``region`` (the boundaries element, e.g.
  ``proseg_boundaries``), ``slide`` and ``area``, plus ``obsm['spatial']``;
* ``leiden`` only with ``--use_scanpy_preprocessing``;
* ``cell_type`` only with ``--use_fluorescence_annotation``;
* the segmentation method's own columns: Proseg adds ``volume``,
  ``surface_area``, ``scale``, ``component``..., Baysor adds ``n_transcripts``,
  ``density``, ``elongation``, its own ``cluster``....

A dashboard cannot bind to a column that exists on one run and not the next,
so this recipe folds those variants into one schema: ``cluster`` is Leiden when
it ran and the segmentation method's own clustering otherwise, ``method`` is
the boundaries element without its ``_boundaries`` suffix, and a column the run
did not produce is null rather than missing. Method-specific columns stay with
their method's catalog tool (``proseg/cell_metadata``, ``baysor/cell_metadata``).
The other table outputs of this tool read this one, under the ``sopa_cells``
data-collection tag.

Input: the ``sopa_cells_raw`` data collection, a ``format: spatialdata`` table
DC over the stores (one File per store, ``sample`` = store name without
``.zarr``), with ``x`` / ``y`` in the pixels of the image the viewer shows::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: ".+\\.zarr"}}}
      dc_specific_properties:
        format: spatialdata
        spatialdata: {table: tables/table, image: images/<morphology image>}

``area`` is in the units of the boundaries element, which are the image pixels
for the staining-based methods (Cellpose, StarDist) and microns for the
transcript-based ones (Proseg, Baysor, ComSeg). ``n_transcripts`` is only
filled when the table carries a per-cell count (Baysor's ``n_transcripts``, or
a ``total_counts`` column).

Output schema:
    sample : Utf8            store the cell belongs to
    cell_id : Utf8           sopa's cell id (instance key of the table), unique
                             within a sample only
    cell_uid : Utf8          "<sample>:<cell_id>", unique over the run: the key a
                             lasso or a table row selects cells by
    x, y : Float64           cell centroid, level-0 pixels of the image
    area : Float64           cell area (units of the boundaries element)
    method : Utf8            segmentation method (proseg, cellpose, stardist, ...)
    cluster : Utf8           Leiden cluster, else the method's cluster, else null
    cell_type : Utf8         fluorescence annotation, else null
    n_transcripts : Float64  transcripts assigned to the cell, when known
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads (see the module docstring).
RAW_DC_TAG = "sopa_cells_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="table", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cell_id": pl.Utf8,
    "cell_uid": pl.Utf8,
    "x": pl.Float64,
    "y": pl.Float64,
    "area": pl.Float64,
    "method": pl.Utf8,
    "cluster": pl.Utf8,
    "cell_type": pl.Utf8,
    "n_transcripts": pl.Float64,
}

#: obs columns holding a clustering, in order of preference.
CLUSTER_COLUMNS = ("leiden", "cluster")
#: obs columns holding a per-cell transcript count, in order of preference.
COUNT_COLUMNS = ("total_counts", "n_transcripts")


def _first(df: pl.DataFrame, names: tuple[str, ...], dtype: type[pl.DataType]) -> pl.Expr:
    present = [pl.col(n).cast(dtype, strict=False) for n in names if n in df.columns]
    return pl.coalesce(present) if present else pl.lit(None, dtype=dtype)


def cell_uid(cell_id: str) -> pl.Expr:
    """``<sample>:<cell_id>``: sopa numbers the cells of every store from the same start."""
    return pl.concat_str(pl.col("sample"), pl.col(cell_id).cast(pl.Utf8), separator=":").alias(
        "cell_uid"
    )


def normalise(df: pl.DataFrame) -> pl.DataFrame:
    """The raw table folded onto ``EXPECTED_SCHEMA``."""
    if "sample" not in df.columns:
        raise ValueError("sopa cells: the table has no 'sample' column (not a spatialdata DC?)")
    cell_id = "cell_id" if "cell_id" in df.columns else "obs_id"
    if cell_id not in df.columns:
        raise ValueError("sopa cells: the table has neither 'cell_id' nor 'obs_id'")
    method = (
        pl.col("region").cast(pl.Utf8).str.replace(r"_boundaries$", "")
        if "region" in df.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    return df.select(
        pl.col("sample").cast(pl.Utf8),
        pl.col(cell_id).cast(pl.Utf8).alias("cell_id"),
        cell_uid(cell_id),
        _first(df, ("x",), pl.Float64).alias("x"),
        _first(df, ("y",), pl.Float64).alias("y"),
        _first(df, ("area",), pl.Float64).alias("area"),
        method.fill_null("unknown").alias("method"),
        _first(df, CLUSTER_COLUMNS, pl.Utf8).alias("cluster"),
        _first(df, ("cell_type",), pl.Utf8).alias("cell_type"),
        _first(df, COUNT_COLUMNS, pl.Float64).alias("n_transcripts"),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["table"]
    if df is None or df.is_empty():
        raise ValueError("sopa cells: the cell table is empty")
    return normalise(df).sort("sample", "cell_id")
