#!/usr/bin/env python3
"""Render why a table must reach deltalake as one batch to keep its row order,
as a hand-drawn SVG (+ PNG).

* ``batches`` — deltalake (measured on 1.6.2) writes the batches of a stream
  concurrently and puts them in the file in the order they finish. A frame
  handed over in several batches came back shuffled: a one-line-per-row scan
  whose file straddled two batches was stored rotated, and the recipes that
  read it rebuilt a broken file (#1418). One batch per frame keeps its rows
  in place.

Usage:
    python dev/diagrams/delta_row_order.py --out docs/images/delta-row-order
    # writes <out>_batches.svg/.png

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
    PINK,
    RED,
    YELLOW,
    Box,
    Sketch,
    tick,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1500, 930
OK = "#2b8a3e"
BATCH = "#5f3dc4"
ROW_H = 22

# The frame: the lines of three files, a1-a3, b1-b4, c1-c3.
FRAME = ["a1", "a2", "a3", "b1", "b2", "b3", "b4", "c1", "c2", "c3"]
FILL = {"a": BLUE, "b": ORANGE, "c": GREEN}


def rows(s: Sketch, x: float, y: float, labels: list[str], *, w: float = 120) -> float:
    """A column of table rows, coloured by the file each line comes from."""
    for i, label in enumerate(labels):
        box = Box(x, y + i * ROW_H, w, ROW_H, FILL[label[0]], "")
        s.rect(box)
        s.text(box.cx, box.y + 16, label, size=14)
    return y + len(labels) * ROW_H


def batch_bracket(s: Sketch, x: float, y0: float, y1: float, label: str) -> None:
    s.line(x, y0 + 2, x, y1 - 2, colour=BATCH, width=2.4)
    s.text(x - 10, (y0 + y1) / 2 + 5, label, size=15, colour=BATCH, anchor="end")


def panel(s: Sketch, y: float, h: float, fill: str, title: str, subtitle: str) -> None:
    s.shade(40, y, W - 80, h, fill=fill, opacity=0.45)
    s.text(64, y + 34, title, size=21, weight="bold", anchor="start")
    s.text(64, y + 58, subtitle, size=14, colour=DIM, anchor="start")


def lane(
    s: Sketch,
    top: float,
    batches: list[list[str]],
    written: list[list[str]],
    verdict: str,
    good: bool,
) -> None:
    """frame -> batches -> deltalake -> the file it writes."""
    x_frame, x_dl, x_file = 260, 640, 1010
    y = top + 112
    s.text(x_frame + 60, y - 14, "frame (3 files' lines)", size=15, colour=DIM)
    yy = y
    for i, batch in enumerate(batches):
        end = rows(s, x_frame, yy, batch)
        batch_bracket(s, x_frame - 12, yy, end, f"batch {i + 1}")
        yy = end + 10

    dl = Box(x_dl, y + 40, 220, 150, YELLOW, "")
    s.rect(dl)
    s.text(dl.cx, dl.y + 34, "deltalake", size=19, weight="bold")
    s.text(dl.cx, dl.y + 62, "writes the batches", size=14, colour=DIM)
    s.text(dl.cx, dl.y + 82, "concurrently, kept", size=14, colour=DIM)
    s.text(dl.cx, dl.y + 102, "in the order they", size=14, colour=DIM)
    s.text(dl.cx, dl.y + 122, "finish", size=14, colour=DIM)
    s.arrow(x_frame + 132, dl.cy, dl.x - 8, dl.cy)
    s.arrow(dl.right + 8, dl.cy, x_file - 12, dl.cy)

    s.text(x_file + 60, y - 14, "the stored table", size=15, colour=DIM)
    yy = y
    for batch in written:
        yy = rows(s, x_file, yy, batch) + 10
    colour = OK if good else RED
    vx = x_file + 160
    if good:
        tick(s, vx, y + 40, size=9)
    else:
        s.cross(vx + 8, y + 40, size=10)
    for i, line in enumerate(verdict.split("\n")):
        s.text(vx + 26, y + 46 + i * 22, line, size=15, colour=colour, anchor="start")


def build_batches() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "A Delta write keeps the row order of one batch, not of several",
        "deltalake 1.6.2; colours are the files a one-line-per-row scan read",
    )

    top = 110
    panel(
        s,
        top,
        380,
        PINK,
        "1.22.0: the frame handed over a slice / chunk at a time",
        "several batches; file b straddles batches 1 and 2",
    )
    lane(
        s,
        top,
        [["a1", "a2", "a3", "b1", "b2"], ["b3", "b4", "c1", "c2", "c3"]],
        [["b3", "b4", "c1", "c2", "c3"], ["a1", "a2", "a3", "b1", "b2"]],
        "file b is stored rotated:\nb3 b4 … b1 b2\nits reader rebuilds a\nbroken file (#1418)",
        good=False,
    )

    top = 510
    panel(
        s,
        top,
        380,
        GREEN,
        "the fix: one batch per frame",
        "a whole frame goes through polars' export, as `write_delta` did before 1.22.0",
    )
    lane(
        s,
        top,
        [FRAME],
        [FRAME],
        "every row in place;\na recipe's batches each\nkeep their order too",
        good=True,
    )
    s.text(W - 60, H - 18, "batches are bracketed in violet", size=12.5, colour=DIM, anchor="end")
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/delta-row-order"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the batches schema under --out."""
    write(build_batches(), out, "batches", png=png)


if __name__ == "__main__":
    app()
