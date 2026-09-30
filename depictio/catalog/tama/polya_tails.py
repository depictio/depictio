"""Poly(A) tail lengths TAMA trimmed from the FLNC reads, per sample.

``tama_flnc_polya_cleanup.py`` removes the poly(A) tail left on full-length
reads before mapping and writes ``<prefix>_polya_flnc_report.txt`` (gzipped by
nf-core/isoseq): a two-column histogram, tail length (``polya_num``) against
the number of reads with that tail (``polya_num_count``). Reads whose tail was
already clipped upstream report 0. A library of intact mRNA shows a broad
distribution of long tails; a pile at 0 to 5 means the tails were trimmed
before (``isoseq refine --require-polya`` does), or the RNA was not
poly(A)-selected.

The recipe pools the chunks and SMRT cells of a sample and reports each length
as a share of the sample's reads; tails past 100 nt fall in the last point.
Sample ids follow ``pbccs/zmw_yield``.

Output schema (one row per sample and tail length):
    sample : Utf8          sample
    tail_length : Int64    poly(A) tail length removed, nt (100 means 100 or more)
    reads : Int64          reads with that tail length
    pct : Float64          reads over the sample's reads, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="tails",
        glob_pattern="**/*_polya_flnc_report.txt*",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "tail_length": pl.Int64,
    "reads": pl.Int64,
    "pct": pl.Float64,
}

MAX_TAIL = 100


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    tails = sources["tails"]
    missing = {"polya_num", "polya_num_count"} - set(tails.columns)
    if missing:
        raise ValueError(f"TAMA poly(A) report: missing column(s) {sorted(missing)}")
    base = (
        pl.col("source_path")
        .str.split("/")
        .list.last()
        .str.replace(r"_polya_flnc_report\.txt(\.gz)?$", "")
        .str.replace(r"_tama$", "")
    )
    out = (
        tails.select(
            base.str.replace(r"\.chunk\.?\d+$", "").str.replace(r"_\d+$", "").alias("sample"),
            pl.col("polya_num").cast(pl.Int64, strict=False).clip(0, MAX_TAIL).alias("tail_length"),
            pl.col("polya_num_count").cast(pl.Int64, strict=False).fill_null(0).alias("reads"),
        )
        .drop_nulls("tail_length")
        .group_by("sample", "tail_length")
        .agg(pl.col("reads").sum().cast(pl.Int64))
        .sort("sample", "tail_length")
    )
    total = pl.col("reads").sum().over("sample")
    return out.with_columns(
        pl.when(total > 0)
        .then(pl.col("reads") * 100.0 / total)
        .otherwise(None)
        .cast(pl.Float64)
        .alias("pct")
    ).select(list(EXPECTED_SCHEMA))
