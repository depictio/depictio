"""FLNC insert length distribution per sample, from ``isoseq refine``'s per-read report.

``isoseq refine`` writes ``<prefix>.report.csv`` next to its BAM: one line per
full-length non-chimeric read with the primer and poly(A) lengths it trimmed
and the insert length left (``insertlen``), the length of the cDNA that will
be mapped. The shape of this distribution is the library's size selection:
most Iso-Seq libraries peak between 1 and 4 kb, and a peak far below that means
degraded RNA or a size selection that failed.

The recipe bins the lengths in 100 bp steps, pools the chunks and SMRT cells of
a sample, and reports each bin as a share of the sample's reads so samples of
different depth overlay; lengths past 15 kb fall in the last bin, which keeps
every curve at 150 points or fewer.

Sample ids follow ``pbccs/zmw_yield`` (file prefix without the chunk suffix and
nf-core/isoseq's trailing ``_<row>`` counter).

Output schema (one row per sample and length bin):
    sample : Utf8          sample
    length_bp : Int64      bin start, bp (100 bp bins, the last one open-ended)
    reads : Int64          FLNC reads in the bin
    pct : Float64          reads over the sample's FLNC reads, percent
    cumulative_pct : Float64  reads up to and including the bin, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reads",
        glob_pattern="**/*.report.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0, "columns": ["id", "insertlen"]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "length_bp": pl.Int64,
    "reads": pl.Int64,
    "pct": pl.Float64,
    "cumulative_pct": pl.Float64,
}

BIN_BP = 100
MAX_BP = 15_000


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    reads = sources["reads"]
    if "insertlen" not in reads.columns:
        raise ValueError("isoseq refine: the scanned *.report.csv carry no insertlen column")
    base = pl.col("source_path").str.split("/").list.last().str.replace(r"\.report\.csv$", "")
    binned = (
        reads.select(
            base.str.replace(r"\.chunk\.?\d+$", "").str.replace(r"_\d+$", "").alias("sample"),
            pl.col("insertlen").cast(pl.Int64, strict=False).alias("_len"),
        )
        .drop_nulls("_len")
        .with_columns(
            ((pl.col("_len").clip(0, MAX_BP) // BIN_BP) * BIN_BP).cast(pl.Int64).alias("length_bp")
        )
        .group_by("sample", "length_bp")
        .agg(pl.len().cast(pl.Int64).alias("reads"))
        .sort("sample", "length_bp")
    )
    if binned.is_empty():
        raise ValueError("isoseq refine: no read with an insert length in the scanned reports")
    total = pl.col("reads").sum().over("sample")
    return binned.with_columns(
        (pl.col("reads") * 100.0 / total).cast(pl.Float64).alias("pct"),
        (pl.col("reads").cum_sum().over("sample") * 100.0 / total)
        .cast(pl.Float64)
        .alias("cumulative_pct"),
    ).select(list(EXPECTED_SCHEMA))
