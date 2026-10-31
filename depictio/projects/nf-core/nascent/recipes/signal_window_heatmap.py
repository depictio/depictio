"""The windows that change most, as a window x time point matrix for a heatmap.

The ``TOP_N`` rising or falling windows of ``signal_window_dynamics`` with the
largest absolute peak change, one row each (``chr1:250000-500000``), one column
per time point in time order, holding the window's mean ``log2(rpm + 1)``
there. The tile z-scores each row; ``trend`` rides along as the row annotation.
Columns are named by the time point labels, libraries of one time point
averaged.

Sources:
    bins      ``bedtools_strand_bins`` (catalog ``bedtools/strand_bins.py``)
    samples   ``samples`` (the sample hub)
    dynamics  ``signal_window_dynamics``

Output schema:
    window_id : Utf8
    trend : Utf8
    <time_point> : Float64   one column per time point, in time order
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
        input_schema={"window_id": pl.Utf8, "trend": pl.Utf8, "abs_peak_log2fc": pl.Float64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it. The time
# point columns are the run's own.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "window_id": pl.Utf8,
    "trend": pl.Utf8,
}

#: Rows of the heatmap.
TOP_N = 40


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    top = (
        sources["dynamics"]
        .filter(pl.col("trend") != "Stable")
        .sort(["abs_peak_log2fc", "window_id"], descending=[True, False])
        .head(TOP_N)
        .select("window_id", "trend")
    )
    if top.is_empty():
        raise ValueError("nascent signal_window_heatmap: no window rises or falls on this run")
    long = (
        sources["bins"]
        .with_columns(sc.window_id_expr())
        .join(top.select("window_id"), on="window_id", how="inner")
    )
    times = sources["samples"].select("sample", *tc.TIME_POINT_COLUMNS)
    points = tc.time_point_values(
        long.select("window_id", "sample", "log2_signal"),
        times,
        key="window_id",
        value_col="log2_signal",
    )
    order = (
        points.select("time_point", "time_order")
        .unique()
        .sort("time_order")["time_point"]
        .to_list()
    )
    wide = points.pivot(
        on="time_point", index="window_id", values="value", aggregate_function="first"
    )
    return top.join(wide, on="window_id", how="left").select(
        "window_id", "trend", *[pl.col(t).cast(pl.Float64) for t in order]
    )
