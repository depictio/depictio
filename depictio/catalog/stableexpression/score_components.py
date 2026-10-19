"""The stability score of every candidate gene, split into its parts (long form).

One row per candidate and part: each of the four stability measures
(Normfinder, geNorm M, coefficient of variation, robust CV) normalised to 0-1
and times its weight, and the penalty for the samples where the gene was not
measured. A candidate's parts add up to its stability score, so a stacked bar
of them per section or per gene shows what makes a gene rank where it does.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import (
    MISSING_COMPONENT,
    STABILITY_MEASURES,
    TEXT_READ_KWARGS,
    candidates_with_parts,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reporting/all_genes_summary.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        input_schema={
            "gene_id": pl.Utf8,
            "section": pl.Utf8,
            "stability_score": pl.Utf8,
            "rank": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "part_key": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "section": pl.Utf8,
    "section_index": pl.Int64,
    "section_rank": pl.Int64,
    "overall_rank": pl.Int64,
    "stability_score": pl.Float64,
    "component": pl.Utf8,
    "component_order": pl.Int64,
    "contribution": pl.Float64,
    "normalised_value": pl.Float64,
}

_KEEP = ["gene_id", "gene_name", "section", "section_index", "section_rank", "overall_rank", "stability_score"]  # fmt: skip


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    genes = candidates_with_parts(sources["summary"])
    parts = [
        genes.select(
            *_KEEP,
            pl.lit(label).alias("component"),
            pl.lit(order, dtype=pl.Int64).alias("component_order"),
            pl.col(f"{stem}_part").alias("contribution"),
            pl.col(f"{stem}_norm").alias("normalised_value"),
        )
        for order, (_raw, _value, stem, label) in enumerate(STABILITY_MEASURES, start=1)
    ]
    parts.append(
        genes.select(
            *_KEEP,
            pl.lit(MISSING_COMPONENT).alias("component"),
            pl.lit(len(STABILITY_MEASURES) + 1, dtype=pl.Int64).alias("component_order"),
            pl.col("missing_penalty").alias("contribution"),
            pl.col("missing_penalty").alias("normalised_value"),
        )
    )
    return (
        pl.concat(parts)
        .with_columns((pl.col("gene_id") + "|" + pl.col("component")).alias("part_key"))
        .select(list(OUTPUT_SCHEMA))
        .sort("section_index", "section_rank", "component_order")
    )
