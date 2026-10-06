"""Reads per library and lane, with the undetermined reads, from BCL Convert reports.

``Reports/Demultiplex_Stats.csv`` has one row per (lane, sample), the
Undetermined reads included, with the index-match counts::

    Lane,SampleID,Index,# Reads,# Perfect Index Reads,# One Mismatch Index Reads,...
    1,S1,ACAGGGCTAC-GAGCATCTAT,8554720,8365833,188887,...
    1,Undetermined,Undetermined,2893684750,2893684750,0,...

(BCL Convert 4 adds a ``Sample_Project`` column, which is ignored.) The yield
and base quality come from ``Reports/Quality_Metrics.csv`` (one row per lane,
sample and read), an optional second source: without it those three columns
are null. The schema is identical to ``bcl2fastq/demux_stats``; see there for
the column meanings. ``flowcell`` is the run folder the reports were published
under, since BCL Convert does not name the flowcell in these files.

Both files are plain CSV, scanned with ``infer_schema_length: 0`` and
``include_file_paths: source_path``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bclconvert_reports import num, quality_by, with_run

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="demux",
        dc_ref="bclconvert_demux_raw",
        input_schema={
            "SampleID": pl.Utf8,
            "Lane": pl.Utf8,
            "# Reads": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="quality",
        dc_ref="bclconvert_quality_raw",
        optional=True,
        input_schema={
            "SampleID": pl.Utf8,
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
    "sample": pl.Utf8,
    "index": pl.Utf8,
    "is_undetermined": pl.Boolean,
    "level": pl.Utf8,
    "reads": pl.Int64,
    "pct_of_lane": pl.Float64,
    "yield_mb": pl.Float64,
    "pct_q30": pl.Float64,
    "mean_quality": pl.Float64,
    "pct_perfect_index": pl.Float64,
    "pct_one_mismatch_index": pl.Float64,
}

DEMUX_DC_TAG = "bclconvert_demux_raw"
QUALITY_DC_TAG = "bclconvert_quality_raw"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (lane, sample), Undetermined included."""
    demux = sources["demux"]
    if demux is None or demux.is_empty():
        raise ValueError("bclconvert_demux_stats: Demultiplex_Stats.csv is empty")
    d = with_run(demux).with_columns(
        pl.col("SampleID").cast(pl.Utf8).alias("sample"),
        num(demux, "# Reads", pl.Int64).alias("reads"),
        num(demux, "# Perfect Index Reads", pl.Float64).alias("_perfect"),
        num(demux, "# One Mismatch Index Reads", pl.Float64).alias("_one"),
        pl.col("Index").cast(pl.Utf8).str.replace_all("-", "+").alias("_index")
        if "Index" in demux.columns
        else pl.lit("", dtype=pl.Utf8).alias("_index"),
    )
    d = d.unique(subset=["flowcell", "lane", "sample"], keep="first", maintain_order=True)
    und = pl.col("sample") == "Undetermined"
    d = d.with_columns(
        und.alias("is_undetermined"),
        pl.when(und).then(pl.lit("")).otherwise(pl.col("_index")).alias("index"),
        (100.0 * pl.col("reads") / pl.col("reads").sum().over(["flowcell", "lane"])).alias(
            "pct_of_lane"
        ),
        pl.when(und | (pl.col("reads") == 0))
        .then(None)
        .otherwise(100.0 * pl.col("_perfect") / pl.col("reads"))
        .alias("pct_perfect_index"),
        pl.when(und | (pl.col("reads") == 0))
        .then(None)
        .otherwise(100.0 * pl.col("_one") / pl.col("reads"))
        .alias("pct_one_mismatch_index"),
    )
    q = quality_by(sources.get("quality"), ["flowcell", "lane", "sample"])
    if q is not None:
        d = d.join(q, on=["flowcell", "lane", "sample"], how="left")
    else:
        d = d.with_columns(pl.lit(None, dtype=pl.Float64).alias(c) for c in ("_y", "_q30", "_qs"))
    out = d.with_columns(
        pl.format("Lane {}", pl.col("lane")).alias("lane_label"),
        pl.lit("Library").alias("level"),
        (pl.col("_y") / 1e6).alias("yield_mb"),
        pl.when(pl.col("_y") > 0).then(100.0 * pl.col("_q30") / pl.col("_y")).alias("pct_q30"),
        pl.when(pl.col("_y") > 0).then(pl.col("_qs") / pl.col("_y")).alias("mean_quality"),
    )
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["flowcell", "lane", "sample"]
    )
