"""Canonical UMAP embedding DC for nf-core/scrnaseq.

Megatest source: AnnData ``.h5ad`` written by scanpy at the end of the pipeline.
Read with ``anndata.read_h5ad``, extract ``obs[['sample', 'leiden']]`` and
``obsm['X_umap']``, then concatenate into a long DataFrame.

Output (canonical embedding schema):

    sample_id : Utf8
    dim_1     : Float64    (UMAP1)
    dim_2     : Float64    (UMAP2)
    cluster   : Utf8       (optional)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "cluster": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/scrnaseq megatest AnnData h5ad — see docstring."
    )
