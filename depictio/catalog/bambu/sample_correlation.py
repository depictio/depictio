"""Sample-to-sample expression correlation of a Bambu gene matrix.

A PCA says how the samples arrange themselves; a correlation matrix says how
close they actually are, and it is the plot that shows a swapped label or a
replicate that did not replicate. One row per sample, one column per sample,
so it drops straight into a clustered heatmap with no reshaping.

Spearman rather than Pearson: long-read gene counts span five orders of
magnitude and a handful of very highly expressed genes would otherwise set the
whole coefficient. Ranks are computed with ties averaged, from numpy, so the
recipe adds no dependency.

The matrix is built on ``log2(CPM + 1)`` of the genes that carry at least
``MIN_TOTAL_COUNT`` reads across the run, with the annotation's entries summed
per Ensembl gene id first (see ``counts_gene_long.py`` for why that sum is
what turns the file into a gene matrix).
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.bambu import (
    condition_of,
    gene_id_expr,
    log_cpm_matrix,
    name_sample_columns,
    sample_names,
    spearman_matrix,
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
    "sample_id": pl.Utf8,
    "condition": pl.Utf8,
    "mean_correlation": pl.Float64,
}
# The matrix columns are one per sample of the run, so they are named only at
# ingest and sit outside the declared schema (the same contract as
# `counts_gene.py` and `deseq2/vst_top_variable.py`).

#: Genes under this total read count take no part in the correlation.
MIN_TOTAL_COUNT = 1.0


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Gene matrix -> a square sample x sample Spearman correlation frame."""
    samples = sample_names(sources["header"].row(0))
    counts, descriptor = name_sample_columns(sources["counts"], samples)

    per_gene = (
        counts.with_columns(gene_id_expr(descriptor).alias("gene_id"))
        .filter(pl.col("gene_id").is_not_null())
        .group_by("gene_id")
        .agg(*[pl.col(c).sum().alias(c) for c in samples])
    )
    expressed = per_gene.filter(pl.sum_horizontal(samples) >= MIN_TOTAL_COUNT)
    log_cpm = log_cpm_matrix(expressed, "gene_id", samples)

    values = np.nan_to_num(log_cpm.select(samples).to_numpy().astype(np.float64), nan=0.0)
    correlation = spearman_matrix(values)
    # The diagonal is 1 by construction and would dominate a "how close is this
    # sample to the others" reading, so the summary column leaves it out.
    off_diagonal = correlation.copy()
    np.fill_diagonal(off_diagonal, np.nan)

    frame = pl.DataFrame(
        {
            "sample_id": samples,
            "condition": [condition_of(s) for s in samples],
            "mean_correlation": np.nanmean(off_diagonal, axis=1).tolist()
            if len(samples) > 1
            else [1.0] * len(samples),
            **{name: correlation[:, j].tolist() for j, name in enumerate(samples)},
        }
    )
    return frame.with_columns(
        pl.col("sample_id").cast(pl.Utf8),
        pl.col("condition").cast(pl.Utf8),
        pl.col("mean_correlation").cast(pl.Float64),
        *[pl.col(c).cast(pl.Float64) for c in samples],
    ).sort("sample_id")
