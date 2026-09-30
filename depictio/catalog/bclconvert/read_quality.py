"""Base quality per lane and read from BCL Convert ``Reports/Quality_Metrics.csv``.

``Quality_Metrics.csv`` has one row per (lane, sample, read) with the yield,
the Q30 yield and the quality-score sum; the recipe pools every sample of a
lane (Undetermined included) per read. The schema is identical to
``bcl2fastq/read_quality``; see there for the column meanings.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="quality", dc_ref="bclconvert_quality_raw")]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
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
    """One row per (flowcell, lane, read)."""
    q = _quality_by(sources["quality"], ["flowcell", "lane", "read"])
    if q is None or q.is_empty():
        raise ValueError("bclconvert_read_quality: Quality_Metrics.csv is empty")
    out = q.with_columns(
        pl.format("Lane {}", pl.col("lane")).alias("lane_label"),
        pl.format("Read {}", pl.col("read")).alias("read_label"),
        (pl.col("_y") / 1e9).alias("yield_gb"),
        pl.when(pl.col("_y") > 0).then(100.0 * pl.col("_q30") / pl.col("_y")).alias("pct_q30"),
        pl.when(pl.col("_y") > 0).then(pl.col("_qs") / pl.col("_y")).alias("mean_quality"),
    ).with_columns((pl.col("pct_q30") / 100.0).alias("frac_q30"))
    return out.select([pl.col(c).cast(t) for c, t in EXPECTED_SCHEMA.items()]).sort(
        ["flowcell", "lane", "read"]
    )
