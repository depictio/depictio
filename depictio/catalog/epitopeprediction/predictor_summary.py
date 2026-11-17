"""Binder calls per tool of nf-core/epitopeprediction, one row per sample and tool.

The pipeline's own binding statistics, recomputed from ``predictions/``: for
each sample and prediction tool, the peptides it scored for at least one
allele, the peptides it could not score (allele or length unsupported), the
peptides it calls a binder of at least one allele and their share, the alleles
it scored and the median IC50 of its predictions. Like the MultiQC table, the
counts leave out wild-type peptides added by ``--wild_type``, so the two agree.
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
    "summary_key": pl.Utf8,
    "sample": pl.Utf8,
    "predictor": pl.Utf8,
    "mhc_class": pl.Utf8,
    "peptides": pl.Int64,
    "scored": pl.Int64,
    "unsupported": pl.Int64,
    "binders": pl.Int64,
    "binder_rate": pl.Float64,
    "alleles": pl.Int64,
    "median_ic50_nm": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = load(sources).filter(pl.col("origin") != "Wild type")
    totals = df.group_by("sample").agg(pl.col("sequence").n_unique().alias("peptides"))
    hits = scored(df)
    tools = hits.select("sample", "predictor").unique()
    per_peptide = hits.group_by(["sample", "predictor", "sequence"]).agg(
        pl.col("mhc_class").first(),
        pl.col("binder").fill_null(False).any().alias("_binds"),
    )
    calls = per_peptide.group_by(["sample", "predictor"]).agg(
        pl.col("mhc_class").first(),
        pl.len().cast(pl.Int64).alias("scored"),
        pl.col("_binds").sum().cast(pl.Int64).alias("binders"),
    )
    scores = hits.group_by(["sample", "predictor"]).agg(
        pl.col("allele").n_unique().cast(pl.Int64).alias("alleles"),
        pl.col("ic50_nm").median().round(2).alias("median_ic50_nm"),
    )
    out = (
        tools.join(totals, on="sample", how="left")
        .join(calls, on=["sample", "predictor"], how="left")
        .join(scores, on=["sample", "predictor"], how="left")
    )
    return (
        out.with_columns(
            (pl.col("sample") + "|" + pl.col("predictor")).alias("summary_key"),
            pl.col("peptides").cast(pl.Int64),
            (pl.col("peptides") - pl.col("scored")).cast(pl.Int64).alias("unsupported"),
            pl.when(pl.col("scored") > 0)
            .then((pl.col("binders") / pl.col("scored")).round(4))
            .otherwise(None)
            .alias("binder_rate"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["sample", "predictor"])
    )
