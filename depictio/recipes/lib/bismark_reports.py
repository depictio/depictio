"""Walk the per-library Bismark reports a raw line scan concatenated.

Every Bismark text report (alignment, deduplication, splitting, M-bias) is
scanned into one frame of lines with ``include_file_paths`` naming the file
each line came from. Each recipe then has to put the file back together,
recover the library from its name and parse the text. The first two steps are
the same in every recipe and live here; the parsing differs per report and
stays with the recipe, except for the M-bias table, which two recipes read
with only the choice of context differing.

Shared here rather than copied because five bismark recipes carried the same
eight-line grouping block and the two M-bias recipes carried the same parser
verbatim, and recipes may not import from one another.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import polars as pl

from depictio.recipes.lib.bismark_names import sample_id_from_filename

#: Column carrying the report's path (``include_file_paths`` on the raw DC).
SOURCE_PATH_COL = "source_path"
#: Column holding one full report line.
LINE_COL = "line"

# "CpG context (R1)" / "CHG context (R2)" / ...: the header Bismark writes
# before each of the six tables of an M-bias file.
_SECTION_RE = re.compile(r"^(CpG|CHG|CHH) context \((R[12])\)$")
# "<position>\t<methylated>\t<unmethylated>\t<% methylation>\t<coverage>"
_ROW_RE = re.compile(r"^(\d+)\t(\d+)\t(\d+)\t([\d.]+)\t(\d+)$")


def report_lines(
    raw: pl.DataFrame, recipe: str, suffix: re.Pattern[str]
) -> Iterator[tuple[str, list[str]]]:
    """``(sample, lines)`` for every report in the scan, in scan order.

    ``recipe`` names the caller in the two errors a scan can raise: an empty
    frame, and one without the path column the sample id is read from.
    """
    if raw.is_empty():
        raise ValueError(f"{recipe}: the scanned reports are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(f"{recipe}: the raw scan must carry include_file_paths={SOURCE_PATH_COL}")
    for (source_path,), part in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        sample = sample_id_from_filename(str(source_path), suffix)
        yield sample, [line or "" for line in part.get_column(LINE_COL).to_list()]


def parse_mbias(
    sample: str, lines: list[str], contexts: tuple[str, ...] | None = None
) -> list[dict[str, object]]:
    """One row per position of every M-bias section in ``contexts`` (all when None).

    Rows carry ``sample``, ``context`` (CpG / CHG / CHH), ``read`` (R1 / R2),
    ``position``, ``pct_methylation`` and ``coverage``; the caller adds the
    series label its tile wants.
    """
    rows: list[dict[str, object]] = []
    context: str | None = None
    read: str | None = None
    for line in lines:
        section = _SECTION_RE.match(line.strip())
        if section:
            context, read = section.group(1), section.group(2)
            continue
        if context is None or read is None:
            continue
        if contexts is not None and context not in contexts:
            continue
        data = _ROW_RE.match(line.strip())
        if not data:
            continue
        position, _methylated, _unmethylated, pct, coverage = data.groups()
        rows.append(
            {
                "sample": sample,
                "context": context,
                "read": read,
                "position": int(position),
                "pct_methylation": float(pct),
                "coverage": int(coverage),
            }
        )
    return rows
