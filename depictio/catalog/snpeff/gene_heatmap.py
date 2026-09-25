"""Gene by callset burden matrix, for a clustered heatmap.

Rows are the genes carrying the most coding variants across the run, columns
are one per callset (sample and caller), cells are that gene's total variant
count. Clustering the columns is the quickest read of whether the callers
differ more from each other than the depths do.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [RecipeSource(ref="genes", dc_ref="snpeff_genes")]

#: A clustered heatmap stops being readable well before a hundred rows.
TOP_GENES = 40

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {"gene_name": pl.Utf8}
# One numeric column per callset, known only at ingest.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot the busiest genes into a gene by callset matrix of variant counts."""
    genes = sources["genes"].with_columns(
        pl.concat_str([pl.col("sample"), pl.col("caller")], separator=" / ").alias("callset")
    )

    top = (
        genes.group_by("gene_name")
        .agg(pl.col("n_coding").sum().alias("total_coding"))
        .sort(["total_coding", "gene_name"], descending=[True, False])
        .head(TOP_GENES)
        .select("gene_name")
    )

    wide = (
        genes.join(top, on="gene_name", how="inner")
        .group_by(["gene_name", "callset"])
        .agg(pl.col("n_variants").sum().cast(pl.Float64).alias("burden"))
        .pivot(values="burden", index="gene_name", on="callset", aggregate_function="sum")
    )
    # A pivot's column order follows the group_by order, which is not stable
    # between runs; sorted so the Delta schema and the fixture never churn.
    value_cols = sorted(c for c in wide.columns if c != "gene_name")
    return wide.select(
        "gene_name", *[pl.col(c).fill_null(0.0).cast(pl.Float64) for c in value_cols]
    ).sort("gene_name")
