"""What a report's tiles print on a page with no browser (the PDF, Quarto's typst).

The HTML report draws a table, a card strip, an unavailable tile as HTML. A
typst page reads none of it, and pandoc's own conversion of what it can read
(a markdown pipe table, a bullet list) loses the dashboard's structure. Here
each of those is typst instead, as a raw block inside the cell's markdown
output, drawn by the functions the document's PDF preamble defines
(``api/v1/services/notebook_export/pdf_typst.py``: ``dpx-table``,
``dpx-kpis``, ``dpx-kpi``, ``dpx-bars``, ``dpx-note``).

Only a render with static figures asks for these (``static_figures``), and
only the PDF render sets that.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any

import polars as pl

from depictio.notebook.qmd_safe import typst_str

#: Rows and columns a table keeps on a page; the HTML report has them all.
TABLE_ROWS = 30
TABLE_COLS = 8
# A token longer than this gets break opportunities, so a sample id or a path
# wraps inside its column instead of running off the page.
_LONG_TOKEN = 18


def tstr(text: Any) -> str:
    """A typst string literal (``qmd_safe.typst_str``)."""
    return typst_str(text)


def raw(code: str) -> str:
    """``code`` as a raw typst block of a cell's markdown output."""
    return f"\n````{{=typst}}\n{code}\n````\n"


def note(title: str, detail: str = "") -> str:
    """A tile that could not be drawn: its name and a short neutral sentence."""
    return raw(f"#dpx-note({tstr(title)}, {tstr(detail)})")


def _breakable(text: str, limit: int = _LONG_TOKEN) -> str:
    if len(text) <= limit:
        return text
    # A zero-width space after the separators a long token has.
    return re.sub(r"([_/.\-:,])", "\\1\u200b", text)


def fmt_number(value: Any) -> str:
    """A number as the dashboard prints one: thousands grouped, four
    significant digits for a fraction, none lost for a large count."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer() and abs(value) < 1e15:
            return f"{int(value):,}"
        return f"{value:,.4g}" if abs(value) < 1e6 else f"{value:,.0f}"
    return str(value)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return fmt_number(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()[:19].replace("T", " ")
    return _breakable(str(value).replace("\n", " ")[:160])


def table(df: pl.DataFrame, *, rows: int = TABLE_ROWS, cols: int = TABLE_COLS) -> str:
    """``df`` as a typst table: a styled header row, zebra rows, numbers right
    aligned and formatted, columns as wide as what they hold, and a note when
    rows or columns were left out."""
    total_rows, total_cols = df.height, df.width
    view = df.select(df.columns[:cols]).head(rows)
    numeric = [view.schema[c].is_numeric() for c in view.columns]
    body = [[_cell(v) for v in row] for row in view.iter_rows()]
    weights = []
    for i, name in enumerate(view.columns):
        lengths = sorted(len(r[i]) for r in body) or [0]
        typical = lengths[int(0.9 * (len(lengths) - 1))]
        longest_part = max((len(p) for p in re.split(r"[_/.\-:, ]", str(name))), default=0)
        weights.append(max(4, min(28, max(longest_part + 1, typical))))
    columns = "(" + ", ".join(f"{w:.1f}fr" for w in weights) + ",)"
    align = "(" + ", ".join("right" if n else "left" for n in numeric) + ",)"
    # A header always breaks at its separators: `bill_length_mm` over a column
    # of three-digit numbers would otherwise run into its neighbour.
    header = "(" + ", ".join(tstr(_breakable(str(c), 0)) for c in view.columns) + ",)"
    cells = "(" + ", ".join("(" + ", ".join(tstr(v) for v in r) + ",)" for r in body) + ",)"
    shown = []
    if total_rows > view.height:
        shown.append(f"{view.height:,} of {total_rows:,} rows")
    if total_cols > view.width:
        shown.append(f"{view.width} of {total_cols} columns")
    note_arg = (
        tstr("Showing " + " · ".join(shown) + "; the HTML report has the whole table.")
        if shown
        else "none"
    )
    return raw(
        f"#dpx-table(columns: {columns}, align: {align}, header: {header}, "
        f"rows: {cells}, note: {note_arg})"
    )


def colored_svg(svg: str | None, color: str) -> str | None:
    """An Iconify SVG (``currentColor``) in one colour, as typst can draw it."""
    if not svg:
        return None
    out = svg.replace("currentColor", color)
    if "xmlns=" not in out:
        out = out.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return out


def bars(items: list[tuple[str, float, str]], color: str) -> str:
    """A top-N breakdown: one bar per item, its share, its count."""
    rows = ", ".join(
        f"({tstr(_breakable(name))}, {max(0.0, min(1.0, frac)):.4f}, {tstr(note)})"
        for name, frac, note in items
    )
    return f"dpx-bars(({rows},), rgb({tstr(color)}))"


def kpi(
    *,
    title: str,
    value: str,
    caption: str | None = None,
    icon_svg: str | None = None,
    secondary: str | None = None,
) -> str:
    """One card as a ``dpx-kpi`` call (typst code, not markup)."""
    args = [tstr(title), tstr(value)]
    if caption:
        args.append(f"caption: {tstr(caption)}")
    if icon_svg:
        args.append(f"icon: {tstr(icon_svg)}")
    if secondary:
        args.append(f"secondary: {secondary}")
    return f"dpx-kpi({', '.join(args)})"


def kpis(cards: list[str]) -> str:
    """A strip of cards, as the dashboard lays one out (four across at most)."""
    return raw(f"#dpx-kpis({', '.join(cards)})") if cards else ""
