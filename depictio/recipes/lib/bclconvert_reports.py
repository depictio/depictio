"""Helpers shared by the BCL Convert report recipes.

BCL Convert names neither the flowcell nor the run inside its CSV reports, so the
folder the pipeline published them under stands in for it, and every recipe reads
the lane and Quality_Metrics.csv the same way. Four recipes need exactly this and
recipes may not import each other, so it lives here.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

SOURCE_PATH_COL = "source_path"


def run_name(path: str | None) -> str:
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


def num(df: pl.DataFrame, name: str, dtype: type[pl.DataType]) -> pl.Expr:
    """Column ``name`` cast to ``dtype``, null when the report lacks it."""
    if name not in df.columns:
        return pl.lit(None, dtype=dtype)
    return pl.col(name).cast(pl.Utf8).str.strip_chars().cast(dtype, strict=False)


def with_run(df: pl.DataFrame) -> pl.DataFrame:
    """Add ``flowcell`` from the file path and a numeric ``lane``."""
    paths = df[SOURCE_PATH_COL] if SOURCE_PATH_COL in df.columns else pl.Series([None] * df.height)
    return df.with_columns(
        pl.Series("flowcell", [run_name(p) for p in paths.to_list()], dtype=pl.Utf8),
        num(df, "Lane", pl.Int64).alias("lane"),
    )


def quality_by(quality: pl.DataFrame | None, keys: list[str]) -> pl.DataFrame | None:
    """Yield, Q30 yield and quality-score sum per ``keys``, from Quality_Metrics.csv."""
    if quality is None or quality.is_empty():
        return None
    q = with_run(quality).with_columns(
        num(quality, "Yield", pl.Float64).alias("_y"),
        num(quality, "YieldQ30", pl.Float64).alias("_q30"),
        num(quality, "QualityScoreSum", pl.Float64).alias("_qs"),
        pl.col("SampleID").cast(pl.Utf8).alias("sample")
        if "SampleID" in quality.columns
        else pl.lit(None, dtype=pl.Utf8).alias("sample"),
        num(quality, "ReadNumber", pl.Int64).alias("read"),
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
