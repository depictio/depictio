"""Canonical Manhattan DC for nf-core/raredisease — rank-score per variant.

Megatest source: genmod-ranked, snpEff/VEP-annotated VCFs. The rank_score is in
the INFO column; expose it as the Manhattan score.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chr": pl.Utf8,
    "pos": pl.Int64,
    "score": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature": pl.Utf8,
    "sample": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against genmod-ranked VCFs.")
