"""Sample hub for nf-core/hlatyping: one row per sample of the run.

hlatyping reads its samplesheet from ``--input`` and does not publish it in this
release, so the template reads the file named by ``METADATA_FILE`` (by default
the copy under ``input/``). The pipeline's input schema (2.2.0) fixes
``sample`` and ``seq_type`` (``dna`` or ``rna``), with either ``fastq_1`` (and
``fastq_2`` for paired-end reads) or ``bam``. A sample may take several rows:
its FASTQ runs are concatenated before typing.

One row per sample. Every sheet column is kept under its own name (sanitised to
``[0-9A-Za-z_]``, the first non-empty value of the sample's rows), so
``GROUP_COL`` can name any column a user adds, and five are derived:

* ``seq_type``: ``DNA`` or ``RNA``, the template's default ``GROUP_COL``. It
  picks the HLA reference the reads are mapped to (exome / genome against
  transcript sequences), so the two read differently;
* ``input_format``: ``FASTQ`` or ``BAM``;
* ``read_layout``: ``Paired-end`` or ``Single-end`` for FASTQ input, ``From BAM``
  for a BAM, whose layout the pipeline reads from the file;
* ``runs``: the sheet rows of the sample, concatenated by the pipeline;
* ``input_files``: the input file names, comma-separated.

A sample OptiType typed but the sheet does not list (a sheet given for another
run, or none at all) still gets a row, with ``seq_type`` ``Not stated``, so
every typed sample reaches the filters.
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.optitype import sample_of

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: a tab-separated sheet is read as one column and re-split
    # by _fix_delimiter, so the required columns only exist after transform() starts.
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
    RecipeSource(
        ref="results",
        input_schema={"source_path": pl.Utf8},
        glob_pattern="optitype/*/*_result.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "seq_type": pl.Utf8,
    "input_format": pl.Utf8,
    "read_layout": pl.Utf8,
    "runs": pl.Int64,
    "input_files": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

NOT_STATED = "Not stated"
_SEQ_TYPES = {"dna": "DNA", "rna": "RNA"}
_FILE_COLUMNS = ("fastq_1", "fastq_2", "bam")


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with a comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def _basename(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).rstrip("/").split("/")[-1]


def _blank_to_null(column: str) -> pl.Expr:
    return (
        pl.when(pl.col(column).str.strip_chars() == "")
        .then(None)
        .otherwise(pl.col(column).str.strip_chars())
        .alias(column)
    )


def _sheet_rows(sheet: pl.DataFrame) -> pl.DataFrame:
    sheet = _fix_delimiter(sheet)
    sheet = sheet.select([pl.col(c).cast(pl.Utf8).alias(_sanitise(c)) for c in sheet.columns])
    if "sample" not in sheet.columns:
        raise ValueError(
            f"hlatyping samplesheet: missing required column 'sample'; got {sheet.columns}"
        )
    for column in ("seq_type", *_FILE_COLUMNS):
        if column not in sheet.columns:
            sheet = sheet.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    sheet = sheet.with_columns([_blank_to_null(c) for c in sheet.columns])
    return sheet.filter(pl.col("sample").is_not_null())


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sheet = sources.get("samplesheet")
    typed = sorted({sample_of(p) for p in sources["results"]["source_path"].to_list()})

    if sheet is not None and not sheet.is_empty():
        rows = _sheet_rows(sheet)
    else:
        rows = pl.DataFrame(
            {"sample": [], "seq_type": [], **{c: [] for c in _FILE_COLUMNS}},
            schema={c: pl.Utf8 for c in ("sample", "seq_type", *_FILE_COLUMNS)},
        )

    files = [pl.col(c).map_elements(_basename, return_dtype=pl.Utf8) for c in _FILE_COLUMNS]
    rows = rows.with_columns(
        pl.concat_list(files).list.drop_nulls().list.join(", ").alias("_files"),
        pl.when(pl.col("bam").is_not_null())
        .then(pl.lit("BAM"))
        .when(pl.col("fastq_1").is_not_null())
        .then(pl.lit("FASTQ"))
        .otherwise(None)
        .alias("_format"),
        pl.when(pl.col("bam").is_not_null())
        .then(pl.lit("From BAM"))
        .when(pl.col("fastq_2").is_not_null())
        .then(pl.lit("Paired-end"))
        .when(pl.col("fastq_1").is_not_null())
        .then(pl.lit("Single-end"))
        .otherwise(None)
        .alias("_layout"),
    )
    extra = [c for c in rows.columns if c not in ("sample", "seq_type", *_FILE_COLUMNS)]
    extra = [c for c in extra if not c.startswith("_")]
    per_sample = rows.group_by("sample", maintain_order=True).agg(
        pl.col("seq_type").drop_nulls().first(),
        pl.col("_format").drop_nulls().first().alias("input_format"),
        pl.col("_layout").drop_nulls().first().alias("read_layout"),
        pl.len().cast(pl.Int64).alias("runs"),
        pl.col("_files").filter(pl.col("_files") != "").str.join(", ").alias("input_files"),
        *[pl.col(c).drop_nulls().first() for c in extra],
    )
    missing = [s for s in typed if s not in set(per_sample["sample"].to_list())]
    if missing:
        per_sample = pl.concat(
            [per_sample, pl.DataFrame({"sample": missing, "runs": [0] * len(missing)})],
            how="diagonal_relaxed",
        )
    out = per_sample.with_columns(
        pl.col("seq_type")
        .str.to_lowercase()
        .replace(_SEQ_TYPES)
        .fill_null(NOT_STATED)
        .alias("seq_type"),
        pl.col("runs").cast(pl.Int64),
        pl.when(pl.col("input_files") == "")
        .then(None)
        .otherwise(pl.col("input_files"))
        .alias("input_files"),
    )
    lead = list(OUTPUT_SCHEMA)
    return out.select(lead + [c for c in out.columns if c not in lead]).sort("sample")
