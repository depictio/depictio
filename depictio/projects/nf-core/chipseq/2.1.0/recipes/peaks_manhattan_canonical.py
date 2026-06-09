"""Canonical Manhattan DC for nf-core/chipseq from MACS2 narrowPeak qvalues."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chr": pl.Utf8,
    "pos": pl.Int64,
    "score": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against MACS2 narrowPeak files.")
