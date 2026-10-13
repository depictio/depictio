"""Base quality per lane and read from BCL Convert ``Reports/Quality_Metrics.csv``.

``Quality_Metrics.csv`` has one row per (lane, sample, read) with the yield,
the Q30 yield and the quality-score sum; the recipe pools every sample of a
lane (Undetermined included) per read. The schema is identical to
``bcl2fastq/read_quality``; see there for the column meanings.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bclconvert_reports import quality_by

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="quality",
        dc_ref="bclconvert_quality_raw",
        input_schema={
            "Lane": pl.Utf8,
            "ReadNumber": pl.Utf8,
            "Yield": pl.Utf8,
            "YieldQ30": pl.Utf8,
            "QualityScoreSum": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "flowcell": pl.Utf8,
    "lane": pl.Int64,
    "lane_label": pl.Utf8,
    "read": pl.Int64,
    "read_label": pl.Utf8,
    "yield_gb": pl.Float64,
    "pct_q30": pl.Float64,
    "frac_q30": pl.Float64,
    "mean_quality": pl.Float64,
}

DEMUX_DC_TAG = "bclconvert_demux_raw"
QUALITY_DC_TAG = "bclconvert_quality_raw"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (flowcell, lane, read)."""
    q = quality_by(sources["quality"], ["flowcell", "lane", "read"])
    if q is None or q.is_empty():
        raise ValueError("bclconvert_read_quality: Quality_Metrics.csv is empty")
    out = q.with_columns(
        pl.format("Lane {}", pl.col("lane")).alias("lane_label"),
        pl.format("Read {}", pl.col("read")).alias("read_label"),
        (pl.col("_y") / 1e9).alias("yield_gb"),
        pl.when(pl.col("_y") > 0).then(100.0 * pl.col("_q30") / pl.col("_y")).alias("pct_q30"),
        pl.when(pl.col("_y") > 0).then(pl.col("_qs") / pl.col("_y")).alias("mean_quality"),
    ).with_columns((pl.col("pct_q30") / 100.0).alias("frac_q30"))
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["flowcell", "lane", "read"]
    )
