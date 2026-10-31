"""The genes with the strongest evidence over the cohort, one row per gene and one column per analysis.

A diagnosis rests on genes that light up in more than one analysis, and a gene that
lights up in many samples is more often a technical artefact than a patient's cause.
This recipe collapses the per-sample triage list (``outlier_genes``) to one row per
gene: the strongest -log10 p-value each analysis gave it in any sample, how many samples
call it and how many analyses agree at best. The columns of the three analyses are the
columns of a gene by analysis heatmap, named the way the heatmap prints them.

Only the ``top_genes`` genes with the most evidence are kept, so the grid stays
readable: the genes called by the most analyses first, then the strongest total
evidence, then the symbol.

Sources:
    genes   the per-sample triage list

Params:
    top_genes   genes kept (default 40)

Output schema: see ``OUTPUT_SCHEMA``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="genes",
        dc_ref="outlier_genes",
        input_schema={
            "sample": pl.Utf8,
            "gene_name": pl.Utf8,
            "n_analyses": pl.Int64,
            "significance": pl.Float64,
            "expression_score": pl.Float64,
            "splicing_score": pl.Float64,
            "mae_score": pl.Float64,
            "phenotype_gene": pl.Boolean,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_name": pl.Utf8,
    "Expression": pl.Float64,
    "Splicing": pl.Float64,
    "Mono-allelic": pl.Float64,
    "best_support": pl.Int64,
    "samples_called": pl.Int64,
    "samples_listed": pl.Int64,
    "evidence": pl.Float64,
    "phenotype_gene": pl.Boolean,
}

DEFAULT_TOP_GENES = 40


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """One row per gene, the strongest ones of the cohort first."""
    p = params or {}
    top_genes = int(p.get("top_genes") or DEFAULT_TOP_GENES)

    genes = sources["genes"].filter(pl.col("gene_name").is_not_null())
    out = (
        genes.group_by("gene_name")
        .agg(
            pl.col("expression_score").max().fill_null(0.0).alias("Expression"),
            pl.col("splicing_score").max().fill_null(0.0).alias("Splicing"),
            pl.col("mae_score").max().fill_null(0.0).alias("Mono-allelic"),
            pl.col("n_analyses").max().cast(pl.Int64).alias("best_support"),
            (pl.col("n_analyses") >= 1).sum().cast(pl.Int64).alias("samples_called"),
            pl.col("sample").n_unique().cast(pl.Int64).alias("samples_listed"),
            pl.col("phenotype_gene").any().alias("phenotype_gene"),
        )
        .with_columns(
            (pl.col("Expression") + pl.col("Splicing") + pl.col("Mono-allelic")).alias("evidence")
        )
        .sort(
            ["best_support", "evidence", "gene_name"],
            descending=[True, True, False],
        )
        .head(top_genes)
    )
    return out.select(list(OUTPUT_SCHEMA))
