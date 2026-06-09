"""Canonical marker-dotplot DC for nf-core/scrnaseq.

Megatest source: same AnnData h5ad. Use scanpy's ``sc.tl.rank_genes_groups`` results
to pick top-N markers per cluster, then compute mean expression + fraction
expressing on the raw counts per (cluster, gene).

Output (canonical dot_plot schema):

    cluster         : Utf8
    gene            : Utf8
    mean_expression : Float64
    frac_expressing : Float64
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cluster": pl.Utf8,
    "gene": pl.Utf8,
    "mean_expression": pl.Float64,
    "frac_expressing": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/scrnaseq megatest AnnData h5ad — see docstring."
    )
