"""CDR3 length spectratype per sample, from the AIRR rearrangement table.

Reads the repertoire table enchantR's repertoire analysis starts from
(``*__repertoire-pass.tsv``, one row per collapsed productive sequence, AIRR
Community columns) and counts sequences per CDR3 amino-acid length. The CDR3
is the IMGT junction without its two conserved anchor codons, so its length in
amino acids is ``(junction_length - 6) / 3``. Out-of-frame junctions and
non-productive rows are dropped: a spectratype is read on the translated loop.

A polyclonal repertoire draws a near-Gaussian spectratype; a clonal expansion
shows up as one length towering over its neighbours. Each sample is
normalised to its own total so a sample with ten times the sequences is
compared on shape, not yield.

Only the five columns this needs are read (``read_kwargs.columns``): the table
carries 70-odd columns and runs to hundreds of megabytes on a real run.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_COLUMNS = ["sequence_id", "sample_id", "subject_id", "locus", "productive", "junction_length"]

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="rearrangements",
        glob_pattern="**/*__repertoire-pass.tsv",
        format="TSV",
        read_kwargs={"columns": _COLUMNS, "infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "locus": pl.Utf8,
    "cdr3_aa_length": pl.Int64,
    "sequences": pl.Int64,
    "fraction": pl.Float64,  # share of the sample's productive in-frame sequences
}

_TRUE = ("T", "TRUE", "True", "true", "1")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample, locus and CDR3 amino-acid length."""
    df = sources["rearrangements"].unique(subset=["sample_id", "sequence_id"])
    df = df.filter(pl.col("productive").is_in(_TRUE)).with_columns(
        pl.col("junction_length").cast(pl.Int64, strict=False)
    )
    df = df.filter(
        pl.col("junction_length").is_not_null() & (pl.col("junction_length") % 3 == 0)
    ).with_columns(((pl.col("junction_length") - 6) // 3).alias("cdr3_aa_length"))
    df = df.filter(pl.col("cdr3_aa_length") >= 1)

    keys = ["sample_id", "subject_id", "locus"]
    counts = df.group_by([*keys, "cdr3_aa_length"]).agg(pl.len().cast(pl.Int64).alias("sequences"))
    counts = counts.with_columns(
        (pl.col("sequences") / pl.col("sequences").sum().over(keys))
        .cast(pl.Float64)
        .alias("fraction")
    )
    return counts.select(list(EXPECTED_SCHEMA)).sort([*keys, "cdr3_aa_length"])
