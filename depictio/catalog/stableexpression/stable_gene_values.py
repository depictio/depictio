"""Normalised expression of the very top candidates of each section, sample by sample.

One row per gene and sample that measured it, for the ``top_per_section``
best-ranked candidates of every expression section (2 by default: twenty genes
on a ten-section run), with the sample's dataset. The long form is what lets a
dashboard redraw each box from the samples in view: pick a platform or a
dataset and the boxes are recomputed from its samples alone, which the
pre-aggregated ``stable_gene_distribution`` cannot do. Kept to a few genes per
section on purpose, since every gene adds a row per sample.

Values come from ``merged_data/all_counts.parquet`` (measured values only; see
``stable_gene_distribution`` for the imputed matrix).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import (
    TEXT_READ_KWARGS,
    candidates_with_parts,
    gene_rows,
)

DEFAULT_TOP_PER_SECTION = 2

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
    RecipeSource(
        ref="counts",
        path="merged_data/all_counts.parquet",
        format="parquet",
        input_schema={"gene_id": pl.Utf8},
    ),
    # sample -> dataset; without it the dataset column stays empty.
    RecipeSource(
        ref="design",
        path="merged_data/whole_design.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "value_key": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "section": pl.Utf8,
    "section_index": pl.Int64,
    "section_rank": pl.Int64,
    "overall_rank": pl.Int64,
    "stability_score": pl.Float64,
    "sample": pl.Utf8,
    "dataset": pl.Utf8,
    "value": pl.Float64,
}


def _top_per_section(params: dict[str, str] | None) -> int:
    try:
        value = int(str((params or {}).get("top_per_section", DEFAULT_TOP_PER_SECTION)))
    except ValueError:
        return DEFAULT_TOP_PER_SECTION
    return max(1, value)


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    n_top = _top_per_section(params)
    genes = candidates_with_parts(sources["summary"]).filter(pl.col("section_rank") <= n_top)
    rows = gene_rows(sources["counts"], genes.get_column("gene_id").to_list())
    if rows.is_empty():
        raise ValueError("none of the candidate genes is in the count matrix")
    long = (
        rows.unpivot(index="gene_id", variable_name="sample", value_name="value")
        .with_columns(pl.col("value").cast(pl.Float64))
        .filter(pl.col("value").is_not_null() & pl.col("value").is_not_nan())
    )
    design = sources.get("design")
    if design is not None and {"sample", "batch"} <= set(design.columns):
        sample_dataset = design.select("sample", pl.col("batch").alias("dataset")).unique("sample")
        long = long.join(sample_dataset, on="sample", how="left")
    else:
        long = long.with_columns(pl.lit(None, dtype=pl.Utf8).alias("dataset"))
    keep = ["gene_id", "gene_name", "section", "section_index", "section_rank", "overall_rank", "stability_score"]  # fmt: skip
    return (
        long.join(genes.select(keep), on="gene_id", how="inner")
        .with_columns(
            (pl.col("gene_id") + "|" + pl.col("sample")).alias("value_key"),
            pl.col("value").round(6),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort("section_index", "section_rank", "sample")
    )
