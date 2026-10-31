"""Expression statistics of every gene of nf-core/stableexpression's merged matrix.

One row per gene of ``reporting/all_genes_summary.csv``: its mean, median,
spread and coefficients of variation over every sample that measured it (the
values are quantile-normalised to 0-1 within each dataset), the share of the
samples that measured it at all and the share that read zero, the expression
section the pipeline put it in (``Section 01`` holds the most expressed genes),
the pipeline's expression level, whether it was one of the section's
candidates, which platforms measured it, and how many source ids (probes,
transcripts) were mapped onto it.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import TEXT_READ_KWARGS, load_gene_summary

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reporting/all_genes_summary.csv",
        format="csv",
        read_kwargs=TEXT_READ_KWARGS,
        input_schema={"gene_id": pl.Utf8, "section": pl.Utf8, "mean": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "gene_symbol": pl.Utf8,
    "description": pl.Utf8,
    "section": pl.Utf8,
    "section_index": pl.Int64,
    "expression_percentile": pl.Float64,
    "expression_level": pl.Utf8,
    "candidate": pl.Utf8,
    "mean": pl.Float64,
    "median": pl.Float64,
    "standard_deviation": pl.Float64,
    "mad": pl.Float64,
    "cv": pl.Float64,
    "robust_cv": pl.Float64,
    "measured_share": pl.Float64,
    "zero_share": pl.Float64,
    "platforms": pl.Utf8,
    "source_ids": pl.Int64,
}
# Per-platform statistics, written only for the platforms the run downloaded.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "rnaseq_mean": pl.Float64,
    "rnaseq_cv": pl.Float64,
    "microarray_mean": pl.Float64,
    "microarray_cv": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    genes = load_gene_summary(sources["summary"])
    optional = [c for c in OPTIONAL_OUTPUT_SCHEMA if c in genes.columns]
    return genes.select(*OUTPUT_SCHEMA, *optional).sort("section_index", "gene_id")
