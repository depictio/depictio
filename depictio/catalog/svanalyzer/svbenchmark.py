"""Normalize an SVanalyzer (svbenchmark) structural-variant summary into a tidy table.

OPTIONAL — not exercised by the public megatest (no SV profile). Targets the
pipeline-aggregated ``sv/summary/tables/svbenchmark/svbenchmark.summary.csv`` (collated from
per-sample SVanalyzer ``*.report``). Column matching is case/format tolerant; pin it against a
real SV run when available.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="svbenchmark_summary",
        path="sv/summary/tables/svbenchmark/svbenchmark.summary.csv",
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
    "tp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
}


def _find(df: pl.DataFrame, *candidates: str) -> str | None:
    norm = {c.lower().replace("-", "").replace("_", "").replace(".", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace("-", "").replace("_", "").replace(".", "")
        if key in norm:
            return norm[key]
    return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve svbenchmark metric columns tolerantly. SVanalyzer reports sensitivity/precision."""
    df = sources["svbenchmark_summary"]

    label_col = _find(df, "Tool", "sample", "label", "File")
    df = (
        df.with_columns(pl.col(label_col).cast(pl.Utf8).alias("label"))
        if label_col
        else df.with_columns(pl.lit("svbenchmark").alias("label"))
    )

    prec = _find(df, "precision", "ppv")
    rec = _find(df, "recall", "sensitivity")
    if prec is None or rec is None:
        raise ValueError(f"svbenchmark_summary: missing precision/recall in {df.columns}")
    df = df.with_columns(
        pl.col(prec).cast(pl.Float64, strict=False).alias("precision"),
        pl.col(rec).cast(pl.Float64, strict=False).alias("recall"),
    )

    f1_col = _find(df, "f1", "f1_score", "fmeasure")
    if f1_col is not None:
        df = df.with_columns(pl.col(f1_col).cast(pl.Float64, strict=False).alias("f1"))
    else:
        df = df.with_columns(
            (
                2
                * pl.col("precision")
                * pl.col("recall")
                / (pl.col("precision") + pl.col("recall"))
            ).alias("f1")
        )

    for out, *cands in (("tp", "TP"), ("fp", "FP"), ("fn", "FN")):
        col = _find(df, *cands)
        if col is not None:
            df = df.with_columns(pl.col(col).cast(pl.Int64, strict=False).alias(out))

    keep = ["label", "precision", "recall", "f1", "tp", "fp", "fn"]
    return df.select([c for c in keep if c in df.columns])
