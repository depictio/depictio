#!/usr/bin/env python3
"""Render the dataset-time-travel schemas as hand-drawn SVGs (+ PNGs).

Sibling of ``dashboard_versioning_schema.py``, which draws how a save becomes a
version and why a restore cannot lose the present. This one draws the *other*
axis, the one that arrives with this work: a dashboard version records what the
data was, and those records are now read back.

Two diagrams, because two questions kept being asked in review:

* *reads* — a rendered component is the product of **two** independent choices,
  which definition and which data. Four combinations, three of them useful, and
  the picture is what makes "current layout, last month's data" obviously
  distinct from "that version, as it was".
* *seam* — where a version's stamps turn into a Delta read, and the two places
  the chain used to break: an unpinned render, and a definition taken from the
  live document.

Generated rather than drawn, so a change in the flow shows up as a diff. Look
and primitives are lifted from ``watch_trigger_schema.py``: every stroke drawn
twice along a jittered bezier, Virgil where installed, and a fixed seed so
re-running produces a byte-identical file.

Usage:
    python dev/diagrams/dashboard_time_travel_schema.py --out docs/images/v0.12/react/schema
    # writes <out>_time_travel_axes.{svg,png} and <out>_time_travel_read.{svg,png}
"""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import typer

app = typer.Typer(add_completion=False)

# Excalidraw's default palette: near-black ink, pastel fills.
INK = "#1e1e1e"
DIM = "#5c5c5c"
RED = "#c92a2a"
BLUE = "#e7f5ff"
YELLOW = "#fff9db"
GREEN = "#ebfbee"
VIOLET = "#f3f0ff"
ORANGE = "#ffe8cc"
PINK = "#ffe3e3"
GREY = "#f1f3f5"

FONT = "Virgil GS, Virgil, Excalifont, Comic Sans MS, Bradley Hand, cursive"


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float
    fill: str
    title: str
    lines: tuple[str, ...] = ()

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


