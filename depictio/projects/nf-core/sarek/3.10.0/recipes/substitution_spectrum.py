"""SNV substitution spectrum per callset, folded onto the six pyrimidine classes.

`bcftools stats` writes the twelve strand-specific substitutions (its `ST`
block). A germline spectrum is read on six classes, each substitution folded
onto its pyrimidine reference (G>A is C>T on the other strand), and split into
transitions (C>T, T>C) and transversions (the other four): that split is the
Ts/Tv ratio drawn as the bars it is made of. An exome callset with a Ts/Tv near
2.5 to 3 is dominated by C>T and T>C; a callset whose transversion bars rise is
carrying noise.

Each callset is normalised to its own SNV total, so callers are compared on the
shape of their spectrum rather than on their yield. Callsets with no SNV at all
(Manta, a structural-variant caller) are dropped: their spectrum has no
denominator.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="sections", dc_ref="bcftools_stats_sections")]

#: Each strand-specific substitution folded onto its pyrimidine reference.
FOLD: dict[str, str] = {
    "C>A": "C>A",
    "G>T": "C>A",
    "C>G": "C>G",
    "G>C": "C>G",
    "C>T": "C>T",
    "G>A": "C>T",
    "T>A": "T>A",
    "A>T": "T>A",
    "T>C": "T>C",
    "A>G": "T>C",
    "T>G": "T>G",
    "A>C": "T>G",
}
TRANSITIONS = ["C>T", "T>C"]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "callset": pl.Utf8,
    "substitution_class": pl.Utf8,
    "mutation_class": pl.Utf8,  # transition / transversion
    "count": pl.Int64,
    "fraction": pl.Float64,  # share of the callset's SNVs
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per callset and pyrimidine substitution class."""
    by_callset = ["sample", "caller"]
    folded = (
        sources["sections"]
        .filter(pl.col("section") == "substitution")
        .with_columns(
            pl.col("label").replace_strict(FOLD, default=None).alias("substitution_class")
        )
        .filter(pl.col("substitution_class").is_not_null())
        .group_by([*by_callset, "substitution_class"])
        .agg(pl.col("count").sum().cast(pl.Int64).alias("count"))
        .filter(pl.col("count").sum().over(by_callset) > 0)
    )
    return (
        folded.with_columns(
            (pl.col("count") / pl.col("count").sum().over(by_callset))
            .cast(pl.Float64)
            .alias("fraction"),
            (pl.col("sample") + pl.lit(" / ") + pl.col("caller")).alias("callset"),
            pl.when(pl.col("substitution_class").is_in(TRANSITIONS))
            .then(pl.lit("transition"))
            .otherwise(pl.lit("transversion"))
            .alias("mutation_class"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort([*by_callset, "substitution_class"])
    )
