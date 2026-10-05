"""Peptide length distribution per sample, the class I / class II signature.

MHC class I grooves are closed at both ends and present mostly 9-mers, with 8-
to 12-mers on either side; class II grooves are open and present 13- to 25-mers
without a sharp mode. The distribution of distinct identified sequences over
length therefore says which class a sample's immunopeptidome comes from and how
clean the elution was: a sharp 9-mer peak is the class I signature, a broad
shoulder of long peptides is class II (or contamination by non-presented
peptides). One row per sample and length, with the count and the share of the
sample's peptides.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PEPTIDES_DC_TAG = "mhcquant_peptides"

SOURCES: list[RecipeSource] = [RecipeSource(ref="peptides", dc_ref=PEPTIDES_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "length": pl.Int64,
    "length_class": pl.Utf8,
    "length_window": pl.Utf8,
    "peptides": pl.Int64,
    "fraction": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    pep = sources["peptides"].unique(subset=["sample", "sequence"])
    counts = pep.group_by("sample", "length", "length_class", "length_window").agg(
        pl.len().cast(pl.Int64).alias("peptides")
    )
    return (
        counts.with_columns(
            (pl.col("peptides") / pl.col("peptides").sum().over("sample")).alias("fraction")
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "length"])
    )
