"""Canonical bin_qc DC for nf-core/mag (PROPOSED viz_kind: bin_qc_scatter).

Megatest source: ``checkm/<sample>/<sample>_checkm.tsv`` + ``quast/<sample>/quast.tsv``.
Join on bin_id; emit one row per (sample, bin).
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "bin_id": pl.Utf8,
    "completeness": pl.Float64,
    "contamination": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "bin_size_bp": pl.Int64,
    "n50": pl.Int64,
    "tool": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against CheckM + QUAST megatest outputs.")
