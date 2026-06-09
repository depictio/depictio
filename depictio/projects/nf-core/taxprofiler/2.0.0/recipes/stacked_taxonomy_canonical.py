"""Canonical stacked_taxonomy DC for nf-core/taxprofiler.

Megatest source: TAXPASTA standardised long table —
``taxpasta/<tool>_<db>.standardised.tsv`` — columns: ``taxonomy_id``, ``name``,
``rank``, ``relative_abundance``, one column per sample.

Output (canonical stacked_taxonomy schema):

    sample_id  : Utf8
    taxon      : Utf8       (taxon name)
    rank       : Utf8       (species / genus / family / ...)
    abundance  : Float64    (relative abundance, 0..1)
    tool       : Utf8       (profiler tool name — optional facet/colour)
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "taxon": pl.Utf8,
    "rank": pl.Utf8,
    "abundance": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "tool": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/taxprofiler megatest TAXPASTA tables — see docstring."
    )
