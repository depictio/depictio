#!/usr/bin/env python3
"""Render how a one-line-per-row scan keeps its files readable whatever order
its Delta table stores the rows in, as a hand-drawn SVG (+ PNG).

* ``flow`` — the scan numbers each line in its file (``source_line``); the
  table may hold the rows in any order; before a recipe reads the source, the
  recipe engine puts each file's lines back in that order and drops the
  column (``recipes.in_file_order``).

Usage:
    python dev/diagrams/raw_scan_line_order.py --out docs/images/raw-scan-line-order
    # writes <out>_flow.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    ORANGE,
    VIOLET,
    YELLOW,
    Box,
    Sketch,
    page,
    tick,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1640, 640
OK = "#2b8a3e"
ROW_H = 24
FILL = {"a": BLUE, "b": ORANGE}


def table(s: Sketch, x: float, y: float, rows: list[tuple[str, int]], *, numbered: bool) -> None:
    """Table rows: the file (colour), its line, and the line number when kept."""
    w_line, w_num = 110, 46
    if numbered:
        s.text(x + w_num / 2, y - 10, "`source_line`", size=12, colour=DIM)
    s.text(x + (w_num if numbered else 0) + w_line / 2, y - 10, "`raw`", size=12, colour=DIM)
    for i, (file, line) in enumerate(rows):
        ry = y + i * ROW_H
        if numbered:
            num = Box(x, ry, w_num, ROW_H, YELLOW, "")
            s.rect(num)
            s.text(num.cx, ry + 17, str(line), size=14)
        cell = Box(x + (w_num if numbered else 0), ry, w_line, ROW_H, FILL[file], "")
        s.rect(cell)
        s.text(cell.cx, ry + 17, f"{file} line {line}", size=14)


def build_flow() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "A raw text scan is read back in each file's line order",
        "colours are the two files a one-line-per-row scan read; `source_path` is on every row",
    )
    top = 150

    # 1. the files
    for i, (name, fill) in enumerate((("a.aln", BLUE), ("b.hmm", ORANGE))):
        page(s, 60, top + i * 150, 110, 130, fill)
        s.text(115, top + i * 150 + 72, name, size=16)
    s.text(115, top + 330, "the run's files", size=15, colour=DIM)

    # 2. the scan numbers each line in its file
    scanned = [("a", 1), ("a", 2), ("a", 3), ("b", 1), ("b", 2), ("b", 3)]
    s.arrow(185, top + 140, 255, top + 140)
    table(s, 270, top + 60, scanned, numbered=True)
    s.text(348, top + 250, "the scan numbers", size=15, colour=DIM)
    s.text(348, top + 272, "each file's lines", size=15, colour=DIM)
    s.text(348, top + 294, "`row_index_name: source_line`", size=12.5, colour=DIM)

    # 3. the Delta table may hold them in any order
    stored = [("a", 3), ("b", 1), ("b", 2), ("b", 3), ("a", 1), ("a", 2)]
    s.arrow(445, top + 140, 535, top + 140)
    s.text(490, top + 120, "Delta", size=14, colour=DIM)
    table(s, 550, top + 60, stored, numbered=True)
    s.text(628, top + 250, "the table holds them", size=15, colour=DIM)
    s.text(628, top + 272, "in any order", size=15, colour=DIM)

    # 4. the recipe engine
    engine = Box(790, top + 60, 330, 170, VIOLET, "")
    s.rect(engine)
    s.text(engine.cx, engine.y + 32, "recipe engine", size=19, weight="bold")
    s.text(engine.cx, engine.y + 56, "`in_file_order`, before the recipe", size=13, colour=DIM)
    for i, line in enumerate(
        (
            "in order already: one pass",
            "else each file's lines by `source_line`,",
            "files where their first line was",
            "then `source_line` is dropped",
        )
    ):
        s.text(engine.x + 22, engine.y + 92 + i * 22, line, size=14, anchor="start")
    s.arrow(725, top + 140, engine.x - 10, top + 140)

    # 5. what the recipe reads
    s.arrow(engine.right + 10, top + 140, 1190, top + 140)
    table(s, 1205, top + 60, scanned, numbered=False)
    tick(s, 1345, top + 70, size=9)
    s.text(1365, top + 76, "each file reads as written,", size=15, colour=OK, anchor="start")
    s.text(1365, top + 98, "whatever the table's order", size=15, colour=OK, anchor="start")
    s.text(1365, top + 130, "the recipe sees the columns", size=14, colour=DIM, anchor="start")
    s.text(1365, top + 152, "it always saw", size=14, colour=DIM, anchor="start")

    s.shade(40, top + 370, W - 80, 80, fill=GREEN, opacity=0.35)
    s.text(
        64,
        top + 404,
        "Rows written before scans numbered their lines carry no `source_line`: "
        "they keep their stored order.",
        size=15,
        anchor="start",
    )
    s.text(
        64,
        top + 428,
        "A raw scan without the line number fails `test_every_raw_scan_numbers_its_lines`.",
        size=15,
        anchor="start",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/raw-scan-line-order"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the flow schema under --out."""
    write(build_flow(), out, "flow", png=png)


if __name__ == "__main__":
    app()
