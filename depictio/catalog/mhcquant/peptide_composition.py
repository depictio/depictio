"""Per-sample composition of the identified peptides, three ways.

A long table for a stacked composition bar with a rank switch: each sample's
distinct peptidoforms split by length (``Peptide length``), by precursor charge
(``Precursor charge``) and by modification state (``Modification``). Each rank
sums to the sample's peptidoform count, so a normalised bar reads as the share
of the sample in each category.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PEPTIDES_DC_TAG = "mhcquant_peptides"

SOURCES: list[RecipeSource] = [RecipeSource(ref="peptides", dc_ref=PEPTIDES_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "rank": pl.Utf8,
    "category": pl.Utf8,
    "peptides": pl.Int64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

RANKS = {
    "Peptide length": "length_class",
    "Precursor charge": "charge_state",
    "Modification": "modification_state",
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    pep = sources["peptides"].unique(subset=["sample", "peptide"])
    frames = [
        pep.group_by("sample", pl.col(col).fill_null("unknown").alias("category"))
        .agg(pl.len().cast(pl.Int64).alias("peptides"))
        .with_columns(pl.lit(rank).alias("rank"))
        for rank, col in RANKS.items()
    ]
    return (
        pl.concat(frames, how="vertical_relaxed")
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "rank", "peptides"], descending=[False, False, True])
    )
