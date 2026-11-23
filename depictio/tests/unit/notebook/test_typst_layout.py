"""The PDF's typst layout: table orientation, column blocks, wide figures.

``table()`` keeps a portrait page's worth of columns as it always has, turns
the page for more (one landscape table while the columns fit, column blocks
with the id column repeated when they do not), and takes an explicit
``orientation``; ``figure()`` wraps a static figure and its caption in one
non-breakable block, on a landscape page when the figure is wide.
"""

from __future__ import annotations

import base64
import struct
import zlib

import polars as pl

from depictio.notebook.typst import (
    LANDSCAPE_TABLE_COLS,
    SPLIT_TABLE_COLS,
    TABLE_COLS,
    figure,
    table,
)

_ROWS_NOTE = "Showing 30 of 40 rows; the HTML report has the whole table."


def _inner(raw_block: str) -> str:
    """The typst code a raw block carries (what the document compiles)."""
    lines = raw_block.strip().splitlines()
    assert lines[0] == "````{=typst}" and lines[-1] == "````", lines[:1]
    return "\n".join(lines[1:-1])


def _frame(columns: int, rows: int = 40) -> pl.DataFrame:
    """``rows`` rows and ``columns`` columns: a string id, numbers, then text."""
    numbers = (columns - 1) // 2
    return pl.DataFrame(
        {
            "id": [f"SRR{i:03d}" for i in range(rows)],
            **{f"num_{i}": [i * 1000 + j for j in range(rows)] for i in range(numbers)},
            **{f"text_{i}": [f"v{i}" for _ in range(rows)] for i in range(columns - 1 - numbers)},
        }
    )


