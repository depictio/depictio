"""Normalize the som.py somatic benchmark summary into a tidy per-caller table.

Consumes the pipeline-aggregated ``indel/summary/tables/sompy/sompy.summary.csv``
(``HAPPY_SOMPY`` collated across callers). One row per somatic caller × variant type, with
precision/recall/F1 and the binomial confidence intervals som.py reports.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sompy_summary",
        path="indel/summary/tables/sompy/sompy.summary.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "caller": pl.Utf8,
    "variant_type": pl.Utf8,
    "tp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
    "recall": pl.Float64,
    "precision": pl.Float64,
    "f1": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "recall_lower": pl.Float64,
    "recall_upper": pl.Float64,
    "precision_lower": pl.Float64,
    "precision_upper": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename som.py columns to the tidy schema and cast numeric types."""
    df = sources["sompy_summary"]

    df = df.rename({"Tool": "caller", "Type": "variant_type"})

    for out, src in (("tp", "TP_base"), ("fp", "FP"), ("fn", "FN")):
        df = df.with_columns(pl.col(src).cast(pl.Int64, strict=False).alias(out))
    for out, src in (("recall", "Recall"), ("precision", "Precision"), ("f1", "F1")):
        df = df.with_columns(pl.col(src).cast(pl.Float64, strict=False).alias(out))
    for col_name in ("recall_lower", "recall_upper", "precision_lower", "precision_upper"):
        if col_name in df.columns:
            df = df.with_columns(pl.col(col_name).cast(pl.Float64, strict=False))

    keep = [
        "caller",
        "variant_type",
        "tp",
        "fp",
        "fn",
        "recall",
        "precision",
        "f1",
        "recall_lower",
        "recall_upper",
        "precision_lower",
        "precision_upper",
    ]
    return df.select([c for c in keep if c in df.columns])
