#!/usr/bin/env python3
"""Render the notebook-export schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, each drawing the thing rather than naming it:

* ``notebook_export``        — the dashboard grid and the document it becomes.
  The same nine tiles appear twice, in the same colours and the same numbers:
  laid out in a grid on the left, stacked in reading order on the right. The
  picture is the linearisation; the words only label it.
* ``notebook_report_render`` — the render job as a sequence over four
  lifelines, with the worker's activation drawn to scale against the wait, and
  an inset for the two ways Quarto returns an empty report and exits 0.

Usage:
    python dev/diagrams/notebook_export_schemas.py \
        --out docs/images/v0.12/react/schema
    # writes <out>_notebook_export.svg/.png and <out>_notebook_report_render.*

PNG rendering needs Playwright (already a dev dependency) and a local Virgil GS.
See sketch.py for the drawing primitives.
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


# --------------------------------------------------------------------------
# Shared shapes.
# --------------------------------------------------------------------------


def _file(s: Sketch, x: float, y: float, w: float, h: float, fill: str, name: str, sub: str):
    """A page with a folded corner: the artefact you end up with on disk."""
    fold = 20
    s.poly(
        [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)],
        fill=fill,
    )
    s.line(x + w - fold, y, x + w - fold, y + fold, colour=DIM, width=1.4, amount=1.0)
    s.line(x + w - fold, y + fold, x + w, y + fold, colour=DIM, width=1.4, amount=1.0)
    s.text(x + w / 2 - 8, y + 38, name, size=17, weight="bold")
    s.text(x + w / 2 - 8, y + 60, sub, size=13, colour=DIM)


def _ruled(s: Sketch, x1: float, x2: float, y: float, rows: int, gap: float, *, last: float = 1.0):
    """Grey rules standing in for text, so a block reads as content not as a label."""
    for i in range(rows):
        end = x2 if i < rows - 1 else x1 + (x2 - x1) * last
        s.line(x1, y + i * gap, end, y + i * gap, colour=GREY, width=1.4, amount=0.8, passes=1)


def _fold_mark(s: Sketch, x: float, y: float):
    """The disclosure triangle that says this section folds."""
    s.poly([(x, y - 5), (x + 11, y - 5), (x + 5.5, y + 5)], fill=DIM, colour=DIM, amount=0.6)


# --------------------------------------------------------------------------
# 1. The grid on the left is the scroll on the right.
# --------------------------------------------------------------------------

EXPORT_W, EXPORT_H = 1460, 920

# Nine tiles, in the order the export reads them: across each row, then down.
# The fill is the whole point of the diagram, so it is the first field: green
# is the author's own code inlined, blue is a component Depictio renders.
TILES = (
    (GREEN, "text"),
    (BLUE, "card"),
    (BLUE, "card"),
    (GREEN, "table"),
    (BLUE, "figure"),
    (GREEN, "figure"),
    (BLUE, "MultiQC"),
    (GREEN, "figure"),
    (BLUE, "heatmap"),
)

DX, DY, DW, DH = 56, 150, 470, 420
PX, PY, PW, PH = 900, 150, 420, 700
FX, FW = 604, 212


def _dashboard(s: Sketch) -> None:
    s.rect(Box(DX, DY, DW, DH, WHITE, ""))

    s.line(DX, DY + 40, DX + DW, DY + 40, colour=GREY, width=1.4, amount=0.8, passes=1)
    s.text(DX + 16, DY + 27, "nf-core/viralrecon", size=15, colour=DIM, anchor="start")

    for i, tab in enumerate(("MultiQC", "Coverage", "Variants")):
        tx = DX + 16 + i * 110
        s.rect(
            Box(tx, DY + 52, 102, 26, YELLOW if i == 0 else WHITE, ""),
            colour=INK if i == 0 else GREY,
        )
        s.text(tx + 51, DY + 70, tab, size=13, colour=INK if i == 0 else DIM)

    rail = Box(DX + 16, DY + 92, 96, DH - 112, VIOLET, "")
    s.rect(rail)
    s.text(rail.cx, DY + 116, "filters", size=14)
    _ruled(s, rail.x + 12, rail.right - 12, DY + 140, 5, 32, last=0.55)

    for i, (fill, label) in enumerate(TILES):
        col, row = i % 3, i // 3
        tile = Box(DX + 126 + col * 114, DY + 92 + row * 111, 100, 92, fill, "")
        s.rect(tile)
        s.text(tile.x + 9, tile.y + 20, str(i + 1), size=15, colour=DIM, anchor="start")
        s.text(tile.cx, tile.cy + 6, label, size=14)


def _document(s: Sketch) -> None:
    s.rect(Box(PX, PY, PW, PH, WHITE, ""))

    s.text(PX + PW / 2, PY + 40, "nf-core/viralrecon", size=19, weight="bold")
    _ruled(s, PX + 40, PX + PW - 40, PY + 60, 1, 0, last=0.7)

    # Provenance: three ruled rows, the shape of the table at the top of a report.
    for i in range(3):
        row = Box(PX + 34, PY + 78 + i * 26, PW - 68, 20, BLUE if i else YELLOW, "")
        s.rect(row, colour=GREY)
    s.text(
        PX + PW / 2,
        PY + 92 + 26 * 3,
        "where it came from, and how to re-run it",
        size=13,
        colour=DIM,
    )

    _fold_mark(s, PX + 34, PY + 200)
    s.text(PX + 54, PY + 206, "Filters", size=17, weight="bold", anchor="start")
    stages = Box(PX + 34, PY + 218, PW - 68, 64, VIOLET, "")
    s.rect(stages)
    s.text(stages.cx, stages.cy + 5, "what was active, and the funnel", size=14)

    _fold_mark(s, PX + 34, PY + 312)
    s.text(PX + 54, PY + 318, "Results", size=17, weight="bold", anchor="start")

    for i, (fill, label) in enumerate(TILES):
        cell = Box(PX + 34, PY + 332 + i * 38, PW - 68, 32, fill, "")
        s.rect(cell)
        s.text(cell.x + 10, cell.cy + 6, str(i + 1), size=15, colour=DIM, anchor="start")
        s.text(cell.x + 38, cell.cy + 5, label, size=14, anchor="start")
        _ruled(s, cell.x + 130, cell.right - 14, cell.cy - 3, 2, 12, last=0.45)


def build_export() -> Sketch:
    s = Sketch(EXPORT_W, EXPORT_H)

    s.heading(
        46,
        54,
        "A dashboard becomes a document",
        "the same nine tiles, read row by row instead of laid out in a grid",
    )

    _dashboard(s)
    _document(s)

    files = (
        (GREEN, "marimo .py", "canonical"),
        (GREEN, ".ipynb", "outputs stripped"),
        (GREEN, ".quarto.ipynb", "plus front matter"),
        (ORANGE, "report.html", "rendered here, opt-in"),
    )
    for i, (fill, name, sub) in enumerate(files):
        y = 168 + i * 106
        _file(s, FX, y, FW, 86, fill, name, sub)
        if i:
            s.arrow(FX + FW / 2 - 8, y - 20, FX + FW / 2 - 8, y - 2)

    # In and out of the file column: the export on one side, the render on the
    # other. Both arrows land on the artefact they actually concern.
    s.arrow(DX + DW + 8, DY + 150, FX - 8, 200)
    s.text(DX + DW + 12, DY + 182, "export", size=14, colour=DIM, anchor="start")
    s.arrow(FX + FW + 8, 530, PX - 8, 400)
    s.text(FX + FW + 14, 556, "render", size=14, colour=DIM, anchor="start")

    s.text(FX + FW / 2 - 8, 148, "one generator, four artefacts", size=14, colour=DIM)

    # The legend is the diagram's only real claim, so it sits under the grid
    # whose colours it explains rather than in a corner.
    for i, (fill, line) in enumerate(
        ((GREEN, "the author's own code, inlined"), (BLUE, "rendered through Depictio"))
    ):
        y = DY + DH + 44 + i * 44
        s.rect(Box(DX + 4, y, 34, 26, fill, ""))
        s.text(DX + 50, y + 19, line, size=15, anchor="start")

    s.text(
        DX + 4,
        DY + DH + 152,
        "nothing is guessed: a tile with no path either way is listed as omitted",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        PX + PW / 2,
        PY + PH + 34,
        "filters first, then each tab, row by row",
        size=14,
        colour=DIM,
    )
    return s


# --------------------------------------------------------------------------
# 2. The render job, over four lifelines.
# --------------------------------------------------------------------------

RENDER_W, RENDER_H = 1460, 960

LANES = (170, 520, 870, 1180)
TOP, BOTTOM = 148, 640


def _actor(s: Sketch, cx: float, label: str, sub: str, fill: str) -> None:
    s.rect(Box(cx - 100, TOP, 200, 54, fill, ""))
    s.text(cx, TOP + 25, label, size=17, weight="bold")
    s.text(cx, TOP + 44, sub, size=12, colour=DIM)
    s.line(cx, TOP + 54, cx, BOTTOM, dashed=True, colour=GREY, width=1.4, amount=0.8, passes=1)


def _msg(s: Sketch, i: int, j: int, y: float, label: str, *, dashed: bool = False) -> None:
    x1, x2 = LANES[i], LANES[j]
    step = 12 if x2 > x1 else -12
    s.arrow(x1 + step, y, x2 - step, y, dashed=dashed)
    s.text((x1 + x2) / 2, y - 11, label, size=13, colour=DIM)


def build_render() -> Sketch:
    s = Sketch(RENDER_W, RENDER_H)

    s.heading(
        46,
        54,
        "The report is a job, not a request",
        "the notebook is too big to pass around, and the render is too slow to wait on",
    )

    _actor(s, LANES[0], "Export modal", "in the browser", BLUE)
    _actor(s, LANES[1], "API", "owner check, then queue", VIOLET)
    _actor(s, LANES[2], "S3", "the notebook in, the report out", YELLOW)
    _actor(s, LANES[3], "Worker", "quarto + a jupyter kernel", ORANGE)

    _msg(s, 0, 1, 240, "asks for the report")
    _msg(s, 1, 2, 285, "stages the notebook")
    _msg(s, 1, 3, 330, "queues the job, with a short-lived token")
    _msg(s, 1, 0, 375, "hands back a job id, right away", dashed=True)
    _msg(s, 3, 2, 420, "reads the notebook back")

    # The activation bar is the only quantity here: it is drawn as long as the
    # reader actually waits, which is the reason the whole flow is a job.
    run = Box(LANES[3] - 20, 440, 40, 130, ORANGE, "")
    s.rect(run)
    s.text(LANES[3] - 34, 484, "quarto render", size=15, weight="bold", anchor="end")
    s.text(LANES[3] - 34, 508, "the notebook executed,", size=13, colour=DIM, anchor="end")
    s.text(LANES[3] - 34, 528, "not just converted", size=13, colour=DIM, anchor="end")
    s.text(LANES[3] + 34, 496, "forty-five seconds warm,", size=14, colour=DIM, anchor="start")
    s.text(LANES[3] + 34, 518, "four minutes cold", size=14, colour=DIM, anchor="start")

    # Polling runs the whole time the worker does, so it is drawn as a loop
    # spanning the activation rather than as one more message in the list.
    s.curve(
        [(LANES[0] + 12, 440), (LANES[0] + 92, 440), (LANES[0] + 92, 570), (LANES[0] + 24, 570)],
        colour=DIM,
    )
    s.arrow(LANES[0] + 40, 570, LANES[0] + 14, 570, colour=DIM)
    s.text(LANES[0] + 102, 508, "asks again", size=13, colour=DIM, anchor="start")
    s.text(LANES[0] + 102, 528, "every three seconds", size=13, colour=DIM, anchor="start")

    _msg(s, 3, 2, 600, "writes one self-contained page")
    _msg(s, 2, 0, 632, "the page comes back, through the API", dashed=True)

    # -- inset: what Quarto does when nobody checks ------------------------
    IY = 692
    s.text(
        46, IY, "Two ways Quarto hands back an empty report", size=18, weight="bold", anchor="start"
    )
    s.text(46, IY + 24, "both of them exit zero", size=14, colour=DIM, anchor="start")

    good = Box(52, IY + 44, 150, 118, WHITE, "")
    s.rect(good)
    _ruled(s, good.x + 16, good.right - 16, good.y + 26, 2, 16, last=0.7)
    s.rect(Box(good.x + 16, good.y + 62, good.w - 32, 40, GREEN, ""), colour=GREY)
    s.text(good.cx, good.bottom + 26, "with --execute", size=14)

    for k, (dx, caption) in enumerate(((226, "without it"), (400, "or with a python"))):
        bad = Box(52 + dx, IY + 44, 150, 118, WHITE, "")
        s.rect(bad)
        _ruled(s, bad.x + 16, bad.right - 16, bad.y + 26, 2, 16, last=0.7)
        s.rect(Box(bad.x + 16, bad.y + 62, bad.w - 32, 40, WHITE, ""), colour=GREY, dashed=True)
        s.cross(bad.cx, bad.y + 82, size=13)
        s.text(bad.cx, bad.bottom + 26, caption, size=14)
        if k:
            s.text(bad.cx, bad.bottom + 46, "that has no jupyter", size=14)

    s.text(
        52,
        IY + 250,
        "so the guard reads the log for an execution phase, never the exit code",
        size=14,
        colour=DIM,
        anchor="start",
    )

    # -- inset: whose code runs -------------------------------------------
    trust = Box(760, IY + 30, 650, 150, PINK, "")
    s.rect(trust, dashed=True, colour=RED)
    s.text(
        785,
        IY + 62,
        "The worker runs the dashboard author's own code",
        size=17,
        weight="bold",
        anchor="start",
    )
    s.text(
        785,
        IY + 92,
        "under a token minted for whoever asked for the report, so",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        785,
        IY + 114,
        "rendering is owner-only. A reader gets a refusal naming the",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        785,
        IY + 136,
        "code tiles, and the notebook to run themselves.",
        size=14,
        colour=DIM,
        anchor="start",
    )

    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"),
        "--out",
        help="Path prefix; each diagram appends its own name.",
    ),
    png: bool = typer.Option(True, help="Also rasterise each SVG with Playwright."),
) -> None:
    write(build_export(), out, "notebook_export", png=png)
    write(build_render(), out, "notebook_report_render", png=png)


if __name__ == "__main__":
    app()
