"""Structural category composition per sample, by isoform and by read.

Two levels of the same split, stacked to 100 % per sample: the share of the
isoforms in each structural category (how much of the transcriptome is new)
and the share of the FLNC reads (how much of the expression is). A sample whose
novel categories are large by isoform but small by read found many rare
isoforms; one where they are large by read too expresses them. Categories are
those of ``tama/transcripts`` (``unclassified`` everywhere without a reference
annotation).

Source:
    transcripts  ``tama_transcripts`` (catalog ``tama/transcripts``)

Output schema (one row per sample, level and category):
    sample : Utf8                sample
    level : Utf8                 "Isoforms" or "FLNC reads"
    structural_category : Utf8   FSM, ISM, NIC, NNC, genic, antisense, intergenic, unclassified
    count : Int64                isoforms, or FLNC reads, in the category
    pct : Float64                count over the sample's total at that level, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

TRANSCRIPTS_DC_TAG = "tama_transcripts"

SOURCES: list[RecipeSource] = [RecipeSource(ref="transcripts", dc_ref=TRANSCRIPTS_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "level": pl.Utf8,
    "structural_category": pl.Utf8,
    "count": pl.Int64,
    "pct": pl.Float64,
}

ISOFORMS = "Isoforms"
READS = "FLNC reads"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    tx = sources["transcripts"]
    if tx.is_empty():
        raise ValueError("TAMA category composition: the transcripts collection is empty")
    per = tx.group_by("sample", "structural_category").agg(
        pl.len().cast(pl.Int64).alias(ISOFORMS),
        pl.col("read_support").sum().cast(pl.Int64).alias(READS),
    )
    long = per.unpivot(
        index=["sample", "structural_category"],
        on=[ISOFORMS, READS],
        variable_name="level",
        value_name="count",
    ).with_columns(pl.col("count").cast(pl.Int64))
    total = pl.col("count").sum().over("sample", "level")
    return (
        long.with_columns(
            pl.when(total > 0)
            .then(pl.col("count") * 100.0 / total)
            .otherwise(None)
            .cast(pl.Float64)
            .alias("pct")
        )
        .sort(["sample", "level", "count"], descending=[False, True, True])
        .select(list(EXPECTED_SCHEMA))
    )
