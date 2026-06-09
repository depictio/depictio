"""Canonical UpSet DC for nf-core/funcscan — AMR gene × tool binary matrix."""

import polars as pl

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raise NotImplementedError(
        "Wire against hAMRonization-merged outputs (AMRFinderPlus / RGI / DeepARG / fARGene)."
    )
