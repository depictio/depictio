"""Canonical-schema DA-barplot DC for ampliseq.

Consumes the existing ``ancombc_results`` DC and renames its columns to the
canonical advanced-viz da_barplot schema (see
depictio/models/components/advanced_viz/schemas.py):

    feature_id : Utf8
    contrast : Utf8
    lfc : Float64

Optional ``significance`` (q_val) and ``label`` (Phylum / taxonomy) roles are
included so the renderer can highlight significant bars and show taxonomy
labels in hover. Kingdom / Phylum / neg_log10_qval are carried through for
filter / colour binding in the dashboard tile.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="ancombc", dc_ref="ancombc_results"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "contrast": pl.Utf8,
    "lfc": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "significance": pl.Float64,
    "label": pl.Utf8,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "neg_log10_qval": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename ANCOM-BC columns to the canonical da_barplot schema."""
    df = sources["ancombc"]

    rename_map = {"id": "feature_id", "q_val": "significance"}
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})

    df = df.with_columns(
        pl.col("feature_id").cast(pl.Utf8),
        pl.col("contrast").cast(pl.Utf8),
        pl.col("lfc").cast(pl.Float64, strict=False),
    )
    if "significance" in df.columns:
        df = df.with_columns(pl.col("significance").cast(pl.Float64, strict=False))

    # Label: prefer Phylum (informative), fall back to taxonomy if present.
    if "Phylum" in df.columns:
        df = df.with_columns(pl.col("Phylum").alias("label"))
    elif "taxonomy" in df.columns:
        df = df.with_columns(pl.col("taxonomy").alias("label"))

    keep = [
        c
        for c in (
            "feature_id",
            "contrast",
            "lfc",
            "significance",
            "label",
            "Kingdom",
            "Phylum",
            "neg_log10_qval",
        )
        if c in df.columns
    ]
    return df.select(keep)
