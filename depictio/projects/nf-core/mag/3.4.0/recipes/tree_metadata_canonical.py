"""GTDB-Tk MAG → taxonomy mapping for the phylogenetic tree tips."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "taxon": pl.Utf8,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    "Domain": pl.Utf8,
    "Phylum": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against gtdbtk.bac120.summary.tsv.")
