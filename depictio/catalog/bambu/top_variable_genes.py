"""The most variable genes of a Bambu matrix, on a log-CPM scale.

The counts heatmap next to this one shows the genes with the highest total
count, which on any run is the same short list of mitochondrial and ribosomal
genes and says nothing about the design. Ranking by variance of
``log2(CPM + 1)`` instead shows the genes that actually separate the samples,
which is the heatmap a reader is looking for when they open a quantification
tab.

Normalising first is what makes the ranking meaningful: on raw counts the
variance ranking is a library-size ranking. Annotation entries are summed per
Ensembl gene id first, so a gene appears once however granular the GTF is.

Output: wide, ``gene_id`` + ``gene_biotype`` + one Float64 column of
``log2(CPM + 1)`` per sample, ``TOP_N`` rows.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import (
    gene_biotype_expr,
    gene_id_expr,
    log_cpm_matrix,
    name_sample_columns,
    sample_names,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="header",
        glob_pattern="**/bambu/counts_gene.txt",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "n_rows": 1,
            "infer_schema_length": 0,
            "truncate_ragged_lines": True,
        },
    ),
    RecipeSource(
        ref="counts",
        glob_pattern="**/bambu/counts_gene.txt",
        format="tsv",
        read_kwargs={"has_header": False, "skip_rows": 1, "infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_biotype": pl.Utf8,
    "log_cpm_variance": pl.Float64,
}
# One log-CPM column per sample of the run: named only at ingest, so outside
# the declared schema (the same contract as `counts_gene.py`).

#: Rows kept, ranked by variance of log CPM across the samples.
TOP_N = 100
#: Genes under this total read count are never ranked.
MIN_TOTAL_COUNT = 10.0


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Gene matrix -> the TOP_N most variable genes as a wide log-CPM frame."""
    samples = sample_names(sources["header"].row(0))
    counts, descriptor = name_sample_columns(sources["counts"], samples)

    per_gene = (
        counts.with_columns(
            gene_id_expr(descriptor).alias("gene_id"),
            gene_biotype_expr(descriptor).fill_null("unannotated").alias("gene_biotype"),
        )
        .filter(pl.col("gene_id").is_not_null())
        .group_by("gene_id")
        .agg(
            pl.col("gene_biotype").drop_nulls().first().alias("gene_biotype"),
            *[pl.col(c).sum().alias(c) for c in samples],
        )
        .filter(pl.sum_horizontal(samples) >= MIN_TOTAL_COUNT)
    )

    biotypes = per_gene.select("gene_id", "gene_biotype")
    log_cpm = log_cpm_matrix(per_gene, "gene_id", samples)
    ranked = (
        log_cpm.with_columns(
            pl.concat_list([pl.col(c) for c in samples]).list.var().alias("log_cpm_variance")
        )
        .join(biotypes, on="gene_id", how="left")
        .sort("log_cpm_variance", descending=True, nulls_last=True)
        .head(TOP_N)
    )
    return ranked.select(
        pl.col("gene_id").cast(pl.Utf8),
        pl.col("gene_biotype").cast(pl.Utf8),
        pl.col("log_cpm_variance").cast(pl.Float64),
        *[pl.col(c).cast(pl.Float64) for c in samples],
    )
