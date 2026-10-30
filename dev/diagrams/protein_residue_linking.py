#!/usr/bin/env python3
"""Render the protein-tile linking schema as a hand-drawn SVG (+ PNG).

Two ideas, drawn rather than boxed:

* the tiles of one protein share ``entity`` + ``position``. A click or a brush in
  any of them becomes a filter (entity, residue range) that narrows every table;
  a hover only highlights the residue in the other tiles, in the browser.
* the 3D model comes from a structure file of the run, or, when the server enables
  the structure resolver, from the cache, then AlphaFold DB, UniProt and ESMFold.

Usage:
    python dev/diagrams/protein_residue_linking.py --out docs/images/guides/protein-tiles/schema
    # writes <out>_residue_linking.svg and, unless --no-png, the PNG beside it

See sketch.py for the drawing primitives.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    BLUE_INK,
    DIM,
    GOLD,
    GREEN,
    GREEN_INK,
    GREY,
    LIGHT_GREY,
    ORANGE,
    PINK,
    RED,
    RED_INK,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    circle,
    tick,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1500, 900

# Residue cells of the sequence track and alignment, drawn on a shared grid so the
# same position lines up under every tile.
CELL, GAP, N_CELLS = 22, 2, 22
PICKED = range(9, 15)  # the brushed stretch
HOVERED = 17  # the residue under the pointer


def _band(s: Sketch, x: float, y: float, w: float, h: float, fill: str, opacity: float) -> None:
    s._parts.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" '
        f'fill="{fill}" fill-opacity="{opacity}"/>'
    )


def _tile(s: Sketch, x: float, y: float, w: float, h: float, title: str) -> Box:
    box = Box(x, y, w, h, WHITE, title, ())
    s.rect(box)
    s.text(x + 12, y + 22, title, size=14, anchor="start", weight="bold")
    return box


def _cell_x(x0: float, i: int) -> float:
    return x0 + i * (CELL + GAP)


def _hover_ring(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    s.rect(Box(x - 3, y - 3, w + 6, h + 6, "none", ""), colour=RED, dashed=True)


def _structure(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """The 3D tile: a folded ribbon with three picked residues and one hovered."""
    _tile(s, x, y, w, h, "3D structure")
    ribbon = [
        (x + 54, y + 150),
        (x + 78, y + 110),
        (x + 110, y + 128),
        (x + 138, y + 84),
        (x + 168, y + 112),
        (x + 192, y + 78),
        (x + 214, y + 104),
    ]
    s.curve(ribbon, colour=BLUE_INK)
    s.curve([(px + 4, py + 5) for px, py in ribbon], colour=BLUE_INK)
    for px, py in ((x + 110, y + 128), (x + 138, y + 84), (x + 168, y + 112)):
        s.dot(px, py, 7, fill=GOLD)
    px, py = ribbon[5]
    s.dot(px, py, 6, fill=WHITE, colour=RED)
    s.rect(Box(px - 12, py - 12, 24, 24, "none", ""), colour=RED, dashed=True)


def _sequence(s: Sketch, x: float, y: float, w: float, h: float) -> float:
    _tile(s, x, y, w, h, "sequence track")
    x0, y0 = x + 14, y + 42
    for i in range(N_CELLS):
        fill = GOLD if i in PICKED else LIGHT_GREY
        s.rect(Box(_cell_x(x0, i), y0, CELL, 32, fill, ""), colour=GREY)
    s.text(_cell_x(x0, PICKED.start) + 3 * (CELL + GAP), y0 + 52, "brushed", size=12, colour=DIM)
    _hover_ring(s, _cell_x(x0, HOVERED), y0, CELL, 32)
    return x0


def _alignment(s: Sketch, x: float, y: float, w: float, h: float, x0: float) -> None:
    _tile(s, x, y, w, h, "alignment")
    colours = (BLUE, GREEN, PINK, VIOLET)
    right = _cell_x(x0, N_CELLS) - GAP
    for i, fill in enumerate(colours):
        ry = y + 36 + i * 16
        s.poly(
            [(x0, ry), (right, ry), (right, ry + 11), (x0, ry + 11)],
            fill=fill,
            colour=GREY,
            amount=0.6,
        )
    first, last = PICKED.start, PICKED.stop - 1
    _band(s, _cell_x(x0, first), y + 30, _cell_x(x0, last) + CELL - _cell_x(x0, first), 74, GOLD, 0.55)
    _hover_ring(s, _cell_x(x0, HOVERED), y + 33, CELL, 68)


def _table(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    _tile(s, x, y, w, h, "variants table")
    cols = (x + 190, x + 360, x + 530)
    for cx, label in zip(cols, ("entity", "position", "consequence")):
        s.text(cx, y + 22, label, size=12, colour=DIM, anchor="start")
    s.line(x + 180, y + 28, x + w - 14, y + 28, colour=GREY, amount=0.4, passes=1, width=1)
    rows = (
        ("demo_protein", "44", "missense", True),
        ("demo_protein", "47", "nonsense", True),
        ("demo_protein", "53", "missense", True),
    )
    for i, (ent, pos, cons, keep) in enumerate(rows):
        ry = y + 34 + i * 16
        _band(s, x + 180, ry, w - 194, 15, GOLD, 0.35)
        for cx, val in zip(cols, (ent, pos, cons)):
            s.text(cx, ry + 12, val, size=12, anchor="start")
    s.text(x + 12, y + 52, "12 rows,", size=13, anchor="start", colour=DIM)
    s.text(x + 12, y + 70, "3 kept", size=13, anchor="start")


def build() -> Sketch:
    s = Sketch(W, H)

    s.heading(
        46,
        52,
        "Protein tiles: one protein, linked by residue",
        "the tiles share `entity` + `position`; a pick filters, a hover only highlights",
    )

    # -- the linked dashboard -------------------------------------------------
    bx, by, bw, bh = 46, 120, 860, 372
    browser(s, bx, by, bw, bh)
    _structure(s, bx + 18, by + 42, 250, 220)
    x0 = _sequence(s, bx + 286, by + 42, 556, 100)
    _alignment(s, bx + 286, by + 154, 556, 108, x0)
    _table(s, bx + 18, by + 274, bw - 36, 88)

    # Legend for the two marks every tile carries.
    ly = 520
    _band(s, 50, ly - 13, 24, 16, GOLD, 0.9)
    s.text(84, ly, "picked range: becomes the filter", size=14, colour=DIM, anchor="start")
    s.rect(Box(420, ly - 15, 24, 20, "none", ""), colour=RED, dashed=True)
    s.text(456, ly, "hovered residue: highlight only", size=14, colour=DIM, anchor="start")

    # -- the two gestures -----------------------------------------------------
    pick = Box(1000, 140, 454, 92, BLUE, "A click or a brush is a filter",
               ("`entity` + a residue range", "the last gesture wins"))
    narrow = Box(1000, 290, 454, 78, GREEN, "Every table narrows", ("each one with those columns",))
    hover = Box(1000, 408, 454, 92, LIGHT_GREY, "A hover only highlights",
                ("the same residue in the other tiles", "browser only: no filter, no request"))
    for b in (pick, narrow, hover):
        s.box(b)
    s.arrow(bx + bw + 8, pick.cy, pick.x - 10, pick.cy)
    s.text(bx + bw + 46, pick.cy - 12, "click, brush", size=13, colour=DIM)
    s.arrow(pick.cx, pick.bottom + 8, pick.cx, narrow.y - 10)
    s.arrow(bx + bw + 8, hover.cy, hover.x - 10, hover.cy, dashed=True)
    s.text(bx + bw + 46, hover.cy - 12, "hover", size=13, colour=DIM)

    # -- where the 3D model comes from ---------------------------------------
    s.line(46, 552, W - 46, 552, dashed=True, colour=GREY, width=1.2, passes=1)
    s.heading(46, 596, "Where the 3D model comes from")

    file_src = Box(46, 640, 270, 88, ORANGE, "`structure_source: file`",
                   ("a pdb or mmcif file", "per protein, from the run"))
    indexed = Box(380, 640, 380, 88, WHITE, "An indexed_file collection",
                  ("fetched with a presigned URL", "no outbound call from the server"))
    resolve = Box(46, 760, 270, 88, PINK, "`structure_source: resolve`",
                  ("off until the server", "enables the resolver"))
    cache = Box(380, 760, 190, 88, LIGHT_GREY, "Bucket cache", ("a model fetched", "before"))
    alphafold = Box(618, 760, 200, 88, BLUE, "AlphaFold DB", ("by UniProt accession",))
    uniprot = Box(866, 760, 190, 88, BLUE, "UniProt", ("gene + taxon", "to an accession"))
    esmfold = Box(1104, 760, 190, 88, BLUE, "ESMFold", ("folds a sequence", "up to 400 aa"))
    for b in (file_src, indexed, resolve, cache, alphafold, uniprot, esmfold):
        s.box(b)
    s.arrow(file_src.right + 8, file_src.cy, indexed.x - 10, indexed.cy)
    s.arrow(resolve.right + 8, resolve.cy, cache.x - 10, cache.cy)
    for a, b in ((cache, alphafold), (alphafold, uniprot), (uniprot, esmfold)):
        s.arrow(a.right + 8, a.cy, b.x - 10, b.cy)

    # The tile both routes end in.
    tx, ty, tw, th = 1364, 690, 90, 120
    s.rect(Box(tx, ty, tw, th, WHITE, ""))
    s.text(tx + tw / 2, ty + 22, "3D tile", size=14, weight="bold")
    s.curve([(tx + 18, ty + 92), (tx + 34, ty + 62), (tx + 52, ty + 78), (tx + 72, ty + 50)], colour=BLUE_INK)
    s.dot(tx + 52, ty + 78, 5, fill=GOLD)
    s.arrow(indexed.right + 8, indexed.cy, tx - 10, ty + 38)
    s.arrow(esmfold.right + 8, esmfold.cy, tx - 10, ty + 84)

    s.text(
        W - 46,
        H - 26,
        "first hit wins, and the tile names the source it used",
        size=14,
        colour=DIM,
        anchor="end",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/guides/protein-tiles/schema"),
        "--out",
        help="Output prefix; '_residue_linking.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the schema SVG (and PNG) under --out."""
    write(build(), out, "residue_linking", png=png)


if __name__ == "__main__":
    app()