class Sketch:
    """Accumulates SVG fragments drawn with a hand-drawn wobble."""

    def __init__(self, width: int, height: int, seed: int = 11) -> None:
        self.w = width
        self.h = height
        self._rng = random.Random(seed)
        self._parts: list[str] = []

    # -- primitives ---------------------------------------------------------

    def _jitter(self, amount: float) -> float:
        return self._rng.uniform(-amount, amount)

    def _wobble(self, x1: float, y1: float, x2: float, y2: float, amount: float) -> str:
        """One stroke as a cubic bezier whose control points wander off the line.

        Bending the curve rather than displacing the endpoints is what keeps a
        rectangle's corners meeting while its edges still bow.
        """
        cx1 = x1 + (x2 - x1) / 3 + self._jitter(amount)
        cy1 = y1 + (y2 - y1) / 3 + self._jitter(amount)
        cx2 = x1 + 2 * (x2 - x1) / 3 + self._jitter(amount)
        cy2 = y1 + 2 * (y2 - y1) / 3 + self._jitter(amount)
        sx, sy = x1 + self._jitter(amount / 2), y1 + self._jitter(amount / 2)
        ex, ey = x2 + self._jitter(amount / 2), y2 + self._jitter(amount / 2)
        return f"M{sx:.1f},{sy:.1f} C{cx1:.1f},{cy1:.1f} {cx2:.1f},{cy2:.1f} {ex:.1f},{ey:.1f}"

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        width: float = 1.7,
        colour: str = INK,
        amount: float = 2.0,
        dashed: bool = False,
        passes: int = 2,
    ) -> None:
        dash = ' stroke-dasharray="9 7"' if dashed else ""
        for _ in range(passes):
            d = self._wobble(x1, y1, x2, y2, amount)
            self._parts.append(
                f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
                f'stroke-linecap="round"{dash}/>'
            )

    def rect(self, box: Box) -> None:
        # Fill first, as a plain rounded rect: a wobbling fill edge reads as a
        # smudge, while a wobbling outline on top of it reads as a pen stroke.
        self._parts.append(
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
            f'rx="6" fill="{box.fill}"/>'
        )
        corners = [
            (box.x, box.y, box.right, box.y),
            (box.right, box.y, box.right, box.bottom),
            (box.right, box.bottom, box.x, box.bottom),
            (box.x, box.bottom, box.x, box.y),
        ]
        for x1, y1, x2, y2 in corners:
            self.line(x1, y1, x2, y2, amount=1.6)

    def arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        dashed: bool = False,
        colour: str = INK,
    ) -> None:
        self.line(x1, y1, x2, y2, dashed=dashed, colour=colour)
        angle = math.atan2(y2 - y1, x2 - x1)
        for sign in (1, -1):
            head = angle + sign * math.radians(28)
            self.line(
                x2,
                y2,
                x2 - 14 * math.cos(head),
                y2 - 14 * math.sin(head),
                amount=1.0,
                colour=colour,
                passes=1,
            )

    def curve(self, points: list[tuple[float, float]], *, colour: str = DIM) -> None:
        """A multi-segment stroke, for the loops that no straight line can express."""
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            self.line(x1, y1, x2, y2, colour=colour, amount=1.4, width=1.5)

    def cross(self, x: float, y: float, size: float = 11, colour: str = RED) -> None:
        """The universal 'not this way' mark."""
        self.line(x - size, y - size, x + size, y + size, colour=colour, amount=1.0, passes=1)
        self.line(x - size, y + size, x + size, y - size, colour=colour, amount=1.0, passes=1)

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: float = 16,
        colour: str = INK,
        anchor: str = "middle",
        weight: str = "normal",
    ) -> None:
        self._parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'fill="{colour}" text-anchor="{anchor}" font-weight="{weight}">'
            f"{escape(content)}</text>"
        )

    def box(self, box: Box) -> None:
        self.rect(box)
        self.text(box.cx, box.y + 27, box.title, size=18, weight="bold")
        for i, line in enumerate(box.lines):
            self.text(box.cx, box.y + 51 + i * 21, line, size=14, colour=DIM)

    def title(self, heading: str, subtitle: str) -> None:
        self.text(46, 52, heading, size=25, anchor="start")
        self.text(46, 78, subtitle, size=15, colour=DIM, anchor="start")

    # -- drawn figures ------------------------------------------------------
    #
    # The point of these is that the diagram shows the *thing*, not a caption
    # naming it. "a box plot on 50 rows" beside "a box plot on 150 rows" is two
    # identical labels; two drawn box plots differ at a glance, which is the
    # entire claim the feature makes.

    def frame(self, x: float, y: float, w: float, h: float, *, fill: str = "#ffffff") -> None:
        """A plain sketched panel with no title — a place to draw inside."""
        self.rect(Box(x, y, w, h, fill, ""))

    def axes(self, x: float, y: float, w: float, h: float) -> None:
        """L-shaped plot axes: left spine and baseline, nothing else."""
        self.line(x, y, x, y + h, amount=1.2, width=1.4)
        self.line(x, y + h, x + w, y + h, amount=1.2, width=1.4)

    def boxplot(
        self,
        x: float,
        baseline: float,
        *,
        width: float,
        scale,
        stats: tuple[float, float, float, float, float],
        colour: str,
    ) -> None:
        """One box-and-whisker at `x`, in data units mapped through `scale`.

        `stats` is (min, q1, median, q3, max). Drawn from real numbers taken
        from the demo's own batches, so the shape a reader compares against the
        screenshots is the shape the screenshots show.
        """
        lo, q1, med, q3, hi = (scale(v) for v in stats)
        half = width / 2
        # A real IQR can be a fraction of the shared scale — Setosa's is 0.2 cm
        # against a 6.6 cm span, which lands on three pixels, and three pixels
        # holding four outline strokes and a median renders as a black smear.
        # Floor the drawn height so the fill and the median stay distinguishable;
        # the whiskers and the median position are untouched, so the comparison
        # the reader makes is still the real one.
        MIN_BOX = 9.0
        if q1 - q3 < MIN_BOX:
            centre = (q1 + q3) / 2
            q3, q1 = centre - MIN_BOX / 2, centre + MIN_BOX / 2
        # Whiskers, with the caps that make them read as whiskers.
        self.line(x, hi, x, q3, amount=1.0, width=1.3, passes=1)
        self.line(x, q1, x, lo, amount=1.0, width=1.3, passes=1)
        self.line(x - half / 2, hi, x + half / 2, hi, amount=0.8, width=1.3, passes=1)
        self.line(x - half / 2, lo, x + half / 2, lo, amount=0.8, width=1.3, passes=1)
        # The IQR box, filled so the three series separate by colour.
        self._parts.append(
            f'<rect x="{x - half:.1f}" y="{q3:.1f}" width="{width:.1f}" '
            f'height="{q1 - q3:.1f}" rx="2" fill="{colour}" opacity="0.55"/>'
        )
        for x1, y1, x2, y2 in (
            (x - half, q3, x + half, q3),
            (x + half, q3, x + half, q1),
            (x + half, q1, x - half, q1),
            (x - half, q1, x - half, q3),
        ):
            self.line(x1, y1, x2, y2, amount=0.9, width=1.3, passes=1)
        # Median: the one heavier stroke, since it is what the eye compares.
        # Clamped inside the drawn box, which matters only for the floored case
        # above — otherwise it would sit on or outside an edge.
        med = min(max(med, q3 + 1.5), q1 - 1.5)
        self.line(x - half, med, x + half, med, amount=0.7, width=2.2, passes=1)

    def histogram(
        self,
        x: float,
        baseline: float,
        *,
        heights: tuple[float, ...],
        bar_w: float,
        colour: str,
    ) -> None:
        """Adjacent bars rising from `baseline` — a histogram, drawn."""
        for i, height in enumerate(heights):
            bx = x + i * bar_w
            self._parts.append(
                f'<rect x="{bx:.1f}" y="{baseline - height:.1f}" width="{bar_w:.1f}" '
                f'height="{height:.1f}" fill="{colour}" opacity="0.55"/>'
            )
            for x1, y1, x2, y2 in (
                (bx, baseline - height, bx + bar_w, baseline - height),
                (bx + bar_w, baseline - height, bx + bar_w, baseline),
                (bx, baseline - height, bx, baseline),
            ):
                self.line(x1, y1, x2, y2, amount=0.7, width=1.2, passes=1)

    def thumbnail(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        tiles: tuple[tuple[float, float, float, float], ...],
        fill: str,
    ) -> None:
        """A dashboard as its grid: an outer frame with tiles laid inside.

        `tiles` are fractions of the frame, so one layout can be redrawn at any
        size and two layouts can be compared by shape alone.
        """
        self.frame(x, y, w, h)
        for fx, fy, fw, fh in tiles:
            tx, ty = x + fx * w, y + fy * h
            tw, th = fw * w, fh * h
            self._parts.append(
                f'<rect x="{tx:.1f}" y="{ty:.1f}" width="{tw:.1f}" height="{th:.1f}" '
                f'rx="3" fill="{fill}" opacity="0.75"/>'
            )
            self.line(tx, ty, tx + tw, ty, amount=0.8, width=1.2, passes=1)
            self.line(tx + tw, ty, tx + tw, ty + th, amount=0.8, width=1.2, passes=1)
            self.line(tx + tw, ty + th, tx, ty + th, amount=0.8, width=1.2, passes=1)
            self.line(tx, ty + th, tx, ty, amount=0.8, width=1.2, passes=1)

    def commit_strip(
        self,
        x: float,
        y: float,
        *,
        labels: tuple[str, ...],
        spacing: float,
        selected: int | None = None,
    ) -> None:
        """A Delta log as a line of commits, one optionally ringed as chosen."""
        end = x + (len(labels) - 1) * spacing
        self.line(x - 16, y, end + 16, y, colour=DIM, amount=1.2, width=1.4)
        for i, label in enumerate(labels):
            cx = x + i * spacing
            chosen = i == selected
            self._parts.append(
                f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="{7 if chosen else 5}" '
                f'fill="{"#ffd43b" if chosen else "#ffffff"}" stroke="{INK}" stroke-width="1.4"/>'
            )
            if chosen:
                self._parts.append(
                    f'<circle cx="{cx:.1f}" cy="{y:.1f}" r="13" fill="none" '
                    f'stroke="{INK}" stroke-width="1.3" stroke-dasharray="3 3"/>'
                )
            self.text(cx, y + 30, label, size=13, colour=DIM)

    def svg(self) -> str:
        body = "\n  ".join(self._parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}">\n'
            f'  <rect width="{self.w}" height="{self.h}" fill="#ffffff"/>\n  {body}\n</svg>\n'
        )


