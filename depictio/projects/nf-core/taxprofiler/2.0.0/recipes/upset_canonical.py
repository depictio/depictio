"""Canonical UpSet DC for nf-core/taxprofiler.

Megatest source: cross-tool detection table. For each taxon, mark binary
presence (1/0) in each profiler tool's output (Kraken2 / Bracken / Centrifuge /
Diamond / KrakenUniq / MetaPhlAn).

Output (binary membership table — UpSet renderer auto-detects sets):

    taxon          : Utf8     (row id)
    Kraken2        : Int8     (0/1)
    Bracken        : Int8
    Centrifuge     : Int8
    Diamond        : Int8
    KrakenUniq     : Int8
    MetaPhlAn      : Int8
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "taxon": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/taxprofiler megatest per-tool tables — see docstring."
    )
