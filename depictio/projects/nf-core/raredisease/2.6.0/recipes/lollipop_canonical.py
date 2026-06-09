"""Canonical lollipop DC for nf-core/raredisease."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "position": pl.Int64,
    "category": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against VEP-annotated VCFs + UniProt aa lengths.")
