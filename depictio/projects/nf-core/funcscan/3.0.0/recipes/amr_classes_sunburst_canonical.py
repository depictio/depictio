"""Canonical sunburst DC for nf-core/funcscan — AMR drug-class hierarchy."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "drug_class": pl.Utf8,
    "subclass": pl.Utf8,
    "gene": pl.Utf8,
    "abundance": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against hAMRonization drug-class annotations.")
