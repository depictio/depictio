"""Pool hap.py per-sample summaries into a germline SNP/INDEL performance table.

``HAPPY_HAPPY`` writes one ``*.summary.csv`` per sample under
``small/<sample>/benchmarks/happy/`` with a row per ``Type`` (SNP/INDEL) × ``Filter``
(ALL/PASS). The megatest does not aggregate hap.py across samples, and the glob loader
concatenates the matched files without a per-file label, so we *pool* the counts by
``Type`` × ``Filter`` (sum TP/FN/FP) and recompute precision/recall/F1. This yields the
per-variant-type germline breakdown that rtg-tools (per-sample, overall) does not provide.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="happy_raw",
        glob_pattern="*/*/benchmarks/happy/*.summary.csv",
        format="CSV",
        input_schema={
            "Type": pl.Utf8,
            "Filter": pl.Utf8,
            "TRUTH.TP": pl.Int64,
            "TRUTH.FN": pl.Int64,
            "QUERY.FP": pl.Int64,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "variant_type": pl.Utf8,
    "filter": pl.Utf8,
    "truth_tp": pl.Float64,
    "truth_fn": pl.Float64,
    "query_fp": pl.Float64,
    "recall": pl.Float64,
    "precision": pl.Float64,
    "f1": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pool counts across samples by variant type & filter, then recompute metrics."""
    df = sources["happy_raw"]

    for src in ("TRUTH.TP", "TRUTH.FN", "QUERY.FP"):
        df = df.with_columns(pl.col(src).cast(pl.Float64, strict=False))

    pooled = (
        df.group_by(["Type", "Filter"])
        .agg(
            pl.col("TRUTH.TP").sum().alias("truth_tp"),
            pl.col("TRUTH.FN").sum().alias("truth_fn"),
            pl.col("QUERY.FP").sum().alias("query_fp"),
        )
        .rename({"Type": "variant_type", "Filter": "filter"})
    )

    # A ratio whose denominator is 0 is undefined, so null rather than polars' NaN: recall
    # without truth variants, precision without calls, and F1 when either is. F1 is written
    # 2·TP / (2·TP + FP + FN), which is 0 (not 0/0) when no call is a true positive.
    tp, fn, fp = pl.col("truth_tp"), pl.col("truth_fn"), pl.col("query_fp")
    no_truth, no_calls = (tp + fn) == 0, (tp + fp) == 0
    null = pl.lit(None, dtype=pl.Float64)
    pooled = pooled.with_columns(
        pl.when(no_truth).then(null).otherwise(tp / (tp + fn)).alias("recall"),
        pl.when(no_calls).then(null).otherwise(tp / (tp + fp)).alias("precision"),
        pl.when(no_truth | no_calls).then(null).otherwise(2 * tp / (2 * tp + fp + fn)).alias("f1"),
    )

    return pooled.select(
        [
            "variant_type",
            "filter",
            "truth_tp",
            "truth_fn",
            "query_fp",
            "recall",
            "precision",
            "f1",
        ]
    ).sort(["variant_type", "filter"])
