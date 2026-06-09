"""Canonical Manhattan DC for nf-core/atacseq from MACS2 narrowPeak qvalues."""

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
    raise NotImplementedError("Wire against MACS2 narrowPeak files.")
