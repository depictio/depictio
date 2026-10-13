#!/usr/bin/env python3
"""Render where a PR's CI time went, before and after, as a hand-drawn SVG (+ PNG).

* ``critical_path`` — one push to a PR as a timeline drawn to scale: the jobs
  each one waits for, before (run 37733462452 on main, step timings from the
  Actions API) and after this change, then the three ideas behind the cut: the
  representative catalog walk, cancelling superseded runs, and skipping the
  images on docs-only changes.

Usage:
    python dev/diagrams/ci_speed.py --out docs/images/ci-speed
    # writes <out>_critical_path.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    DIM,
    GREY,
    INK,
    PINK,
    RED,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)

# Stronger fills for bars and pictograms, still in Excalidraw's pastel family.
LINT = "#b2f2bb"
PYTEST = "#d3f9d8"
BUILD = "#ffd8a8"
WALK = "#d0bfff"
SUITE = "#a5d8ff"
SETUP = "#e9ecef"
PIXI = "#fff3bf"
SCREEN = "#f8f9fa"

W, H = 1640, 1060
X0 = 290  # where minute 0 sits
PX = 16  # pixels per minute


def tx(minutes: float) -> float:
    return X0 + minutes * PX


# --------------------------------------------------------------------------
# Timings, in minutes from the run's start.
# --------------------------------------------------------------------------

# Before: run 37733462452 (push to main, 75.7 min), from each job's and step's
# started_at / completed_at.
BEFORE_QUALITY = (0.3, 6.6)
BEFORE_BUILD = (
    ("", 6.6, 7.1, SETUP),
    ("api", 7.1, 8.4, BUILD),
    ("worker", 8.4, 12.0, BUILD),
    ("viewer", 12.0, 13.1, BUILD),
    ("pull", 13.1, 14.3, PINK),
)
BEFORE_E2E_SETUP = (14.9, 19.3)
BEFORE_WALK_END = 75.7
BEFORE_WALK_CHUNKS = 8
BEFORE_SUITE = (19.3, 24.3)
BEFORE_PIXI = (0.3, 11.3)

# After: what each job now waits for, with the durations those jobs already
# showed (lint is quality's install + ruff + ty; a build leg is one image; an
# e2e leg is the same setup plus the suite and a ~20-render walk on 2 workers).
AFTER_LINT = (0.3, 1.5)
AFTER_PYTEST = (1.5, 7.5)
AFTER_BUILD = (("api", 1.5, 3.3), ("worker", 1.5, 5.6), ("viewer", 1.5, 3.1))
AFTER_E2E_SETUP = (5.6, 10.0)
AFTER_E2E_TESTS = (10.0, 15.0)
AFTER_PIXI = (0.3, 1.8)


# --------------------------------------------------------------------------
# Pictograms, built from sketch.py's strokes and filled polygons.
# --------------------------------------------------------------------------


def _ellipse(cx: float, cy: float, rx: float, ry: float, t0: float, t1: float, n: int = 18):
    return [
        (cx + rx * math.cos(t0 + (t1 - t0) * i / n), cy + ry * math.sin(t0 + (t1 - t0) * i / n))
        for i in range(n + 1)
    ]


def circle(s: Sketch, cx: float, cy: float, r: float, fill: str, colour: str = INK) -> None:
    s.poly(_ellipse(cx, cy, r, r, 0, 2 * math.pi, 16)[:-1], fill=fill, colour=colour, amount=0.8)


def checklist(s: Sketch, cx: float, cy: float) -> None:
    """Lint: a sheet with ticked lines."""
    s.rect(Box(cx - 15, cy - 19, 30, 38, WHITE, ""))
    for i in range(3):
        y = cy - 9 + i * 10
        s.line(cx - 10, y, cx - 7, y + 3, width=1.6, passes=1, colour="#2f9e44", amount=0.4)
        s.line(cx - 7, y + 3, cx - 2, y - 4, width=1.6, passes=1, colour="#2f9e44", amount=0.4)
        s.line(cx + 1, y, cx + 10, y, width=1.2, passes=1, colour=DIM, amount=0.6)


def tube(s: Sketch, cx: float, cy: float) -> None:
    """Tests: a test tube, half full."""
    body = [(cx - 7, cy - 18), (cx + 7, cy - 18)]
    body += _ellipse(cx, cy + 10, 7, 8, 0, math.pi, 8)
    s.poly(body, fill=WHITE, amount=0.8)
    liquid = [(cx - 7, cy - 2), (cx + 7, cy - 2)]
    liquid += _ellipse(cx, cy + 10, 7, 8, 0, math.pi, 8)
    s.poly(liquid, fill=LINT, amount=0.6, edges=())
    s.line(cx - 10, cy - 18, cx + 10, cy - 18, width=2, passes=1)


def container(s: Sketch, cx: float, cy: float, w: float = 46, h: float = 30) -> None:
    """An image: a ribbed shipping container."""
    s.rect(Box(cx - w / 2, cy - h / 2, w, h, BUILD, ""))
    for i in range(1, 5):
        x = cx - w / 2 + i * w / 5
        s.line(x, cy - h / 2 + 5, x, cy + h / 2 - 5, width=1.0, colour=DIM, passes=1)


def browser(s: Sketch, cx: float, cy: float, w: float = 48, h: float = 36) -> None:
    """An e2e leg: a browser window with a chart in it."""
    x, y = cx - w / 2, cy - h / 2
    s.rect(Box(x, y, w, h, WHITE, ""))
    s.line(x, y + 9, x + w, y + 9, amount=0.6, passes=1)
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        circle(s, x + 6 + i * 6, y + 5, 1.8, colour, colour=colour)
    for i, frac in enumerate((0.4, 0.8, 0.55, 0.95)):
        bh = (h - 16) * frac
        s.rect(Box(x + 7 + i * 9, y + h - 4 - bh, 6, bh, SUITE, ""))


def cube(s: Sketch, cx: float, cy: float, size: float, fill: str) -> None:
    """A package: front, top and side faces of a taped box."""
    d = size * 0.35
    h = size / 2
    front = [(cx - h, cy - h + d), (cx + h - d, cy - h + d), (cx + h - d, cy + h), (cx - h, cy + h)]
    top = [(cx - h, cy - h + d), (cx - h + d, cy - h), (cx + h, cy - h), (cx + h - d, cy - h + d)]
    side = [(cx + h - d, cy - h + d), (cx + h, cy - h), (cx + h, cy + h - d), (cx + h - d, cy + h)]
    s.poly(front, fill=fill)
    s.poly(top, fill=WHITE)
    s.poly(side, fill=fill)
    tape = cx - h + size * 0.3
    s.line(tape, cy - h + d, tape + d, cy - h, width=2.4, passes=1, colour=RED)
    s.line(tape, cy - h + d, tape, cy - h + d + size * 0.3, width=2.4, passes=1, colour=RED)


def document(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """A text file: a page with a folded corner and a few lines."""
    fold = w * 0.28
    s.poly([(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)], fill=WHITE)
    s.poly([(x + w - fold, y), (x + w - fold, y + fold), (x + w, y + fold)], fill=SETUP)
    for i in range(4):
        ly = y + fold + 14 + i * 14
        s.line(x + 10, ly, x + w - 12 - (i % 2) * 14, ly, width=1.2, passes=1, colour=DIM)


def mini_chart(s: Sketch, x: float, y: float, kind: str) -> None:
    """One render *shape*, drawn small: what the walk keeps one of."""
    w, h = 54, 40
    s.rect(Box(x, y, w, h, SCREEN, ""), colour=GREY)
    if kind == "bar":
        for i, frac in enumerate((0.45, 0.85, 0.6, 0.3)):
            bh = (h - 12) * frac
            s.rect(Box(x + 7 + i * 11, y + h - 6 - bh, 8, bh, SUITE, ""))
    elif kind == "line":
        values = (0.2, 0.6, 0.4, 0.85, 0.7)
        pts = [(x + 7 + i * (w - 14) / 4, y + h - 7 - (h - 14) * v) for i, v in enumerate(values)]
        s.curve(pts, colour="#7048e8")
    elif kind == "card":
        s.text(x + w / 2, y + h / 2 + 8, "42", size=21, weight="bold")
    elif kind == "table":
        for i in range(1, 4):
            s.line(x + 5, y + i * h / 4, x + w - 5, y + i * h / 4, width=1.0, passes=1, colour=DIM)
        s.line(x + w / 2.6, y + 5, x + w / 2.6, y + h - 5, width=1.0, passes=1, colour=DIM)
    elif kind == "heatmap":
        cells = ("#ffc9c9", "#ff8787", "#fff3bf", "#ffa8a8", "#ffe3e3", "#fa5252")
        for i, fill in enumerate(cells):
            cw, ch = (w - 12) / 3, (h - 12) / 2
            s.rect(Box(x + 6 + (i % 3) * cw, y + 6 + (i // 3) * ch, cw, ch, fill, ""))
    elif kind == "slider":
        s.line(x + 8, y + h / 2, x + w - 8, y + h / 2, width=2.2, passes=1, colour=DIM)
        circle(s, x + w * 0.62, y + h / 2, 6, SUITE)


# --------------------------------------------------------------------------
# Timeline pieces.
# --------------------------------------------------------------------------


def bar(
    s: Sketch,
    start: float,
    end: float,
    y: float,
    fill: str,
    label: str = "",
    *,
    h: float = 34,
    size: float = 13,
    dashed: bool = False,
) -> None:
    s.rect(Box(tx(start), y, (end - start) * PX, h, fill, ""), dashed=dashed)
    if label:
        s.text(tx(start) + (end - start) * PX / 2, y + h / 2 + size * 0.38, label, size=size)


def row_label(s: Sketch, y: float, title: str, icon) -> None:
    icon(s, 66, y + 17)
    s.text(104, y + 23, title, size=17, weight="bold", anchor="start")


def axis(s: Sketch, y: float, until: int) -> None:
    for minute in range(0, until + 1, 10):
        x = tx(minute)
        s.line(x, y, x, y + 10, width=1.2, colour=DIM, passes=1)
        s.text(x, y + 30, f"{minute} min", size=12, colour=DIM)


# --------------------------------------------------------------------------
# The schema.
# --------------------------------------------------------------------------


def build_critical_path() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "One push to a PR: what it waits for",
        "the same jobs, before and after, drawn to scale",
    )

    # ---- before ---------------------------------------------------------
    top = 118
    s.text(46, top, "before", size=22, weight="bold", anchor="start")
    s.text(140, top, "run 37733462452, measured", size=14, colour=DIM, anchor="start")

    y = top + 26
    row_label(s, y, "quality", tube)
    bar(s, *BEFORE_QUALITY, y, LINT, "lint + pytest")

    y += 54
    row_label(s, y, "images", lambda s, cx, cy: container(s, cx, cy))
    for label, start, end, fill in BEFORE_BUILD:
        # Only the worker is wide enough to name inside its bar at this scale.
        bar(s, start, end, y, fill, label if label == "worker" else "", size=12)
    s.text(
        tx(14.3) + 12,
        y + 14,
        "api → worker → viewer, one after another,",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.text(
        tx(14.3) + 12,
        y + 31,
        "then pulled (pink) onto a runner thrown away",
        size=13,
        colour=DIM,
        anchor="start",
    )

    y += 54
    row_label(s, y, "e2e × 3", lambda s, cx, cy: browser(s, cx, cy))
    bar(s, *BEFORE_E2E_SETUP, y, SETUP, "boot", size=12)
    walk_start = BEFORE_E2E_SETUP[1]
    chunk = (BEFORE_WALK_END - walk_start) / BEFORE_WALK_CHUNKS
    for i in range(BEFORE_WALK_CHUNKS):
        bar(s, walk_start + i * chunk, walk_start + (i + 1) * chunk, y, WALK, "7 min", size=12)
    s.text(
        tx(BEFORE_WALK_END) - 6,
        y - 8,
        "catalog walk: ~550 renders a leg, in 8 chunks, one after the other",
        size=14,
        colour=INK,
        anchor="end",
    )
    bar(s, *BEFORE_SUITE, y + 40, SUITE, h=16)
    s.text(
        tx(BEFORE_SUITE[1]) + 10,
        y + 53,
        "the other 78 tests, on the second worker",
        size=13,
        colour=DIM,
        anchor="start",
    )

    y += 78
    row_label(s, y, "pixi", lambda s, cx, cy: cube(s, cx, cy, 34, PIXI))
    bar(s, *BEFORE_PIXI, y, PIXI, "the whole pytest, serially")
    s.cross(tx(BEFORE_PIXI[1]) + 22, y + 17, size=9)
    s.text(
        tx(BEFORE_PIXI[1]) + 40,
        y + 23,
        "failures ignored (`|| echo`)",
        size=14,
        colour=RED,
        anchor="start",
    )

    end_x = tx(BEFORE_WALK_END)
    s.line(end_x, top + 16, end_x, y + 46, dashed=True, colour=DIM, width=1.3)
    s.text(end_x + 12, top + 66, "76 min", size=26, weight="bold", anchor="start")
    s.text(end_x + 12, top + 90, "up to 156 when", size=13, colour=DIM, anchor="start")
    s.text(end_x + 12, top + 108, "runs queue up", size=13, colour=DIM, anchor="start")
    axis(s, y + 50, 80)

    # ---- after ----------------------------------------------------------
    top = y + 128
    s.text(46, top, "after", size=22, weight="bold", anchor="start")
    s.text(124, top, "expected, from the same jobs' timings", size=14, colour=DIM, anchor="start")
    # Notes sit in one column right of the new end, so the end line crosses none.
    note_x = tx(AFTER_E2E_TESTS[1]) + 24

    y = top + 26
    row_label(s, y, "lint", checklist)
    bar(s, *AFTER_LINT, y, LINT)
    s.text(
        note_x,
        y + 23,
        "lint: ruff + ty, the only gate the images wait for",
        size=13,
        colour=DIM,
        anchor="start",
    )

    y += 50
    row_label(s, y, "pytest", tube)
    bar(s, *AFTER_PYTEST, y, PYTEST, "pytest")
    s.text(
        note_x,
        y + 23,
        "pytest: alongside, nothing waits for it",
        size=13,
        colour=DIM,
        anchor="start",
    )

    y += 50
    row_label(s, y, "images", lambda s, cx, cy: container(s, cx, cy))
    for i, (label, start, end) in enumerate(AFTER_BUILD):
        bar(s, start, end, y + i * 13, BUILD, h=10)
    s.text(
        note_x,
        y + 23,
        "images: api, worker and viewer side by side, nothing pulled",
        size=13,
        colour=DIM,
        anchor="start",
    )

    y += 50
    row_label(s, y, "e2e × 3", lambda s, cx, cy: browser(s, cx, cy))
    bar(s, *AFTER_E2E_SETUP, y, SETUP, "boot", size=12)
    bar(s, *AFTER_E2E_TESTS, y, WALK, "suite + walk", size=12)
    s.text(
        note_x,
        y + 23,
        "e2e: the suite and one render per shape, ~20 a leg",
        size=13,
        colour=DIM,
        anchor="start",
    )

    y += 50
    row_label(s, y, "pixi", lambda s, cx, cy: cube(s, cx, cy, 34, PIXI))
    bar(s, *AFTER_PIXI, y, PIXI, dashed=True)
    s.text(
        note_x,
        y + 23,
        "pixi: only when the dependencies change",
        size=13,
        colour=DIM,
        anchor="start",
    )

    end_x = tx(AFTER_E2E_TESTS[1])
    s.line(end_x, top + 16, end_x, y + 46, dashed=True, colour=DIM, width=1.3)
    s.text(end_x + 14, top + 4, "≈ 15 min", size=26, weight="bold", anchor="start")
    s.line(
        tx(BEFORE_WALK_END),
        top + 16,
        tx(BEFORE_WALK_END),
        y + 46,
        dashed=True,
        colour=GREY,
        width=1.3,
    )
    s.text(tx(BEFORE_WALK_END) - 8, top + 34, "was 76", size=14, colour=GREY, anchor="end")
    axis(s, y + 50, 80)

    # ---- how ------------------------------------------------------------
    top = y + 128
    s.line(46, top - 22, W - 46, top - 22, colour=GREY, width=1.2, passes=1)

    # 1. The walk: 1557 renders, 61 shapes.
    s.text(46, top + 8, "a PR walks one render per shape", size=19, weight="bold", anchor="start")
    palette = (SUITE, WALK, LINT, BUILD, SUITE, PYTEST, WALK)
    for i in range(14 * 7):
        col, row = i % 14, i // 14
        fill = palette[(i * 5 + row) % len(palette)]
        s.rect(Box(46 + col * 17, top + 34 + row * 14, 13, 10, fill, ""), colour=DIM)
    s.text(46 + 7 * 17, top + 152, "1557 renders", size=16, weight="bold")
    funnel = [
        (300, top + 40),
        (380, top + 40),
        (352, top + 96),
        (352, top + 128),
        (328, top + 128),
        (328, top + 96),
    ]
    s.poly(funnel, fill=YELLOW)
    s.arrow(390, top + 84, 418, top + 84)
    for i, kind in enumerate(("bar", "line", "card", "table", "heatmap", "slider")):
        mini_chart(s, 428 + (i % 3) * 62, top + 34 + (i // 3) * 50, kind)
    s.text(428 + 90, top + 152, "61 shapes", size=16, weight="bold")
    s.text(
        46,
        top + 184,
        "+ every render of the catalog tools the PR changed",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        46,
        top + 204,
        "whole catalog: main, nightly, `ci:full-catalog`",
        size=14,
        colour=DIM,
        anchor="start",
    )

    # 2. A new push cancels the run in flight.
    bx = 690
    s.text(
        bx, top + 8, "a new push cancels the run in flight", size=19, weight="bold", anchor="start"
    )
    s.line(bx, top + 56, bx + 400, top + 56, width=2.2)
    for cx, label in ((bx + 50, "push 1"), (bx + 210, "push 2")):
        circle(s, cx, top + 56, 11, WHITE)
        s.text(cx, top + 36, label, size=14, colour=DIM)
    s.line(bx + 50, top + 67, bx + 50, top + 86, width=1.3, colour=DIM, passes=1)
    s.rect(Box(bx + 50, top + 86, 200, 26, WALK, ""), dashed=True)
    s.cross(bx + 236, top + 99, size=9)
    s.text(bx + 262, top + 104, "cancelled", size=14, colour=RED, anchor="start")
    s.line(bx + 210, top + 67, bx + 210, top + 124, width=1.3, colour=DIM, passes=1)
    s.rect(Box(bx + 210, top + 124, 190, 26, LINT, ""))
    s.text(bx + 305, top + 142, "the run that counts", size=13)
    s.text(
        bx,
        top + 184,
        "a PR used to stack 14 jobs per push, three of them",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        bx,
        top + 204,
        "an hour long; main too, the newest push wins",
        size=14,
        colour=DIM,
        anchor="start",
    )

    # 3. Docs-only: no image, no stack job.
    dx = 1200
    s.text(dx, top + 8, "docs only: nothing to build", size=19, weight="bold", anchor="start")
    document(s, dx + 10, top + 34, 70, 92)
    s.text(dx + 45, top + 152, "`*.md`, `docs/`", size=14, colour=DIM)
    s.arrow(dx + 96, top + 80, dx + 170, top + 80)
    s.cross(dx + 133, top + 80, size=10)
    container(s, dx + 230, top + 62, 76, 42)
    browser(s, dx + 230, top + 116, 66, 44)
    s.text(
        dx,
        top + 184,
        "no image, no stack job; `ci-ok` is the one",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        dx,
        top + 204,
        "check to require, skipped jobs count as passing",
        size=14,
        colour=DIM,
        anchor="start",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/ci-speed"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the critical-path schema under --out."""
    write(build_critical_path(), out, "critical_path", png=png)


if __name__ == "__main__":
    app()
