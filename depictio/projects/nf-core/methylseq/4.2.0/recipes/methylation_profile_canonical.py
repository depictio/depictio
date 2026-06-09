"""Canonical signal_profile DC for nf-core/methylseq (PROPOSED viz_kind).

Megatest source: per-CpG methylation merged with a region BED (TSS ± flank,
CpG islands). Compute mean methylation in fixed-size bins around region center.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "feature_id": pl.Utf8,
    "bin": pl.Int64,
    "signal": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "category": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against MethylDackel CpG + TSS BED.")
