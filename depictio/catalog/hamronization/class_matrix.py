"""Drug class by sample ARG hit matrix, one aggregation level above the genes.

``gene_matrix.py`` pivots the hAMRonization combined report gene by sample,
which is the resolution a resistance gene is acted on but not the one a cohort
is read at: 119 gene rows over 19 samples is a heatmap nobody can scan. This
recipe rolls the same report up to the drug class, so the matrix becomes a few
dozen rows and the question it answers changes from "which gene is where" to
"which resistance phenotypes this cohort carries, and how unevenly".

The class label is the same normalised leading class ``gene_matrix.py`` uses
for its annotation strip (hAMRonization passes each tool's vocabulary through
untouched, so CARD's ``macrolide antibiotic; lincosamide antibiotic; ...`` and
AMRFinderPlus's ``LINCOSAMIDE/OXAZOLIDINONE/...`` have to be folded together
before they can be counted as one row).

Output columns:
    drug_class, top_tool, n_genes_band, <one Float64 column per sample>
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.hamronization import primary_class

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="report", dc_ref="hamronization_report"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "drug_class": pl.Utf8,
    "top_tool": pl.Utf8,
    "n_genes_band": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count hits per (drug class, sample) and pivot the samples into columns."""
    df = sources["report"].select(
        pl.col("sample").cast(pl.Utf8),
        pl.col("tool").cast(pl.Utf8),
        pl.col("gene_symbol").cast(pl.Utf8),
        primary_class(pl.col("drug_class").cast(pl.Utf8).fill_null("unclassified")).alias(
            "drug_class"
        ),
    )

    # Row annotations: which screen reports the class most often, and how wide
    # the class is in gene terms. Both are strings on purpose: a numeric
    # column here would be read as one more sample column by the heatmap.
    # ``mode()`` returns its ties in an arbitrary order; sorted so the same
    # report always names the same tool.
    annotation = df.group_by("drug_class").agg(
        pl.col("tool").mode().sort().first().alias("top_tool"),
        pl.col("gene_symbol").n_unique().alias("n_genes"),
    )
    annotation = annotation.with_columns(
        pl.when(pl.col("n_genes") >= 10)
        .then(pl.lit("10+ genes"))
        .when(pl.col("n_genes") >= 4)
        .then(pl.lit("4-9 genes"))
        .when(pl.col("n_genes") >= 2)
        .then(pl.lit("2-3 genes"))
        .otherwise(pl.lit("1 gene"))
        .alias("n_genes_band")
    ).drop("n_genes")

    counts = df.group_by("drug_class", "sample").agg(pl.len().cast(pl.Float64).alias("hits"))
    matrix = counts.pivot(on="sample", index="drug_class", values="hits").fill_null(0.0)
    sample_cols = sorted(c for c in matrix.columns if c != "drug_class")
    return (
        annotation.join(matrix, on="drug_class", how="inner")
        .select("drug_class", "top_tool", "n_genes_band", *sample_cols)
        .sort("drug_class")
    )