# ── diagram 1: two axes, four combinations, each one drawn ──────────────────

AXES_W, AXES_H = 1340, 760

#: Petal-length five-number summaries taken from the demo's own batches, so the
#: shapes here are the shapes the screenshots show.  (min, q1, median, q3, max)
SETOSA_V0 = (1.0, 1.4, 1.5, 1.6, 1.9)
SETOSA_V3 = (1.6, 1.96, 2.1, 2.17, 2.53)
VERSICOLOR_V3 = (3.0, 4.0, 4.3, 4.7, 5.1)
VIRGINICA_V3 = (4.5, 5.1, 5.6, 5.9, 6.9)

#: The same petal lengths binned into seven bars, which is what v1's *pooled*
#: histogram drew. Real counts, from the same two CSVs, scaled to pixels by the
#: cell — an invented shape here would be the one part of the diagram that does
#: not correspond to anything.
#:   v0: 50 Setosa over 1.0–2.05 cm       v3: 150 flowers over 1.5–7.1 cm
HIST_V0 = (2, 2, 20, 13, 11, 0, 2)
HIST_V3 = (46, 5, 7, 30, 34, 22, 6)

BLUE_INK = "#4dabf7"
RED_INK = "#ff8787"
GREEN_INK = "#69db7c"


def build_axes() -> str:
    s = Sketch(AXES_W, AXES_H, seed=31)

    s.title(
        "A rendered chart answers two questions, not one",
        "which definition drew it, and which data it drew — and the two axes move separately",
    )

    # A 2×2 of *drawn charts*, not four captions. Four cells labelled "a box
    # plot" are four identical cells; four drawn plots differ at a glance, which
    # is the whole claim. Every cell is the same component id — the demo's
    # petal-length chart — under a different pair of choices.
    left, top = 300, 172
    cell_w, cell_h = 452, 212
    gap = 34

    # One value→y mapping shared by every cell. Per-cell autoscaling would
    # flatten 1.9 cm and 6.9 cm into two identically-sized boxes, destroying the
    # only thing the reader is here to compare.
    TOP_PAD, BOT_PAD = 58, 40
    DATA_MIN, DATA_MAX = 0.6, 7.2

    def draw_cell(
        col: int,
        row: int,
        fill: str,
        heading: str,
        note: str,
        *,
        kind: str,
        series: tuple[tuple[str, tuple[float, float, float, float, float], str], ...] = (),
        bars: tuple[float, ...] = (),
        bar_colour: str = BLUE_INK,
    ) -> Box:
        x = left + col * (cell_w + gap)
        y = top + row * (cell_h + gap)
        cell = Box(x, y, cell_w, cell_h, fill, "")
        s.rect(cell)
        s.text(x + 16, y + 26, heading, size=17, anchor="start", weight="bold")
        s.text(x + 16, y + 46, note, size=13, colour=DIM, anchor="start")

        plot_top, plot_bottom = y + TOP_PAD, y + cell_h - BOT_PAD
        s.axes(x + 58, plot_top, cell_w - 92, plot_bottom - plot_top)

        if kind == "box":
            span = plot_bottom - plot_top

            def scale(value: float) -> float:
                frac = (value - DATA_MIN) / (DATA_MAX - DATA_MIN)
                return plot_bottom - frac * span

            # Fixed category slots, so a cell holding two varieties reads as a
            # cell *missing* the third rather than a differently-spaced chart.
            for (label, stats, colour), slot in zip(series, (x + 128, x + 240, x + 352)):
                s.boxplot(slot, plot_bottom, width=46, scale=scale, stats=stats, colour=colour)
                s.text(slot, plot_bottom + 19, label, size=12, colour=DIM)
        else:
            # Counts scaled so the tallest bar fills the plot. Per-cell rather
            # than shared, because a histogram's y is a count and the two cells
            # count different totals — 50 flowers against 150.
            tallest = max(bars) or 1
            usable = plot_bottom - plot_top - 8
            s.histogram(
                x + 92,
                plot_bottom,
                heights=tuple(count / tallest * usable for count in bars),
                bar_w=40,
                colour=bar_colour,
            )
            s.text(x + 232, plot_bottom + 19, "petal.length", size=12, colour=DIM)
        return cell

    box_series = (
        ("Setosa", SETOSA_V3, BLUE_INK),
        ("Versicolor", VERSICOLOR_V3, RED_INK),
        ("Virginica", VIRGINICA_V3, GREEN_INK),
    )

    live_live = draw_cell(
        0,
        0,
        GREY,
        "The live dashboard",
        "nothing pinned — the ordinary read",
        kind="box",
        series=box_series,
    )
    live_past = draw_cell(
        1,
        0,
        BLUE,
        "Current layout, older data",
        "the dataset picker, one collection at a time",
        kind="box",
        series=(("Setosa", SETOSA_V0, BLUE_INK),),
    )
    past_live = draw_cell(
        0,
        1,
        ORANGE,
        "Older layout, current data",
        "compare mode's right-hand pane",
        kind="hist",
        bars=HIST_V3,
        bar_colour=RED_INK,
    )
    # Not bound: unlike the other three, nothing is positioned relative to this
    # cell — it is the bottom-right corner of the grid.
    draw_cell(
        1,
        1,
        GREEN,
        "That version, as it was",
        "“Use this data”, and what ?version= opens",
        kind="hist",
        bars=HIST_V0,
        bar_colour=BLUE_INK,
    )

    # Axis heads outside the grid, so each cell reads as a coordinate rather
    # than as a standalone panel.
    # Both axis names on one baseline, with the column values on the next, so
    # the two heads read as a pair rather than as a stray floating label.
    s.text((live_live.cx + live_past.cx) / 2, top - 44, "data  →", size=18, weight="bold")
    s.text(live_live.cx, top - 20, "current — v3, 150 rows", size=14, colour=DIM)
    s.text(live_past.cx, top - 20, "a past commit — v0, 50 rows", size=14, colour=DIM)

    s.text(58, top - 44, "definition  ↓", size=18, anchor="start", weight="bold")
    s.text(58, live_live.cy - 14, "current", size=14, colour=DIM, anchor="start")
    s.text(58, live_live.cy + 8, "box plot,", size=13, colour=DIM, anchor="start")
    s.text(58, live_live.cy + 28, "by variety", size=13, colour=DIM, anchor="start")
    s.text(58, past_live.cy - 14, "v1 Survey", size=14, colour=DIM, anchor="start")
    s.text(58, past_live.cy + 8, "histogram,", size=13, colour=DIM, anchor="start")
    s.text(58, past_live.cy + 28, "pooled", size=13, colour=DIM, anchor="start")

    s.text(
        58,
        AXES_H - 64,
        "read across a row and only the data moved; read down a column and only the chart did.",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        58,
        AXES_H - 38,
        "the off-diagonal cells are the reason both axes exist, and why either one alone is a wrong answer.",
        size=15,
        colour=DIM,
        anchor="start",
    )

    return s.svg()


