"""Parse AGAT ``agat_sp_statistics.pl`` reports into a long table.

The report is plain text, one block per feature type::

    ------------------------------------- mrna -------------------------------------
    Number of gene                                              9934
    Number of mrna                                              23471
    mean exons per mrna                                         10.4
    ...
    mrna have isoforms! Here are the statistics without isoforms shortest isoforms excluded):

    Number of gene                                              9934
    Number of mrna                                              9934
    ...

A metric is the text before the run of spaces, its value the last token (``na``
when AGAT has nothing to say, read as null). The lines after "have isoforms!"
describe the same feature type with one transcript per gene, the longest, so
they are tagged ``longest`` and the lines before ``all``. A type without
isoforms has only the ``all`` block.

Shared by the catalog ``agat`` outputs, which read one report two ways (recipes
may not import each other).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

RAW_LINE_COL = "raw_line"
SOURCE_PATH_COL = "source_path"

#: The raw-line read every AGAT recipe uses: one line per row, nothing parsed.
READ_KWARGS: dict = {
    "separator": "\x1e",
    "has_header": False,
    "new_columns": [RAW_LINE_COL],
    "quote_char": None,
    "infer_schema_length": 0,
}

#: Long-table schema, in column order.
LONG_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "feature_type": pl.Utf8,
    "isoforms": pl.Utf8,
    "metric": pl.Utf8,
    "value": pl.Float64,
    "metric_order": pl.Int64,
}

_SECTION = re.compile(r"^-{3,}\s*(?P<name>[A-Za-z0-9_.:+-]+)\s*-{3,}\s*$")
_ISOFORMS = re.compile(r"have isoforms!", re.IGNORECASE)
_METRIC = re.compile(r"^(?P<metric>\S.*?)\s{2,}(?P<value>\S+)\s*$")
_SUFFIX = re.compile(r"(?:_stats|\.stats)?\.txt$")


def genome_of(source_path: str) -> str:
    """``agat/A/stats/A.stats.txt`` -> ``A``."""
    return _SUFFIX.sub("", PurePosixPath(str(source_path).replace("\\", "/")).name)


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def parse_reports(raw: pl.DataFrame) -> pl.DataFrame:
    """Every report of ``raw`` (one line per row, with ``source_path``) as a long table."""
    rows: list[tuple] = []
    for path, lines in (
        raw.group_by(SOURCE_PATH_COL, maintain_order=True).agg(pl.col(RAW_LINE_COL)).iter_rows()
    ):
        genome = genome_of(path)
        section: str | None = None
        isoforms = "all"
        order = 0
        for line in lines:
            if line is None:
                continue
            text = str(line).rstrip()
            head = _SECTION.match(text.strip())
            if head:
                section, isoforms, order = head.group("name").lower(), "all", 0
                continue
            if section is None or not text.strip():
                continue
            if _ISOFORMS.search(text):
                isoforms, order = "longest", 0
                continue
            metric = _METRIC.match(text.strip())
            if metric is None:
                continue
            order += 1
            rows.append(
                (
                    genome,
                    section,
                    isoforms,
                    metric.group("metric").strip(),
                    _number(metric.group("value")),
                    order,
                )
            )
    return pl.DataFrame(rows, schema=LONG_SCHEMA, orient="row")
