"""Per-sample Bismark alignment summary, one row per library.

``bismark`` writes one ``<sample>_bismark_bt2_{PE,SE}_report.txt`` per library:
a free-text report, not a table. The headline numbers MultiQC's own
``bismark_alignment`` bar plot draws live only in the report's parquet-backed
panel; this recipe reads the same report directly so the exact counts (not
just the bar) are queryable, sortable and filterable as a table and as cards.

Input: the ``bismark_alignment_raw`` data collection, a recursive Table scan of
the per-sample reports read one LINE per row (the report mixes a handful of
plain sentences with `Key:\\tValue` lines, so no single tabular shape fits the
whole file). The DC must therefore be declared with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*_bismark_bt2_(PE|SE)_report\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "|"            # a byte absent from the report; one row = one line
          has_header: false
          new_columns: ["line"]
          include_file_paths: source_path   # carries the sample id
          infer_schema_length: 0

Output schema:
    sample : Utf8               library Bismark aligned
    pairs_analysed : Int64      sequence pairs (or reads, SE) Bismark attempted
    unique_best_hit : Int64     pairs with a single unambiguous best alignment
    mapping_efficiency_pct : Float64  unique_best_hit / pairs_analysed, as Bismark reports it
    no_alignment : Int64        pairs with no alignment under any condition
    not_unique : Int64          pairs that mapped, but not to one unique place
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads (see module docstring).
RAW_DC_TAG = "bismark_alignment_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "pairs_analysed": pl.Int64,
    "unique_best_hit": pl.Int64,
    "mapping_efficiency_pct": pl.Float64,
    "no_alignment": pl.Int64,
    "not_unique": pl.Int64,
}

SOURCE_PATH_COL = "source_path"

# TrimGalore always merges a pair's report under the read-1 basename
# (`_1_val_1` / `_val_1`), so the suffix strips both PE and SE reports.
_SUFFIX_RE = re.compile(r"(_\d+)?_val_\d+_bismark_bt2_(PE|SE)_report\.txt$")

_FIELDS: dict[str, re.Pattern[str]] = {
    "pairs_analysed": re.compile(
        r"Sequence pairs analysed in total:\t(\d+)|Sequences analysed in total:\t(\d+)"
    ),
    "unique_best_hit": re.compile(
        r"Number of paired-end alignments with a unique best hit:\t(\d+)"
        r"|Number of alignments with a unique best hit from the different alignments:\t(\d+)"
    ),
    "mapping_efficiency_pct": re.compile(r"Mapping efficiency:\t([\d.]+)\s*%"),
    "no_alignment": re.compile(
        r"Sequence pairs with no alignments under any condition:\t(\d+)"
        r"|Sequences with no alignments under any condition:\t(\d+)"
    ),
    "not_unique": re.compile(
        r"Sequence pairs did not map uniquely:\t(\d+)|Sequences did not map uniquely:\t(\d+)"
    ),
}


def _sample_id(path: str) -> str:
    name = Path(str(path)).name
    return _SUFFIX_RE.sub("", name)


def _first_group(match: re.Match[str]) -> str:
    return next(g for g in match.groups() if g is not None)


def _parse_report(sample: str, text: str) -> dict[str, object]:
    row: dict[str, object] = {"sample": sample}
    for field, pattern in _FIELDS.items():
        match = pattern.search(text)
        if match is None:
            row[field] = None
            continue
        value = _first_group(match)
        row[field] = float(value) if field == "mapping_efficiency_pct" else int(value)
    return row


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Re-assemble each report from its lines, then parse it into one row."""
    raw = sources["lines"]
    if raw.is_empty():
        raise ValueError("bismark_alignment_summary: the scanned reports are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "bismark_alignment_summary: the raw scan must carry include_file_paths=source_path"
        )

    rows: list[dict[str, object]] = []
    for (source_path,), part in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        sample = _sample_id(source_path)
        text = "\n".join(line or "" for line in part.get_column("line").to_list())
        rows.append(_parse_report(sample, text))

    if not rows:
        raise ValueError("bismark_alignment_summary: no report produced a row")

    frame = pl.DataFrame(rows, infer_schema_length=None)
    return frame.select(
        pl.col("sample"),
        pl.col("pairs_analysed").cast(pl.Int64, strict=False),
        pl.col("unique_best_hit").cast(pl.Int64, strict=False),
        pl.col("mapping_efficiency_pct").cast(pl.Float64, strict=False),
        pl.col("no_alignment").cast(pl.Int64, strict=False),
        pl.col("not_unique").cast(pl.Int64, strict=False),
    ).sort("sample")