# ── diagram 2: the seam between a version's stamps and the rows drawn ───────

READ_W, READ_H = 1500, 720

#: The demo's four Delta commits, which is what a pin actually chooses between.
COMMITS = ("v0 · 50", "v1 · 100", "v2 · 100", "v3 · 150")

#: v1's five-component layout and the current nine, as grid fractions. Drawn
#: rather than described: "5 components" and "9 components" are two labels,
#: while two grids are visibly two different dashboards.
LAYOUT_V1 = (
    (0.06, 0.14, 0.40, 0.24),
    (0.52, 0.14, 0.42, 0.24),
    (0.06, 0.46, 0.88, 0.40),
)
LAYOUT_NOW = (
    (0.06, 0.12, 0.27, 0.20),
    (0.36, 0.12, 0.27, 0.20),
    (0.66, 0.12, 0.28, 0.20),
    (0.06, 0.38, 0.42, 0.26),
    (0.51, 0.38, 0.43, 0.26),
    (0.06, 0.70, 0.88, 0.18),
)


def build_read() -> str:
    s = Sketch(READ_W, READ_H, seed=47)

    s.title(
        "One request carries two payloads, and each was missing once",
        "a version pins the data AND the definition — either one alone renders a state that never existed",
    )

    # Left: the thing chosen. A timeline row, drawn as a row.
    s.text(58, 152, "a row in the timeline", size=15, anchor="start", weight="bold")
    row = Box(58, 168, 300, 96, VIOLET, "")
    s.rect(row)
    s.text(76, 196, "v1 Survey", size=17, anchor="start", weight="bold")
    s.text(76, 220, "Jul 29 · 5 components", size=13, colour=DIM, anchor="start")
    s.text(76, 242, "1 data collection pinned", size=13, colour=DIM, anchor="start")
    # The pin icon, drawn, because it is the mark the row actually carries.
    s._parts.append(
        f'<circle cx="{330}" cy="{196}" r="9" fill="#ffd43b" stroke="{INK}" stroke-width="1.4"/>'
    )

    # What the row holds: a stamp per collection, and a layout.
    s.text(58, 316, "what it recorded", size=15, anchor="start", weight="bold")
    s.commit_strip(96, 372, labels=COMMITS, spacing=74, selected=0)
    s.text(58, 348, "the data:", size=13, colour=DIM, anchor="start")
    s.text(58, 430, "the layout:", size=13, colour=DIM, anchor="start")
    s.thumbnail(96, 446, 232, 150, tiles=LAYOUT_V1, fill=VIOLET)

    # Middle: the two payloads, drawn as two separate arrows into one request.
    s.text(470, 152, "one render request", size=15, anchor="start", weight="bold")
    body = Box(470, 168, 320, 200, YELLOW, "")
    s.rect(body)
    s.text(490, 200, "POST /render_figure", size=16, anchor="start", weight="bold")
    s.text(490, 232, "as_of_version: v1", size=14, anchor="start")
    s.text(490, 256, "→ every stamp becomes a pin", size=13, colour=DIM, anchor="start")
    s.text(490, 292, "component_overrides: {…}", size=14, anchor="start")
    s.text(490, 316, "→ the definition it was saved with", size=13, colour=DIM, anchor="start")
    s.text(490, 348, "wf_id · dc_id · dc_config refused", size=13, colour=RED, anchor="start")

    s.arrow(row.right + 12, 214, body.x - 14, 232)
    s.arrow(340, 372, body.x - 14, 292)
    s.arrow(340, 500, body.x - 14, 316)

    # Right: what comes back. Drawn, again — the whole argument is that these
    # two are different pictures, not two differently-labelled ones.
    s.text(890, 152, "what is drawn", size=15, anchor="start", weight="bold")
    right = Box(890, 168, 540, 200, GREEN, "")
    s.rect(right)
    s.text(910, 198, "both payloads honoured", size=16, anchor="start", weight="bold")
    s.thumbnail(910, 214, 200, 138, tiles=LAYOUT_V1, fill=GREEN_INK)
    s.text(1130, 246, "v1's five components,", size=14, colour=DIM, anchor="start")
    s.text(1130, 268, "drawn from v0's 50 rows —", size=14, colour=DIM, anchor="start")
    s.text(1130, 290, "a state that really existed", size=14, colour=DIM, anchor="start")

    # The two failures, each drawn as the *wrong* picture it produced. Both
    # returned 200 and both looked plausible, which is why they get pictures
    # rather than a bullet list.
    s.text(890, 424, "and the two ways it broke", size=15, anchor="start", weight="bold")

    miss_pins = Box(890, 442, 540, 118, PINK, "")
    s.rect(miss_pins)
    s.text(910, 470, "no pins", size=16, anchor="start", weight="bold")
    s.thumbnail(910, 480, 128, 66, tiles=LAYOUT_V1, fill=VIOLET)
    # The strip and its verdict both inside the frame: at the previous x the
    # verdict ran off the canvas, and half a sentence is worse than none.
    s.commit_strip(1078, 496, labels=("v0", "v1", "v2", "v3"), spacing=40, selected=3)
    s.text(1252, 494, "v1's layout,", size=13, colour=DIM, anchor="start")
    s.text(1252, 516, "today's numbers", size=13, colour=DIM, anchor="start")

    miss_defs = Box(890, 578, 540, 118, PINK, "")
    s.rect(miss_defs)
    s.text(910, 606, "no definitions", size=16, anchor="start", weight="bold")
    s.thumbnail(910, 616, 128, 66, tiles=LAYOUT_NOW, fill=RED_INK)
    s.commit_strip(1078, 632, labels=("v0", "v1", "v2", "v3"), spacing=40, selected=0)
    s.text(1252, 630, "“Mean … (Average)”", size=13, colour=DIM, anchor="start")
    s.text(1252, 652, "showing the live max", size=13, colour=DIM, anchor="start")

    s.cross(870, miss_pins.cy)
    s.cross(870, miss_defs.cy)

    s.text(
        58,
        READ_H - 92,
        "Neither failure is visible in review: each half is",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        58,
        READ_H - 68,
        "correct on its own, and the seam between them holds",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        58,
        READ_H - 44,
        "no code to read. Both are pinned by checks that run",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        58,
        READ_H - 20,
        "the real functions and inspect the served bundle.",
        size=14,
        colour=DIM,
        anchor="start",
    )

    return s.svg()


