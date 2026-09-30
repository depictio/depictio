"""Marker by sample matrix of median log1p intensity, for a heatmap.

One row per marker of the panel, one Float64 column per sample holding the
median over that sample's cells of log1p(mean intensity), from MCQUANT's
per-cell tables. It is the at-a-glance answer to "which marker is bright in
which sample" that a per-cell table cannot give without aggregation.

The sample columns are named by the run's samples, so only ``marker`` and
``marker_type`` are fixed. The optional ``segmenter`` param keeps one
segmentation module (a cell is only counted once per mask); without it every
segmenter's cells are pooled.

Output columns:
    marker, marker_type, <one Float64 column per sample>
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.mcquant.cells import SOURCES as CELL_SOURCES
from depictio.catalog.mcquant.cells import is_nuclear, load_cells
from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = list(CELL_SOURCES)

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "marker": pl.Utf8,
    "marker_type": pl.Utf8,
}
# One column per sample; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    segmenter = ((params or {}).get("segmenter") or "").strip() or None
    frame, markers = load_cells(sources["quant"], segmenter)
    if frame.is_empty() or not markers:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    medians = frame.group_by("sample").agg(
        pl.col(m).fill_null(0.0).clip(lower_bound=0.0).log1p().median().alias(m) for m in markers
    )
    samples = sorted(medians.get_column("sample").to_list())
    wide = (
        medians.unpivot(on=markers, index="sample", variable_name="marker")
        .pivot(on="sample", index="marker", values="value")
        .select("marker", *samples)
    )
    order = {m: i for i, m in enumerate(markers)}
    return (
        wide.with_columns(
            pl.col("marker")
            .replace_strict({m: ("nuclear" if is_nuclear(m) else "marker") for m in markers})
            .alias("marker_type"),
            pl.col("marker").replace_strict(order, return_dtype=pl.Int64).alias("_order"),
            *[pl.col(s).cast(pl.Float64) for s in samples],
        )
        .sort("_order")
        .select("marker", "marker_type", *samples)
    )
