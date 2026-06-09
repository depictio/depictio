"""Canonical stacked_taxonomy DC for nf-core/mag.

Megatest source: GTDB-Tk classification + bin coverage. Join the bin → taxonomy
mapping (``gtdbtk/gtdbtk.bac120.summary.tsv``) with the per-sample bin abundance
(typically from coverM or coverage on the binned contigs) and emit one row per
(sample, taxon, rank).

Output: sample_id / taxon / rank / abundance (Float64).
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "taxon": pl.Utf8,
    "rank": pl.Utf8,
    "abundance": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against nf-core/mag megatest GTDB-Tk + coverM.")
