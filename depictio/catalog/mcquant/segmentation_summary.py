"""Cells and their sizes per image and segmenter (MCQUANT).

One row per image (``sample``) and segmentation method: how many cells the mask
holds, and the median, quartiles and mean of their area, with the medians of the
shape measures (major axis, eccentricity, solidity, aspect ratio). Two
segmenters on one image are two rows, which is how a run that segments with
both Mesmer and Cellpose compares them.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mcquant import load_cells

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="mcquant",
        input_schema={
            "source_path": pl.Utf8,
            "CellID": pl.Int64,
            "X_centroid": pl.Float64,
            "Y_centroid": pl.Float64,
        },
        glob_pattern="quantification/mcquant/*/*.csv",
        format="csv",
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "summary_key": pl.Utf8,
    "sample": pl.Utf8,
    "segmenter": pl.Utf8,
    "n_cells": pl.Int64,
    "median_area": pl.Float64,
    "q1_area": pl.Float64,
    "q3_area": pl.Float64,
    "mean_area": pl.Float64,
    "total_area": pl.Float64,
    "median_major_axis": pl.Float64,
    "median_eccentricity": pl.Float64,
    "median_solidity": pl.Float64,
    "median_aspect_ratio": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_KEY = ["sample", "segmenter"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cells = load_cells(sources["mcquant"])
    out = cells.group_by(_KEY).agg(
        pl.len().cast(pl.Int64).alias("n_cells"),
        pl.col("Area").median().round(2).alias("median_area"),
        pl.col("Area").quantile(0.25, "linear").round(2).alias("q1_area"),
        pl.col("Area").quantile(0.75, "linear").round(2).alias("q3_area"),
        pl.col("Area").mean().round(2).alias("mean_area"),
        pl.col("Area").sum().cast(pl.Float64).alias("total_area"),
        pl.col("MajorAxisLength").median().round(3).alias("median_major_axis"),
        pl.col("Eccentricity").median().round(4).alias("median_eccentricity"),
        pl.col("Solidity").median().round(4).alias("median_solidity"),
        pl.col("aspect_ratio").median().round(4).alias("median_aspect_ratio"),
    )
    return (
        out.with_columns(
            pl.concat_str([pl.col("sample"), pl.col("segmenter")], separator="|").alias(
                "summary_key"
            )
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(_KEY)
    )
