"""Canonical PCA embedding DC for nf-core/differentialabundance.

Megatest source: DESeq2 rlog/VST matrix → first two PCs of `prcomp(t(vst))`. The
pipeline emits a ``plots/exploratory/pca.csv`` (or similar); fall back to computing
PCA on the VST matrix locally if not present.

Output (canonical embedding schema):

    sample_id : Utf8
    dim_1     : Float64    (PC1)
    dim_2     : Float64    (PC2)
    condition : Utf8       (optional colour grouping from samplesheet)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "condition": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/differentialabundance megatest PCA output — see module docstring."
    )
