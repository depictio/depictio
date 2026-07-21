"""Reshape the som.py region-stratified benchmark into a caller × AF-bin metrics table.

Consumes ``indel/summary/tables/sompy/sompy.regions.csv``. som.py encodes the
allele-fraction stratum inside the ``Type`` column as ``indels.<lo>-<hi>``; we split that
into a clean ``af_bin`` so the result drives a caller × AF-bin heatmap of recall/precision/F1.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sompy_regions",
        path="indel/summary/tables/sompy/sompy.regions.csv",
        format="CSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "caller": pl.Utf8,
    "af_bin": pl.Utf8,
    "recall": pl.Float64,
    "precision": pl.Float64,
    "f1": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "tp": pl.Int64,
    "fp": pl.Int64,
    "fn": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Split the AF stratum out of ``Type`` and standardize metric columns."""
    df = sources["sompy_regions"]

    df = df.rename({"Tool": "caller"})

    # ``Type`` is e.g. "indels.0.000000-0.200000" -> af_bin "0.000000-0.200000".
    df = df.with_columns(pl.col("Type").cast(pl.Utf8).str.replace(r"^[^.]*\.", "").alias("af_bin"))

    for out, src in (("recall", "Recall"), ("precision", "Precision"), ("f1", "F1")):
        df = df.with_columns(pl.col(src).cast(pl.Float64, strict=False).alias(out))
    for out, src in (("tp", "TP_base"), ("fp", "FP"), ("fn", "FN")):
        if src in df.columns:
            df = df.with_columns(pl.col(src).cast(pl.Int64, strict=False).alias(out))

    keep = ["caller", "af_bin", "recall", "precision", "f1", "tp", "fp", "fn"]
    return df.select([c for c in keep if c in df.columns])
