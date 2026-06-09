"""Canonical signal_profile DC for nf-core/atacseq (PROPOSED viz_kind).

Megatest source: BigWig signal + a TSS BED. Use ``pybigwig`` to query signal at
±N bp around each TSS in fixed bins.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "feature_id": pl.Utf8,
    "bin": pl.Int64,
    "signal": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against BigWigs + TSS BED.")
