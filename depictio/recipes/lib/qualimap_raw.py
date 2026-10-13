"""Read Qualimap BamQC's raw per-position tables, which never name their sample.

Qualimap BamQC publishes a per-sample directory (``<sample>_stats/``,
``<sample>_rmdup_stats/`` after deduplication, ``<sample>/`` on some wrappers)
holding ``genome_results.txt`` and a ``raw_data_qualimapReport/`` subdirectory
(``raw_data/`` on Qualimap builds before 2.2) with one plain table per plot:
``coverage_across_reference.txt``, ``coverage_histogram.txt``,
``genome_fraction_coverage.txt`` and seven more.

Every one of those tables has the same shape: a single ``#``-prefixed header
line, then tab-separated numeric columns. None of them carries the sample name,
which lives only in the directory two or three levels up, so the recipes that
read them all need the same two things and get them here:

* :func:`sample_from_report_path`, the sample id, walking past whichever
  ``raw_data*`` directory the Qualimap build wrote.
* :func:`split_columns`, the tab split, applied to the raw one-line-per-row
  scan the data collections use (a separator the tables cannot contain, so
  nothing splits before the recipe sees it and a table's column count is not
  baked into the scan).

Shared here rather than copied because four catalog recipes in one tool need
exactly this, and recipes may not import each other.
"""

from __future__ import annotations

import polars as pl

#: Column holding one full line of the table (the raw DC scans with a separator
#: the file cannot contain, so every line lands in this single column).
RAW_LINE_COL = "raw"
#: Column carrying the table's path (``include_file_paths`` on the raw DC).
SOURCE_PATH_COL = "source_path"

#: Directories Qualimap interposes between the sample directory and the table.
_RAW_DIRS = frozenset({"raw_data_qualimapreport", "raw_data"})

#: Trailing underscore-separated tokens of the sample directory that describe a
#: processing stage rather than the sample: Qualimap's own ``_stats`` suffix,
#: plus the dedupper stage a pipeline ran before BamQC (Picard MarkDuplicates
#: writes ``_rmdup``, DeDup writes ``_dedup``).
_STAGE_TOKENS = frozenset({"stats", "rmdup", "dedup", "results", "bamqc"})


def sample_from_report_path(source_path: str) -> str:
    """The sample id a Qualimap table belongs to, read off its directory.

    Never returns an empty string: a directory made entirely of stage tokens is
    handed back as it came, because dropping it would merge two samples.
    """
    parts = str(source_path).replace("\\", "/").split("/")[:-1]
    while parts and parts[-1].lower() in _RAW_DIRS:
        parts.pop()
    dirname = parts[-1] if parts else ""
    tokens = dirname.split("_")
    while len(tokens) > 1 and tokens[-1].lower() in _STAGE_TOKENS:
        tokens.pop()
    return "_".join(tokens) or dirname


def split_columns(raw: pl.DataFrame, names: list[str], *, recipe: str) -> pl.DataFrame:
    """``sample`` plus one Utf8 column per name, split off the raw line column.

    Rows shorter than ``names`` come back with nulls rather than raising: a
    Qualimap table truncated by an interrupted run should cost its rows, not
    the whole collection.
    """
    if raw.is_empty():
        raise ValueError(f"{recipe}: the scanned tables are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"{recipe}: no {column} column, the data collection must scan one "
                f"line per row with include_file_paths: source_path"
            )

    fields = pl.col(RAW_LINE_COL).str.strip_chars().str.split("\t")
    return (
        raw.filter(pl.col(RAW_LINE_COL).is_not_null() & (pl.col(RAW_LINE_COL).str.len_chars() > 0))
        .filter(~pl.col(RAW_LINE_COL).str.starts_with("#"))
        .with_columns(fields.alias("__fields"))
        .select(
            pl.col(SOURCE_PATH_COL)
            .map_elements(sample_from_report_path, return_dtype=pl.Utf8)
            .alias("sample"),
            *[
                pl.col("__fields").list.get(i, null_on_oob=True).str.strip_chars().alias(name)
                for i, name in enumerate(names)
            ],
        )
    )


#: Marker opening the per-contig block that closes ``genome_results.txt``.
CONTIG_MARKER = ">>>>>>> Coverage per contig"

#: Columns of :func:`contig_coverage_block`, in the order the block writes them.
CONTIG_BLOCK_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chromosome": pl.Utf8,
    "length": pl.Int64,
    "mapped_bases": pl.Int64,
    "mean_coverage": pl.Float64,
    "coverage_std": pl.Float64,
}


def _int_or_none(text: str | None) -> int | None:
    try:
        return int(float(text))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _float_or_none(text: str | None) -> float | None:
    try:
        return float(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def contig_coverage_block(raw: pl.DataFrame, *, recipe: str) -> pl.DataFrame:
    """One row per (sample, contig) from the ``Coverage per contig`` block, in file order.

    ``raw`` is the one-line-per-row scan of ``genome_results.txt``. The block lists
    every reference sequence as contig, length, mapped bases, mean depth and depth
    standard deviation, tab-separated and leading-tab indented. A line whose length
    does not parse is skipped outright; the other three numbers are null when they
    are missing or unparsable, so each caller decides whether a contig without a
    depth is worth a row. Rows keep the file's order, which is the reference order
    Qualimap concatenated its genome-wide axis in.

    Raises ``ValueError`` when the scan is empty or lacks the two columns. Returns
    an empty frame (with :data:`CONTIG_BLOCK_SCHEMA`) when no report carries the
    block, which Qualimap omits on a single-sequence reference.
    """
    if raw.is_empty():
        raise ValueError(f"{recipe}: the scanned reports are empty")
    for column in (RAW_LINE_COL, SOURCE_PATH_COL):
        if column not in raw.columns:
            raise ValueError(
                f"{recipe}: no {column} column, the data collection must scan one "
                f"line per row with include_file_paths: source_path"
            )

    rows: list[dict] = []
    for (path,), group in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        sample = sample_from_report_path(str(path))
        in_block = False
        for line in group[RAW_LINE_COL].to_list():
            text = line or ""
            if text.startswith(CONTIG_MARKER):
                in_block = True
                continue
            if not in_block:
                continue
            if text.startswith(">>>>>>>"):
                break
            fields = [f for f in text.split("\t") if f]
            if len(fields) < 2:
                continue
            length = _int_or_none(fields[1])
            if length is None:
                continue
            rows.append(
                {
                    "sample": sample,
                    "chromosome": fields[0],
                    "length": length,
                    "mapped_bases": _int_or_none(fields[2]) if len(fields) > 2 else None,
                    "mean_coverage": _float_or_none(fields[3]) if len(fields) > 3 else None,
                    "coverage_std": _float_or_none(fields[4]) if len(fields) > 4 else None,
                }
            )
    return pl.DataFrame(rows, schema=CONTIG_BLOCK_SCHEMA)
