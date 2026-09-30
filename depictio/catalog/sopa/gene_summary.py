"""Marker dot plot table: each chosen gene's mean expression and fraction of
expressing cells, per cluster, over the whole run.

The scanpy / Seurat dot plot reading: a marker is a gene whose dot is dark
(high mean) and large (most cells express it) in one cluster and faint
elsewhere. Genes are the run's chosen list (see ``sopa/gene_expression``); a
cell counts as expressing when its value is above ``EXPRESSED_ABOVE``. Cells
without a cluster are pooled as ``unassigned``.

Input: the ``sopa_cell_genes_long`` data collection (the ``sopa/gene_expression``
output).

Output schema:
    cluster : Utf8             cluster (or "unassigned")
    gene : Utf8                gene name
    mean_expression : Float64  mean value in X over the cluster's cells
    frac_expressing : Float64  share of the cluster's cells above zero (0-1)
    n_cells : Int64            cells in the cluster
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag of the long per-cell expression (``sopa/gene_expression``).
LONG_DC_TAG = "sopa_cell_genes_long"

SOURCES: list[RecipeSource] = [RecipeSource(ref="long", dc_ref=LONG_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "cluster": pl.Utf8,
    "gene": pl.Utf8,
    "mean_expression": pl.Float64,
    "frac_expressing": pl.Float64,
    "n_cells": pl.Int64,
}

EXPRESSED_ABOVE = 0.0


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    long = sources["long"]
    if long is None or long.is_empty():
        raise ValueError("sopa gene_summary: the per-cell expression table is empty")
    return (
        long.with_columns(pl.col("cluster").cast(pl.Utf8).fill_null("unassigned"))
        .group_by("cluster", "gene")
        .agg(
            pl.col("expression").cast(pl.Float64).mean().alias("mean_expression"),
            (pl.col("expression") > EXPRESSED_ABOVE)
            .mean()
            .cast(pl.Float64)
            .alias("frac_expressing"),
            pl.len().cast(pl.Int64).alias("n_cells"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort("gene", "cluster")
    )
