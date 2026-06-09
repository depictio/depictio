"""Canonical PCoA embedding DC for nf-core/taxprofiler.

Megatest source: TAXPASTA wide abundance matrix (taxon × sample). Compute
Bray-Curtis distance, then PCoA via ``scikit-bio`` or polars + scipy.

Output (canonical embedding schema):

    sample_id : Utf8
    dim_1     : Float64    (PCoA axis 1)
    dim_2     : Float64    (PCoA axis 2)
    group     : Utf8       (optional — joined from samplesheet)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "group": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/taxprofiler megatest abundance matrix — see docstring."
    )
