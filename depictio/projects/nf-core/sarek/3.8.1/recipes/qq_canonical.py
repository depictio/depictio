"""Canonical QQ-plot DC for nf-core/sarek.

Megatest source: same VCFs as the Manhattan recipe. Derive a per-variant p-value
either from QUAL (Phred-encoded → p = 10^(-QUAL/10)) or from a strand-bias /
allele-frequency test stored in INFO fields.

Output (canonical QQ schema):

    p_value     : Float64     (raw p-value, 0..1)
    feature_id  : Utf8        (optional — variant id for hover)
    category    : Utf8        (optional — sample identifier for stratification)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "p_value": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "category": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against nf-core/sarek megatest VCFs — see module docstring.")
