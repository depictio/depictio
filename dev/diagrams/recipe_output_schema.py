#!/usr/bin/env python3
"""Render the anatomy of a recipe file, with the output constants renamed by #863,
as a hand-drawn SVG (+ PNG).

A recipe is a Python module that turns raw pipeline files into one table: it
declares its inputs (``SOURCES``), does the work in ``transform()`` and declares
its output (``OUTPUT_SCHEMA``, ``OPTIONAL_OUTPUT_SCHEMA``). The output constants
used to be ``EXPECTED_SCHEMA`` / ``OPTIONAL_SCHEMA``; a recipe still using those
names is rejected at load time with the rename to make.

Usage:
    python dev/diagrams/recipe_output_schema.py --out docs/images/recipe-output-schema
    # writes <out>_contract.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    GREY,
    INK,
    MONO,
    RED,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)

W = 1360
OK = "#2b8a3e"
CODE_BG = "#f8f9fa"
CODE_HEAD = "#e9ecef"
COMMENT = "#868e96"
STRING = "#c2255c"
TERM_BG = "#1f2328"
TERM_INK = "#e9ecef"
TERM_DIM = "#8b949e"
TERM_RED = "#ff8787"

# Accent inks for the three parts of a recipe; the tints come from sketch.py.
IN_INK, WORK_INK, OUT_INK = "#1971c2", "#e67700", OK

CODE_SIZE = 18
LH = CODE_SIZE * 1.45
CHAR = 0.602  # monospace advance, in em

Seg = tuple[str, str] | tuple[str, str, bool]


# -- local helpers built on the Sketch primitives ----------------------------


def rounded(s: Sketch, x: float, y: float, w: float, h: float, fill: str, rx: float = 12) -> None:
    """A flat rounded fill with no outline, for tinted panel and card backgrounds."""
    s._parts.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}"/>'
    )


def code_line(s: Sketch, x: float, y: float, segs: list[Seg], size: float = CODE_SIZE) -> None:
    """One monospace line made of coloured (and optionally bold) runs."""
    spans = []
    for seg in segs:
        text, colour = seg[0], seg[1]
        bold = ' font-weight="bold"' if len(seg) > 2 and seg[2] else ""
        spans.append(f'<tspan fill="{colour}"{bold}>{escape(text)}</tspan>')
    s._parts.append(
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO}" font-size="{size}" '
        f'xml:space="preserve">{"".join(spans)}</text>'
    )


def lines_left(
    s: Sketch, x: float, y: float, lines: tuple[str, ...], size: float = 18, colour: str = INK
) -> None:
    for i, line in enumerate(lines):
        s.text(x, y + i * size * 1.35, line, size=size, colour=colour, anchor="start")


def note(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    lines: tuple[str, ...],
    fill: str,
    size: float = 19,
    *,
    title: str = "",
    title_colour: str = INK,
    min_h: float = 0,
) -> float:
    """A sticky note with a folded corner and an optional title; returns its bottom."""
    pad = size * 1.75 if title else 0
    h = max(min_h, 26 + pad + len(lines) * size * 1.35)
    fold = 18
    s.poly(
        [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)],
        fill=fill,
        colour=DIM,
        amount=1.0,
    )
    s.line(x + w - fold, y, x + w - fold, y + fold, colour=DIM, amount=0.6, passes=1)
    s.line(x + w - fold, y + fold, x + w, y + fold, colour=DIM, amount=0.6, passes=1)
    if title:
        s.text(x + 18, y + 36, title, size=size + 3, anchor="start", colour=title_colour)
    lines_left(s, x + 18, y + 34 + pad, lines, size=size)
    return y + h


def leader(s: Sketch, x1: float, y1: float, x2: float, y2: float, colour: str = DIM) -> None:
    """A thin dotted pointer from a note to what it explains."""
    s._parts.append(
        f'<path d="M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}" stroke="{colour}" stroke-width="1.8" '
        f'stroke-dasharray="2 6" stroke-linecap="round" fill="none"/>'
    )
    s._parts.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="4.5" fill="{colour}"/>')


def bracket(s: Sketch, x: float, y1: float, y2: float, colour: str) -> None:
    """A hand-drawn right-facing curly brace spanning y1..y2 at x."""
    mid = (y1 + y2) / 2
    d = 12
    s.curve([(x, y1), (x + d, y1 + 8), (x + d, mid - 10), (x + 2 * d, mid)], colour=colour)
    s.curve([(x + 2 * d, mid), (x + d, mid + 10), (x + d, y2 - 8), (x, y2)], colour=colour)


def struck(s: Sketch, x: float, y: float, text: str, size: float = 20) -> float:
    """An old name in grey monospace with a red hand-drawn strike-through; returns its end x."""
    code_line(s, x, y, [(text, COMMENT)], size=size)
    end = x + len(text) * size * CHAR
    s.line(x - 4, y - size * 0.32, end + 4, y - size * 0.36, colour=RED, width=2.6, amount=1.2)
    return end


def burst(s: Sketch, cx: float, cy: float, r: float = 30) -> None:
    """A jagged star: the load blew up here."""
    pts = []
    for i in range(18):
        rad = r if i % 2 == 0 else r * 0.55
        a = math.pi * 2 * i / 18 - math.pi / 2
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    s.poly(pts, fill="#ffd8a8", colour=RED, amount=0.8)
    s.text(cx, cy + 9, "!", size=26, colour=RED, weight="bold")


def code_card(s: Sketch, x: float, y: float, w: float, h: float, caption: str) -> None:
    """A grey code panel with a caption strip, outlined by a pen stroke."""
    rounded(s, x, y, w, h, CODE_BG)
    rounded(s, x, y, w, 44, CODE_HEAD, rx=10)
    s.rect(Box(x, y, w, h, "none", ""), colour=GREY)
    s.text(x + 20, y + 30, caption, size=18, colour=DIM, anchor="start")


def terminal(s: Sketch, x: float, y: float, w: float, h: float, title: str) -> None:
    """A dark terminal window with the three traffic-light dots."""
    rounded(s, x, y, w, h, TERM_BG, rx=12)
    for i, c in enumerate(("#ff6b6b", "#fcc419", "#51cf66")):
        s._parts.append(f'<circle cx="{x + 24 + i * 22:.1f}" cy="{y + 22:.1f}" r="6" fill="{c}"/>')
    s._parts.append(
        f'<text x="{x + w / 2:.1f}" y="{y + 28:.1f}" font-family="{MONO}" font-size="16" '
        f'fill="{TERM_DIM}" text-anchor="middle">{escape(title)}</text>'
    )


# -- the drawing -------------------------------------------------------------


def c(text: str) -> Seg:
    return (text, INK)


# The arriba recipe, trimmed. Each entry is one line of coloured runs.
CODE: list[list[Seg]] = [
    [("import", WORK_INK), c(" polars "), ("as", WORK_INK), c(" pl")],
    [
        ("from", WORK_INK),
        c(" depictio.models.models.transforms "),
        ("import", WORK_INK),
        c(" RecipeSource"),
    ],
    [],
    [("SOURCES", IN_INK, True), c(": list[RecipeSource] = [")],
    [c("    RecipeSource(")],
    [c("        ref="), ('"fusions"', STRING), c(",")],
    [c("        glob_pattern="), ('"arriba/*.arriba.fusions.tsv"', STRING), c(",")],
    [c("        format="), ('"TSV"', STRING), c(",")],
    [c("    ),")],
    [c("]")],
    [],
    [("OUTPUT_SCHEMA", OUT_INK, True), c(": dict[str, type[pl.DataType]] = {")],
    [c("    "), ('"fusion"', STRING), c(": pl.Utf8,")],
    [c("    "), ('"supporting_reads"', STRING), c(": pl.Int64,")],
    [c("    "), ('"log_support"', STRING), c(": pl.Float64,")],
    [("    # ... 15 more columns", COMMENT)],
    [c("}")],
    [("# ", COMMENT), ("OPTIONAL_OUTPUT_SCHEMA", OUT_INK, True), (" = {...}  if any", COMMENT)],
    [],
    [],
    [
        ("def", WORK_INK),
        c(" "),
        ("transform", WORK_INK, True),
        c("(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:"),
    ],
    [c("    df = sources["), ('"fusions"', STRING), c("]")],
    [("    # join the partners into `fusion`, sum the reads", COMMENT)],
    [("    return", WORK_INK), c(" base.with_columns(...).select(list(OUTPUT_SCHEMA))")],
]

# (first line, last line, tint, ink) of each highlighted part of the recipe.
BANDS = {
    "in": (3, 9, BLUE, IN_INK),
    "out": (11, 17, GREEN, OUT_INK),
    "work": (20, 23, YELLOW, WORK_INK),
}


def build() -> Sketch:
    cx, cy, cw = 40, 138, 840
    base = cy + 86  # first code baseline
    ch = 86 + (len(CODE) - 1) * LH + 30
    low = cy + ch + 56
    s = Sketch(W, low + 296)

    s.text(40, 58, "Anatomy of a recipe: inputs, the work, the output", size=32, anchor="start")
    s.text(
        40,
        98,
        "the output-side constants are renamed so they read like `SOURCES` does for the inputs",
        size=20,
        colour=DIM,
        anchor="start",
    )

    # -- the recipe file, with a tinted band behind each part --------------------
    code_card(s, cx, cy, cw, ch, "`depictio/catalog/arriba/fusions.py`, trimmed")

    def band_edges(first: int, last: int) -> tuple[float, float]:
        return base + first * LH - 21, base + last * LH + 10

    for first, last, tint, ink in BANDS.values():
        top, bot = band_edges(first, last)
        rounded(s, cx + 12, top, cw - 24, bot - top, tint, rx=8)
        rounded(s, cx + 12, top, 6, bot - top, ink, rx=3)
    for i, segs in enumerate(CODE):
        if segs:
            code_line(s, cx + 32, base + i * LH, segs)

    # -- callouts in the right-hand column ---------------------------------------
    nx = cx + cw + 56
    nw = W - 40 - nx

    def brace(key: str) -> tuple[float, float]:
        first, last, _, ink = BANDS[key]
        top, bot = band_edges(first, last)
        bracket(s, cx + cw + 8, top + 4, bot - 4, ink)
        return cx + cw + 32, (top + bot) / 2

    # Inputs.
    bx, by = brace("in")
    top, _ = band_edges(*BANDS["in"][:2])
    nb = note(
        s,
        nx,
        top - 6,
        nw,
        ("the files to read: a path or", "a glob, plus the format", "(unchanged)"),
        BLUE,
        title="Inputs: `SOURCES`",
        title_colour=IN_INK,
    )
    leader(s, nx, (top - 6 + nb) / 2, bx, by, IN_INK)

    # Output: the rename card.
    bx, by = brace("out")
    top, bot = band_edges(*BANDS["out"][:2])
    ry = top - 8
    rh = 212
    s.poly(
        [(nx, ry), (nx + nw - 18, ry), (nx + nw, ry + 18), (nx + nw, ry + rh), (nx, ry + rh)],
        fill=GREEN,
        colour=DIM,
        amount=1.0,
    )
    s.text(nx + 18, ry + 38, "Output: renamed here", size=22, anchor="start", colour=OUT_INK)
    for i, (old, new) in enumerate(
        (("EXPECTED_SCHEMA", "OUTPUT_SCHEMA"), ("OPTIONAL_SCHEMA", "OPTIONAL_OUTPUT_SCHEMA"))
    ):
        oy = ry + 80 + i * 76
        struck(s, nx + 22, oy, old, size=19)
        s.arrow(nx + 36, oy + 10, nx + 36, oy + 34, colour=OUT_INK)
        code_line(s, nx + 58, oy + 34, [(new, OUT_INK, True)], size=19)
    leader(s, nx, ry + rh / 2, bx, by, OUT_INK)

    # The work.
    bx, by = brace("work")
    top, bot = band_edges(*BANDS["work"][:2])
    nb = note(
        s,
        nx,
        top - 14,
        nw,
        ("`sources` in, one DataFrame", "out, checked against", "`OUTPUT_SCHEMA`"),
        YELLOW,
        title="The work: `transform()`",
        title_colour=WORK_INK,
    )
    leader(s, nx, (top - 14 + nb) / 2, bx, by, WORK_INK)

    # -- a legacy recipe and what loading it prints ------------------------------
    s.text(40, low, "A recipe still on an old name fails at load", size=28, anchor="start")
    s.text(
        40,
        low + 34,
        "`load_recipe()` names the rename to make, before any file is read",
        size=19,
        colour=DIM,
        anchor="start",
    )
    ly = low + 64
    lw, lh = 420, 196
    code_card(s, 40, ly, lw, lh, "`my_tool/x.py`")
    legacy: list[list[Seg]] = [
        [("SOURCES", IN_INK, True), c(" = [...]")],
        [("EXPECTED_SCHEMA", RED, True), c(" = {")],
        [c("    "), ('"value"', STRING), c(": pl.Int64,")],
        [c("}")],
    ]
    for i, segs in enumerate(legacy):
        code_line(s, 62, ly + 84 + i * LH, segs)

    tx = 40 + lw + 190
    tw = W - 40 - tx
    s.arrow(40 + lw + 18, ly + lh / 2, tx - 18, ly + lh / 2, colour=RED)
    s.text(40 + lw + 95, ly + lh / 2 - 16, "`load_recipe()`", size=18, colour=RED)
    terminal(s, tx, ly, tw, lh, "python")
    term: list[list[Seg]] = [
        [("Traceback (most recent call last):", TERM_DIM)],
        [("  ...", TERM_DIM)],
        [("RecipeError", TERM_RED, True), (": Recipe my_tool/x.py:", TERM_INK)],
        [("  rename EXPECTED_SCHEMA to OUTPUT_SCHEMA", TERM_INK, True)],
    ]
    for i, segs in enumerate(term):
        code_line(s, tx + 24, ly + 76 + i * LH, segs)
    burst(s, tx + tw - 44, ly + lh - 40, r=28)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/recipe-output-schema"),
        "--out",
        help="Output prefix; <out>_contract.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the recipe contract schema under --out."""
    write(build(), out, "contract", png=png)


if __name__ == "__main__":
    app()
