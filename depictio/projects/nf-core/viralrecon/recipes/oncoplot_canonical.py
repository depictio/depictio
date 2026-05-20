"""Canonical-schema Oncoplot DC for viralrecon variants.

Consumes the existing ``variants_long`` DC and renames its columns to the
canonical oncoplot roles:

    sample_id : Utf8
    gene : Utf8
    mutation_type : Utf8

The renderer pivots to a sample × gene matrix with cell colour from
``mutation_type``. Multiple variants per (sample, gene) are kept as separate
rows — the renderer aggregates per-cell at compute time.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="variants", dc_ref="variants_long"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "gene": pl.Utf8,
    "mutation_type": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "mutation_label": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename viralrecon variants_long columns to canonical oncoplot roles."""
    df = sources["variants"]

    rename_map = {"sample": "sample_id", "GENE": "gene", "EFFECT": "mutation_type"}
    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})

    df = df.with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("gene").cast(pl.Utf8),
        pl.col("mutation_type").cast(pl.Utf8),
    )

    keep = [c for c in ("sample_id", "gene", "mutation_type", "mutation_label") if c in df.columns]
    return df.select(keep)
