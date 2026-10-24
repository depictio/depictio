"""Parse RepeatMasker ``.tbl`` summaries.

RepeatMasker closes every run with a fixed-width summary table::

    ==================================================
    file name: genome.fna
    sequences:           177
    total length:  225250884 bp  (223937270 bp excl N/X-runs)
    GC level:         32.53 %
    bases masked:   38935182 bp ( 17.29 %)
    ==================================================
                   number of      length   percentage
                   elements*    occupied  of sequence
    --------------------------------------------------
    Retroelements        18689      2803554 bp    1.24 %
       SINEs:              335        41217 bp    0.02 %
       ...
         L2/CR1/Rex       2394       171922 bp    0.08 %
    ...
    Total interspersed repeats:    27682653 bp   12.29 %

The header gives the assembly totals; the body one line per repeat class, its
depth in the hierarchy given by the indent (none for a top class, three spaces
for a class of retroelement or transposon, five for a family). A name can wrap
onto the next line (``Other (Mirage,`` then ``P-element, Transib)``).

Every body line is read with a ``rank``:

* ``Class``: the classes that partition what was masked (SINEs, LINEs, LTR
  elements and Penelope under the retroelements, then DNA transposons,
  rolling-circles, unclassified, small RNA, satellites, simple repeats and low
  complexity), the ones a composition bar stacks;
* ``Family``: the families under a class (L2/CR1/Rex, Gypsy/DIRS1, Tc1-IS630-Pogo...);
* ``Summary``: the two lines that add classes up (Retroelements, Total
  interspersed repeats), never stacked with the rest.

Shared by the catalog ``repeatmasker`` outputs (recipes may not import each other).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

RAW_LINE_COL = "raw_line"
SOURCE_PATH_COL = "source_path"

READ_KWARGS: dict = {
    "separator": "\x1e",
    "has_header": False,
    "new_columns": [RAW_LINE_COL],
    "quote_char": None,
    "infer_schema_length": 0,
}

CLASS_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "repeat_class": pl.Utf8,
    "parent_class": pl.Utf8,
    "rank": pl.Utf8,
    "class_order": pl.Int64,
    "elements": pl.Int64,
    "length_bp": pl.Int64,
    "genome_pct": pl.Float64,
}

SUMMARY_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "sequences": pl.Int64,
    "total_length": pl.Int64,
    "length_excl_n": pl.Int64,
    "gc_pct": pl.Float64,
    "masked_bp": pl.Int64,
    "masked_pct": pl.Float64,
}

#: Top-level lines that add classes up rather than being one.
SUMMARY_LINES = frozenset({"retroelements", "total interspersed repeats"})

#: One body line, stripped: name, element count (absent on the totals), length, share.
_BODY = re.compile(
    r"^(?P<name>\S.*?):?\s+(?:(?P<elements>\d+)\s+)?(?P<length>\d+)\s+bp\s+"
    r"(?P<pct>[\d.]+)\s*%\s*$"
)
_HEADER_NUM = re.compile(r"^(?P<key>[a-zA-Z ]+):\s*(?P<rest>.*)$")
_SUFFIX = re.compile(r"\.tbl$")


def genome_of(source_path: str) -> str:
    """``repeatmasker/A/A.tbl`` -> ``A``."""
    return _SUFFIX.sub("", PurePosixPath(str(source_path).replace("\\", "/")).name)


def _first_int(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _header(lines: list[str]) -> dict:
    out: dict = {"sequences": None, "total_length": None, "length_excl_n": None}
    out.update({"gc_pct": None, "masked_bp": None, "masked_pct": None})
    for line in lines:
        match = _HEADER_NUM.match(line.strip())
        if match is None:
            continue
        key, rest = match.group("key").strip().lower(), match.group("rest")
        if key == "sequences":
            out["sequences"] = _first_int(rest)
        elif key == "total length":
            numbers = re.findall(r"(\d+)\s*bp", rest)
            out["total_length"] = int(numbers[0]) if numbers else None
            out["length_excl_n"] = int(numbers[1]) if len(numbers) > 1 else None
        elif key == "gc level":
            pct = re.search(r"[\d.]+", rest)
            out["gc_pct"] = float(pct.group(0)) if pct else None
        elif key == "bases masked":
            out["masked_bp"] = _first_int(rest)
            pct = re.search(r"\(\s*([\d.]+)\s*%", rest)
            out["masked_pct"] = float(pct.group(1)) if pct else None
    return out


def _lines_by_file(raw: pl.DataFrame) -> list[tuple[str, list[str]]]:
    grouped = raw.group_by(SOURCE_PATH_COL, maintain_order=True).agg(pl.col(RAW_LINE_COL))
    return [(path, [str(x) for x in lines if x is not None]) for path, lines in grouped.iter_rows()]


def _level(indent: int) -> int:
    """Hierarchy level of a body line from its indent: 0 top, 1 class, 2 family, 3 below."""
    if indent == 0:
        return 0
    if indent <= 3:
        return 1
    return 2 if indent <= 5 else 3


def parse_classes(raw: pl.DataFrame) -> pl.DataFrame:
    """Every repeat class line of every table, with its rank and parent class."""
    rows: list[list] = []
    for path, lines in _lines_by_file(raw):
        genome = genome_of(path)
        in_body, order = False, 0
        # (indent, name) of the open lines above the current one.
        stack: list[tuple[int, str]] = []
        last: list | None = None
        for line in lines:
            text = line.rstrip()
            if text.startswith("-----"):
                in_body = True
                continue
            if not in_body or not text.strip():
                continue
            if text.startswith("====="):
                break
            indent = len(text) - len(text.lstrip())
            match = _BODY.match(text.strip())
            if match is None:
                # The wrapped tail of the previous name ("P-element, Transib)").
                if last is not None and indent > 0:
                    last[1] = f"{last[1]} {text.strip()}"
                continue
            name = re.sub(r"\s+", " ", match.group("name")).strip().rstrip(":").strip()
            # RepeatMasker's indents drift by a space within a level (CRE/SLACS
            # sits at 4, its siblings at 5), so they are bucketed into levels.
            level = _level(indent)
            while stack and stack[-1][0] >= level:
                stack.pop()
            top = stack[0][1] if stack else None
            parent = stack[-1][1] if stack else None
            if indent == 0:
                rank = "Summary" if name.lower() in SUMMARY_LINES else "Class"
            elif top is not None and top.lower() in SUMMARY_LINES and len(stack) == 1:
                # SINEs, LINEs, LTR elements, Penelope: the classes the
                # retroelement line adds up.
                rank = "Class"
            else:
                rank = "Family"
            order += 1
            elements = match.group("elements")
            last = [
                genome,
                name,
                parent,
                rank,
                order,
                int(elements) if elements is not None else None,
                int(match.group("length")),
                float(match.group("pct")),
            ]
            rows.append(last)
            stack.append((level, name))
    return pl.DataFrame([tuple(r) for r in rows], schema=CLASS_SCHEMA, orient="row")


def parse_summaries(raw: pl.DataFrame) -> pl.DataFrame:
    """The header totals of every table, one row per assembly."""
    rows = []
    for path, lines in _lines_by_file(raw):
        head = _header(lines)
        if head["total_length"] is None and head["masked_bp"] is None:
            continue
        rows.append({"genome": genome_of(path), **head})
    return pl.DataFrame(rows, schema=SUMMARY_SCHEMA)
