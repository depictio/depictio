"""Source proteins of the presented peptides, one row per sample and protein.

Every identified peptide names the protein(s) its sequence maps to. Counting
peptides per source protein shows which proteins feed the MHC pathway most in a
sample, and whether a protein is sampled by one peptide or tiled by many.
Shared peptides (mapping to several proteins) are credited to each of them, and
flagged through ``shared_peptides``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PEPTIDES_DC_TAG = "mhcquant_peptides"

SOURCES: list[RecipeSource] = [RecipeSource(ref="peptides", dc_ref=PEPTIDES_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "protein": pl.Utf8,
    "protein_entry": pl.Utf8,
    "peptides": pl.Int64,
    "shared_peptides": pl.Int64,
    "psms": pl.Int64,
    "best_score": pl.Float64,
    "log10_intensity": pl.Float64,
    "peptide_list": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

MAX_LISTED = 25


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    pep = sources["peptides"].filter(pl.col("proteins").is_not_null())
    exploded = (
        pep.with_columns(pl.col("proteins").str.split(";").alias("_acc"))
        .explode("_acc")
        .with_columns(
            pl.col("_acc")
            .str.extract(r"^[a-z]{2}\|([^|]+)\|", 1)
            .fill_null(pl.col("_acc"))
            .alias("_protein"),
            pl.col("_acc")
            .str.extract(r"^[a-z]{2}\|[^|]+\|(.+)$", 1)
            .fill_null(pl.col("_acc"))
            .alias("_entry"),
        )
    )
    return (
        exploded.group_by("sample", pl.col("_protein").alias("protein"))
        .agg(
            pl.col("_entry").first().alias("protein_entry"),
            pl.col("sequence").n_unique().cast(pl.Int64).alias("peptides"),
            pl.col("sequence")
            .filter(pl.col("n_proteins") > 1)
            .n_unique()
            .cast(pl.Int64)
            .alias("shared_peptides"),
            pl.col("psms").sum().cast(pl.Int64).alias("psms"),
            pl.col("score").max().alias("best_score"),
            # log10 of the summed peptide intensities
            (10 ** pl.col("log10_intensity")).sum().log10().alias("log10_intensity"),
            pl.col("sequence")
            .unique()
            .sort()
            .head(MAX_LISTED)
            .str.join(", ")
            .alias("peptide_list"),
        )
        .with_columns(
            pl.when(pl.col("log10_intensity").is_finite())
            .then(pl.col("log10_intensity"))
            .alias("log10_intensity")
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "peptides"], descending=[False, True])
    )
