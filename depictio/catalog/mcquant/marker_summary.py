"""Marker intensity per image, segmenter and marker (MCQUANT).

One row per image (``sample``), segmentation method and marker: the cells
measured, the mean, median and quartiles of their mean intensity, the median on
the asinh scale (``asinh(x / 150)``) and the coefficient of variation over the
cells, which says how unevenly the marker is expressed across the image. The
marker keeps its position in the panel and its role (nuclear stain or marker).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mcquant import load_cells, melt_markers

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
    "marker": pl.Utf8,
    "marker_order": pl.Int64,
    "marker_role": pl.Utf8,
    "n_cells": pl.Int64,
    "mean_intensity": pl.Float64,
    "median_intensity": pl.Float64,
    "q1_intensity": pl.Float64,
    "q3_intensity": pl.Float64,
    "median_asinh": pl.Float64,
    "cv": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_KEY = ["sample", "segmenter", "marker"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    long = melt_markers(load_cells(sources["mcquant"]))
    out = long.group_by(_KEY).agg(
        pl.col("marker_order").first(),
        pl.col("marker_role").first(),
        pl.col("intensity").count().cast(pl.Int64).alias("n_cells"),
        pl.col("intensity").mean().round(3).alias("mean_intensity"),
        pl.col("intensity").median().round(3).alias("median_intensity"),
        pl.col("intensity").quantile(0.25, "linear").round(3).alias("q1_intensity"),
        pl.col("intensity").quantile(0.75, "linear").round(3).alias("q3_intensity"),
        pl.col("asinh_intensity").median().round(4).alias("median_asinh"),
        pl.col("intensity").std().alias("_sd"),
    )
    return (
        out.with_columns(
            pl.concat_str([pl.col(c) for c in _KEY], separator="|").alias("summary_key"),
            # A marker no cell expresses has a zero mean: its spread is undefined, not 0.
            pl.when(pl.col("mean_intensity") > 0)
            .then((pl.col("_sd") / pl.col("mean_intensity")).round(4))
            .otherwise(None)
            .alias("cv"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["sample", "segmenter", "marker_order"])
    )
