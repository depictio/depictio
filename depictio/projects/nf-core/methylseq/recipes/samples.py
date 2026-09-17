"""One row per methylseq sample, from the samplesheet the pipeline was launched
with.

Every Bismark output file names itself after the samplesheet `sample` column
directly (no `_T<n>` technical-replicate suffix, unlike cutandrun / eager), so
this hub needs no id reconstruction. What it adds is the cell line and
condition the AWS megatest's SRA/GEO-derived sample names carry as free text
(`<SRR>_<GSM>_<cell_line>_<condition>`) and that no other file in the run
spells out structurally, the megatest compares two hESC lines (MShef11 under
low-oxygen replicates, MShef4 across passage/differentiation conditions), and
without this split the sample filter can only pick samples one at a time.

A samplesheet whose `sample` column does not follow this convention (any run
using its own naming) still ingests: `cell_line` and `condition` fall back to
null rather than raising, so the hub always has at least the sample id and the
FASTQ paths.

Output schema:
    sample_id : Utf8        the samplesheet's own sample name (matches every
                             Bismark output file for this sample)
    srr_accession : Utf8    SRA run accession, when the sample name starts with one
    gsm_accession : Utf8    GEO sample accession, when the sample name carries one
    cell_line : Utf8        third underscore-separated token (e.g. MShef11, MShef4)
    condition : Utf8        everything after the cell line (e.g. low_oxygen_Q1, bulk, J1)
    fastq_1 : Utf8          read 1 FASTQ path/URL from the samplesheet
    fastq_2 : Utf8          read 2 FASTQ path/URL, empty for single-end samples
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet_full.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "srr_accession": pl.Utf8,
    "gsm_accession": pl.Utf8,
    "cell_line": pl.Utf8,
    "condition": pl.Utf8,
    "fastq_1": pl.Utf8,
    "fastq_2": pl.Utf8,
}

# "<SRR accession>_<GSM accession>_<cell line>_<condition...>". Only the first
# three underscore-separated tokens are structural; everything after the cell
# line is the condition, comma-free so it survives as one token.
_NAME_PATTERN = r"^(SRR\d+)_(GSM\d+)_([A-Za-z0-9]+)_(.+)$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Add the cell-line / condition split on top of the raw samplesheet rows."""
    df = sources["samplesheet"]
    if "sample" not in df.columns:
        raise ValueError(
            f"methylseq samples: samplesheet lacks a 'sample' column, got {df.columns}"
        )

    extracted = pl.col("sample").str.extract_groups(_NAME_PATTERN)
    df = df.with_columns(
        pl.col("sample").alias("sample_id"),
        extracted.struct.field("1").alias("srr_accession"),
        extracted.struct.field("2").alias("gsm_accession"),
        extracted.struct.field("3").alias("cell_line"),
        extracted.struct.field("4").alias("condition"),
        (pl.col("fastq_1") if "fastq_1" in df.columns else pl.lit(None, pl.Utf8)).alias("fastq_1"),
        (pl.col("fastq_2") if "fastq_2" in df.columns else pl.lit(None, pl.Utf8)).alias("fastq_2"),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort("sample_id")
