"""Normalize a Wittyer CNV/SV benchmark summary into a tidy, optionally stratified table.

OPTIONAL — not exercised by the public megatest (no CNV profile). Targets the
pipeline-aggregated ``cnv/summary/tables/wittyer/wittyer.summary.csv`` (collated from per-sample
Wittyer ``*.json``, which stratifies precision/recall/F1 by event type and size bin). Column
matching is case/format tolerant; pin it against a real CNV run when available.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="wittyer_summary",
        path="cnv/summary/tables/wittyer/wittyer.summary.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "label": pl.Utf8,
    "precision": pl.Float64,
    "recall": pl.Float64,
    "f1": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "event_type": pl.Utf8,
    "size_bin": pl.Utf8,
}


def _find(df: pl.DataFrame, *candidates: str) -> str | None:
    norm = {c.lower().replace("-", "").replace("_", "").replace(".", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace("-", "").replace("_", "").replace(".", "")
        if key in norm:
            return norm[key]
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve Wittyer metric/stratum columns tolerantly and standardize names."""
    df = sources["wittyer_summary"]

    label_col = _find(df, "Tool", "sample", "label", "File")
    df = (
        df.with_columns(pl.col(label_col).cast(pl.Utf8).alias("label"))
        if label_col
        else df.with_columns(pl.lit("wittyer").alias("label"))
    )

    prec = _find(df, "precision", "ppv")
    rec = _find(df, "recall", "sensitivity")
    f1_col = _find(df, "f1", "fscore", "f1_score")
    if prec is None or rec is None or f1_col is None:
        raise ValueError(f"wittyer_summary: missing precision/recall/f1 in {df.columns}")
    df = df.with_columns(
        pl.col(prec).cast(pl.Float64, strict=False).alias("precision"),
        pl.col(rec).cast(pl.Float64, strict=False).alias("recall"),
        pl.col(f1_col).cast(pl.Float64, strict=False).alias("f1"),
    )

    et = _find(df, "event_type", "variant_type", "type", "svtype")
    if et is not None:
        df = df.with_columns(pl.col(et).cast(pl.Utf8).alias("event_type"))
    sb = _find(df, "size_bin", "bin", "binid")
    if sb is not None:
        df = df.with_columns(pl.col(sb).cast(pl.Utf8).alias("size_bin"))

    keep = ["label", "event_type", "size_bin", "precision", "recall", "f1"]
    return df.select([c for c in keep if c in df.columns])
