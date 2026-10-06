"""Run health per lane from BCL Convert reports: reads, yield, quality, balance.

The schema is identical to ``bcl2fastq/lane_summary``; see there for the
column meanings. BCL Convert writes only passing-filter reads, so
``clusters_pf`` is the sum of the lane's reads (Undetermined included) and
``clusters_raw`` / ``pct_pf`` are null: the raw cluster count lives in the
InterOp ``TileMetricsOut.bin``, which ``interop/summary`` reads once
``interop_summary`` has turned it into text. Yield and quality come from the
optional ``Quality_Metrics.csv`` source and are null without it.
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
    "clusters_raw": pl.Int64,
    "clusters_pf": pl.Int64,
    "pct_pf": pl.Float64,
    "yield_gb": pl.Float64,
    "pct_q30": pl.Float64,
    "mean_quality": pl.Float64,
    "n_libraries": pl.Int64,
    "library_reads": pl.Int64,
    "undetermined_reads": pl.Int64,
    "pct_undetermined": pl.Float64,
    "library_reads_cv": pl.Float64,
    "lowest_library_pct_of_mean": pl.Float64,
}

DEMUX_DC_TAG = "bclconvert_demux_raw"
QUALITY_DC_TAG = "bclconvert_quality_raw"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (flowcell, lane)."""
    demux = sources["demux"]
    if demux is None or demux.is_empty():
        raise ValueError("bclconvert_lane_summary: Demultiplex_Stats.csv is empty")
    d = (
        with_run(demux)
        .with_columns(
            pl.col("SampleID").cast(pl.Utf8).alias("sample"),
            num(demux, "# Reads", pl.Int64).alias("reads"),
        )
        .unique(subset=["flowcell", "lane", "sample"], keep="first", maintain_order=True)
    )
    und = pl.col("sample") == "Undetermined"
    lib_reads = pl.col("reads").filter(~und)
    lanes = d.group_by(["flowcell", "lane"]).agg(
        pl.col("reads").sum().alias("clusters_pf"),
        lib_reads.len().cast(pl.Int64).alias("n_libraries"),
        lib_reads.sum().alias("library_reads"),
        pl.col("reads").filter(und).sum().alias("undetermined_reads"),
        (100.0 * lib_reads.std() / lib_reads.mean()).alias("library_reads_cv"),
        (100.0 * lib_reads.min() / lib_reads.mean()).alias("lowest_library_pct_of_mean"),
    )
    q = quality_by(sources.get("quality"), ["flowcell", "lane"])
    if q is not None:
        lanes = lanes.join(q, on=["flowcell", "lane"], how="left")
    else:
        lanes = lanes.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(c) for c in ("_y", "_q30", "_qs")
        )
    out = lanes.with_columns(
        pl.format("Lane {}", pl.col("lane")).alias("lane_label"),
        pl.lit(None, dtype=pl.Int64).alias("clusters_raw"),
        pl.lit(None, dtype=pl.Float64).alias("pct_pf"),
        (pl.col("_y") / 1e9).alias("yield_gb"),
        pl.when(pl.col("_y") > 0).then(100.0 * pl.col("_q30") / pl.col("_y")).alias("pct_q30"),
        pl.when(pl.col("_y") > 0).then(pl.col("_qs") / pl.col("_y")).alias("mean_quality"),
        pl.when(pl.col("clusters_pf") > 0)
        .then(100.0 * pl.col("undetermined_reads") / pl.col("clusters_pf"))
        .alias("pct_undetermined"),
    )
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["flowcell", "lane"]
    )
