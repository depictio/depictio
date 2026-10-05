"""Protein x database membership: 1 when a database annotates the protein.

One row per protein of the filtered FASTA, one Int64 0/1 column per database
the pipeline searches (``DATABASES``), for an UpSet plot of which databases
agree on which proteins. A skipped database is a column of zeros, so it shows
as an empty set rather than disappearing.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.protein_annotation import DATABASES

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="sequences", dc_ref="seqkit_sequences"),
    RecipeSource(ref="domains", dc_ref="proteinannotator_domains", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "sample": pl.Utf8,
    **{db: pl.Int64 for db in DATABASES},
}

KEYS = ["entity", "sample"]


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Flag every (protein, database) pair with at least one domain."""
    out = sources["sequences"].select(*KEYS)
    domains = sources.get("domains")
    if domains is None or domains.is_empty():
        return out.with_columns(*[pl.lit(0, dtype=pl.Int64).alias(db) for db in DATABASES])
    hits = domains.group_by(KEYS).agg(
        *[(pl.col("database") == db).any().cast(pl.Int64).alias(db) for db in DATABASES]
    )
    out = out.join(hits, on=KEYS, how="left").with_columns(
        *[pl.col(db).fill_null(0) for db in DATABASES]
    )
    return out.select(list(EXPECTED_SCHEMA)).sort(KEYS)
