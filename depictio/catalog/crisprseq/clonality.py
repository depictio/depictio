"""Clonality call per library, from the crisprseq clonality classifier.

``clonality/<sample>_edits_classified.csv`` restates the outcome shares and adds
the classifier's verdict: a zygosity class (homozygous wild type,
heterozygous, homozygous edited and so on) with its confidence, and a
clonality label from the indel peak structure (how many indel peaks carry the
edited reads and how much of them the main peak holds). Written unless the run
used ``--skip_clonality``.

Output: one row per library (see EXPECTED_SCHEMA).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import first_matching, num, rounded, sample_expr

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="classified",
        glob_pattern="**/*_edits_classified.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0, "null_values": ["NA", ""]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "classification": pl.Utf8,
    "clonality": pl.Utf8,
    "class_confidence": pl.Float64,
    "total_reads": pl.Int64,
    "wt_pct": pl.Float64,
    "deletion_pct": pl.Float64,
    "insertion_pct": pl.Float64,
    "delins_pct": pl.Float64,
    "inframe_pct": pl.Float64,
    "frameshift_pct": pl.Float64,
    "indel_peaks": pl.Int64,
    "max_peak_pct": pl.Float64,
    "mean_peak_pct": pl.Float64,
    "peak_occupancy": pl.Float64,
}

# output column -> (source header, dtype)
_COLS: dict[str, tuple[str, type[pl.DataType]]] = {
    "classification": ("Classification", pl.Utf8),
    "clonality": ("clonality", pl.Utf8),
    "class_confidence": ("Class_Conf", pl.Float64),
    "total_reads": ("Total Reads", pl.Int64),
    "wt_pct": ("% Wt", pl.Float64),
    "deletion_pct": ("% Dels", pl.Float64),
    "insertion_pct": ("% Ins", pl.Float64),
    "delins_pct": ("% Delins", pl.Float64),
    "inframe_pct": ("% Inframe", pl.Float64),
    "frameshift_pct": ("% Outframe", pl.Float64),
    "indel_peaks": ("edition_peak_count", pl.Int64),
    "max_peak_pct": ("max_peak", pl.Float64),
    "mean_peak_pct": ("av_peak", pl.Float64),
    "peak_occupancy": ("peak_occupancy", pl.Float64),
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["classified"]
    exprs = [sample_expr()]
    for out, (raw, dtype) in _COLS.items():
        src = first_matching(df.columns, raw)
        if src is None:
            exprs.append(pl.lit(None, dtype=dtype).alias(out))
        elif dtype == pl.Utf8:
            exprs.append(pl.col(src).cast(pl.Utf8).str.strip_chars().alias(out))
        else:
            exprs.append(num(src, dtype).cast(dtype).alias(out))
    shares = [c for c, t in EXPECTED_SCHEMA.items() if t == pl.Float64]
    out = df.select(exprs).unique(subset=["sample"], keep="first").with_columns(rounded(*shares))
    return out.select(list(EXPECTED_SCHEMA)).sort("sample")
