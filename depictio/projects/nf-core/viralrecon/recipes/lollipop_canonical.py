"""Canonical-schema Lollipop DC for viralrecon variants.

Consumes the existing ``variants_long`` DC and exposes the canonical lollipop
roles for variant / mutation tracks along the SARS-CoV-2 genome:

    feature_id : Utf8   -- gene the variant is on (GENE)
    position : Int64    -- genomic position (POS)
    category : Utf8     -- variant effect class (EFFECT / FUNCLASS)

Optional ``effect`` (numeric AF) modulates marker size.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="variants", dc_ref="variants_long"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "position": pl.Int64,
    "category": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "effect": pl.Float64,
    "mutation_label": pl.Utf8,
    "sample": pl.Utf8,
    # GENE / EFFECT alias columns preserved verbatim from `variants_long` so
    # left-rail filters configured against the upstream DC (`column_name: GENE`
    # / `column_name: EFFECT`) still resolve against this DC. Without these,
    # `apply_runtime_filters` silently skips the filter because the column
    # isn't on the renamed canonical schema — i.e. the user changes the Gene
    # filter and the lollipop tile doesn't refresh.
    "GENE": pl.Utf8,
    "EFFECT": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename viralrecon variants_long columns to canonical lollipop roles.

    Also preserves the original GENE / EFFECT names as alias columns so that
    interactive filters declared against `variants_long.GENE` / `.EFFECT` keep
    working on this derived DC.
    """
    df = sources["variants"]

    # Alias the originals BEFORE renaming so both names survive.
    if "GENE" in df.columns:
        df = df.with_columns(pl.col("GENE").cast(pl.Utf8).alias("GENE_alias"))
    if "EFFECT" in df.columns:
        df = df.with_columns(pl.col("EFFECT").cast(pl.Utf8).alias("EFFECT_alias"))

    rename_map = {"GENE": "feature_id", "POS": "position", "EFFECT": "category"}
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})

    # Restore originals from the aliases now that the renamed canonical
    # columns exist.
    if "GENE_alias" in df.columns:
        df = df.rename({"GENE_alias": "GENE"})
    if "EFFECT_alias" in df.columns:
        df = df.rename({"EFFECT_alias": "EFFECT"})

    df = df.with_columns(
        pl.col("feature_id").cast(pl.Utf8),
        pl.col("position").cast(pl.Int64, strict=False),
        pl.col("category").cast(pl.Utf8),
    )

    if "AF" in df.columns:
        df = df.with_columns(pl.col("AF").cast(pl.Float64, strict=False).alias("effect"))

    keep = [
        c
        for c in (
            "feature_id",
            "position",
            "category",
            "effect",
            "mutation_label",
            "sample",
            "GENE",
            "EFFECT",
        )
        if c in df.columns
    ]
    return df.select(keep)
