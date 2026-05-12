"""Canonical-schema stacked-taxonomy DC for ampliseq.

Source: ``taxonomy_rel_abundance_long.tsv`` (same TSV the existing
``taxonomy_rel_abundance`` DC reads). Renames + adds a synthetic ``rank``
column derived from the depth of the taxonomy string.

Canonical schema (see advanced_viz/schemas.py):
    sample_id : Utf8
    taxon : Utf8
    rank : Utf8
    abundance : Float64
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rel_abundance",
        path="taxonomy_rel_abundance_long.tsv",
        format="TSV",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "taxon": pl.Utf8,
    "rank": pl.Utf8,
    "abundance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "lineage": pl.Utf8,
    "parent_taxon": pl.Utf8,
}

# Map taxonomic depth (number of semicolon-separated segments) to rank name.
_RANK_BY_DEPTH = {
    1: "Kingdom",
    2: "Phylum",
    3: "Class",
    4: "Order",
    5: "Family",
    6: "Genus",
    7: "Species",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename + derive rank from taxonomy depth."""
    df = sources["rel_abundance"]

    df = df.rename(
        {
            k: v
            for k, v in {
                "sample": "sample_id",
                "taxonomy": "taxon",
                "rel_abundance": "abundance",
            }.items()
            if k in df.columns
        }
    )

    # Carry the full taxonomy string as `lineage` if a `taxon` column was
    # derived from it (helpful for hover).
    if "taxon" in df.columns:
        df = df.with_columns(pl.col("taxon").alias("lineage"))

    # Derive rank from the taxonomy string depth. The ampliseq pipeline emits
    # rel-table at one collapsed level (Phylum here, per the project YAML),
    # so the depth count is consistent across rows.
    df = df.with_columns(pl.col("taxon").str.split(";").list.len().alias("_depth"))
    df = df.with_columns(
        pl.col("_depth")
        .replace_strict(_RANK_BY_DEPTH, default="Unknown", return_dtype=pl.Utf8)
        .alias("rank")
    )
    df = df.drop("_depth")

    df = df.with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("taxon").cast(pl.Utf8),
        pl.col("abundance").cast(pl.Float64, strict=False),
    )

    keep = [c for c in ("sample_id", "taxon", "rank", "abundance", "lineage") if c in df.columns]
    return df.select(keep)
