"""Bambu's gene count matrix, melted to one row per sample and gene.

``counts_gene.txt`` is a wide matrix: one column per sample, one row per entry
of the annotation Bambu was given. Nothing downstream of it carries a
``sample`` column, which is why a sample filter picked on the hub reaches the
MultiQC panels and stops there. Melting the matrix is what puts ``sample``
back on the quantification side of the dashboard, so the same pick narrows
counts, CPM and every tile built on them.

Two reshapes happen on the way:

* **Rows are summed per Ensembl gene id.** A minimal or exon-granular GTF
  makes Bambu emit several rows carrying the same ``ENSG...``, one per
  annotation entry (208 722 rows for 63 677 genes in the nanoseq megatest).
  Summing the entries that share an id is what turns the file into a gene
  matrix; the column totals, and therefore the library sizes, are unchanged.
* **Counts are normalised to CPM** against the full library, before the
  ``MIN_TOTAL_COUNT`` filter, so dropping unexpressed genes cannot move the
  normalisation. ``log_cpm`` is ``log2(cpm + 1)``.

Sources: the file's header line and its data rows read separately, because
``counts_gene.txt`` names only its sample columns (the row-id column is
unnamed) and a single ``has_header`` read fails on the width mismatch. See
``counts_gene.py``, which reads the same file the same way.

Output: ``sample`` x ``gene_id`` long, with the biotype and the condition the
sample belongs to carried along so a figure can colour by either.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import (
    condition_of,
    gene_biotype_expr,
    gene_id_expr,
    melt_counts,
    name_sample_columns,
    sample_names,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="header",
        glob_pattern="**/bambu/counts_gene.txt",
        format="tsv",
        # `truncate_ragged_lines`: the header's fields are one short of every
        # data row, and polars scans ahead and raises on the mismatch even
        # though `n_rows=1` never returns those rows.
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
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_biotype": pl.Utf8,
    "count": pl.Float64,
    "cpm": pl.Float64,
    "log_cpm": pl.Float64,
}

#: Genes under this total read count across the run are dropped: they are the
#: three quarters of a whole-genome annotation that a targeted long-read run
#: never sees, and they would multiply the row count by four for no signal.
MIN_TOTAL_COUNT = 1.0


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Ragged wide matrix -> long (sample, gene) rows with CPM."""
    samples = sample_names(sources["header"].row(0))
    counts, descriptor = name_sample_columns(sources["counts"], samples)

    per_entry = counts.with_columns(
        gene_id_expr(descriptor).alias("gene_id"),
        gene_biotype_expr(descriptor).alias("gene_biotype"),
    ).filter(pl.col("gene_id").is_not_null())

    per_gene = per_entry.group_by("gene_id").agg(
        pl.col("gene_biotype").drop_nulls().first().alias("gene_biotype"),
        *[pl.col(c).sum().alias(c) for c in samples],
    )

    long = melt_counts(
        per_gene,
        id_columns=["gene_id", "gene_biotype"],
        samples=samples,
        min_total=MIN_TOTAL_COUNT,
    )
    conditions = {name: condition_of(name) for name in samples}
    return (
        long.with_columns(
            pl.col("sample")
            .replace_strict(conditions, default=None, return_dtype=pl.Utf8)
            .alias("condition"),
            pl.col("gene_biotype").fill_null("unannotated"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "gene_id"])
    )
