"""Adaptor and vector calls of FCS-adaptor, from its ``*.fcs_adaptor_report.txt``.

The report is a ``#``-prefixed header and one row per flagged sequence::

    #accession  length  action  range  name

``range`` lists one or more ``start..end`` spans, comma-separated. Each span is
one output row. An assembly whose report has no row keeps one row with action
``none``, so a clean assembly counts as screened. The ``ACTION_`` prefix FCS
writes (``ACTION_TRIM``) is dropped. The assembly is the file name before
``.fcs_adaptor_report.txt``.

Input: every ``*.fcs_adaptor_report.txt`` under the run, one line per row,
with its path in ``source_path``.

Output schema:
    genome : Utf8        assembly, from the file name
    seq_id : Utf8        flagged sequence (null on a ``none`` row)
    seq_len : Int64      its length
    action : Utf8        TRIM, EXCLUDE... or none
    start : Int64        span start, 1-based
    end : Int64          span end, inclusive
    flagged_bp : Int64   bases in the span (0 on a ``none`` row)
    adaptor : Utf8       the adaptor or vector matched (``Pacific Biosciences Blunt Adapter``)
    source_type : Utf8   ADAPTOR or VECTOR, from FCS's ``CONTAMINATION_SOURCE_TYPE_`` tag
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
        glob_pattern="**/*.fcs_adaptor_report.txt",
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
    "seq_len": pl.Int64,
    "action": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "flagged_bp": pl.Int64,
    "adaptor": pl.Utf8,
    "source_type": pl.Utf8,
}

_SUFFIX = re.compile(r"\.fcs_adaptor_report\.txt$")
_SPAN = re.compile(r"(\d+)\.\.(\d+)")
_SOURCE = re.compile(r"CONTAMINATION_SOURCE_TYPE_(?P<type>[A-Z]+)")


def _name_parts(text: str) -> tuple[str | None, str | None]:
    """``CONTAMINATION_SOURCE_TYPE_ADAPTOR:NGB00972.1:PacBio Blunt`` -> (``PacBio Blunt``, ``ADAPTOR``)."""
    text = text.strip()
    if not text:
        return None, None
    source = _SOURCE.search(text)
    return text.rsplit(":", 1)[-1].strip() or text, source.group("type") if source else None


def genome_of(source_path: str) -> str:
    return _SUFFIX.sub("", PurePosixPath(str(source_path).replace("\\", "/")).name)


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
            cells += [""] * (5 - len(cells))
            try:
                seq_len = int(cells[1])
            except ValueError:
                seq_len = None
            action = re.sub(r"^ACTION_", "", cells[2].strip()) or None
            adaptor, source_type = _name_parts(cells[4])
            spans = [(int(a), int(b)) for a, b in _SPAN.findall(cells[3])] or [(None, None)]
            for start, end in spans:
                rows.append(
                    {
                        "genome": genome,
                        "seq_id": cells[0].strip(),
                        "seq_len": seq_len,
                        "action": action,
                        "start": start,
                        "end": end,
                        "flagged_bp": (end - start + 1) if start is not None else seq_len,
                        "adaptor": adaptor,
                        "source_type": source_type,
                    }
                )
            flagged += 1
        if flagged == 0:
            rows.append({"genome": genome, "action": "none", "flagged_bp": 0})
    if not rows:
        raise ValueError("fcsadaptor_actions: no FCS-adaptor report found")
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA).sort(["genome", "seq_id"], nulls_last=True)
