"""Canonical lollipop DC for nf-core/sarek.

Megatest source: snpEff / VEP-annotated VCF. Filter to coding variants (Missense,
Stop, Splice) and join to a UniProt protein-length table to get aa positions.

Output (canonical lollipop schema):

    feature_id : Utf8       (gene symbol)
    position   : Int64      (aa position, 1-based)
    category   : Utf8       (variant consequence)
    effect     : Float64    (optional — SIFT/PolyPhen score for marker size)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "feature_id": pl.Utf8,
    "position": pl.Int64,
    "category": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "effect": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/sarek megatest annotated VCFs — see module docstring."
    )