SCENES: dict[str, tuple[int, int]] = {
    "time_travel_axes": (AXES_W, AXES_H),
    "time_travel_read": (READ_W, READ_H),
}

BUILDERS = {"time_travel_axes": build_axes, "time_travel_read": build_read}


#: Virgil ships in the repo for the viewer, so the diagram can use the real
#: Excalidraw hand for its PNG instead of falling back to whatever cursive the
#: rendering host happens to have (which, on a clean container, is a serif —
#: and a serif undoes the whole hand-drawn look).
VIRGIL_TTF = Path("depictio/viewer/src/assets/fonts/Virgil.ttf")


def _font_face_css() -> str:
    """A base64 ``@font-face`` for Virgil, or '' when the file is missing.

    Injected into the rasterising page rather than into the SVG itself: the
    committed SVG stays a few KB and keeps referencing the font by name, while
    the PNG — the artifact people actually look at — always gets the real hand.
    """
    import base64

    if not VIRGIL_TTF.is_file():
        return ""
    encoded = base64.b64encode(VIRGIL_TTF.read_bytes()).decode("ascii")
    return (
        "@font-face{font-family:'Virgil';font-style:normal;font-weight:400;"
        f"src:url(data:font/ttf;base64,{encoded}) format('truetype');}}"
    )


