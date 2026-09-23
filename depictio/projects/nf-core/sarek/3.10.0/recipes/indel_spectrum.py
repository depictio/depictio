"""Indel length spectrum per callset, from the `IDD` block of `bcftools stats`.

Deletions carry a negative length, insertions a positive one, so the spectrum
reads left to right from long deletions to long insertions. In coding
sequence a real callset shows a frame signature (lengths 3 and 6 stand out)
and a deletion excess; a caller whose one-base insertions tower over
everything else is usually calling homopolymer noise.

Each callset is normalised to its own total, so a caller that calls fewer
indels is compared on the shape of its spectrum rather than on its yield.
Lengths are kept within +/- `MAX_LENGTH` bp, which holds about 98 percent of
the megatest's indels; `fraction` is still over every indel of the callset, so
the bars of a callset sum to slightly less than one when it calls longer
events. Callsets with no indel in that window (Manta, whose events are longer)
are dropped.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="sections", dc_ref="bcftools_stats_sections")]

MAX_LENGTH = 20

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "callset": pl.Utf8,
    "length": pl.Int64,  # negative for deletions
    "indel_class": pl.Utf8,  # insertion / deletion
    "count": pl.Int64,
    "fraction": pl.Float64,  # share of all the callset's indels
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per callset and indel length in [-MAX_LENGTH, MAX_LENGTH]."""
    by_callset = ["sample", "caller"]
    idd = (
        sources["sections"]
        .filter(pl.col("section") == "indel_length", pl.col("bin").is_not_null())
        .with_columns(pl.col("bin").round(0).cast(pl.Int64).alias("length"))
        .filter(pl.col("length") != 0)
        .group_by([*by_callset, "length"])
        .agg(pl.col("count").sum().cast(pl.Int64).alias("count"))
        .with_columns(
            (pl.col("count") / pl.col("count").sum().over(by_callset))
            .cast(pl.Float64)
            .alias("fraction")
        )
        .filter(pl.col("length").abs() <= MAX_LENGTH)
    )
    return (
        idd.filter(pl.col("count").sum().over(by_callset) > 0)
        .with_columns(
            (pl.col("sample") + pl.lit(" / ") + pl.col("caller")).alias("callset"),
            pl.when(pl.col("length") > 0)
            .then(pl.lit("insertion"))
            .otherwise(pl.lit("deletion"))
            .alias("indel_class"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort([*by_callset, "length"])
    )
