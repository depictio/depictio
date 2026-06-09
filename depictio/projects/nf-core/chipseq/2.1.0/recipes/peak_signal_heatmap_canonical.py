"""Canonical ComplexHeatmap DC for nf-core/chipseq — peaks × samples signal matrix."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "peak_id": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against per-sample peak read counts.")
