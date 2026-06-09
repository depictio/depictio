"""Canonical coverage_track DC for nf-core/methylseq — % methylation as signal.

Megatest source: ``methyldackel/<sample>/<sample>_CpG.bedGraph`` or
``bismark/<sample>/<sample>.bismark.cov.gz`` (chrom, start, end, methylation%, meth_count, unmeth_count).
Aggregate to fixed bins (e.g. 200 bp) for the canonical coverage_track schema.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "chromosome": pl.Utf8,
    "position": pl.Int64,
    "value": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "end": pl.Int64,
    "sample": pl.Utf8,
    "category": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against MethylDackel / Bismark coverage files.")
