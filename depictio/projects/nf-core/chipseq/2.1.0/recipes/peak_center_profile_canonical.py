"""Canonical signal_profile DC for nf-core/chipseq (PROPOSED viz_kind).

Megatest source: BigWig signal + consensus peak BED. ``pybigwig`` query for
±N bp around each peak center in fixed bins.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "feature_id": pl.Utf8,
    "bin": pl.Int64,
    "signal": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against BigWigs + consensus peak BED.")
