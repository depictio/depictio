"""One row per methylseq sample, from the samplesheet the pipeline was launched
with.

Every Bismark output file names itself after the samplesheet `sample` column
directly (no `_T<n>` technical-replicate suffix, unlike cutandrun / eager), so
this hub needs no id reconstruction. What it adds is the design the AWS
megatest's SRA/GEO-derived sample names carry as free text
(`<SRR>_<GSM>_<cell_line>_<condition>`) and that no other file in the run spells
out structurally: two hESC lines, MShef11 under three low-oxygen replicates and
MShef4 across a bulk sample and three passage conditions.

`condition` alone is one value per sample, which is a label, not a factor: a
filter on it can only pick samples one at a time and a card broken down by it
has seven slices of one. So the condition is split further, into the treatment
and the replicate inside it:

    low_oxygen_Q1  ->  treatment low_oxygen, replicate 1
    J2             ->  treatment J,          replicate 2
    bulk           ->  treatment bulk,       replicate 1

which leaves three treatments and three replicates, both usable as filters and
as breakdowns. A condition with no replicate token is its own first replicate,
so the column has no holes.

`group` names the two-level factor the cohort was designed around, which the
catalog's window comparison reads to decide what it is testing. Here that is the
cell line, and the dashboard says so plainly: in this megatest MShef11 is
exactly the low-oxygen arm and MShef4 exactly the normoxic one, so cell line and
oxygen condition are the same split and neither can be attributed separately.

A samplesheet whose `sample` column does not follow this convention (any run
using its own naming) still ingests: the parsed columns fall back to null rather
than raising, so the hub always has at least the sample id and the FASTQ paths.

Output schema:
    sample_id : Utf8        the samplesheet's own sample name (matches every
                             Bismark output file for this sample)
    srr_accession : Utf8    SRA run accession, when the sample name starts with one
    gsm_accession : Utf8    GEO sample accession, when the sample name carries one
    cell_line : Utf8        third underscore-separated token (e.g. MShef11, MShef4)
    condition : Utf8        everything after the cell line (e.g. low_oxygen_Q1, bulk, J1)
    treatment : Utf8        the condition without its replicate token
    replicate : Utf8        the replicate number inside the treatment, "1" when absent
    group : Utf8            the two-level factor the cohort compares (the cell line)
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
    "treatment": pl.Utf8,
    "replicate": pl.Utf8,
    "group": pl.Utf8,
    "fastq_1": pl.Utf8,
    "fastq_2": pl.Utf8,
}

# "<SRR accession>_<GSM accession>_<cell line>_<condition...>". Only the first
# three underscore-separated tokens are structural; everything after the cell
# line is the condition, comma-free so it survives as one token.
_NAME_PATTERN = r"^(SRR\d+)_(GSM\d+)_([A-Za-z0-9]+)_(.+)$"

# The condition, split into what was done and which replicate of it this is.
# Two spellings occur and they need different greediness, so they are two
# patterns rather than one alternation: `low_oxygen_Q1` separates the replicate
# token with an underscore (take the LAST one, hence the greedy prefix), while
# `J2` glues a numeric replicate to an alphabetic treatment. A condition that
# matches neither carries no replicate token and is the whole treatment.
_SEPARATED_TREATMENT = r"^(.+)_[A-Za-z]*\d+$"
_SEPARATED_REPLICATE = r"^.+_([A-Za-z]*\d+)$"
_GLUED_TREATMENT = r"^([A-Za-z]+)\d+$"
_GLUED_REPLICATE = r"^[A-Za-z]+(\d+)$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Add the cell-line / treatment / replicate split on top of the samplesheet."""
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

    condition = pl.col("condition")
    replicate_token = pl.coalesce(
        condition.str.extract(_SEPARATED_REPLICATE, 1),
        condition.str.extract(_GLUED_REPLICATE, 1),
    )
    return (
        df.with_columns(
            # A condition that carries no replicate token is the whole treatment.
            pl.coalesce(
                condition.str.extract(_SEPARATED_TREATMENT, 1),
                condition.str.extract(_GLUED_TREATMENT, 1),
                condition,
            )
            .cast(pl.Utf8)
            .alias("treatment"),
            # Only the digits: `Q1` and `1` are the first replicate of their own
            # treatment, and keeping the letter would split a three-level factor
            # into six. A condition with no replicate token is its own first.
            pl.when(condition.is_null())
            .then(None)
            .otherwise(pl.coalesce(replicate_token.str.extract(r"(\d+)", 1), pl.lit("1")))
            .cast(pl.Utf8)
            .alias("replicate"),
            pl.col("cell_line").alias("group"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort("sample_id")
    )
