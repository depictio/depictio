"""Duplication metrics from a Picard MarkDuplicates report.

Picard writes an htsjdk metrics file: ``##``/``#`` header lines carrying the
command line and the run date, then a ``## METRICS CLASS`` marker, one header
row and one data row per library::

    ## METRICS CLASS        picard.sam.DuplicationMetrics
    LIBRARY  UNPAIRED_READS_EXAMINED  READ_PAIRS_EXAMINED  ...  PERCENT_DUPLICATION  ESTIMATED_LIBRARY_SIZE
    Unknown Library  16801402  0  0  0  4682948  0  0  0.278724

The ``LIBRARY`` field is whatever the read group said, which for a pipeline that
sets no read-group library is the literal ``Unknown Library``, useless as an
id, so the sample is recovered from the report's file name instead, the way
every other per-sample report in this catalog is.

Column names differ between Picard versions only by addition, so the header row
is read rather than assumed, and a column a version does not write comes back
null instead of failing the collection. The recipe also keeps only files whose
``METRICS CLASS`` is ``DuplicationMetrics``: Picard writes a dozen other metrics
files under names a duplication glob happily matches.

Two derived columns: the total duplicate reads (Picard reports unpaired and
paired duplicates separately, and a collapsed ancient-DNA library has only the
first) and the reads left after removal, which is what downstream coverage
actually rests on.

Input: a data collection reading every matched report one LINE per row (a
separator the report cannot contain), with ``include_file_paths: source_path``.

Output schema:
    sample : Utf8                    library MarkDuplicates ran on
    library : Utf8                   Picard's own LIBRARY field, as written
    unpaired_reads_examined : Int64  single-end reads considered
    read_pairs_examined : Int64      read pairs considered
    unmapped_reads : Int64           reads MarkDuplicates could not place
    unpaired_read_duplicates : Int64 single-end duplicates flagged
    read_pair_duplicates : Int64     paired duplicates flagged
    read_pair_optical_duplicates : Int64  of those, optical duplicates
    duplicate_reads : Int64          unpaired + 2 x paired duplicates
    reads_after_dedup : Int64        examined reads left once duplicates are removed
    percent_duplication : Float64    Picard's own PERCENT_DUPLICATION, 0-1
    estimated_library_size : Int64   Picard's library-size estimate (null when unreported)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

#: Data-collection tag the template must scan the reports into.
RAW_DC_TAG = "picard_markduplicates_metrics_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="reports", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "library": pl.Utf8,
    "unpaired_reads_examined": pl.Int64,
    "read_pairs_examined": pl.Int64,
    "unmapped_reads": pl.Int64,
    "unpaired_read_duplicates": pl.Int64,
    "read_pair_duplicates": pl.Int64,
    "read_pair_optical_duplicates": pl.Int64,
    "duplicate_reads": pl.Int64,
    "reads_after_dedup": pl.Int64,
    "percent_duplication": pl.Float64,
    "estimated_library_size": pl.Int64,
}

RAW_LINE_COL = "raw"
SOURCE_PATH_COL = "source_path"

_METRICS_MARKER = "## METRICS CLASS"
_DUPLICATION_CLASS = "DuplicationMetrics"

#: Picard header name -> output column. Every one is optional.
_FIELDS: dict[str, str] = {
    "UNPAIRED_READS_EXAMINED": "unpaired_reads_examined",
    "READ_PAIRS_EXAMINED": "read_pairs_examined",
    "UNMAPPED_READS": "unmapped_reads",
    "UNPAIRED_READ_DUPLICATES": "unpaired_read_duplicates",
    "READ_PAIR_DUPLICATES": "read_pair_duplicates",
    "READ_PAIR_OPTICAL_DUPLICATES": "read_pair_optical_duplicates",
    "ESTIMATED_LIBRARY_SIZE": "estimated_library_size",
}

#: Trailing dot-separated tokens of the report name that describe the dedupper
#: stage rather than the sample. ``strip_stage_suffixes`` handles the shared
#: alignment tokens; these are the MarkDuplicates-specific ones.
_REPORT_TOKENS = ("metrics", "markduplicates", "rmdup", "dedup", "duplicates")


def _sample_from_path(source_path: str) -> str:
    name = str(source_path).replace("\\", "/").rsplit("/", 1)[-1]
    stem = strip_stage_suffixes(name)
    tokens = stem.split(".")
    while len(tokens) > 1 and tokens[-1].lower() in _REPORT_TOKENS:
        tokens.pop()
    stem = ".".join(tokens)
    # eager 2.x names the report `<library>_rmdup.metrics`: the stage is joined
    # with an underscore, not a dot, so the dot-token pass above cannot see it.
    parts = stem.split("_")
    while len(parts) > 1 and parts[-1].lower() in _REPORT_TOKENS:
        parts.pop()
    return "_".join(parts)


def _parse(source_path: str, lines: list[str]) -> list[dict]:
    """Every data row of the report's DuplicationMetrics block."""
    header: list[str] | None = None
    in_block = False
    rows: list[dict] = []
    for line in lines:
        text = (line or "").rstrip("\n")
        if text.startswith(_METRICS_MARKER):
            in_block = _DUPLICATION_CLASS in text
            header = None
            continue
        if not in_block:
            continue
        if not text.strip():
            if header is not None:
                in_block = False  # blank line closes the block
            continue
        if text.startswith("#"):
            continue
        fields = text.split("\t")
        if header is None:
            header = [f.strip() for f in fields]
            continue
        values = dict(zip(header, fields))
        row: dict = {
            "sample": _sample_from_path(source_path),
            "library": (values.get("LIBRARY") or "").strip() or None,
            "percent_duplication": values.get("PERCENT_DUPLICATION"),
        }
        for picard_name, column in _FIELDS.items():
            row[column] = values.get(picard_name)
        rows.append(row)
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (report, library)."""
    raw = sources["reports"]
    if raw.is_empty():
        raise ValueError("picard_markduplicates_metrics: the scanned reports are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"picard_markduplicates_metrics: no {column} column, the data collection "
                f"must scan one line per row with include_file_paths: source_path"
            )

    records: list[dict] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        records.extend(_parse(str(path), group[RAW_LINE_COL].to_list()))

    if not records:
        raise ValueError(
            "picard_markduplicates_metrics: no report carried a "
            f"'{_METRICS_MARKER} ... {_DUPLICATION_CLASS}' block"
        )

    frame = pl.DataFrame(records, infer_schema_length=None).with_columns(
        pl.col("sample").cast(pl.Utf8),
        pl.col("library").cast(pl.Utf8),
        pl.col("percent_duplication").cast(pl.Utf8).cast(pl.Float64, strict=False),
        *[
            pl.col(column).cast(pl.Utf8).cast(pl.Float64, strict=False).cast(pl.Int64).alias(column)
            for column in _FIELDS.values()
        ],
    )

    examined = pl.col("unpaired_reads_examined").fill_null(0) + 2 * pl.col(
        "read_pairs_examined"
    ).fill_null(0)
    duplicates = pl.col("unpaired_read_duplicates").fill_null(0) + 2 * pl.col(
        "read_pair_duplicates"
    ).fill_null(0)
    return (
        frame.with_columns(
            duplicates.cast(pl.Int64).alias("duplicate_reads"),
            (examined - duplicates).cast(pl.Int64).alias("reads_after_dedup"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort("sample")
    )
