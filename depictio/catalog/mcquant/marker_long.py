"""MCQUANT marker intensities melted to one row per (cell, marker).

The wide per-cell table (``mcquant/cells.py``) has one column per marker, which
is what an image overlay and a cell record want, but a distribution plot of one
marker across samples, or of every marker side by side, needs the marker as a
value. This recipe melts the marker columns and adds ``log_intensity``
(log1p of the mean intensity), the scale marker distributions are read on.

A whole-slide run quantifies hundreds of thousands of cells per sample, so the
long table would be the cell count times the panel size. The ``max_cells``
param (default 5000) caps the cells melted per sample and segmenter: when a
sample has more, every k-th cell in ``CellID`` order is kept (a deterministic
stride, not a random draw, so a re-ingest gives the same rows). The per-cell
table keeps every cell; this one is for distributions only.

``marker_type`` is ``nuclear`` for the nuclear stains (``DNA``, ``DAPI``,
``Hoechst`` prefixes) and ``marker`` otherwise, so the stains that every cell
carries can be set aside with one filter. The optional ``segmenter`` param keeps
one segmentation module, as in ``mcquant/cells.py``.

Output columns:
    sample, segmenter, cell_id, cell_uid, marker, marker_type, intensity,
    log_intensity
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.mcquant.cells import SOURCES as CELL_SOURCES
from depictio.catalog.mcquant.cells import is_nuclear, load_cells
from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = list(CELL_SOURCES)

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "segmenter": pl.Utf8,
    "cell_id": pl.Int64,
    "cell_uid": pl.Utf8,
    "marker": pl.Utf8,
    "marker_type": pl.Utf8,
    "intensity": pl.Float64,
    "log_intensity": pl.Float64,
}

DEFAULT_MAX_CELLS = 5000


def _max_cells(params: dict[str, str] | None) -> int:
    raw = ((params or {}).get("max_cells") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_CELLS
    except ValueError:
        value = DEFAULT_MAX_CELLS
    return max(value, 1)


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    segmenter = ((params or {}).get("segmenter") or "").strip() or None
    frame, markers = load_cells(sources["quant"], segmenter)
    if frame.is_empty() or not markers:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    cap = _max_cells(params)
    # Stride per (sample, segmenter): ceil(n / cap), 1 when the sample fits.
    frame = (
        frame.with_columns(
            pl.int_range(pl.len()).over("sample", "segmenter").alias("_rank"),
            ((pl.len().over("sample", "segmenter") + cap - 1) // cap).alias("_stride"),
        )
        .filter(pl.col("_rank") % pl.col("_stride") == 0)
        .drop("_rank", "_stride")
    )
    long = frame.unpivot(
        on=markers,
        index=["sample", "segmenter", "cell_id", "cell_uid"],
        variable_name="marker",
        value_name="intensity",
    )
    nuclear = {m: ("nuclear" if is_nuclear(m) else "marker") for m in markers}
    return long.with_columns(
        pl.col("marker").replace_strict(nuclear, return_dtype=pl.Utf8).alias("marker_type"),
        pl.col("intensity").cast(pl.Float64),
        pl.col("intensity").cast(pl.Float64).clip(lower_bound=0.0).log1p().alias("log_intensity"),
    ).select(*EXPECTED_SCHEMA)
