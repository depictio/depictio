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

import base64
import datetime as _dt
import math
import re
import struct
from collections.abc import Callable
from typing import Any

import polars as pl

from depictio.notebook.qmd_safe import typst_str

#: Rows a table keeps on a page; the HTML report has them all.
TABLE_ROWS = 30
#: Columns a portrait page takes; wider tables print on a landscape page.
TABLE_COLS = 8
#: Columns a landscape page takes in one table; wider tables split into
#: column blocks, the first (id) column repeated on each.
LANDSCAPE_TABLE_COLS = 14
#: Data columns per block of a split table (the id column comes on top, so a
#: block is this wide plus one).
SPLIT_TABLE_COLS = 13
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


def _dpx_cell(text: str, colour: str | None, bar: tuple[str, float] | None = None) -> str:
    """A cell as typst: a string, a chip (``dpx-table`` draws a dictionary
    as one) when the value has its colour, or the value over its data bar
    (colour, share of the cell in %), as MultiQC's General Statistics."""
    if bar:
        share = max(0.0, min(100.0, float(bar[1])))
        return f"(bar: {share / 100:.4f}, color: {tstr(bar[0])}, text: {tstr(text)})"
    if colour:
        return f"(chip: {tstr(text)}, color: {tstr(colour)})"
    return tstr(text)


def _dpx_table(
    df: pl.DataFrame,
    *,
    rows: int,
    column_note: str = "",
    chips: dict[str, dict[str, str]] | None = None,
    text: dict[str, Callable[[Any], str]] | None = None,
    bars: dict[str, Callable[[Any], tuple[str, float] | None]] | None = None,
) -> str:
    """One ``dpx-table`` call: the first ``rows`` rows of ``df``, all of its
    columns shown, widths from what they hold. ``column_note`` leads the note
    ("Columns 2-14 of 28") when part of the table is elsewhere. ``text``
    writes a column's values its own way (a unit); ``bars`` draws each value
    over its data bar."""
    total_rows = df.height
    view = df.head(rows)
    text = text or {}
    bars = bars or {}
    # A barred column reads from the left, as the bar grows.
    numeric = [view.schema[c].is_numeric() and c not in bars for c in view.columns]
    writers = [text.get(c) for c in view.columns]
    body = [
        [w(v) if w is not None else _cell(v) for v, w in zip(row, writers, strict=True)]
        for row in view.iter_rows()
    ]
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
    colours = [(chips or {}).get(c) for c in view.columns]
    barred = [bars.get(c) for c in view.columns]
    raw_rows = list(view.iter_rows())
    cells = (
        "("
        + ", ".join(
            "("
            + ", ".join(
                _dpx_cell(
                    v,
                    colours[i].get(str(raw[i])) if colours[i] and raw[i] is not None else None,
                    barred[i](raw[i]) if barred[i] is not None else None,
                )
                for i, v in enumerate(r)
            )
            + ",)"
            for r, raw in zip(body, raw_rows, strict=True)
        )
        + ",)"
    )
    shown = []
    if column_note:
        shown.append(column_note)
    if total_rows > view.height:
        shown.append(f"Showing {view.height:,} of {total_rows:,} rows")
    note_arg = (
        tstr(" · ".join(shown) + "; the HTML report has the whole table.") if shown else "none"
    )
    return (
        f"#dpx-table(columns: {columns}, align: {align}, header: {header}, "
        f"rows: {cells}, note: {note_arg})"
    )


def table(
    df: pl.DataFrame,
    *,
    rows: int = TABLE_ROWS,
    orientation: str = "auto",
    chips: dict[str, dict[str, str]] | None = None,
    text: dict[str, Callable[[Any], str]] | None = None,
    bars: dict[str, Callable[[Any], tuple[str, float] | None]] | None = None,
) -> str:
    """``df`` as a typst table: a styled header row, zebra rows, numbers right
    aligned and formatted, columns as wide as what they hold, and a note when
    rows or columns were left out.

    A portrait page holds ``TABLE_COLS`` columns. Wider tables print on a
    landscape page: one table while every column fits it, else column blocks
    of ``SPLIT_TABLE_COLS`` columns with the first (id) column repeated on
    each, one block per landscape page. ``orientation`` forces one or the
    other (``"auto"``, ``"portrait"``, ``"landscape"``); landscape pages come
    from the preamble's show rule, which flips the page of a float whose body
    carries ``dpx-wide`` — the mark a wide table wears here.
    """
    total_cols = df.width
    if orientation not in ("portrait", "landscape"):
        orientation = "landscape" if total_cols > TABLE_COLS else "portrait"
    if orientation == "portrait":
        dropped = total_cols - TABLE_COLS
        note = f"Columns 1-{TABLE_COLS} of {total_cols}" if dropped > 0 else ""
        return raw(
            _dpx_table(
                df.select(df.columns[:TABLE_COLS]),
                rows=rows,
                column_note=note,
                chips=chips,
                text=text,
                bars=bars,
            )
        )
    if total_cols <= LANDSCAPE_TABLE_COLS:
        body = _dpx_table(df, rows=rows, chips=chips, text=text, bars=bars)
    else:
        blocks = []
        for start in range(0, total_cols, SPLIT_TABLE_COLS):
            names = list(df.columns[start : start + SPLIT_TABLE_COLS])
            if start:
                names = [df.columns[0], *names]
            note = (
                f"Columns {start + 1}-{min(start + SPLIT_TABLE_COLS, total_cols)} of {total_cols}"
            )
            block = _dpx_table(
                df.select(names), rows=rows, column_note=note, chips=chips, text=text, bars=bars
            )
            # Non-breakable, so a block a landscape page cannot hold moves
            # whole onto the next one instead of splitting mid-table.
            blocks.append(f"#block(breakable: false)[\n{block}\n]")
        body = "\n#v(6pt)\n".join(blocks)
    return raw(f"#dpx-wide[\n{body}\n]")


def _png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    w, h = struct.unpack(">II", data[16:24])
    return (w, h) if w and h else None


def _figure_svg(png: str) -> str | None:
    """A base64 PNG as the SVG text typst can draw (``image(bytes(...))``).

    Typst reads no data URI and decodes no base64; an SVG it reads as text,
    and an SVG may hold a PNG as its own data URI.
    """
    try:
        data = base64.b64decode(png)
    except ValueError:
        return None
    size = _png_size(data)
    if size is None:
        return None
    w, h = size
    uri = f"data:image/png;base64,{png}"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<image width="{w}" height="{h}" xlink:href="{uri}"/></svg>'
    )


def figure(png: str, caption: str | None = None, *, orientation: str = "auto") -> str:
    """A static figure as typst: the picture and, when given, its caption in
    one non-breakable block, so a page break cannot come between them.

    ``orientation`` (``"auto"``, ``"portrait"``, ``"landscape"``; landscape
    when the figure is wider than ``components.LANDSCAPE_FIGURE_RATIO``:1)
    puts the block on a landscape page via the preamble's ``dpx-wide`` show
    rule, as a wide table's is.
    """
    svg = _figure_svg(png)
    if svg is None:
        return ""
    parts = [f"#image(bytes({tstr(svg)}), width: 100%)"]
    if caption:
        parts.append("#v(3pt)")
        parts.append(f"#text(size: 8pt, fill: dpx-muted, {tstr(caption)})")
    inner = "#block(breakable: false)[\n" + "\n".join(parts) + "\n]"
    if orientation == "landscape":
        return raw(f"#dpx-wide[\n{inner}\n]")
    return raw(inner)


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
