"""Canonical Manhattan DC for nf-core/methylseq DMR results.

Megatest source: depends on which differential-methylation caller is enabled
(methylKit, dmrseq, DSS). Use the per-region p-value and -log10 transform.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chr": pl.Utf8,
    "pos": pl.Int64,
    "score": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against methylKit/dmrseq/DSS DMR tables.")
