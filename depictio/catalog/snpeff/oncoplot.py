"""Canonical oncoplot rows: callset by gene, coloured by the worst impact.

A germline run has one individual, so the informative x axis is not the sample
but the callset (sample and caller): the oncoplot then reads as "which callers
report a damaging variant in this gene, and at which depth", which is the
comparison this kind of run exists to make.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="genes", dc_ref="snpeff_genes")]

#: An oncoplot is read row by row; thirty genes is the usual ceiling.
TOP_GENES = 30

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "gene": pl.Utf8,
    "mutation_type": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {"n_variants": pl.Int64}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per callset and gene, carrying that cell's most severe impact."""
    genes = sources["genes"]

    top = (
        genes.group_by("gene_name")
        .agg(
            pl.col("n_high").sum().alias("total_high"),
            pl.col("n_coding").sum().alias("total_coding"),
        )
        .sort(["total_high", "total_coding", "gene_name"], descending=[True, True, False])
        .head(TOP_GENES)
        .select("gene_name")
    )

    return (
        genes.join(top, on="gene_name", how="inner")
        .with_columns(
            pl.concat_str([pl.col("sample"), pl.col("caller")], separator=" / ").alias("sample_id"),
            pl.col("gene_name").alias("gene"),
        )
        # ``snpeff_genes`` is one row per gene AND biotype; an oncoplot cell is
        # one callset and gene, so the impact counts are summed over the
        # biotypes before the worst impact is read off them.
        .group_by(["sample_id", "gene"])
        .agg(
            pl.col("n_high").sum(),
            pl.col("n_moderate").sum(),
            pl.col("n_low").sum(),
            pl.col("n_variants").sum(),
        )
        .with_columns(
            pl.when(pl.col("n_high") > 0)
            .then(pl.lit("HIGH"))
            .when(pl.col("n_moderate") > 0)
            .then(pl.lit("MODERATE"))
            .when(pl.col("n_low") > 0)
            .then(pl.lit("LOW"))
            .otherwise(pl.lit("MODIFIER"))
            .alias("mutation_type"),
        )
        .select(["sample_id", "gene", "mutation_type", "n_variants"])
        .sort(["gene", "sample_id"])
    )
