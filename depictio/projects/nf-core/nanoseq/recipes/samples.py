"""One row per nf-core/nanoseq sample, from the samplesheet the pipeline validated.

Unlike cutandrun, nanoseq's ``sample`` column already IS the name every output
file uses (FastQC, NanoPlot, minimap2, Bambu's count-matrix column headers all
key on it directly), so no name derivation is needed here, only tidying: the
group (``A549`` / ``K562``) and replicate number split out of ``<group>_R<n>``
for the sample-sheet card and the QC-thresholds grouping, and the reference
genome/transcriptome columns cast to a readable form.

Output schema:
    sample_id : Utf8        the samplesheet ``sample`` column, unmodified
    condition : Utf8        `<group>` in `<group>_R<replicate>` (the biological condition)
    replicate : Int64       replicate number inside the condition
    reference : Utf8        genome/transcriptome build (the ``fasta`` column)
    is_transcripts : Boolean true when ``input_file`` is already a transcriptome, not reads
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
    "reference": pl.Utf8,
    "is_transcripts": pl.Boolean,
    "has_fast5": pl.Boolean,
}

_REQUIRED = ["sample", "fasta"]


def _truthy(column: pl.Expr) -> pl.Expr:
    return column.cast(pl.Utf8).str.to_lowercase().is_in(["1", "true", "yes", "y"]).fill_null(False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["samplesheet"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"nanoseq samples: samplesheet lacks columns {missing}")

    split = pl.col("sample").str.extract(r"^(.*)_R(\d+)$", 1)
    replicate = pl.col("sample").str.extract(r"^(.*)_R(\d+)$", 2)

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
        pl.col("fasta").cast(pl.Utf8).alias("reference"),
        is_transcripts.alias("is_transcripts"),
        has_fast5.alias("has_fast5"),
    )
    return df.select(list(EXPECTED_SCHEMA)).unique(subset=["sample_id"]).sort("sample_id")
