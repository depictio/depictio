#!/usr/bin/env python3
"""Render a recipe's contract, inputs on one side and output on the other, as a
hand-drawn SVG (+ PNG), with the constants renamed by #863.

Usage:
    python dev/diagrams/recipe_output_schema.py --out docs/images/recipe-output-schema
    # writes <out>_contract.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import BLUE, DIM, GREEN, GREY, PINK, VIOLET, YELLOW, Box, Sketch, write  # noqa: E402

app = typer.Typer(add_completion=False)

W, H = 1120, 700


def panel(
    s: Sketch, x: float, y: float, w: float, h: float, fill: str, title: str, lines: tuple[str, ...]
) -> Box:
    box = Box(x, y, w, h, fill, "")
    s.rect(box)
    s.text(box.cx, y + 38, title, size=22, weight="bold")
    for i, line in enumerate(lines):
        s.text(box.cx, y + 72 + i * 26, line, size=18, colour=DIM)
    return box


def build() -> Sketch:
    s = Sketch(W, H)
    s.text(40, 54, "A recipe declares its inputs and its output", size=32, anchor="start")
    s.text(
        40,
        90,
        "the output-side constants now say so, like `SOURCES` does for the inputs",
        size=20,
        colour=DIM,
        anchor="start",
    )

    sources = panel(
        s,
        40,
        150,
        300,
        170,
        BLUE,
        "`SOURCES`",
        ("inputs: files, globs,", "or another DC", "(`RecipeSource`)"),
    )
    transform = panel(
        s, 410, 150, 300, 170, YELLOW, "`transform()`", ("`sources` in,", "one DataFrame out")
    )
    output = Box(780, 150, 300, 170, GREEN, "")
    s.rect(output)
    s.text(output.cx, 188, "output checked against", size=19, colour=DIM)
    s.text(output.cx, 232, "`OUTPUT_SCHEMA`", size=21, weight="bold")
    s.text(output.cx, 258, "required columns and types", size=17, colour=DIM)
    s.text(output.cx, 294, "`OPTIONAL_OUTPUT_SCHEMA`", size=19, weight="bold")
    s.arrow(sources.right + 8, sources.cy, transform.x - 8, transform.cy)
    s.arrow(transform.right + 8, transform.cy, output.x - 8, output.cy)

    s.text(40, 400, "Renamed in every bundled recipe", size=24, anchor="start")
    for i, (old, new) in enumerate(
        (("EXPECTED_SCHEMA", "OUTPUT_SCHEMA"), ("OPTIONAL_SCHEMA", "OPTIONAL_OUTPUT_SCHEMA"))
    ):
        y = 440 + i * 70
        s.rect(Box(40, y, 330, 50, VIOLET, ""))
        s.text(205, y + 33, f"`{old}`", size=20)
        s.arrow(385, y + 25, 455, y + 25)
        s.rect(Box(470, y, 380, 50, GREEN, ""))
        s.text(660, y + 33, f"`{new}`", size=20)

    note = Box(40, 600, 1040, 64, PINK, "")
    s.rect(note, colour=GREY)
    s.cross(78, 632, size=12)
    s.text(
        110,
        640,
        "a recipe still using an old name fails to load, with the rename to make",
        size=20,
        anchor="start",
    )
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
