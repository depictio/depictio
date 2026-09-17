"""Per-sample Bismark deduplication summary, one row per library.

``deduplicate_bismark`` writes one ``<sample>_bismark_bt2_pe.deduplication_report.txt``
per library, five short lines, not a table. MultiQC's ``bismark_deduplication``
bar plot draws the duplication share alone; this recipe keeps the raw counts
(examined, removed, leftover) queryable as a table and as threshold cards.

Input: the ``bismark_dedup_raw`` data collection, a recursive Table scan of the
per-sample reports read one LINE per row (see ``alignment_summary.py`` for why:
the report is prose plus `Key:\\tValue` lines, not one tabular shape). The DC
must be declared with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.deduplication_report\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "|"
          has_header: false
          new_columns: ["line"]
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8                  library deduplicate_bismark ran on
    total_alignments : Int64       alignments examined before deduplication
    duplicates_removed : Int64     alignments dropped as duplicates
    pct_duplication : Float64      duplicates_removed / total_alignments * 100
    leftover_sequences : Int64     alignments kept after deduplication
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "bismark_dedup_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_alignments": pl.Int64,
    "duplicates_removed": pl.Int64,
    "pct_duplication": pl.Float64,
    "leftover_sequences": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

_SUFFIX_RE = re.compile(r"(_\d+)?_val_\d+_bismark_bt2_(pe|se)\.deduplication_report\.txt$")

_TOTAL_RE = re.compile(r"Total number of alignments analysed in [^:]+:\t(\d+)")
_REMOVED_RE = re.compile(r"Total number duplicated alignments removed:\t(\d+)\s*\(([\d.]+)%\)")
_LEFTOVER_RE = re.compile(r"Total count of deduplicated leftover sequences:\s*(\d+)")


def _sample_id(path: str) -> str:
    name = Path(str(path)).name
    return _SUFFIX_RE.sub("", name)


def _parse_report(sample: str, text: str) -> dict[str, object]:
    total = _TOTAL_RE.search(text)
    removed = _REMOVED_RE.search(text)
    leftover = _LEFTOVER_RE.search(text)
    return {
        "sample": sample,
        "total_alignments": int(total.group(1)) if total else None,
        "duplicates_removed": int(removed.group(1)) if removed else None,
        "pct_duplication": float(removed.group(2)) if removed else None,
        "leftover_sequences": int(leftover.group(1)) if leftover else None,
    }


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Re-assemble each report from its lines, then parse it into one row."""
    raw = sources["lines"]
    if raw.is_empty():
        raise ValueError("bismark_deduplication_summary: the scanned reports are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "bismark_deduplication_summary: the raw scan must carry include_file_paths=source_path"
        )

    rows: list[dict[str, object]] = []
    for (source_path,), part in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        sample = _sample_id(source_path)
        text = "\n".join(line or "" for line in part.get_column("line").to_list())
        rows.append(_parse_report(sample, text))

    if not rows:
        raise ValueError("bismark_deduplication_summary: no report produced a row")

    frame = pl.DataFrame(rows, infer_schema_length=None)
    return frame.select(
        pl.col("sample"),
        pl.col("total_alignments").cast(pl.Int64, strict=False),
        pl.col("duplicates_removed").cast(pl.Int64, strict=False),
        pl.col("pct_duplication").cast(pl.Float64, strict=False),
        pl.col("leftover_sequences").cast(pl.Int64, strict=False),
    ).sort("sample")
