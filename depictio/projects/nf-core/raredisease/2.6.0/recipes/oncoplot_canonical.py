"""Canonical oncoplot DC for nf-core/raredisease — clinically actionable rare variants."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "gene": pl.Utf8,
    "mutation_type": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against ranked + filtered VCFs.")
