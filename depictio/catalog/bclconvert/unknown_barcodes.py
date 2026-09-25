"""Top unknown barcodes per lane, classed as likely index swaps, from BCL Convert reports.

``Reports/Top_Unknown_Barcodes.csv`` lists the most frequent unassigned index
pairs per lane::

    Lane,index,index2,# Reads,% of Unknown Barcodes,% of All Reads

The indexes in use on each lane come from ``Demultiplex_Stats.csv`` (second
source). The schema and the four swap classes are identical to
``bcl2fastq/unknown_barcodes``; see there for their meaning. The recipe keeps
the 100 most frequent barcodes of each lane.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="unknown", dc_ref="bclconvert_unknown_raw"),
    RecipeSource(ref="demux", dc_ref="bclconvert_demux_raw"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "flowcell": pl.Utf8,
    "lane": pl.Int64,
    "lane_label": pl.Utf8,
    "barcode": pl.Utf8,
    "index1": pl.Utf8,
    "index2": pl.Utf8,
    "reads": pl.Int64,
    "rank": pl.Int64,
    "pct_of_lane": pl.Float64,
    "pct_of_undetermined": pl.Float64,
    "i7_in_use": pl.Boolean,
    "i5_in_use": pl.Boolean,
    "swap_class": pl.Utf8,
}

#: Barcodes kept per lane, most frequent first.
TOP_N_PER_LANE = 100

SWAP_BOTH = "Both indexes in use"
SWAP_I7 = "Only i7 in use"
SWAP_I5 = "Only i5 in use"
SWAP_NONE = "Neither index in use"
SWAP_NO_INDEX = "Poly-G or N index"

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


def _no_index(seq: str) -> bool:
    """A read with no usable index: all G (two-colour dark cycles) or any N."""
    return bool(seq) and ("N" in seq or set(seq) == {"G"})


def classify(i7: str, i5: str, used_i7: set[str], used_i5: set[str]) -> tuple[bool, bool, str]:
    """(i7 in use, i5 in use, swap class) of one unknown barcode."""
    i7_in = i7 in used_i7
    i5_in = bool(i5) and i5 in used_i5
    if _no_index(i7) or _no_index(i5):
        return i7_in, i5_in, SWAP_NO_INDEX
    if i7_in and i5_in:
        return i7_in, i5_in, SWAP_BOTH
    if i7_in:
        return i7_in, i5_in, SWAP_I7
    if i5_in:
        return i7_in, i5_in, SWAP_I5
    return i7_in, i5_in, SWAP_NONE


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Up to ``TOP_N_PER_LANE`` rows per lane, most frequent first."""
    unknown, demux = sources["unknown"], sources["demux"]
    if unknown is None or unknown.is_empty():
        raise ValueError("bclconvert_unknown_barcodes: Top_Unknown_Barcodes.csv is empty")
    d = (
        _with_run(demux)
        .with_columns(
            pl.col("SampleID").cast(pl.Utf8).alias("sample"),
            _num(demux, "# Reads", pl.Int64).alias("reads"),
            pl.col("Index").cast(pl.Utf8).str.replace_all("-", "+").alias("index")
            if "Index" in demux.columns
            else pl.lit("", dtype=pl.Utf8).alias("index"),
        )
        .unique(subset=["flowcell", "lane", "sample"], keep="first", maintain_order=True)
    )
    lane_info: dict[tuple[str, int], dict] = {}
    for (flowcell, lane), g in d.group_by(["flowcell", "lane"]):
        libs = g.filter(pl.col("sample") != "Undetermined")
        i7s, i5s = set(), set()
        for idx in libs["index"].fill_null("").to_list():
            i7, _, i5 = idx.partition("+")
            i7s.add(i7)
            if i5:
                i5s.add(i5)
        lane_info[(flowcell, lane)] = {
            "i7": i7s,
            "i5": i5s,
            "und": int(g.filter(pl.col("sample") == "Undetermined")["reads"].sum() or 0),
            "total": int(g["reads"].sum() or 0),
        }
    u = _with_run(unknown).with_columns(
        pl.col("index").cast(pl.Utf8).fill_null("").alias("index1")
        if "index" in unknown.columns
        else pl.lit("", dtype=pl.Utf8).alias("index1"),
        pl.col("index2").cast(pl.Utf8).fill_null("").alias("index2")
        if "index2" in unknown.columns
        else pl.lit("", dtype=pl.Utf8).alias("index2"),
        _num(unknown, "# Reads", pl.Int64).alias("reads"),
    )
    rows: list[dict] = []
    for (flowcell, lane), g in u.group_by(["flowcell", "lane"], maintain_order=True):
        info = lane_info.get((flowcell, lane), {"i7": set(), "i5": set(), "und": 0, "total": 0})
        top = g.sort("reads", descending=True).head(TOP_N_PER_LANE)
        for rank, rec in enumerate(top.iter_rows(named=True), start=1):
            i7, i5, reads = rec["index1"], rec["index2"], int(rec["reads"] or 0)
            i7_in, i5_in, swap = classify(i7, i5, info["i7"], info["i5"])
            rows.append(
                {
                    "flowcell": flowcell,
                    "lane": lane,
                    "lane_label": f"Lane {lane}",
                    "barcode": f"{i7}+{i5}" if i5 else i7,
                    "index1": i7,
                    "index2": i5,
                    "reads": reads,
                    "rank": rank,
                    "pct_of_lane": 100.0 * reads / info["total"] if info["total"] else None,
                    "pct_of_undetermined": 100.0 * reads / info["und"] if info["und"] else None,
                    "i7_in_use": i7_in,
                    "i5_in_use": i5_in,
                    "swap_class": swap,
                }
            )
    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["flowcell", "lane", "rank"])
