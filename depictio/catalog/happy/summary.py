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

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="happy_raw",
        glob_pattern="small/*/benchmarks/happy/*.summary.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
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

    pooled = pooled.with_columns(
        (pl.col("truth_tp") / (pl.col("truth_tp") + pl.col("truth_fn"))).alias("recall"),
        (pl.col("truth_tp") / (pl.col("truth_tp") + pl.col("query_fp"))).alias("precision"),
    ).with_columns(
        (
            2 * pl.col("precision") * pl.col("recall") / (pl.col("precision") + pl.col("recall"))
        ).alias("f1")
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
