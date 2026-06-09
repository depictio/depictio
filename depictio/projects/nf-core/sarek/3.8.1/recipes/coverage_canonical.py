"""Canonical coverage_track DC for nf-core/sarek.

Megatest source: ``preprocessing/mosdepth/<sample>/<sample>.regions.bed.gz`` — one row
per genomic bin, columns: chrom, start, end, coverage.

Output (canonical coverage_track schema):

    chromosome : Utf8
    position   : Int64    (bin center or start; treated as interval with end_col)
    value      : Float64  (mean coverage in bin)
    end        : Int64    (optional — bin end → interval mode)
    sample     : Utf8     (optional — per-sample subplot row)
    category   : Utf8     (optional — annotation lane: exon / target region)
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
    raise NotImplementedError(
        "Wire against nf-core/sarek megatest mosdepth BED files — see module docstring."
    )
