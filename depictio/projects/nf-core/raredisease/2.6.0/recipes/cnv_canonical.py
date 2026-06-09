"""Canonical cnv_ideogram DC for nf-core/raredisease (PROPOSED viz_kind).

Megatest source: TIDDIT / GATK CNV VCFs + bcftools ROH output. Merge into one
long table with event_type ∈ {gain, loss, roh, neutral}.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "chr": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "event_type": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "effect": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against TIDDIT/GATK CNV + bcftools ROH.")
