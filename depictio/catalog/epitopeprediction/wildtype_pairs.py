"""Mutant peptides against their wild type, nf-core/epitopeprediction.

With ``--wild_type`` the pipeline also predicts the wild-type peptide of every
missense mutant peptide (the ``wildtype`` column of the variant tables). This
recipe pairs them: one row per sample, mutant peptide, allele and tool whose
wild-type peptide the same tool scored against the same allele, with both
IC50s, both binder calls and the agretopicity (mutant IC50 over wild-type IC50:
below 1, the mutation strengthens binding). ``pair_call`` names the outcome, the
first of which, a mutant binder whose wild type does not bind, is the classic
neoepitope candidate.

Indels and frameshifts have no wild-type peptide, and a run without
``--wild_type`` predicts none, so such runs have no rows.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.epitope_predictions import (
    LINE_COLUMN,
    LINE_READ_KWARGS,
    load,
    scored,
    with_wildtype,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="predictions",
        input_schema={"source_path": pl.Utf8, LINE_COLUMN: pl.Utf8},
        glob_pattern="predictions/*.tsv",
        format="csv",
        read_kwargs=LINE_READ_KWARGS,
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "pair_key": pl.Utf8,
    "sample": pl.Utf8,
    "sequence": pl.Utf8,
    "wildtype": pl.Utf8,
    "length_class": pl.Utf8,
    "allele": pl.Utf8,
    "hla_locus": pl.Utf8,
    "predictor": pl.Utf8,
    "gene": pl.Utf8,
    "HGVSp": pl.Utf8,
    "genomic_anchor": pl.Utf8,
    "ic50_nm": pl.Float64,
    "wt_ic50_nm": pl.Float64,
    "agretopicity": pl.Float64,
    "log10_agretopicity": pl.Float64,
    "binder": pl.Int64,
    "wt_binder": pl.Int64,
    "pair_call": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

PAIR_CALLS = (
    "Mutant binds, wild type does not",
    "Both bind",
    "Wild type binds, mutant does not",
    "Neither binds",
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = with_wildtype(scored(load(sources)))
    pairs = df.filter(
        pl.col("origin").str.starts_with("Mutant")
        & pl.col("wildtype").is_not_null()
        & pl.col("wt_binder").is_not_null()
    )
    if pairs.is_empty():
        raise ValueError(
            "epitopeprediction wild-type pairs: no mutant peptide has a predicted wild "
            "type (the run had no missense variant, or was not started with --wild_type)"
        )
    mt = pl.col("binder").fill_null(False)
    wt = pl.col("wt_binder").fill_null(False)
    return (
        pairs.with_columns(
            (
                pl.col("sample")
                + "|"
                + pl.col("sequence")
                + "|"
                + pl.col("allele")
                + "|"
                + pl.col("predictor")
            ).alias("pair_key"),
            pl.when(pl.col("agretopicity") > 0)
            .then(pl.col("agretopicity").log10().round(3))
            .otherwise(None)
            .alias("log10_agretopicity"),
            mt.cast(pl.Int64).alias("binder"),
            wt.cast(pl.Int64).alias("wt_binder"),
            pl.when(mt & ~wt)
            .then(pl.lit(PAIR_CALLS[0]))
            .when(mt & wt)
            .then(pl.lit(PAIR_CALLS[1]))
            .when(wt)
            .then(pl.lit(PAIR_CALLS[2]))
            .otherwise(pl.lit(PAIR_CALLS[3]))
            .alias("pair_call"),
        )
        .unique(subset=["pair_key"], keep="first", maintain_order=True)
        .select(list(OUTPUT_SCHEMA))
        .sort(["sample", "allele", "predictor", "sequence"])
    )
