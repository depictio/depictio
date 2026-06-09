"""Canonical gene_context_map DC for nf-core/funcscan (PROPOSED viz_kind).

Megatest source: hAMRonization merged TSV (or antiSMASH BGC GFF for BGC mode).
Carries contig_id + per-gene start/end/strand.
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "contig_id": pl.Utf8,
    "gene_id": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Utf8,
    "category": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against hAMRonization / antiSMASH outputs.")
