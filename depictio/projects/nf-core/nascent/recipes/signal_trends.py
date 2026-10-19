"""The typical course of the rising, falling and stable windows: median change per time point.

The window counterpart of ``response_profiles``. For the windows of each trend
of ``signal_window_dynamics`` (Rising, Falling, Stable), per time point, the
median log2 fold change of the window signal against the baseline with the first
and third quartile as a band. The window selection and the averaging are those
of ``signal_window_dynamics`` (the windows it holds, through
``depictio/recipes/lib/time_course.py``).

Sources:
    bins      ``bedtools_strand_bins`` (catalog ``bedtools/strand_bins.py``)
    samples   ``samples`` (the sample hub)
    dynamics  ``signal_window_dynamics``

Output schema:
    trend, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64, phase : Utf8
    median_log2fc, q1_log2fc, q3_log2fc : Float64
    n_windows : Int64
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib import strand_coverage as sc
from depictio.recipes.lib import time_course as tc

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="bins",
        dc_ref="bedtools_strand_bins",
        input_schema={
            "sample": pl.Utf8,
            "chromosome": pl.Utf8,
            "start": pl.Int64,
            "end": pl.Int64,
            "log2_signal": pl.Float64,
        },
    ),
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={
            "sample": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "phase": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="dynamics",
        dc_ref="signal_window_dynamics",
        input_schema={"window_id": pl.Utf8, "trend": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "trend": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "phase": pl.Utf8,
    "median_log2fc": pl.Float64,
    "q1_log2fc": pl.Float64,
    "q3_log2fc": pl.Float64,
    "n_windows": pl.Int64,
}


def window_points(
    bins: pl.DataFrame, samples: pl.DataFrame, dynamics: pl.DataFrame
) -> pl.DataFrame:
    """Per window of ``dynamics`` and time point: mean log2 signal, log2fc, trend."""
    long = bins.with_columns(sc.window_id_expr()).join(
        dynamics.select("window_id"), on="window_id", how="inner"
    )
    times = samples.select("sample", *tc.TIME_POINT_COLUMNS)
    points = tc.time_point_values(
        long.select("window_id", "sample", "log2_signal"),
        times,
        key="window_id",
        value_col="log2_signal",
    )
    return points.join(dynamics.select("window_id", "trend"), on="window_id", how="inner")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    points = window_points(sources["bins"], sources["samples"], sources["dynamics"])
    return (
        tc.spread_by_class(points, class_col="trend")
        .rename({"n_features": "n_windows"})
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["trend", "time_order"])
    )
