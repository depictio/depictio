#!/usr/bin/env python3
"""Render how a recipe's output reaches Delta Lake, before and after streaming,
as a hand-drawn SVG (+ PNG).

* ``peak`` — the hmm_profile recipe at reporter scale. Before, ``transform()``
  built the whole table in memory and ``write_delta`` exported it in one go, so
  the frame, its export copy and the digest's floats were all resident at once.
  After, ``transform_batches()`` yields one batch at a time and
  ``write_deltalake`` consumes them as a single Arrow stream: one commit, a
  fraction of the peak. A bar chart gives the peak RSS of each step on the way.

Usage:
    python dev/diagrams/recipe_memory.py --out docs/images/recipe-memory
    # writes <out>_peak.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
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
    tick,
    warning,
    write,
)

app = typer.Typer(add_completion=False)

# Peak RSS of the reporter-scale run, in GB, one entry per step of the fix.
# The last value is an estimate until it is measured: change it here and the
# bar chart and the "after" badge both follow.
PEAK_RSS_GB: dict[str, float] = {
    "`main`": 10.2,
    "files read one at a time": 10.0,
    "sliced write": 7.3,
    "Categorical text columns": 4.8,
    "streamed recipe": 2.2,
}
#: Entries of PEAK_RSS_GB that are estimates rather than measurements.
ESTIMATED: frozenset[str] = frozenset()

BAR_FILLS = (PINK, PINK, ORANGE, YELLOW, GREEN)

W, H = 1600, 1080
OK = "#2b8a3e"
DELTA = "#d0ebff"


def gb(label: str) -> str:
    """A peak as printed: ``≈`` in front of an estimate."""
    value = PEAK_RSS_GB[label]
    return f"{'≈' if label in ESTIMATED else ''}{value:g} GB"


# -- local helpers built on the Sketch primitives ----------------------------


def stage(
    s: Sketch,
    box: Box,
    lines: tuple[tuple[str, str], ...],
    *,
    dashed: bool = False,
    colour: str = INK,
) -> Box:
    """A box with a bold title and centred lines, each in its own ink."""
    s.rect(box, dashed=dashed, colour=colour)
    s.text(box.cx, box.y + 30, box.title, size=18, weight="bold")
    for i, (line, ink) in enumerate(lines):
        s.text(box.cx, box.y + 58 + i * 22, line, size=14.5, colour=ink)
    return box


def link(s: Sketch, a: Box, b: Box, label: str = "", *, y: float | None = None) -> None:
    """A left-to-right arrow between two boxes, its label above it."""
    ay = a.cy if y is None else y
    s.arrow(a.right + 6, ay, b.x - 6, ay)
    if label:
        s.text((a.right + b.x) / 2, ay - 10, label, size=12.5, colour=DIM)


def panel(s: Sketch, y: float, h: float, fill: str, title: str, peak: str, ink: str) -> None:
    s.shade(40, y, W - 80, h, fill=fill, opacity=0.45, colour=GREY)
    s.text(64, y + 34, title, size=21, weight="bold", anchor="start")
    s.text(W - 64, y + 36, peak, size=24, weight="bold", colour=ink, anchor="end")


def batch_cards(s: Sketch, x: float, y: float) -> None:
    """Three small cards on an arrow: the batches going by, one at a time."""
    for i in range(3):
        s.rect(Box(x + i * 16, y - i * 3, 22, 16, VIOLET, ""), colour=DIM)


# -- the schema ---------------------------------------------------------------


def build_peak() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "A recipe's output on its way to Delta Lake",
        "hmm_profile at reporter scale: the whole table at once, then one batch at a time",
    )

    # Five columns, shared by both panels so the two pipelines line up.
    cols = ((70, 190), (320, 260), (670, 290), (1070, 220), (1350, 180))

    # ---- before -------------------------------------------------------------
    top = 110
    panel(s, top, 280, PINK, "before (`main`)", f"peak {gb('`main`')}", RED)
    warning(s, W - 64 - 200, top + 28, size=12)
    by, bh = top + 70, 180

    def col(i: int, title: str, fill: str, y: float = by, h: float = bh) -> Box:
        x, w = cols[i]
        return Box(x, y, w, h, fill, title)

    src = stage(
        s,
        col(0, "sources", WHITE),
        (("scan of HMM and", DIM), ("alignment text files", DIM), ("~1 GB", INK)),
    )
    tr = stage(
        s,
        col(1, "`transform()`", ORANGE),
        (
            ("builds the whole table", DIM),
            ("25.5M rows, 5.1 GB", RED),
            ("(String / Float64)", DIM),
            ("+ every text decompressed", RED),
            ("in a Python dict", DIM),
        ),
    )
    wd = stage(
        s,
        col(2, "`write_delta`", ORANGE),
        (("exports the whole frame", DIM), ("at once", DIM), ("+4 GB copy", RED)),
    )
    dg = stage(
        s,
        col(3, "digest", ORANGE),
        (("copies every float", DIM), ("to hash the rows", DIM)),
    )
    dl = stage(s, col(4, "Delta Lake", DELTA), (("one commit", DIM),))
    link(s, src, tr)
    link(s, tr, wd)
    link(s, wd, dg)
    link(s, dg, dl)
    s.text(
        (tr.x + dg.right) / 2,
        by + bh + 22,
        "all of it is resident at the same time",
        size=14,
        colour=RED,
    )

    # ---- after --------------------------------------------------------------
    top = 420
    panel(s, top, 320, GREEN, "after (this PR)", f"peak {gb('streamed recipe')}", OK)
    tick(s, W - 64 - 190, top + 28, size=9)
    by, bh = top + 70, 180

    src = stage(
        s,
        col(0, "sources", WHITE, by),
        (("scan of HMM and", DIM), ("alignment text files", DIM), ("~1 GB", INK)),
    )
    tb = stage(
        s,
        col(1, "`transform_batches()`", ORANGE, by),
        (
            ("yields one batch at a time", DIM),
            ("~256 families,", DIM),
            ("~150 MB", OK),
            ("text columns held", DIM),
            ("as Categorical", OK),
        ),
    )
    x, w = cols[2]
    each = Box(x, by, w, bh, VIOLET, "each batch")
    s.rect(each)
    s.text(each.cx, by + 30, "each batch", size=18, weight="bold")
    steps = (
        "validate the schema",
        "tag `depictio_run_id`",
        "hash rows for the digest",
        "Categorical → String",
    )
    for i, step in enumerate(steps):
        s.text(x + 24, by + 62 + i * 30, f"{i + 1}.", size=15, colour=DIM, anchor="start")
        s.text(x + 48, by + 62 + i * 30, step, size=15, anchor="start")
    wl = stage(
        s,
        col(3, "`write_deltalake`", ORANGE, by),
        (("consumes the batches", DIM), ("as one Arrow stream", DIM)),
    )
    dl = stage(
        s, col(4, "Delta Lake", DELTA, by), (("ONE commit", INK), ("for the whole run", DIM))
    )
    link(s, src, tb)
    s.arrow(tb.right + 6, tb.cy, each.x - 6, tb.cy)
    batch_cards(s, (tb.right + each.x) / 2 - 27, tb.cy - 26)
    link(s, each, wl, "Arrow batches")
    link(s, wl, dl)
    # The loop back: the next batch is only built once this one has gone.
    s.arc(each.cx, each.bottom + 4, tb.cx, tb.bottom + 4, lift=-34, colour=DIM)
    s.text(
        (each.cx + tb.cx) / 2,
        tb.bottom + 50,
        "next batch, once this one is written",
        size=13.5,
        colour=DIM,
    )

    # ---- peak RSS, step by step ----------------------------------------------
    cy0 = 790
    s.text(64, cy0, "Peak RSS, reporter-scale run", size=19, weight="bold", anchor="start")
    x0, px_per_gb, row = 340, 52, 42
    gmax = 12
    rows_top = cy0 + 22
    for i, (label, value) in enumerate(PEAK_RSS_GB.items()):
        ry = rows_top + i * row
        estimated = label in ESTIMATED
        s.text(x0 - 14, ry + 22, label, size=15, anchor="end")
        bar = Box(x0, ry + 4, value * px_per_gb, row - 12, BAR_FILLS[i], "")
        s.rect(bar, dashed=estimated, colour=DIM if estimated else INK)
        s.text(bar.right + 12, ry + 23, gb(label), size=15, weight="bold", anchor="start")
        if estimated:
            s.text(bar.right + 82, ry + 23, "estimated", size=13, colour=DIM, anchor="start")
    base = rows_top + len(PEAK_RSS_GB) * row
    s.axes(
        x0,
        rows_top,
        gmax * px_per_gb,
        base - rows_top,
        x_ticks=tuple((x0 + g * px_per_gb, f"{g} GB") for g in range(0, gmax + 1, 2)),
    )

    # ---- the commit is all or nothing -------------------------------------------
    note = Box(1060, 830, 460, 150, YELLOW, "")
    s.rect(note)
    s.lock(note.x + 40, note.y + 42, 13)
    s.text(note.x + 70, note.y + 48, "all or nothing", size=19, weight="bold", anchor="start")
    for i, line in enumerate(
        (
            "If the recipe raises mid-stream, nothing",
            "is committed: the table stays at its",
            "last version.",
        )
    ):
        s.text(note.x + 30, note.y + 86 + i * 24, line, size=15.5, anchor="start")
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/recipe-memory"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the peak-memory schema under --out."""
    write(build_peak(), out, "peak", png=png)


if __name__ == "__main__":
    app()
