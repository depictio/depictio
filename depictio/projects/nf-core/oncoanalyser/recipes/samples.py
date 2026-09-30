"""Sample hub for nf-core/oncoanalyser: the run's samplesheet, one row per sample.

oncoanalyser does not publish the samplesheet it ran on, so the template reads
the file named by ``METADATA_FILE`` (by default the copy under ``input/``). The
pipeline's input schema fixes the columns this recipe relies on:

* ``group_id``: the analysis unit, one tumor (plus its optional normal and RNA)
  per group; every output is published under ``<group_id>/``;
* ``subject_id``: the patient;
* ``sample_id``: the id every per-sample output file is named after
  (``<sample_id>.purple.purity.tsv``, ``<sample_id>.bam_metric.summary.tsv``);
* ``sample_type``: ``tumor`` or ``normal``;
* ``sequence_type``: ``dna`` or ``rna``.

A sheet lists one row per input file (FASTQ lanes, BAM, CRAM), so the rows are
collapsed to one per ``sample_id``. The design columns are kept under their own
names, so ``GROUP_COL`` can name any of them, and three columns are added:

* ``sample_class``: ``sample_type`` and ``sequence_type`` joined, e.g.
  ``tumor_dna``, the role a sample plays in the run;
* ``input_files``: how many sheet rows the sample had (lanes or files);
* ``filetypes``: the distinct input file types, comma separated.

Columns specific to one input file (``info``, ``filepath``) are dropped: they
differ per lane and say nothing about the sample.

Output:
    sample_id, group_id, subject_id, sample_type, sequence_type, sample_class,
    filetypes : Utf8, input_files : Int64, <other sheet columns> : Utf8
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "group_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "sample_type": pl.Utf8,
    "sequence_type": pl.Utf8,
    "sample_class": pl.Utf8,
    "input_files": pl.Int64,
    "filetypes": pl.Utf8,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_REQUIRED = ("group_id", "subject_id", "sample_id", "sample_type", "sequence_type")
#: Per-file columns: they vary between the lanes of one sample.
_PER_FILE = ("info", "filepath", "filetype")


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with the comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.select(
        [pl.col(c).cast(pl.Utf8).str.strip_chars().alias(_sanitise(c)) for c in sheet.columns]
    )
    missing = [c for c in _REQUIRED if c not in sheet.columns]
    if missing:
        raise ValueError(
            f"oncoanalyser samplesheet: missing required column(s) {missing}; got {sheet.columns}"
        )
    extra = [c for c in sheet.columns if c not in _REQUIRED and c not in _PER_FILE]
    filetype = pl.col("filetype") if "filetype" in sheet.columns else pl.lit(None, pl.Utf8)
    out = (
        sheet.with_columns(filetype.alias("_filetype"))
        .group_by("sample_id", maintain_order=True)
        .agg(
            [pl.col(c).drop_nulls().first() for c in _REQUIRED if c != "sample_id"]
            + [pl.col(c).drop_nulls().first() for c in extra]
            + [
                pl.len().cast(pl.Int64).alias("input_files"),
                pl.col("_filetype")
                .drop_nulls()
                .unique(maintain_order=True)
                .str.join(", ")
                .alias("filetypes"),
            ]
        )
        .with_columns(
            pl.concat_str(
                [
                    pl.col("sample_type").str.to_lowercase(),
                    pl.col("sequence_type").str.to_lowercase(),
                ],
                separator="_",
            ).alias("sample_class")
        )
    )
    lead = list(EXPECTED_SCHEMA)
    return out.select(lead + [c for c in out.columns if c not in lead]).sort(
        ["group_id", "sample_type", "sequence_type", "sample_id"],
        descending=[False, True, False, False],
    )
