"""Canonical sunburst DC for nf-core/taxprofiler.

Megatest source: Kraken2 kreport (``classification/kraken2/<sample>.kraken2.report``).
Use ``ktImportTaxonomy``-style logic: walk the report's depth-indented lines to
reconstruct Domain → Species lineage for each leaf, then explode into one row
per leaf-taxon × sample.

Output (canonical sunburst schema):

    Domain     : Utf8
    Phylum     : Utf8
    Class      : Utf8
    Order      : Utf8
    Family     : Utf8
    Genus      : Utf8
    Species    : Utf8
    abundance  : Float64
    sample_id  : Utf8
"""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "Domain": pl.Utf8,
    "Phylum": pl.Utf8,
    "Class": pl.Utf8,
    "Order": pl.Utf8,
    "Family": pl.Utf8,
    "Genus": pl.Utf8,
    "Species": pl.Utf8,
    "abundance": pl.Float64,
    "sample_id": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against nf-core/taxprofiler megatest Kraken2 kreports — see docstring."
    )
