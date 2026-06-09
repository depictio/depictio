"""Canonical coverage_track DC for nf-core/atacseq (BigWig → per-bin signal)."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chromosome": pl.Utf8,
    "position": pl.Int64,
    "value": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "end": pl.Int64,
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against deepTools bamCoverage BigWigs.")
