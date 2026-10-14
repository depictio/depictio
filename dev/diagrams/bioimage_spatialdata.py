#!/usr/bin/env python3
"""Render the SpatialData table source schemas as hand-drawn SVGs (+ PNGs).

* ``one_store_two_dcs``       - one SpatialData store feeds two data collections:
  the image subtree for the viewer tile, the AnnData table for filters and cards.
* ``sync_and_coordinates``    - what a CLI re-run picks up after the AnnData
  changes, and how shape centres become the image's pixels.

Usage:
    python dev/diagrams/bioimage_spatialdata.py --out docs/images/bioimage/schema
    # writes <out>_one_store_two_dcs.svg/.png and <out>_sync_and_coordinates.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    GREY,
    INK,
    ORANGE,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)

# Stronger fills for the pictograms, still in Excalidraw's pastel family.
TISSUE = "#fcc2d7"
TISSUE_DARK = "#e64980"
S3 = "#ffd8a8"
DELTA = "#b2f2bb"
BAR_BLUE = "#a5d8ff"
SCREEN = "#f8f9fa"
CLUSTERS = ("#4dabf7", "#f59f00", "#40c057", "#be4bdb")


# --------------------------------------------------------------------------
# Pictograms.
# --------------------------------------------------------------------------


def _ellipse(cx: float, cy: float, rx: float, ry: float, t0: float, t1: float, n: int = 18):
    return [
        (cx + rx * math.cos(t0 + (t1 - t0) * i / n), cy + ry * math.sin(t0 + (t1 - t0) * i / n))
        for i in range(n + 1)
    ]


def circle(s: Sketch, cx: float, cy: float, r: float, fill: str, colour: str = INK) -> None:
    s.poly(_ellipse(cx, cy, r, r, 0, 2 * math.pi, 14)[:-1], fill=fill, colour=colour, amount=0.6)


def folder(s: Sketch, x: float, y: float, w: float, h: float, fill: str) -> None:
    """A folder: a tab on the top left, then the body."""
    s.poly([(x, y + 18), (x, y), (x + 120, y), (x + 138, y + 18)], fill=fill)
    s.rect(Box(x, y + 18, w, h - 18, fill, ""))


def tissue(s: Sketch, x: float, y: float, w: float, h: float, *, spots: bool = True) -> None:
    """An H&E thumbnail: a pink blob, optionally with cluster-coloured spots on it."""
    s.rect(Box(x, y, w, h, WHITE, ""))
    cx, cy = x + w / 2, y + h / 2
    blob = [
        (
            cx + (w * 0.4) * math.cos(t) * (1 + 0.12 * math.sin(3 * t)),
            cy + (h * 0.38) * math.sin(t) * (1 + 0.1 * math.cos(2 * t)),
        )
        for t in (2 * math.pi * i / 16 for i in range(16))
    ]
    s.poly(blob, fill=TISSUE, colour=TISSUE_DARK, amount=1.0)
    if spots:
        for i in range(4):
            for j in range(3):
                px = cx - w * 0.24 + i * w * 0.16
                py = cy - h * 0.18 + j * h * 0.18
                circle(s, px, py, 3.4, CLUSTERS[(i + j) % 4], colour=CLUSTERS[(i + j) % 4])


def bucket(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """Object storage: a pail wider at the rim than at the base."""
    rx, ry, base = w / 2, h * 0.13, w * 0.36
    body = [(cx - rx, top + ry)]
    body += _ellipse(cx, top + h - ry * 0.7, base, ry * 0.7, math.pi, 0)
    body += [(cx + rx, top + ry)]
    s.poly(body, fill=fill, edges=tuple(range(len(body) - 1)))
    s.poly(_ellipse(cx, top + ry, rx, ry, 0, 2 * math.pi)[:-1], fill=WHITE, amount=0.8)


def cylinder(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """A table store: a body with a rounded bottom, capped by a lighter ellipse."""
    rx, ry = w / 2, h * 0.14
    body = [(cx - rx, top + ry)]
    body += _ellipse(cx, top + h - ry, rx, ry, math.pi, 0)
    body += [(cx + rx, top + ry)]
    s.poly(body, fill=fill, edges=tuple(range(len(body) - 1)))
    s.poly(_ellipse(cx, top + ry, rx, ry, 0, 2 * math.pi)[:-1], fill=WHITE, amount=0.8)


def pill(s: Sketch, cx: float, cy: float, text: str, fill: str, *, w: float = 150) -> None:
    s.rect(Box(cx - w / 2, cy - 17, w, 34, fill, ""))
    s.text(cx, cy + 6, text, size=16, weight="bold")


def chip(
    s: Sketch, cx: float, cy: float, text: str, fill: str, *, w: float, size: float = 15
) -> None:
    s.rect(Box(cx - w / 2, cy - 16, w, 32, fill, ""))
    s.text(cx, cy + 5, text, size=size)


# --------------------------------------------------------------------------
# 1. One store, two data collections.
# --------------------------------------------------------------------------

STORE_W, STORE_H = 1640, 890


def build_one_store_two_dcs() -> Sketch:
    s = Sketch(STORE_W, STORE_H)
    s.heading(
        46,
        52,
        "One SpatialData store, two data collections",
        "the image and its AnnData table come from the same `skin.zarr`; nothing is exported by hand",
    )

    # -- the store, drawn as a folder tree ---------------------------------
    folder(s, 40, 118, 360, 480, YELLOW)
    s.text(60, 132, "`skin.zarr`", size=18, anchor="start")
    tx = 70
    rows = (
        (0, "`images/he`", 190),
        (0, "`tables/table`", 330),
        (1, "`obs`  spot_id, cluster", 368),
        (1, "`obsm`  spatial", 404),
        (1, "`X`  genes", 440),
        (0, "`shapes/spots`", 500),
    )
    s.line(tx - 12, 170, tx - 12, 495, width=1.3, colour=DIM, passes=1)
    for depth, label, y in rows:
        x = tx + depth * 34
        s.line(x - 12, y - 5, x - 2, y - 5, width=1.3, colour=DIM, passes=1)
        s.text(x + 2, y, label, size=16, anchor="start")
    s.line(tx + 22, 342, tx + 22, 435, width=1.3, colour=DIM, passes=1)
    tissue(s, 90, 204, 150, 100, spots=False)
    for i in range(6):
        circle(s, 110 + i * 26, 530, 7, WHITE, colour=DIM)
    s.text(176, 566, "spot geometries", size=13, colour=DIM)

    # -- the CLI -------------------------------------------------------------
    pill(s, 480, 380, "`depictio run`", WHITE, w=150)
    s.text(480, 414, "CLI ingest", size=14, colour=DIM)
    s.arrow(372, 380, 402, 380)

    # -- (a) bioimage DC ---------------------------------------------------
    dca = Box(600, 128, 380, 190, BLUE, "bioimage DC")
    s.box(dca)
    s.text(dca.x + 24, dca.y + 62, "only the `images/he` subtree", size=15, anchor="start")
    s.text(dca.x + 24, dca.y + 86, "is uploaded to S3", size=15, anchor="start")
    s.text(dca.x + 24, dca.y + 122, "served by byte ranges", size=15, anchor="start")
    s.text(dca.x + 24, dca.y + 146, "to the viewer", size=15, anchor="start")
    bucket(s, dca.right - 58, dca.y + 96, 70, 68, S3)
    s.text(dca.right - 58, dca.y + 180, "S3", size=14, colour=DIM)
    s.curve([(480, 362), (480, 223), (590, 223)], colour=INK)
    s.arrow(575, 223, 598, 223)

    # -- (b) table DC ------------------------------------------------------
    dcb = Box(600, 400, 380, 238, GREEN, "table DC")
    s.box(dcb)
    for i, line in enumerate(
        (
            "`obs` columns",
            "x, y converted to the image pixels",
            "selected genes as columns",
            "written to Delta",
        )
    ):
        s.text(dcb.x + 24, dcb.y + 66 + i * 30, line, size=15, anchor="start")
    cylinder(s, dcb.right - 58, dcb.y + 132, 64, 64, DELTA)
    s.text(dcb.right - 58, dcb.y + 222, "Delta", size=14, colour=DIM)
    s.curve([(480, 424), (480, 519), (590, 519)], colour=INK)
    s.arrow(575, 519, 598, 519)

    # -- before: the hand-made CSV ------------------------------------------
    s.text(220, 670, "before: export CSV by hand", size=17, colour=RED)
    s.line(220, 602, 220, 646, dashed=True, colour=GREY)
    s.line(220, 684, 220, 740, dashed=True, colour=GREY)
    s.line(220, 740, dcb.cx, 740, dashed=True, colour=GREY)
    s.arrow(dcb.cx, 740, dcb.cx, dcb.bottom + 8, dashed=True, colour=GREY)
    s.cross(500, 740, size=14)
    s.text(500, 778, "no more stale `spots.csv` next to the store", size=14, colour=DIM)

    # -- the dashboard -----------------------------------------------------
    dash = Box(1070, 118, 550, 740, VIOLET, "")
    s.rect(dash)
    s.text(dash.cx, dash.y + 34, "Dashboard", size=21, weight="bold")

    # viewer tile
    tile = Box(dash.x + 18, dash.y + 56, 330, 250, WHITE, "")
    s.rect(tile)
    s.text(tile.cx, tile.y + 24, "viewer tile: image + points", size=15, weight="bold")
    tissue(s, tile.x + 24, tile.y + 40, 282, 190)
    # lasso, on the left of the tissue so its arrow drops clear of the rest
    lcx = tile.x + 110
    lasso = _ellipse(lcx, tile.y + 136, 64, 42, 0, 2 * math.pi, 14)
    for (x1, y1), (x2, y2) in zip(lasso, lasso[1:]):
        s.line(x1, y1, x2, y2, dashed=True, colour=INK, amount=1.0, width=1.4, passes=1)

    # sidebar filters, right of the tile
    side = Box(tile.right + 40, tile.y, dash.right - 18 - tile.right - 40, 250, WHITE, "")
    s.rect(side, colour=DIM)
    s.text(side.cx, side.y + 26, "filters", size=15, weight="bold")
    for i, label in enumerate(("cluster", "n_nuclei", "gene_A")):
        y = side.y + 66 + i * 62
        s.text(side.x + 14, y, label, size=13, colour=DIM, anchor="start")
        s.line(side.x + 16, y + 24, side.right - 16, y + 24, width=1.3, colour=DIM, passes=1)
        circle(s, side.x + 40 + i * 24, y + 24, 6, BAR_BLUE)
    s.arrow(side.x - 4, side.y + 130, tile.right + 4, side.y + 130, dashed=True, colour=INK)
    s.text(side.cx, side.bottom + 28, "filters fade", size=15, weight="bold")
    s.text(side.cx, side.bottom + 48, "points on the image", size=15, weight="bold")

    # table
    tab = Box(dash.x + 18, tile.bottom + 110, dash.w - 36, 170, WHITE, "")
    s.rect(tab)
    s.text(tab.x + 16, tab.y + 26, "table", size=15, weight="bold", anchor="start")
    cols = ("spot_id", "cluster", "x", "y", "gene_A")
    step = (tab.w - 40) / len(cols)
    for i, c in enumerate(cols):
        s.text(tab.x + 20 + step * (i + 0.5), tab.y + 58, f"`{c}`", size=13)
    s.line(tab.x + 10, tab.y + 68, tab.right - 10, tab.y + 68, width=1.2, colour=DIM, passes=1)
    for r in range(3):
        y = tab.y + 88 + r * 26
        s.rect(Box(tab.x + 12, y, tab.w - 24, 18, SCREEN if r != 1 else BAR_BLUE, ""), colour=GREY)

    # lasso -> table
    s.curve([(lcx - 20, tile.y + 176), (lcx - 20, tile.bottom + 4)], colour=INK)
    s.arrow(lcx - 20, tile.bottom + 4, lcx - 20, tab.y - 4)
    s.text(lcx - 4, tile.bottom + 46, "lasso =", size=15, weight="bold", anchor="start")
    s.text(lcx - 4, tile.bottom + 68, "filter on cell ids", size=15, weight="bold", anchor="start")

    # cards
    for i, (val, label) in enumerate((("618", "spots"), ("4", "clusters"))):
        card = Box(dash.x + 18 + i * 264, tab.bottom + 22, 250, 84, ORANGE, "")
        s.rect(card)
        s.text(card.cx, card.y + 42, val, size=26, weight="bold")
        s.text(card.cx, card.y + 68, label, size=14, colour=DIM)

    # DCs into the dashboard
    s.arrow(dca.right + 4, dca.cy, tile.x - 4, dca.cy)
    s.curve([(dcb.right + 4, dcb.y + 190), (1036, dcb.y + 190), (1036, tab.cy)], colour=INK)
    s.arrow(1036, tab.cy, tab.x - 4, tab.cy)
    s.text(1010, dcb.y + 180, "linked", size=13, colour=DIM)
    return s


# --------------------------------------------------------------------------
# 2. Sync on re-run, and coordinates.
# --------------------------------------------------------------------------

SYNC_W, SYNC_H = 1640, 820


def build_sync_and_coordinates() -> Sketch:
    s = Sketch(SYNC_W, SYNC_H, seed=11)

    # -- left: stays in sync on re-run ---------------------------------------
    s.heading(46, 52, "Stays in sync on re-run", "the store's fingerprint is the file hash")
    steps = (
        (PINK, "AnnData edited", "new clusters in `obs`"),
        (YELLOW, "fingerprint changes", "`tables/table` + shapes + image metadata"),
        (WHITE, "`depictio run`", "re-extracts only that table"),
        (GREEN, "Delta updated", "same DC, table rewritten"),
        (VIOLET, "dashboard", "shows the new clusters"),
    )
    x, w, h, gap = 60, 440, 76, 36
    for i, (fill, title, line) in enumerate(steps):
        y = 120 + i * (h + gap)
        s.box(Box(x, y, w, h, fill, title, (line,)))
        if i:
            s.arrow(x + w / 2, y - gap + 4, x + w / 2, y - 4)
    # the image is left alone
    run_y = 120 + 2 * (h + gap)
    img = Box(556, run_y - 6, 236, 88, WHITE, "")
    s.rect(img, colour=DIM, dashed=True)
    tissue(s, img.x + 12, img.y + 12, 70, 64, spots=False)
    s.text(img.x + 160, img.y + 38, "`images/he`", size=14)
    s.text(img.x + 160, img.y + 62, "not re-uploaded", size=14, colour=RED)
    s.line(x + w + 4, run_y + h / 2, img.x - 4, run_y + h / 2, dashed=True, colour=GREY)
    s.cross(530, run_y + h / 2, size=10)

    note_y = 120 + 5 * (h + gap) + 10
    s.rect(Box(60, note_y, 700, 52, SCREEN, ""), colour=GREY, dashed=True)
    s.text(410, note_y + 33, "live sync without re-running the CLI: next PR", size=17, colour=DIM)

    s.line(820, 100, 820, 780, dashed=True, colour=GREY)

    # -- right: coordinates ------------------------------------------------
    s.heading(870, 52, "Coordinates", "x, y land in the image's own pixels")
    csteps = (
        (BLUE, "shape centres", "x, y in the shapes space"),
        (WHITE, "element transform", "shapes to the coordinate system"),
        (YELLOW, 'coordinate system "global"', "shared by shapes and image"),
        (WHITE, "inverse of the image's transform", "level 0 only"),
        (GREEN, "image pixels", "`x`, `y` columns of the table DC"),
    )
    cx0, cw = 880, 440
    for i, (fill, title, line) in enumerate(csteps):
        y = 120 + i * (h + gap)
        s.box(Box(cx0, y, cw, h, fill, title, (line,)))
        if i:
            s.arrow(cx0 + cw / 2, y - gap + 4, cx0 + cw / 2, y - 4)
    inv_y = 120 + 3 * (h + gap) + h / 2
    chip(s, 1470, inv_y, "Visium hires: scale 0.08", ORANGE, w=230)
    s.line(cx0 + cw + 4, inv_y, 1355 - 4, inv_y, dashed=True, colour=DIM)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/bioimage/schema"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render PNGs through Playwright."),
) -> None:
    """Write the one-store and sync/coordinates schemas under --out."""
    write(build_one_store_two_dcs(), out, "one_store_two_dcs", png=png)
    write(build_sync_and_coordinates(), out, "sync_and_coordinates", png=png)


if __name__ == "__main__":
    app()