def _chromium_executable() -> str | None:
    """An explicit Chromium path when the bundled build is not the one on disk.

    CI images and dev containers often ship a pinned Chromium under
    ``PLAYWRIGHT_BROWSERS_PATH`` whose build number differs from the one the
    installed ``playwright`` package expects, which makes ``launch()`` ask for
    ``playwright install`` even though a perfectly good browser is present.
    Returning a path here uses it instead of downloading a second copy.
    """
    import os

    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not root.is_dir():
        return None
    for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome")):
        if candidate.is_file():
            return str(candidate)
    return None


async def _render_png(svg_path: Path, png_path: Path, width: int, height: int) -> None:
    from playwright.async_api import async_playwright

    # Wrap the SVG in a page carrying the embedded font, rather than opening
    # the SVG directly: a file:// SVG cannot pull in a sibling font, and
    # without the font the whole hand-drawn look collapses into a serif.
    page_html = (
        "<!doctype html><meta charset='utf-8'>"
        f"<style>{_font_face_css()}"
        "html,body{margin:0;padding:0;background:#fff}</style>"
        f"{svg_path.read_text(encoding='utf-8')}"
    )
    html_path = svg_path.with_suffix(".render.html")
    html_path.write_text(page_html, encoding="utf-8")

    executable = _chromium_executable()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=executable)
            page = await browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=2
            )
            await page.goto(html_path.resolve().as_uri())
            await page.evaluate("document.fonts.ready")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(png_path))
            await browser.close()
    finally:
        html_path.unlink(missing_ok=True)


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"),
        "--out",
        help="Output prefix; '_time_travel_axes' / '_time_travel_read' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write both time-travel schema SVGs (and PNGs) under --out."""
    for name, (width, height) in SCENES.items():
        svg_path = out.with_name(f"{out.name}_{name}.svg")
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(BUILDERS[name](), encoding="utf-8")
        typer.echo(f"→ {svg_path}")
        if png:
            png_path = svg_path.with_suffix(".png")
            asyncio.run(_render_png(svg_path, png_path, width, height))
            typer.echo(f"→ {png_path}")


if __name__ == "__main__":
    app()
