"""Extract a germline precision/recall ROC curve from hap.py per-quality ROC output.

Optional. ``HAPPY_HAPPY`` emits ``*.roc.Locations.SNP.PASS.csv.gz`` (and INDEL variants) with
one row per quality threshold (``QQ``). We expose the overall (``Subtype``/``Subset`` == "*")
sweep as ``quality / recall / precision / f1`` for a precision-recall curve. There is no
dedicated ROC advanced-viz yet (see VALIDATION_REPORT.md "Advanced viz to develop"); a native
line figure (precision vs recall) renders it in the meantime.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="happy_roc",
        glob_pattern="small/*/benchmarks/happy/*.roc.Locations.SNP.PASS.csv.gz",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "quality": pl.Float64,
    "recall": pl.Float64,
    "precision": pl.Float64,
    "f1": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Keep the overall stratum and standardize the threshold/metric columns."""
    df = sources["happy_roc"]

    for col_name in ("Subtype", "Subset"):
        if col_name in df.columns and (df[col_name].cast(pl.Utf8) == "*").any():
            df = df.filter(pl.col(col_name).cast(pl.Utf8) == "*")

    df = df.with_columns(
        pl.col("QQ").cast(pl.Float64, strict=False).alias("quality"),
        pl.col("METRIC.Recall").cast(pl.Float64, strict=False).alias("recall"),
        pl.col("METRIC.Precision").cast(pl.Float64, strict=False).alias("precision"),
        pl.col("METRIC.F1_Score").cast(pl.Float64, strict=False).alias("f1"),
    )

    return df.select(["quality", "recall", "precision", "f1"]).drop_nulls("quality").sort("quality")
