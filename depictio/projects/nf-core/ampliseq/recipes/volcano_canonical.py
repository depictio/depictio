"""Canonical-schema volcano DC for ampliseq.

Reads the same ANCOM-BC per-taxon differential-abundance table the existing
`ancombc_results` DC points at (``ancombc_habitat_level2.tsv``) and renames
columns to the canonical advanced-viz volcano schema
(see depictio/models/components/advanced_viz/schemas.py):

    feature_id : Utf8
    effect_size : Float64
    significance : Float64

Optional columns are carried through unchanged so they remain available in
hover tooltips (contrast, Kingdom, Phylum, neg_log10_qval, significant).
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ancombc_table",
        path="ancombc_habitat_level2.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "effect_size": pl.Float64,
    "significance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "label": pl.Utf8,
    "category": pl.Utf8,
    "neg_log10_qval": pl.Float64,
    "significant": pl.Boolean,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename ANCOM-BC columns to the canonical volcano schema."""
    df = sources["ancombc_table"]

    # The ANCOM-BC TSV already contains `id`, `lfc`, `q_val` (and usually
    # `contrast`, `Kingdom`, `Phylum`, `neg_log10_qval`, `significant`).
    rename_map = {
        "id": "feature_id",
        "lfc": "effect_size",
        "q_val": "significance",
    }
    present_renames = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df.rename(present_renames)

    df = df.with_columns(
        pl.col("effect_size").cast(pl.Float64, strict=False),
        pl.col("significance").cast(pl.Float64, strict=False),
        pl.col("feature_id").cast(pl.Utf8),
    )

    # Optional `label` for hover — Phylum if present, else taxonomy string.
    if "Phylum" in df.columns:
        df = df.with_columns(pl.col("Phylum").alias("label"))
    elif "taxonomy" in df.columns:
        df = df.with_columns(pl.col("taxonomy").alias("label"))

    # Optional `category` from contrast (one volcano per contrast on the
    # client side, or all contrasts shown coloured by contrast).
    if "contrast" in df.columns:
        df = df.with_columns(pl.col("contrast").alias("category"))

    keep = [
        c
        for c in (
            "feature_id",
            "effect_size",
            "significance",
            "label",
            "category",
            "contrast",
            "Kingdom",
            "Phylum",
            "neg_log10_qval",
            "significant",
        )
        if c in df.columns
    ]
    return df.select(keep)
