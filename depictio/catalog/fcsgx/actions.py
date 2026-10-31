"""Contamination calls of FCS-GX, from its ``*.fcs_gx_report.txt``.

The report opens with a ``##`` line of JSON run metadata, then a ``#``-prefixed
header::

    #seq_id  start_pos  end_pos  seq_len  action  div  agg_cont_cov  top_tax_name

and one row per range the screen flags. Most assemblies have none, and their
report is the header alone. Each flagged range is one output row; an assembly
whose report has no row keeps one row with action ``none`` and null
coordinates, so a dashboard counts it as screened and clean rather than as
absent. The assembly is the file name before ``.fcs_gx_report.txt``.

Input: every ``*.fcs_gx_report.txt`` under the run, one line per row, with its
path in ``source_path``.

Output schema:
    genome : Utf8            assembly, from the file name
    seq_id : Utf8            flagged sequence (null on a ``none`` row)
    start : Int64            range start, 1-based as FCS-GX writes it
    end : Int64              range end, inclusive
    seq_len : Int64          length of the whole sequence
    action : Utf8            EXCLUDE, TRIM, FIX, REVIEW, INFO... or none
    division : Utf8          contaminant division (``prok:CFB group bacteria``)
    division_group : Utf8    its kingdom code before the colon (prok, fung, anml, synt...)
    contaminant_cov : Float64  FCS-GX's aggregate contaminant coverage of the range, percent
    top_taxon : Utf8         the best-matching contaminant taxon
    flagged_bp : Int64       bases in the range (0 on a ``none`` row)
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_LINE_COL = "raw_line"
SOURCE_PATH_COL = "source_path"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="reports",
        glob_pattern="**/*.fcs_gx_report.txt",
        format="csv",
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "new_columns": [RAW_LINE_COL],
            "quote_char": None,
            "infer_schema_length": 0,
        },
        source_path=SOURCE_PATH_COL,
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "seq_id": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "seq_len": pl.Int64,
    "action": pl.Utf8,
    "division": pl.Utf8,
    "division_group": pl.Utf8,
    "contaminant_cov": pl.Float64,
    "top_taxon": pl.Utf8,
    "flagged_bp": pl.Int64,
}

_SUFFIX = re.compile(r"\.fcs_gx_report\.txt$")


def genome_of(source_path: str) -> str:
    return _SUFFIX.sub("", PurePosixPath(str(source_path).replace("\\", "/")).name)


def _int(text: str | None) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _float(text: str | None) -> float | None:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    raw = sources["reports"]
    rows: list[dict] = []
    for path, lines in (
        raw.group_by(SOURCE_PATH_COL, maintain_order=True).agg(pl.col(RAW_LINE_COL)).iter_rows()
    ):
        genome = genome_of(path)
        flagged = 0
        for line in lines:
            if line is None or not str(line).strip() or str(line).startswith("#"):
                continue
            cells = str(line).rstrip("\r\n").split("\t")
            cells += [""] * (8 - len(cells))
            start, end = _int(cells[1]), _int(cells[2])
            division = cells[5].strip() or None
            rows.append(
                {
                    "genome": genome,
                    "seq_id": cells[0].strip(),
                    "start": start,
                    "end": end,
                    "seq_len": _int(cells[3]),
                    "action": cells[4].strip() or None,
                    "division": division,
                    "division_group": division.split(":", 1)[0] if division else None,
                    "contaminant_cov": _float(cells[6]),
                    "top_taxon": cells[7].strip() or None,
                    "flagged_bp": (end - start + 1)
                    if start is not None and end is not None
                    else None,
                }
            )
            flagged += 1
        if flagged == 0:
            rows.append({"genome": genome, "action": "none", "flagged_bp": 0})
    if not rows:
        raise ValueError("fcsgx_actions: no FCS-GX report found")
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA).sort(["genome", "seq_id"], nulls_last=True)
