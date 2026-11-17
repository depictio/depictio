"""Each compared window's log2 fold change at every time point, with its trend.

The window counterpart of ``gene_trajectories``. For every window of
``signal_window_dynamics``, per time point, the mean log2 signal of the
libraries of that time point against the window's baseline, with the window's
chromosome and its trend (Rising, Falling, Stable). A ``profile`` tile with
``aggregate: median_iqr`` draws the median of each trend with its quartile band
from these rows, so the curves follow the window filters (chromosome, size of
the change), which a summary written here could not. The window selection and
the averaging are those of ``signal_window_dynamics`` (through
``depictio/recipes/lib/time_course.py``).

Sources:
    bins      ``bedtools_strand_bins`` (catalog ``bedtools/strand_bins.py``)
    samples   ``samples`` (the sample hub)
    dynamics  ``signal_window_dynamics``

Output schema:
    window_id, chromosome, trend, time_point : Utf8
    time_h : Float64, time_order : Int64, time_axis : Float64, phase : Utf8
    log2fc : Float64
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
        input_schema={"window_id": pl.Utf8, "chromosome": pl.Utf8, "trend": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "window_id": pl.Utf8,
    "chromosome": pl.Utf8,
    "trend": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "phase": pl.Utf8,
    "log2fc": pl.Float64,
}


def window_points(
    bins: pl.DataFrame, samples: pl.DataFrame, dynamics: pl.DataFrame
) -> pl.DataFrame:
    """Per window of ``dynamics`` and time point: mean log2 signal, log2fc, chromosome, trend."""
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
    return points.join(
        dynamics.select("window_id", "chromosome", "trend"), on="window_id", how="inner"
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    points = window_points(sources["bins"], sources["samples"], sources["dynamics"])
    return points.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["window_id", "time_order"]
    )
