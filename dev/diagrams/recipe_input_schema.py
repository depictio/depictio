#!/usr/bin/env python3
"""Render the checkpoints a recipe's data goes through, with the new input schema
check, as a hand-drawn SVG (+ PNG).

Each ``RecipeSource`` can now declare an ``input_schema``: the columns the raw
pipeline file must contain. ``validate_sources()`` checks it after the files are
read and before ``transform()`` runs, so a file missing a column fails with the
source and the column named, instead of a Polars ``ColumnNotFoundError`` raised
from inside the recipe's own code.

Usage:
    python dev/diagrams/recipe_input_schema.py --out docs/images/recipe-input-schema
    # writes <out>_checkpoints.svg/.png

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
    ORANGE,
    RED,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)

W = 1360
OK = "#2b8a3e"
NEW_INK = "#e8590c"
IN_INK = "#1971c2"
WORK_INK = "#e67700"
CODE_BG = "#f8f9fa"
CODE_HEAD = "#e9ecef"
COMMENT = "#868e96"
STRING = "#c2255c"
TERM_BG = "#1f2328"
TERM_INK = "#e9ecef"
TERM_DIM = "#8b949e"
TERM_RED = "#ff8787"

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
    s: Sketch, x: float, y: float, lines: tuple[str, ...], size: float = 19, colour: str = INK
) -> None:
    for i, line in enumerate(lines):
        s.text(x, y + i * size * 1.35, line, size=size, colour=colour, anchor="start")


def badge(s: Sketch, cx: float, cy: float, label: str, fill: str = INK) -> None:
    """A numbered checkpoint marker."""
    s._parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="15" fill="{fill}"/>')
    s._parts.append(
        f'<text x="{cx:.1f}" y="{cy + 6:.1f}" font-family="{MONO}" font-size="17" '
        f'font-weight="bold" fill="#ffffff" text-anchor="middle">{label}</text>'
    )


def pill(s: Sketch, x: float, y: float, label: str, fill: str = NEW_INK) -> None:
    """A small solid tag, e.g. NEW."""
    w = len(label) * 12 + 24
    rounded(s, x, y, w, 28, fill, rx=14)
    s._parts.append(
        f'<text x="{x + w / 2:.1f}" y="{y + 20:.1f}" font-family="{MONO}" font-size="16" '
        f'font-weight="bold" fill="#ffffff" text-anchor="middle">{escape(label)}</text>'
    )


def check(s: Sketch, cx: float, cy: float, size: float = 11) -> None:
    kx, ky = cx - size / 3, cy + size * 0.8
    s.line(cx - size, cy, kx, ky, colour=OK, width=3.2, amount=0.8, passes=1)
    s.line(kx, ky, cx + size, cy - size, colour=OK, width=3.2, amount=0.8, passes=1)


def burst(s: Sketch, cx: float, cy: float, r: float = 30) -> None:
    """A jagged star: the run blew up here."""
    pts = []
    for i in range(18):
        rad = r if i % 2 == 0 else r * 0.55
        a = math.pi * 2 * i / 18 - math.pi / 2
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    s.poly(pts, fill="#ffd8a8", colour=RED, amount=0.8)
    s.text(cx, cy + 9, "!", size=26, colour=RED, weight="bold")


def cylinder(s: Sketch, cx: float, y: float, w: float, h: float, fill: str = WHITE) -> None:
    """A table drum, with the usual hand-drawn double stroke."""
    rx, ry = w / 2, 13
    x0, x1 = cx - rx, cx + rx
    body = (
        f"M{x0:.1f},{y + ry:.1f} L{x0:.1f},{y + h - ry:.1f} "
        f"A{rx:.1f},{ry} 0 0 0 {x1:.1f},{y + h - ry:.1f} L{x1:.1f},{y + ry:.1f} "
        f"A{rx:.1f},{ry} 0 0 0 {x0:.1f},{y + ry:.1f} Z"
    )
    s._parts.append(f'<path d="{body}" fill="{fill}" stroke="none"/>')
    for dx in (0, 1.2):
        s._parts.append(
            f'<path d="{body}" fill="none" stroke="{INK}" stroke-width="1.7" '
            f'transform="translate({dx},{dx})"/>'
        )
        s._parts.append(
            f'<ellipse cx="{cx + dx:.1f}" cy="{y + ry + dx:.1f}" rx="{rx:.1f}" ry="{ry}" '
            f'fill="none" stroke="{INK}" stroke-width="1.7"/>'
        )
    # Two inner rings read as stacked Parquet parts of one table.
    for f in (0.42, 0.7):
        yy = y + ry + (h - 2 * ry) * f
        s._parts.append(
            f'<path d="M{x0:.1f},{yy:.1f} A{rx:.1f},{ry} 0 0 0 {x1:.1f},{yy:.1f}" '
            f'fill="none" stroke="{DIM}" stroke-width="1.3"/>'
        )


def page(s: Sketch, x: float, y: float, w: float, h: float, label: str) -> None:
    """A file icon: a page with a folded corner and a few ruled lines."""
    fold = 16
    s.poly(
        [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)],
        fill=WHITE,
        amount=0.9,
    )
    s.line(x + w - fold, y, x + w - fold, y + fold, amount=0.5, passes=1)
    s.line(x + w - fold, y + fold, x + w, y + fold, amount=0.5, passes=1)
    for i in range(3):
        yy = y + 28 + i * 13
        s.line(x + 10, yy, x + w - 12 - (i % 2) * 14, yy, colour=GREY, amount=0.6, passes=1)
    s.text(x + w / 2, y + h - 10, label, size=17, colour=DIM)


def header_strip(
    s: Sketch,
    x: float,
    y: float,
    cols: list[str],
    marks: list[str] | None = None,
    size: float = 18,
) -> float:
    """A table header row, one cell per column, with a tick or cross under each; returns width."""
    cx = x
    for i, col in enumerate(cols):
        w = len(col) * size * CHAR + 26
        bad = marks is not None and marks[i] == "bad"
        s.rect(Box(cx, y, w, 40, "#fff0f0" if bad else WHITE, ""), colour=RED if bad else INK)
        code_line(s, cx + 13, y + 27, [(col, RED if bad else INK, True)], size=size)
        if marks is not None and marks[i] == "ok":
            check(s, cx + w / 2, y + 62)
        elif bad:
            s.cross(cx + w / 2, y + 62, size=10)
        cx += w
    return cx - x


def code_card(s: Sketch, x: float, y: float, w: float, h: float, caption: str) -> None:
    """A grey code panel with a caption strip, outlined by a pen stroke."""
    rounded(s, x, y, w, h, CODE_BG)
    rounded(s, x, y, w, 44, CODE_HEAD, rx=10)
    s.rect(Box(x, y, w, h, "none", ""), colour=GREY)
    s.text(x + 20, y + 30, caption, size=18, colour=DIM, anchor="start")


def terminal(s: Sketch, x: float, y: float, w: float, lines: list[list[Seg]]) -> float:
    """A dark terminal window with traffic-light dots; returns its bottom."""
    h = 58 + len(lines) * LH + 8
    rounded(s, x, y, w, h, TERM_BG, rx=12)
    for i, c in enumerate(("#ff6b6b", "#fcc419", "#51cf66")):
        s._parts.append(f'<circle cx="{x + 24 + i * 22:.1f}" cy="{y + 22:.1f}" r="6" fill="{c}"/>')
    for i, segs in enumerate(lines):
        code_line(s, x + 22, y + 72 + i * LH, segs)
    return y + h


def stage(
    s: Sketch, x: float, y: float, w: float, h: float, fill: str, title: str, sub: str
) -> Box:
    """A plain step in the flow: a title and a dim subtitle."""
    box = Box(x, y, w, h, fill, "")
    s.rect(box)
    s.text(box.cx, y + 34, title, size=22)
    s.text(box.cx, y + 62, sub, size=18, colour=DIM)
    return box


def down(s: Sketch, x: float, y1: float, y2: float, colour: str = INK) -> None:
    s.arrow(x, y1 + 6, x, y2 - 6, colour=colour)


# -- the drawing -------------------------------------------------------------


def c(text: str) -> Seg:
    return (text, INK)


# The arriba recipe's SOURCES, trimmed. Each entry is one line of coloured runs.
CODE: list[list[Seg]] = [
    [("# INPUT SCHEMA: the columns each source must contain,", NEW_INK, True)],
    [("# checked before transform().", NEW_INK, True)],
    [("SOURCES", IN_INK, True), c(": list[RecipeSource] = [")],
    [c("    RecipeSource(")],
    [c("        ref="), ('"fusions"', STRING), c(",")],
    [c("        glob_pattern="), ('"arriba/*.arriba.fusions.tsv"', STRING), c(",")],
    [c("        format="), ('"TSV"', STRING), c(",")],
    [c("        "), ("input_schema", NEW_INK, True), c("={")],
    [c("            "), ('"#gene1"', STRING), c(": pl.Utf8,")],
    [c("            "), ('"gene2"', STRING), c(": pl.Utf8,")],
    [c("            "), ('"split_reads1"', STRING), c(": pl.Int64,")],
    [("            # ... 13 more columns", COMMENT)],
    [c("        },")],
    [c("    ),")],
    [c("]")],
]
NEW_BANDS = ((0, 1), (7, 12))


def code_panel(s: Sketch, x: float, y: float, w: float) -> float:
    base = y + 86
    h = 86 + (len(CODE) - 1) * LH + 30
    code_card(s, x, y, w, h, "`depictio/catalog/arriba/fusions.py`, trimmed")
    for first, last in NEW_BANDS:
        top, bot = base + first * LH - 21, base + last * LH + 10
        rounded(s, x + 12, top, w - 24, bot - top, ORANGE, rx=8)
        rounded(s, x + 12, top, 6, bot - top, NEW_INK, rx=3)
    top = base + NEW_BANDS[1][0] * LH - 21
    pill(s, x + w - 92, top + 8, "NEW")
    for i, segs in enumerate(CODE):
        code_line(s, x + 32, base + i * LH, segs)
    return y + h


def before_panel(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    rounded(s, x, y, w, h, "#fff5f5", rx=16)
    s.text(
        x + 22, y + 44, "Before: it failed in `transform()`", size=26, colour=RED, anchor="start"
    )
    s.text(
        x + 22,
        y + 76,
        "same file, no input schema",
        size=19,
        colour=DIM,
        anchor="start",
    )
    tb = terminal(
        s,
        x + 20,
        y + 100,
        w - 40,
        [
            [("Traceback (most recent call last):", TERM_DIM)],
            [('  File ".../arriba/fusions.py",', TERM_DIM)],
            [("  in transform: ", TERM_DIM), ("base = df.select(", TERM_INK)],
            [("ColumnNotFoundError", TERM_RED, True), (": unable", TERM_INK)],
            [('  to find column "#gene1";', TERM_INK)],
            [('  valid columns: ["gene1", ...]', TERM_INK)],
        ],
    )
    s.cross(x + 40, tb + 34, size=10)
    lines_left(
        s,
        x + 64,
        tb + 40,
        (
            "names a column, but not the source or",
            "the file; the stack points into the",
            "recipe's own code",
        ),
        size=19,
    )


def build() -> Sketch:
    s = Sketch(W, 1600)

    s.text(40, 58, "A recipe now checks its inputs before `transform()`", size=32, anchor="start")
    s.text(
        40,
        98,
        "each source declares an `input_schema`; a pipeline file missing a column fails by name",
        size=20,
        colour=DIM,
        anchor="start",
    )

    # -- row 1: the declaration, and what the failure looked like before ---------
    ty = 136
    cb = code_panel(s, 40, ty, 720)
    before_panel(s, 790, ty, W - 40 - 790, cb - ty)

    # -- row 2: the flow through both checkpoints --------------------------------
    py = cb + 40
    rounded(s, 24, py, W - 48, 0, "#f4fcf5", rx=16)  # placeholder, resized below
    panel_idx = len(s._parts) - 1
    s.text(
        48,
        py + 48,
        "After: two checkpoints around `transform()`",
        size=30,
        colour=OK,
        anchor="start",
    )

    fx, fw = 70, 480
    fcx = fx + fw / 2

    # Raw pipeline files.
    y = py + 92
    for i, name in enumerate(("S1", "S2", "S3")):
        page(s, fx + 10 + i * 88, y, 72, 92, f"`{name}`")
    s.text(fx + 290, y + 36, "`arriba/*.arriba.fusions.tsv`", size=19, anchor="start")
    s.text(fx + 290, y + 66, "raw pipeline output,", size=19, colour=DIM, anchor="start")
    s.text(fx + 290, y + 92, "one TSV per sample", size=19, colour=DIM, anchor="start")
    y += 108
    down(s, fcx, y, y + 40)

    # Read + concat.
    y += 40
    read = stage(
        s,
        fx,
        y,
        fw,
        80,
        BLUE,
        "read each file, stack them",
        "`resolve_sources()`, one frame per source",
    )
    down(s, fcx, read.bottom, read.bottom + 42)

    # Checkpoint 1: the new input schema check.
    y = read.bottom + 42
    ck1 = Box(fx, y, fw, 216, ORANGE, "")
    s.rect(ck1, colour=NEW_INK)
    badge(s, fx + 30, y + 34, "1", NEW_INK)
    s.text(fx + 56, y + 42, "Input schema check", size=24, anchor="start")
    pill(s, ck1.right - 82, y + 18, "NEW")
    s.text(fx + 56, y + 72, "`validate_sources()`", size=19, colour=DIM, anchor="start")
    header_strip(
        s, fx + 24, y + 96, ["#gene1", "gene2", "split_reads1", "..."], ["ok", "ok", "ok", "ok"]
    )
    s.text(fx + 24, y + 200, "every declared column is there", size=18, colour=OK, anchor="start")

    # The failure branch off checkpoint 1.
    rx = 660
    rw = W - 40 - rx
    s.arrow(ck1.right + 6, ck1.cy, rx - 14, ck1.cy, colour=RED, dashed=True)
    s.text((ck1.right + rx) / 2, ck1.cy - 14, "missing", size=18, colour=RED)
    fy = ck1.y - 46
    s.text(rx, fy, "if S3 was written without the `#`:", size=19, anchor="start")
    header_strip(
        s, rx, fy + 20, ["gene1", "gene2", "split_reads1", "..."], ["bad", None, None, None]
    )
    tb = terminal(
        s,
        rx,
        fy + 106,
        rw,
        [
            [("RecipeError", TERM_RED, True), (": Recipe arriba/fusions.py:", TERM_INK)],
            [("  source 'fusions' lacks input column(s)", TERM_INK, True)],
            [("  ['#gene1']", TERM_RED, True), (". Got columns: ['gene1', ...]", TERM_INK)],
        ],
    )
    burst(s, rx + rw - 36, fy + 124, r=26)
    lines_left(
        s,
        rx,
        tb + 34,
        ("stops before `transform()` runs, naming", "the source and the column"),
        size=19,
        colour=RED,
    )

    down(s, fcx, ck1.bottom, ck1.bottom + 50, colour=OK)
    check(s, fcx + 30, ck1.bottom + 26, size=9)

    # The work.
    y = ck1.bottom + 50
    work = stage(
        s, fx, y, fw, 80, YELLOW, "`transform(sources)`", "join the partners, sum the read counts"
    )
    down(s, fcx, work.bottom, work.bottom + 42)

    # Checkpoint 2: the output schema check, as before.
    y = work.bottom + 42
    ck2 = Box(fx, y, fw, 176, GREEN, "")
    s.rect(ck2, colour=OK)
    badge(s, fx + 30, y + 34, "2", OK)
    s.text(fx + 56, y + 42, "Output schema check", size=24, anchor="start")
    s.text(
        fx + 56, y + 72, "`validate_schema()`, `OUTPUT_SCHEMA`", size=19, colour=DIM, anchor="start"
    )
    header_strip(s, fx + 24, y + 96, ["fusion", "supporting_reads", "..."], ["ok", "ok", "ok"])

    # Out to the Delta table and the dashboard.
    dcx, dy = 800, ck2.y + 40
    s.arrow(ck2.right + 6, ck2.cy, dcx - 66, ck2.cy)
    cylinder(s, dcx, dy, 110, 96)
    s.text(dcx, dy + 130, "Delta table", size=19)
    bx, by, bw, bh = 960, ck2.y + 20, 320, 140
    s.arrow(dcx + 66, ck2.cy, bx - 12, ck2.cy)
    s.rect(Box(bx, by, bw, bh, WHITE, ""))
    rounded(s, bx + 3, by + 3, bw - 6, 24, CODE_HEAD, rx=4)
    for i, hgt in enumerate((62, 38, 80, 50, 26)):
        s.rect(Box(bx + 22 + i * 26, by + bh - 14 - hgt, 18, hgt, BLUE, ""), colour=IN_INK)
    for px, pyy, r in ((200, 70, 7), (228, 96, 11), (256, 60, 5), (284, 84, 9), (240, 116, 6)):
        s._parts.append(
            f'<circle cx="{bx + px:.1f}" cy="{by + pyy:.1f}" r="{r}" fill="{ORANGE}" '
            f'stroke="{WORK_INK}" stroke-width="1.5"/>'
        )
    s.text(bx + bw / 2, by + bh + 34, "dashboard", size=19)

    bottom = ck2.bottom + 60
    s._parts[panel_idx] = s._parts[panel_idx].replace('height="0.0"', f'height="{bottom - py:.1f}"')
    s.height = bottom + 24
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/recipe-input-schema"),
        "--out",
        help="Output prefix; <out>_checkpoints.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the recipe checkpoints schema under --out."""
    write(build(), out, "checkpoints", png=png)


if __name__ == "__main__":
    app()
