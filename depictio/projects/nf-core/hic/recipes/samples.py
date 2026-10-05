"""One row per Hi-C sample, from the samplesheet the pipeline validated.

nf-core/hic writes ``samplesheet/samplesheet.valid.csv`` with one row per FASTQ
read pair. A sample can be sequenced across several lanes/runs that HiC-Pro
merges before mapping, so the samplesheet carries more rows than there are
samples: the megatest run has one sample (``HIC_ES_4``) and three read-pair
rows. This recipe collapses that to the hub the sample filter and every
project link key on.

Output schema:
    sample_id : Utf8      sample name every HiC-Pro/cooler/cooltools output uses
    n_libraries : Int64    FASTQ read-pair rows merged into the sample
    single_end : Boolean   true when every merged library is single-end
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="samplesheet/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "n_libraries": pl.Int64,
    "single_end": pl.Boolean,
}

_REQUIRED = ["sample", "single_end"]


def _truthy(column: str) -> pl.Expr:
    """A "True"/"False"/0/1 samplesheet flag as a Boolean."""
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["1", "true", "yes", "y"])
        .fill_null(False)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Collapse the samplesheet's read-pair rows to one row per sample."""
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"hic samples: samplesheet lacks columns {missing}")

    df = df.with_columns(
        pl.col("sample").cast(pl.Utf8).alias("sample_id"),
        _truthy("single_end").alias("single_end"),
    )

    samples = df.group_by("sample_id").agg(
        pl.len().cast(pl.Int64).alias("n_libraries"),
        pl.col("single_end").all().alias("single_end"),
    )
    return samples.select(list(EXPECTED_SCHEMA)).sort("sample_id")
