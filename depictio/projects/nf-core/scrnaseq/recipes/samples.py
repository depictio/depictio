"""One row per scRNA-seq sample, from the samplesheet the pipeline validated.

nf-core/scrnaseq writes one samplesheet row per FASTQ pair (a sample split
across lanes gets several rows, `pbmc8k` has two here). Cell Ranger count runs
once per sample and pools every lane itself, so the hub groups the samplesheet
by `sample` and counts the lanes merged into it.

Output schema:
    sample_id : Utf8        Cell Ranger sample name, `cellranger/count/<sample_id>/outs/`
    expected_cells : Int64  samplesheet `expected_cells` (first non-null value)
    n_lanes : Int64         FASTQ pairs (lanes) merged into this sample
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "expected_cells": pl.Int64,
    "n_lanes": pl.Int64,
}

_REQUIRED = ["sample", "fastq_1"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"scrnaseq samples: samplesheet lacks columns {missing}")

    df = df.with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("expected_cells").cast(pl.Int64, strict=False)
        if "expected_cells" in df.columns
        else pl.lit(None).cast(pl.Int64).alias("expected_cells"),
    )

    result = df.group_by("sample").agg(
        pl.col("expected_cells").drop_nulls().first().alias("expected_cells"),
        pl.len().cast(pl.Int64).alias("n_lanes"),
    )
    result = result.rename({"sample": "sample_id"})
    return result.select(list(EXPECTED_SCHEMA)).sort("sample_id")
