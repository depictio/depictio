"""Canonical rarefaction DC for nf-core/taxprofiler.

Megatest source: TAXPASTA species-level abundance table per sample. Compute
rarefaction by random subsampling at multiple depths, repeated N times, then
compute Shannon + observed_features per (sample, depth, iter).

Output (canonical rarefaction schema):

    sample_id          : Utf8
    depth              : Int64
    iter               : Int64
    shannon            : Float64
    observed_features  : Float64
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "depth": pl.Int64,
    "iter": pl.Int64,
    "shannon": pl.Float64,
    "observed_features": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/taxprofiler megatest TAXPASTA tables — see docstring."
    )
