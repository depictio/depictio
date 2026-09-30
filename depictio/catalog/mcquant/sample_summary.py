"""One row per sample and segmenter: how many cells, and how they are shaped.

The per-sample roll-up of MCQUANT's per-cell tables: the cell count each
segmentation module found in each image, and the median of every morphology
feature (area, axis lengths, eccentricity, solidity, extent) over those cells.
It is the table two segmenters are compared on (same image, different cell
counts and shapes) and the one a sample-level parallel-coordinates view reads.

``summary_id`` (``<sample>/<segmenter>``) is the row key a table selection and a
record card match on.

Output columns:
    summary_id, sample, segmenter, n_cells, median_area, median_major_axis_length,
    median_minor_axis_length, median_eccentricity, median_solidity, median_extent,
    n_markers
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.mcquant.cells import SOURCES as CELL_SOURCES
from depictio.catalog.mcquant.cells import load_cells
from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = list(CELL_SOURCES)

_FEATURES = [
    "area",
    "major_axis_length",
    "minor_axis_length",
    "eccentricity",
    "solidity",
    "extent",
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "summary_id": pl.Utf8,
    "sample": pl.Utf8,
    "segmenter": pl.Utf8,
    "n_cells": pl.Int64,
    **{f"median_{f}": pl.Float64 for f in _FEATURES},
    "n_markers": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    frame, markers = load_cells(sources["quant"])
    return (
        frame.group_by("sample", "segmenter")
        .agg(
            pl.len().cast(pl.Int64).alias("n_cells"),
            *[pl.col(f).median().cast(pl.Float64).alias(f"median_{f}") for f in _FEATURES],
        )
        .with_columns(
            pl.concat_str([pl.col("sample"), pl.col("segmenter")], separator="/").alias(
                "summary_id"
            ),
            pl.lit(len(markers), dtype=pl.Int64).alias("n_markers"),
        )
        .sort("sample", "segmenter")
        .select(*EXPECTED_SCHEMA)
    )
