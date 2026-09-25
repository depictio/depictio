"""One row per nf-core/mag sample, from the samplesheet the pipeline validated.

nf-core/mag's `samplesheet.full.v4.csv` is already one row per sample (unlike
cutandrun/hic, which merge several sequencing-library rows into a sample): the
megatest run has three samples (CAPES_S7, CAPES_S11, CAPES_S21), each with one
short-read pair and, optionally, one long-read run for hybrid assembly. This
recipe renames the samplesheet's `sample` column to `sample_id` (the hub key
every other collection is linked on) and drops the S3 FASTQ URLs, which are
inputs, not something a dashboard viewer filters or reads.

Output schema:
    sample_id : Utf8             sample name every GenomeBinning output uses
    group : Utf8                 co-assembly group (mag's `group` column)
    short_reads_platform : Utf8  sequencing platform of the short-read pair
    long_reads_platform : Utf8   sequencing platform of the long-read run, null if short-read only
    has_long_reads : Boolean     true when the sample also has a long-read run (hybrid assembly)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.full.v4.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "group": pl.Utf8,
    "short_reads_platform": pl.Utf8,
    "long_reads_platform": pl.Utf8,
    "has_long_reads": pl.Boolean,
}

_REQUIRED = ["sample", "group", "short_reads_platform"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename the samplesheet's sample column to sample_id and drop the FASTQ URLs."""
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"mag samples: samplesheet lacks columns {missing}")

    has_long = (
        pl.col("long_reads").is_not_null()
        & (pl.col("long_reads").cast(pl.Utf8).str.len_chars() > 0)
        if "long_reads" in df.columns
        else pl.lit(False)
    )
    long_platform = (
        pl.col("long_reads_platform").cast(pl.Utf8)
        if "long_reads_platform" in df.columns
        else pl.lit(None, dtype=pl.Utf8)
    )

    out = df.with_columns(
        pl.col("sample").cast(pl.Utf8).alias("sample_id"),
        pl.col("group").cast(pl.Utf8).alias("group"),
        pl.col("short_reads_platform").cast(pl.Utf8).alias("short_reads_platform"),
        long_platform.alias("long_reads_platform"),
        has_long.alias("has_long_reads"),
    ).select(
        "sample_id",
        "group",
        "short_reads_platform",
        "long_reads_platform",
        "has_long_reads",
    )
    return out
