"""One row per nf-core/nanoseq sample, from the samplesheet the pipeline validated.

nanoseq's ``sample`` column already IS the name every output file uses (FastQC,
NanoPlot, minimap2, Bambu's count-matrix column headers all key on it
directly), so no name derivation is needed here, only unpacking.

Two of the three real factors of this cohort are not in a column of their own.
The samplesheet's ``sample`` is ``<condition>_R<replicate>``, and its
``input_file`` records which library preparation produced the FASTQ and which
flow-cell run it came off::

    A549_R1,,s3://.../SGNex_A549_cDNA_replicate1_run2.fastq.gz,GRCh37,,0,
    A549_R2,,s3://.../SGNex_A549_directcDNA_replicate3_run2.fastq.gz,GRCh37,,0,

So the three A549 libraries are not three replicates of one thing: one is cDNA
and two are direct cDNA, and they come off three different flow-cell runs. A
dashboard that offers only ``condition`` hides a confounder that is right
there in the sheet, which is why ``protocol``, ``source_replicate`` and
``run_id`` are columns here and filters on the dashboard.

Output schema:
    sample_id : Utf8         the samplesheet ``sample`` column, unmodified
    condition : Utf8         `<group>` in `<group>_R<replicate>`
    replicate : Int64        replicate number inside the condition
    protocol : Utf8          library preparation read off ``input_file``
                              (cdna, directcdna, directrna, ...), "unknown"
                              when the name does not carry one
    source_replicate : Utf8  the replicate the source dataset numbered, which
                              is not the same as `replicate` above
    run_id : Utf8            the flow-cell run the FASTQ came off
    reference : Utf8         genome/transcriptome build (the ``fasta`` column)
    is_transcripts : Boolean true when ``input_file`` is already a transcriptome
    has_fast5 : Boolean      true when a nanopolish fast5 directory was supplied
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "condition": pl.Utf8,
    "replicate": pl.Int64,
    "protocol": pl.Utf8,
    "source_replicate": pl.Utf8,
    "run_id": pl.Utf8,
    "reference": pl.Utf8,
    "is_transcripts": pl.Boolean,
    "has_fast5": pl.Boolean,
}

_REQUIRED = ["sample", "fasta"]

# `<condition>_R<replicate>`, the only structure the sample name itself carries.
_SAMPLE_RE = r"^(.*)_R(\d+)$"

# Longest alternative first: `cDNA` would otherwise match inside `directcDNA`
# and collapse the two preparations into one level.
_PROTOCOL_RE = r"(?i)[_.-](directcDNA|directRNA|dRNA|cDNA|gDNA|RNA|DNA)[_.-]"
_SOURCE_REPLICATE_RE = r"(?i)[_.-](replicate\d+|rep\d+)"
_RUN_RE = r"(?i)[_.-](run\d+|flowcell\d+|fc\d+)"


def _truthy(column: pl.Expr) -> pl.Expr:
    return column.cast(pl.Utf8).str.to_lowercase().is_in(["1", "true", "yes", "y"]).fill_null(False)


def _from_input_file(df: pl.DataFrame, pattern: str, fallback: str) -> pl.Expr:
    """A token of ``input_file``, lower-cased, or ``fallback`` when absent."""
    if "input_file" not in df.columns:
        return pl.lit(fallback, dtype=pl.Utf8)
    extracted = pl.col("input_file").cast(pl.Utf8).str.extract(pattern, 1)
    return extracted.str.to_lowercase().fill_null(fallback)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"nanoseq samples: samplesheet lacks columns {missing}")

    split = pl.col("sample").str.extract(_SAMPLE_RE, 1)
    replicate = pl.col("sample").str.extract(_SAMPLE_RE, 2)

    if "nanopolish_fast5" in df.columns:
        has_fast5 = pl.col("nanopolish_fast5").cast(pl.Utf8).fill_null("").str.len_chars() > 0
    else:
        has_fast5 = pl.lit(False)

    is_transcripts = (
        _truthy(pl.col("is_transcripts")) if "is_transcripts" in df.columns else pl.lit(False)
    )

    df = df.with_columns(
        pl.col("sample").cast(pl.Utf8).alias("sample_id"),
        pl.when(split.is_not_null()).then(split).otherwise(pl.col("sample")).alias("condition"),
        replicate.cast(pl.Int64, strict=False).alias("replicate"),
        _from_input_file(df, _PROTOCOL_RE, "unknown").alias("protocol"),
        _from_input_file(df, _SOURCE_REPLICATE_RE, "unknown").alias("source_replicate"),
        _from_input_file(df, _RUN_RE, "unknown").alias("run_id"),
        pl.col("fasta").cast(pl.Utf8).alias("reference"),
        is_transcripts.alias("is_transcripts"),
        has_fast5.alias("has_fast5"),
    )
    return df.select(list(EXPECTED_SCHEMA)).unique(subset=["sample_id"]).sort("sample_id")
