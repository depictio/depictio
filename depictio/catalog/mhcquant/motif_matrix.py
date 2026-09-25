"""Amino-acid frequency per peptide position, per sample and length.

The binding motif of an MHC allele is read off the anchor positions of the
peptides it presents: for class I, position 2 and the C-terminus of 9-mers carry
a few dominant residues while the middle positions stay close to background. A
sample from a donor with several alleles shows a mixture of motifs.

One row per sample, peptide length and position (``<sample> <n>-mer P<i>``),
with one column per standard amino acid holding the frequency of that residue
at that position among the sample's distinct sequences of that length. Lengths
supported by fewer than ``MIN_PEPTIDES`` sequences are dropped: a position
frequency over a handful of peptides is not a motif. Only the twenty amino-acid
columns are numeric, so a clustered heatmap reads them as the matrix.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PEPTIDES_DC_TAG = "mhcquant_peptides"

SOURCES: list[RecipeSource] = [RecipeSource(ref="peptides", dc_ref=PEPTIDES_DC_TAG)]

AMINO_ACIDS = list("ACDEFGHIKLMNPQRSTVWY")
MIN_PEPTIDES = 20

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "row_id": pl.Utf8,
    "sample": pl.Utf8,
    "length_class": pl.Utf8,
    "position": pl.Utf8,
    "peptides": pl.Int64,
    **{aa: pl.Float64 for aa in AMINO_ACIDS},
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    seqs = (
        sources["peptides"]
        .select("sample", "sequence", "length")
        .unique()
        .filter(pl.len().over("sample", "length") >= MIN_PEPTIDES)
    )
    if seqs.is_empty():
        raise ValueError("mhcquant motif matrix: no length has enough peptides")
    residues = (
        seqs.with_columns(pl.col("sequence").str.split("").alias("aa"))
        .explode("aa")
        .with_columns((pl.int_range(pl.len()).over("sample", "sequence") + 1).alias("pos"))
    )
    counts = residues.group_by("sample", "length", "pos", "aa").agg(pl.len().alias("n"))
    wide = counts.pivot(on="aa", index=["sample", "length", "pos"], values="n")
    for aa in AMINO_ACIDS:
        if aa not in wide.columns:
            wide = wide.with_columns(pl.lit(0).alias(aa))
    support = seqs.group_by("sample", "length").agg(pl.len().cast(pl.Int64).alias("peptides"))
    wide = wide.join(support, on=["sample", "length"])
    freq = [
        (pl.col(aa).fill_null(0) / pl.col("peptides")).cast(pl.Float64).alias(aa)
        for aa in AMINO_ACIDS
    ]
    return (
        wide.sort(["sample", "length", "pos"])
        .with_columns(
            *freq,
            (pl.col("length").cast(pl.Utf8) + "-mer").alias("length_class"),
            ("P" + pl.col("pos").cast(pl.Utf8)).alias("position"),
        )
        .with_columns(
            (pl.col("sample") + " " + pl.col("length_class") + " " + pl.col("position")).alias(
                "row_id"
            )
        )
        .select(list(EXPECTED_SCHEMA))
    )
