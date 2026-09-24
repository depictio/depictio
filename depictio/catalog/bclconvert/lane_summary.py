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

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="demux", dc_ref="bclconvert_demux_raw"),
    RecipeSource(ref="quality", dc_ref="bclconvert_quality_raw", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
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
SOURCE_PATH_COL = "source_path"


def _run_name(path: str | None) -> str:
    """The run folder a ``Reports/`` directory sits in, skipping a lane folder.

    BCL Convert names neither the flowcell nor the run inside its CSV reports,
    so the folder the pipeline published them under stands in for it.
    """
    if not path:
        return ""
    parts = PurePosixPath(str(path).replace("\\", "/")).parts
    if "Reports" not in parts:
        return ""
    i = len(parts) - 1 - parts[::-1].index("Reports")
    j = i - 1
    while j >= 0 and re.fullmatch(r"L\d{3}", parts[j]):
        j -= 1
    return parts[j] if j >= 0 else ""


def _num(df: pl.DataFrame, name: str, dtype: type[pl.DataType]) -> pl.Expr:
    """Column ``name`` cast to ``dtype``, null when the report lacks it."""
    if name not in df.columns:
        return pl.lit(None, dtype=dtype)
    return pl.col(name).cast(pl.Utf8).str.strip_chars().cast(dtype, strict=False)


def _with_run(df: pl.DataFrame) -> pl.DataFrame:
    """Add ``flowcell`` from the file path and a numeric ``lane``."""
    paths = df[SOURCE_PATH_COL] if SOURCE_PATH_COL in df.columns else pl.Series([None] * df.height)
    return df.with_columns(
        pl.Series("flowcell", [_run_name(p) for p in paths.to_list()], dtype=pl.Utf8),
        _num(df, "Lane", pl.Int64).alias("lane"),
    )


def _quality_by(quality: pl.DataFrame | None, keys: list[str]) -> pl.DataFrame | None:
    """Yield, Q30 yield and quality-score sum per ``keys``, from Quality_Metrics.csv."""
    if quality is None or quality.is_empty():
        return None
    q = _with_run(quality).with_columns(
        _num(quality, "Yield", pl.Float64).alias("_y"),
        _num(quality, "YieldQ30", pl.Float64).alias("_q30"),
        _num(quality, "QualityScoreSum", pl.Float64).alias("_qs"),
        pl.col("SampleID").cast(pl.Utf8).alias("sample")
        if "SampleID" in quality.columns
        else pl.lit(None, dtype=pl.Utf8).alias("sample"),
        _num(quality, "ReadNumber", pl.Int64).alias("read"),
    )
    return (
        q.filter(pl.col("read").is_not_null())
        .group_by(keys)
        .agg(
            pl.col("_y").sum().alias("_y"),
            pl.col("_q30").sum().alias("_q30"),
            pl.col("_qs").sum().alias("_qs"),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (flowcell, lane)."""
    demux = sources["demux"]
    if demux is None or demux.is_empty():
        raise ValueError("bclconvert_lane_summary: Demultiplex_Stats.csv is empty")
    d = (
        _with_run(demux)
        .with_columns(
            pl.col("SampleID").cast(pl.Utf8).alias("sample"),
            _num(demux, "# Reads", pl.Int64).alias("reads"),
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
    q = _quality_by(sources.get("quality"), ["flowcell", "lane"])
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
    return out.select([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()]).sort(
        ["flowcell", "lane"]
    )
