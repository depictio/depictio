"""Agreement between prediction tools of nf-core/epitopeprediction.

One row per sample, peptide, allele and pair of tools that both scored that
peptide against that allele (``--tools mhcflurry,mhcnuggets`` gives one pair
per class I prediction). Each row holds the two IC50s, their log10 ratio and the
two binder calls, and ``agreement`` names the outcome: both call a binder,
neither does, or only one of the two (``<tool> only``). Tools are paired in
alphabetical order, so ``predictor_a`` is always the first by name.

A run with a single tool per class has no pair, and so no rows.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.epitope_predictions import (
    LINE_COLUMN,
    LINE_READ_KWARGS,
    load,
    scored,
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
    "length_class": pl.Utf8,
    "allele": pl.Utf8,
    "hla_locus": pl.Utf8,
    "mhc_class": pl.Utf8,
    "predictor_pair": pl.Utf8,
    "predictor_a": pl.Utf8,
    "predictor_b": pl.Utf8,
    "ic50_a_nm": pl.Float64,
    "ic50_b_nm": pl.Float64,
    "log10_ratio": pl.Float64,
    "abs_log10_ratio": pl.Float64,
    "binder_a": pl.Int64,
    "binder_b": pl.Int64,
    "agreement": pl.Utf8,
    "concordant": pl.Int64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_KEY = ["sample", "sequence", "allele"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    hits = (
        scored(load(sources))
        .select(
            *_KEY,
            "length_class",
            "hla_locus",
            "mhc_class",
            "predictor",
            "ic50_nm",
            pl.col("binder").fill_null(False).cast(pl.Int64).alias("binder"),
        )
        .unique(subset=[*_KEY, "predictor"], keep="first")
    )
    a = hits.rename({"predictor": "predictor_a", "ic50_nm": "ic50_a_nm", "binder": "binder_a"})
    b = hits.select(
        *_KEY,
        pl.col("predictor").alias("predictor_b"),
        pl.col("ic50_nm").alias("ic50_b_nm"),
        pl.col("binder").alias("binder_b"),
    )
    pairs = a.join(b, on=_KEY, how="inner").filter(pl.col("predictor_a") < pl.col("predictor_b"))
    if pairs.is_empty():
        raise ValueError(
            "epitopeprediction predictor agreement: no peptide was scored by two tools "
            "against the same allele (a run with one tool per MHC class has no pair)"
        )
    both = (pl.col("binder_a") == 1) & (pl.col("binder_b") == 1)
    neither = (pl.col("binder_a") == 0) & (pl.col("binder_b") == 0)
    ratio = (
        pl.when((pl.col("ic50_a_nm") > 0) & (pl.col("ic50_b_nm") > 0))
        .then((pl.col("ic50_b_nm") / pl.col("ic50_a_nm")).log10().round(3))
        .otherwise(None)
    )
    return (
        pairs.with_columns(
            (pl.col("predictor_a") + " vs " + pl.col("predictor_b")).alias("predictor_pair"),
            ratio.alias("log10_ratio"),
            pl.when(both)
            .then(pl.lit("Both binder"))
            .when(neither)
            .then(pl.lit("Neither"))
            .when(pl.col("binder_a") == 1)
            .then(pl.col("predictor_a") + " only")
            .otherwise(pl.col("predictor_b") + " only")
            .alias("agreement"),
            (both | neither).cast(pl.Int64).alias("concordant"),
        )
        .with_columns(
            pl.col("log10_ratio").abs().alias("abs_log10_ratio"),
            (
                pl.col("sample")
                + "|"
                + pl.col("sequence")
                + "|"
                + pl.col("allele")
                + "|"
                + pl.col("predictor_pair")
            ).alias("pair_key"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["sample", "allele", "sequence", "predictor_pair"])
    )
