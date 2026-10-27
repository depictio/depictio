"""Binding per allele of nf-core/epitopeprediction, one row per sample and allele.

For each allele a sample was predicted against: how many distinct peptides a
tool scored, how many at least one tool called a binder, their share, and the
median and best IC50 of the peptides (each peptide at its lowest IC50 over the
tools). The allele is normalised to ``HLA-A*02:01`` and carries its locus
(``HLA-A`` ... ``HLA-DR``) and MHC class, so it filters and joins like the
alleles typed by other pipelines.
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
    "allele_key": pl.Utf8,
    "sample": pl.Utf8,
    "allele": pl.Utf8,
    "hla_locus": pl.Utf8,
    "mhc_class": pl.Utf8,
    "predictors": pl.Utf8,
    "peptides": pl.Int64,
    "binders": pl.Int64,
    "binder_rate": pl.Float64,
    "median_ic50_nm": pl.Float64,
    "best_ic50_nm": pl.Float64,
    "median_affinity_score": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_KEY = ["sample", "allele"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    hits = scored(load(sources))
    per_peptide = hits.group_by([*_KEY, "sequence"]).agg(
        pl.col("hla_locus").first(),
        pl.col("mhc_class").first(),
        pl.col("binder").fill_null(False).any().alias("_binds"),
        pl.col("ic50_nm").min().alias("_ic50"),
        pl.col("BA").max().alias("_ba"),
    )
    tools = hits.group_by(_KEY).agg(
        pl.col("predictor").unique().sort().str.join(", ").alias("predictors")
    )
    out = per_peptide.group_by(_KEY).agg(
        pl.col("hla_locus").first(),
        pl.col("mhc_class").first(),
        pl.len().cast(pl.Int64).alias("peptides"),
        pl.col("_binds").sum().cast(pl.Int64).alias("binders"),
        pl.col("_ic50").median().round(2).alias("median_ic50_nm"),
        pl.col("_ic50").min().round(2).alias("best_ic50_nm"),
        pl.col("_ba").median().round(4).alias("median_affinity_score"),
    )
    return (
        out.join(tools, on=_KEY, how="left")
        .with_columns(
            (pl.col("sample") + "|" + pl.col("allele")).alias("allele_key"),
            pl.when(pl.col("peptides") > 0)
            .then((pl.col("binders") / pl.col("peptides")).round(4))
            .otherwise(None)
            .alias("binder_rate"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(_KEY)
    )
