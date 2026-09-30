"""Protein x database matrix: the share of each protein a database annotates.

One row per protein of the filtered FASTA, one Float64 column per database the
pipeline searches (``DATABASES``), holding the fraction of the protein's
residues covered by that database's domains (0 to 1). A skipped database is a
column of zeros. Read as a clustered heatmap, proteins group by which
databases describe them and how completely.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.protein_annotation import DATABASES, covered_positions

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="sequences", dc_ref="seqkit_sequences"),
    RecipeSource(ref="domains", dc_ref="proteinannotator_domains", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    **{db: pl.Float64 for db in DATABASES},
}

KEYS = ["entity", "sample"]


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Covered residues per protein and database over the protein length."""
    proteins = sources["sequences"].select(*KEYS, "length")
    domains = sources.get("domains")
    out = proteins
    for db in DATABASES:
        if domains is None or domains.is_empty():
            out = out.with_columns(pl.lit(0.0).alias(db))
            continue
        covered = (
            covered_positions(domains.filter(pl.col("database") == db), by=tuple(KEYS))
            .group_by(KEYS)
            .agg(pl.len().cast(pl.Int64).alias("_n"))
        )
        out = (
            out.join(covered, on=KEYS, how="left")
            .with_columns(
                pl.when(pl.col("length") > 0)
                .then(pl.col("_n").fill_null(0) / pl.col("length"))
                .otherwise(0.0)
                .alias(db)
            )
            .drop("_n")
        )
    return out.select(list(EXPECTED_SCHEMA)).sort(KEYS)
