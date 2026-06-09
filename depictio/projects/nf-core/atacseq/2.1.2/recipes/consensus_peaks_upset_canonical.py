"""Canonical UpSet DC for nf-core/atacseq — consensus peak × sample membership."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "peak_id": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError("Wire against macs2/consensus/*.boolean.txt.")
