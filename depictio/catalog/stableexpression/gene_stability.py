"""Stability score of every candidate gene of nf-core/stableexpression.

One row per candidate (``nb_candidates_per_section`` per expression section,
250 by default): the stability score (lower is more stable), its rank within
the section and over every candidate, the four measures behind it (Normfinder
stability value, geNorm M, coefficient of variation and its robust, MAD-based
form), each measure normalised to 0-1 over the candidates, and the score split
into its parts: each normalised measure times its weight, plus the penalty for
the samples where the gene was not measured. The parts add up to the score.
The weights are a run parameter (``--stability_score_weights``) no table
records, so they are recovered from the scores (see
``stable_expression.stability_weights``).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.stable_expression import TEXT_READ_KWARGS, candidates_with_parts

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
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "gene_symbol": pl.Utf8,
    "description": pl.Utf8,
    "section": pl.Utf8,
    "section_index": pl.Int64,
    "section_rank": pl.Int64,
    "overall_rank": pl.Int64,
    "rank_weight": pl.Float64,
    "stability_score": pl.Float64,
    "normfinder_stability": pl.Float64,
    "genorm_m": pl.Float64,
    "cv": pl.Float64,
    "robust_cv": pl.Float64,
    "normfinder_norm": pl.Float64,
    "genorm_norm": pl.Float64,
    "cv_norm": pl.Float64,
    "robust_cv_norm": pl.Float64,
    "missing_penalty": pl.Float64,
    "normfinder_part": pl.Float64,
    "genorm_part": pl.Float64,
    "cv_part": pl.Float64,
    "robust_cv_part": pl.Float64,
    "mean": pl.Float64,
    "median": pl.Float64,
    "measured_share": pl.Float64,
    "zero_share": pl.Float64,
    "expression_percentile": pl.Float64,
    "expression_level": pl.Utf8,
    "platforms": pl.Utf8,
    "source_ids": pl.Int64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "rnaseq_cv": pl.Float64,
    "microarray_cv": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    out = candidates_with_parts(sources["summary"])
    optional = [c for c in OPTIONAL_OUTPUT_SCHEMA if c in out.columns]
    return out.select(*OUTPUT_SCHEMA, *optional).sort("section_index", "section_rank")
