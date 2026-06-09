"""Canonical sunburst DC for nf-core/mag — pivots stacked taxonomy to wide ranks."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "Domain": pl.Utf8,
    "Phylum": pl.Utf8,
    "Class": pl.Utf8,
    "Order": pl.Utf8,
    "Family": pl.Utf8,
    "Genus": pl.Utf8,
    "Species": pl.Utf8,
    "abundance": pl.Float64,
    "sample_id": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against GTDB-Tk classification — pivot to wide.")