def _png_b64() -> str:
    """A small valid PNG (two blue rows), base64: what a static figure is."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x1f\x77\xb4" * 4
    return base64.b64encode(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * 2))
        + chunk(b"IEND", b"")
    ).decode()


_PNG = _png_b64()


# ── Tables: portrait, landscape, column blocks ───────────────────────────────


def test_five_columns_stay_portrait():
    out = table(_frame(5))
    assert out.strip().startswith("````{=typst}") and "#dpx-table(" in out
    # Five columns fit a portrait page: no landscape mark, no column blocks.
    assert "#dpx-wide" not in out and "#block(breakable" not in out
    # Rows were left out beyond the cap, so the note names rows only.
    assert f'"{_ROWS_NOTE}"' in out


def test_numeric_columns_align_right_and_format():
    out = _inner(table(_frame(5)))
    # The id and the text columns left, the number columns right; grouped digits.
    assert "align: (left, right, right, left, left,)" in out
    assert '"1,000"' in out and '"1,001"' in out


def test_ten_columns_take_one_landscape_block():
    out = _inner(table(_frame(10)))
    # All ten columns, the whole table on one landscape page: the mark the
    # preamble's show rule reads, one dpx-table, no column blocks.
    assert "#dpx-wide[" in out
    assert out.count("#dpx-table(") == 1
    # All ten columns are on the page: the last number and text column's
    # values (a header breaks at its separators, so a cell value reads cleaner).
    assert '"3,029"' in out and '"v4"' in out
    assert "Columns " not in out
    assert f'"{_ROWS_NOTE}"' in out


def test_twenty_eight_columns_split_with_the_id_column_repeated():
    out = _inner(table(_frame(28)))
    blocks = out.count("#dpx-table(")
    assert blocks == 3  # 13 + 13 + 2 columns, one block per landscape page
    assert out.count("#block(breakable: false)[") == blocks
    assert "#dpx-wide[" in out
    # Every block carries the id column: its own in the first, repeated after.
    assert out.count('"id"') == blocks
    # Each block says which of the 28 columns it holds, then the row count.
    assert f'"Columns 1-{SPLIT_TABLE_COLS} of 28 · {_ROWS_NOTE}"' in out
    assert f'"Columns {SPLIT_TABLE_COLS + 1}-{2 * SPLIT_TABLE_COLS} of 28 · {_ROWS_NOTE}"' in out
    assert f'"Columns 27-28 of 28 · {_ROWS_NOTE}"' in out


def test_fifteen_columns_split_into_two_blocks():
    out = _inner(table(_frame(LANDSCAPE_TABLE_COLS + 1)))
    assert out.count("#dpx-table(") == 2
    assert '"Columns 1-13 of 15' in out and '"Columns 14-15 of 15' in out


def test_orientation_override():
    df = _frame(28)
    # Forced portrait: what a portrait page holds, the rest named in the note.
    out = _inner(table(df, orientation="portrait"))
    assert "#dpx-wide" not in out
    assert out.count("#dpx-table(") == 1
    assert f'"Columns 1-{TABLE_COLS} of 28' in out
    # Forced landscape on a narrow frame: the mark, one table, no column note.
    out = _inner(table(_frame(5), orientation="landscape"))
    assert "#dpx-wide[" in out
    assert out.count("#dpx-table(") == 1
    assert "Columns " not in out


# ── Figures: one block with the caption, landscape when wide ─────────────────


def test_a_wide_figure_is_a_flipped_nonbreaking_block():
    out = _inner(figure(_PNG, "Share of reads.", orientation="landscape"))
    # The mark, the non-breakable block around picture and caption, the SVG
    # wrapper that holds the PNG as a data URI.
    assert "#dpx-wide[" in out
    assert "#block(breakable: false)[" in out
    # The SVG text is a typst string, so its attribute quotes come escaped.
    assert "#image(bytes(" in out and 'xlink:href=\\"data:image/png;base64,' in out
    # The caption travels with the figure, inside the block.
    assert "#text(size: 8pt, fill: dpx-muted, " in out and '"Share of reads."' in out


def test_a_portrait_figure_stays_portrait():
    out = _inner(figure(_PNG, "Share of reads."))
    assert "#block(breakable: false)[" in out
    assert "#dpx-wide" not in out


def test_a_figure_that_is_not_a_png_is_left_out():
    assert figure("not base64!!", "A caption.") == ""


def test_figure_orientation_by_ratio_and_override():
    from depictio.notebook.components import (
        LANDSCAPE_FIGURE_RATIO,
        figure_orientation,
        figure_ratio,
    )

    class Fig:
        def __init__(self, width, height):
            self.layout = type("Layout", (), {"width": width, "height": height})()

    assert figure_ratio(Fig(1200, 300)) == 4.0
    assert figure_ratio(Fig(1200, None)) is None
    assert figure_ratio(Fig(None, 400)) is None
    # Wider than LANDSCAPE_FIGURE_RATIO:1 is landscape, the rest portrait.
    assert figure_orientation(LANDSCAPE_FIGURE_RATIO + 0.01) == "landscape"
    assert figure_orientation(LANDSCAPE_FIGURE_RATIO) == "portrait"
    assert figure_orientation(None) == "portrait"
    # An explicit override wins over the ratio.
    assert figure_orientation(4.0, "portrait") == "portrait"
    assert figure_orientation(0.5, "landscape") == "landscape"


def test_figure_png_draws_at_the_layout_ratio(monkeypatch):
    """``figure_png`` keeps the figure's own width:height shape when the
    layout sets both, instead of stretching it to a default height."""
    import plotly.graph_objects as go

    from depictio.notebook import components

    seen = {}
    monkeypatch.setattr(
        go.Figure, "to_image", lambda self, **kw: seen.update(kw) or b"png", raising=True
    )

    def drawn(width: int | None, height: int | None) -> int:
        seen.clear()
        fig = go.Figure(go.Bar(x=[1], y=[1]))
        fig.update_layout(width=width, height=height)
        assert components.figure_png(fig)
        assert seen["width"] == components.STATIC_FIGURE_WIDTH
        return seen["height"]

    # Wide and short (1100:380): drawn at the static width, shaped the same.
    assert drawn(1100, 380) == int(components.STATIC_FIGURE_WIDTH / (1100 / 380))
    assert drawn(900, 400) == int(components.STATIC_FIGURE_WIDTH / 2.25)
    # No ratio (a height missing, or both): the default height stands.
    assert drawn(1100, None) == 420
    assert drawn(None, None) == 420


def test_a_heading_before_a_wide_float_moves_onto_its_landscape_page():
    """The page turn would strand the heading at the foot of a portrait page:
    the rule that skips it comes after the report's own heading rules (so it
    sees the heading first), and the flipped page draws a copy of it."""
    from depictio.api.v1.services.notebook_export.pdf_typst import typst_preamble

    preamble = typst_preamble(title="T", subtitle=None, primary="#228be6")
    skip = preamble.index("if next != none and dpx-is-wide(next) { [] } else { it }")
    styled = preamble.index('let key = if it.has("label")')
    assert skip > styled, "the skipping rule must come last to see the heading first"
    assert "dpx-heading-copy(prev)" in preamble


def test_a_set_page_orientation_turns_a_narrow_table(monkeypatch):
    """The report layer's per-tile override reaches the table's typst."""
    from depictio.notebook import components

    monkeypatch.setenv(components.STATIC_FIGURES_ENV, "1")
    view = components.TableView(_frame(4))
    portrait = view._repr_mimebundle_()[components.MARKDOWN_MIME]
    assert "dpx-wide" not in portrait
    try:
        components.set_page_orientation("landscape")
        landscape = view._repr_mimebundle_()[components.MARKDOWN_MIME]
    finally:
        components.set_page_orientation()
    assert "dpx-wide" in landscape
    assert components.page_orientation() == "auto"
