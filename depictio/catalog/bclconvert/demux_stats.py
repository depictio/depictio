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
    """One row per (lane, sample), Undetermined included."""
    demux = sources["demux"]
    if demux is None or demux.is_empty():
        raise ValueError("bclconvert_demux_stats: Demultiplex_Stats.csv is empty")
    d = _with_run(demux).with_columns(
        pl.col("SampleID").cast(pl.Utf8).alias("sample"),
        _num(demux, "# Reads", pl.Int64).alias("reads"),
        _num(demux, "# Perfect Index Reads", pl.Float64).alias("_perfect"),
        _num(demux, "# One Mismatch Index Reads", pl.Float64).alias("_one"),
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
    q = _quality_by(sources.get("quality"), ["flowcell", "lane", "sample"])
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
    return out.select([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()]).sort(
        ["flowcell", "lane", "sample"]
    )
