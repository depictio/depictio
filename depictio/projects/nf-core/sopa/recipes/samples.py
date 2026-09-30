"""Sample hub of a sopa run: one row per sample, with its design and cell yield.

nf-core/sopa names every output after the sample (``<sample>.zarr``,
``<sample>.explorer/``) and publishes no sample sheet of its own, so the hub is
built from what the run did write: the samples of the segmented cell table
(``sopa_cells``), each with its cell count, median cell area, transcripts per
cell when the table carries them, the number of clusters and the segmentation
method.

The design comes from an optional table declared through ``METADATA_FILE`` (the
ampliseq convention): sample id in ``METADATA_ID_COL`` (else a column named
``sample``, else the first column), every other column a factor. ``condition``
is its ``GROUP_COL`` factor (the ``group_col`` param; the first factor when it
is unset or not a column of the table) and every other factor is carried as an
extra column under its own name. Without a design table ``condition`` reads
``unspecified``: a run is never split by anything parsed out of a sample name.

Output schema:
    sample : Utf8                store name without ``.zarr``, the key every
                                 per-sample and per-cell collection is linked on
    condition : Utf8             GROUP_COL of the design table, else "unspecified"
    n_cells : Int64              segmented cells kept by the aggregation filters
    median_area : Float64        median cell area (units of the boundaries)
    median_transcripts : Float64 median transcripts per cell, when known
    n_clusters : Int64           distinct clusters among the sample's cells
    method : Utf8                segmentation method(s), comma-joined
    <design columns> : Utf8      every other factor of METADATA_FILE, when given
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="cells", dc_ref="sopa_cells"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "n_cells": pl.Int64,
    "median_area": pl.Float64,
    "median_transcripts": pl.Float64,
    "n_clusters": pl.Int64,
    "method": pl.Utf8,
}
# Extra design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: ``GROUP_COL`` value the CLI sets when the run declares no group column.
NO_GROUP_SENTINEL = "__no_group__"
UNSPECIFIED = "unspecified"


def _param(params: dict[str, str] | None, key: str) -> str | None:
    value = ((params or {}).get(key) or "").strip()
    return value if value and value != NO_GROUP_SENTINEL else None


def _design(
    metadata: pl.DataFrame | None, id_col: str | None, group_col: str | None
) -> tuple[pl.DataFrame, list[str]] | None:
    """The design table keyed on ``sample``, with ``condition`` and the extra factors."""
    if metadata is None or metadata.is_empty() or metadata.width < 2:
        return None
    if id_col not in metadata.columns:
        id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    factors = [c for c in metadata.columns if c not in (id_col, "source_path")]
    if not factors:
        return None
    condition_col = group_col if group_col in factors else factors[0]
    extras = [c for c in factors if c != condition_col and c not in EXPECTED_SCHEMA]
    table = metadata.select(
        pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("sample"),
        pl.col(condition_col).cast(pl.Utf8).alias("condition"),
        *[pl.col(c).cast(pl.Utf8) for c in extras],
    ).unique(subset="sample", keep="first", maintain_order=True)
    return table, extras


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    cells = sources["cells"]
    if cells is None or cells.is_empty():
        raise ValueError("sopa samples: the cell table is empty")
    hub = cells.group_by("sample").agg(
        pl.len().cast(pl.Int64).alias("n_cells"),
        pl.col("area").median().cast(pl.Float64).alias("median_area"),
        pl.col("n_transcripts").median().cast(pl.Float64).alias("median_transcripts"),
        pl.col("cluster").drop_nulls().n_unique().cast(pl.Int64).alias("n_clusters"),
        pl.col("method").drop_nulls().unique().sort().str.join(",").alias("method"),
    )
    extras: list[str] = []
    design = _design(sources.get("metadata"), _param(params, "id_col"), _param(params, "group_col"))
    if design is None:
        hub = hub.with_columns(pl.lit(UNSPECIFIED).alias("condition"))
    else:
        table, extras = design
        hub = hub.join(table, on="sample", how="left").with_columns(
            pl.col("condition").fill_null(UNSPECIFIED)
        )
    return hub.select([*EXPECTED_SCHEMA, *extras]).sort("condition", "sample")
