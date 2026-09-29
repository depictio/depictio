#!/usr/bin/env python3
"""Render why beanie was held at 2.0.0 as a hand-drawn SVG (+ PNG).

beanie >= 2.1 asks the client ``callable(client.append_metadata)``. The answer
depends on the driver, and the test double answers differently from the real
one, which is how the failure stayed invisible to the unit suite.

Usage:
    python dev/diagrams/pymongo_driver.py --out docs/images/pymongo-driver
    # writes <out>_append_metadata.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import DIM, GREEN, PINK, WHITE, YELLOW, Box, Sketch, write  # noqa: E402

app = typer.Typer(add_completion=False)

W, H = 1120, 640
COLS = ((40, 330), (430, 350), (840, 240))  # (x, width) of the three columns
ROW_H = 118


def cell(s: Sketch, col: int, y: float, fill: str, title: str, lines: tuple[str, ...]) -> Box:
    x, w = COLS[col]
    box = Box(x, y, w, ROW_H, fill, "")
    s.rect(box)
    s.text(box.cx, y + 36, title, size=21, weight="bold")
    for i, line in enumerate(lines):
        s.text(box.cx, y + 68 + i * 25, line, size=18, colour=DIM)
    return box


def build() -> Sketch:
    s = Sketch(W, H)
    s.text(40, 54, "Why beanie was stuck at 2.0.0", size=32, anchor="start")
    s.text(
        40,
        90,
        "beanie >= 2.1 calls `client.append_metadata(...)` when it is callable",
        size=20,
        colour=DIM,
        anchor="start",
    )
    for (x, w), label in zip(COLS, ("driver", "`client.append_metadata` is", "outcome")):
        s.text(x + w / 2, 142, label, size=19, colour=DIM)

    rows = (
        (
            PINK,
            ("motor (before)", ("`AsyncIOMotorClient`", "deprecated upstream")),
            ("a database named", ("`append_metadata`,", "callable only to raise")),
            ("TypeError", ("API startup fails",)),
        ),
        (
            YELLOW,
            ("mongomock-motor", ("unit-test double",)),
            ("a mock database,", ("not callable:", "beanie skips the call")),
            ("tests pass", ("the mock hid the bug",)),
        ),
        (
            GREEN,
            ("pymongo (this PR)", ("`AsyncMongoClient`", "pymongo >= 4.14")),
            ("a real method", ("beanie calls it", "and moves on")),
            ("startup completes", ("beanie 2.2.0",)),
        ),
    )
    for r, (fill, *cols) in enumerate(rows):
        y = 168 + r * (ROW_H + 30)
        boxes = [cell(s, c, y, fill if c != 1 else WHITE, *cols[c]) for c in range(3)]
        for a, b in zip(boxes, boxes[1:]):
            s.arrow(a.right + 8, a.cy, b.x - 8, b.cy)
        if r == 0:
            s.cross(boxes[2].right - 26, boxes[2].y + 26, size=12)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/pymongo-driver"),
        "--out",
        help="Output prefix; <out>_append_metadata.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the append_metadata schema under --out."""
    write(build(), out, "append_metadata", png=png)


if __name__ == "__main__":
    app()
