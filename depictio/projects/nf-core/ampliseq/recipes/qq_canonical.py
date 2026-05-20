"""Canonical-schema Q-Q DC for ampliseq.

Consumes the existing ``ancombc_results`` DC and exposes the raw p-value
column for the Q-Q diagnostic on ANCOM-BC FDR calibration:

    p_value : Float64

Optional ``feature_id`` (Phylum / taxonomy) appears in hover; optional
``category`` (contrast) lets the renderer stratify into one trace per
contrast.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="ancombc", dc_ref="ancombc_results"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "p_value": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "category": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename p_val → p_value, carry contrast as the optional stratification."""
    df = sources["ancombc"]

    rename_map = {"p_val": "p_value", "id": "feature_id", "contrast": "category"}
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})

    df = df.with_columns(pl.col("p_value").cast(pl.Float64, strict=False))
    df = df.filter(pl.col("p_value").is_not_null() & (pl.col("p_value") > 0))

    if "feature_id" in df.columns:
        df = df.with_columns(pl.col("feature_id").cast(pl.Utf8))
    if "category" in df.columns:
        df = df.with_columns(pl.col("category").cast(pl.Utf8))

    keep = [c for c in ("p_value", "feature_id", "category") if c in df.columns]
    return df.select(keep)
