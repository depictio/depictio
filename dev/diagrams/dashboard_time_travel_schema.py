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
        rotate: float | None = None,
    ) -> None:
        spin = f' transform="rotate({rotate:.0f} {x:.1f} {y:.1f})"' if rotate else ""
        self._parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'fill="{colour}" text-anchor="{anchor}" font-weight="{weight}"{spin}>'
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

    def axes(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        y_ticks: tuple[tuple[float, str], ...] = (),
        y_title: str = "",
    ) -> None:
        """Plot axes: left spine, baseline, and the ticks that make them axes.

        `y_ticks` are (pixel_y, label) pairs, already mapped through the cell's
        scale — a spine with no ticks is a pair of lines, and the reader has to
        take the shared scale on trust rather than reading it off.
        """
        self.line(x, y, x, y + h, amount=1.2, width=1.4)
        self.line(x, y + h, x + w, y + h, amount=1.2, width=1.4)
        for ty, label in y_ticks:
            self.line(x - 6, ty, x, ty, amount=0.5, width=1.2, passes=1)
            self.text(x - 10, ty + 4, label, size=11, colour=DIM, anchor="end")
        if y_title:
            self.text(x - 40, y + h / 2, y_title, size=11.5, colour=DIM, rotate=-90)

    def violin(
        self,
        x: float,
        *,
        width: float,
        scale,
        span: tuple[float, float],
        density: tuple[float, ...],
        stats: tuple[float, float, float, float, float],
        values: tuple[float, ...],
        colour: str,
    ) -> None:
        """One violin at `x`: a KDE silhouette, an inner box, and every point.

        Drawn the way the current definition asks for it — `box=True` puts the
        quartile box inside the silhouette and `points="all"` puts the raw
        observations beside it — so the parameter change between the two rows is
        legible in the chart, not only in the list beside it.
        """
        lo_v, hi_v = span
        half = width / 2
        steps = len(density)
        right: list[tuple[float, float]] = []
        left: list[tuple[float, float]] = []
        for i, d in enumerate(density):
            value = lo_v + (hi_v - lo_v) * i / (steps - 1)
            py = scale(value)
            right.append((x + d * half, py))
            left.append((x - d * half, py))
        outline = right + list(reversed(left))
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}" for i, (px, py) in enumerate(outline)
        )
        self._parts.append(f'<path d="{path} Z" fill="{colour}" opacity="0.45"/>')
        # Outline drawn as its own jittered stroke rather than as the fill's
        # edge: a wobbling fill reads as a smudge, a wobbling stroke as a pen.
        wobbled = " ".join(
            f"{'M' if i == 0 else 'L'}{px + self._jitter(0.7):.1f},{py + self._jitter(0.7):.1f}"
            for i, (px, py) in enumerate(outline)
        )
        self._parts.append(
            f'<path d="{wobbled} Z" fill="none" stroke="{INK}" stroke-width="1.3" '
            f'stroke-linejoin="round"/>'
        )
        # points="all": beside the silhouette, as plotly places them, so they
        # never sit on top of the inner box.
        px_centre = x - half * 1.9
        for value in values:
            self._parts.append(
                f'<circle cx="{px_centre + self._jitter(half * 0.4):.1f}" '
                f'cy="{scale(value):.1f}" r="1.3" fill="{INK}" opacity="0.42"/>'
            )
        # box=True: the quartile box, narrow, inside the silhouette.
        lo, q1, med, q3, hi = (scale(v) for v in stats)
        bw = max(width * 0.16, 5.0)
        self.line(x, hi, x, lo, amount=0.6, width=1.2, passes=1)
        box_h = max(q1 - q3, 6.0)
        self._parts.append(
            f'<rect x="{x - bw / 2:.1f}" y="{q3:.1f}" width="{bw:.1f}" '
            f'height="{box_h:.1f}" rx="1.5" fill="#ffffff" stroke="{INK}" stroke-width="1.1"/>'
        )
        med = min(max(med, q3 + 1.2), q3 + box_h - 1.2)
        self.line(x - bw / 2, med, x + bw / 2, med, amount=0.4, width=1.8, passes=1)

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

AXES_W, AXES_H = 1420, 840

#: Petal-length five-number summaries taken from the demo's own batches, so the
#: shapes here are the shapes the screenshots show.  (min, q1, median, q3, max)
SETOSA_V0 = (1.0, 1.4, 1.5, 1.575, 1.9)
SETOSA_V3 = (1.6, 1.962, 2.1, 2.17, 2.53)
VERSICOLOR_V3 = (3.0, 4.0, 4.3, 4.675, 5.1)
VIRGINICA_V3 = (4.5, 5.1, 5.55, 5.875, 6.9)

#: The same four series as a Gaussian KDE, sampled at 25 points from min to max
#: and normalised to its own peak: the silhouette a violin draws. Computed from
#: the batch CSVs rather than shaped by eye. Bandwidth is Silverman's rule with
#: a 0.11 cm floor, because Setosa is measured to the nearest millimetre and has
#: an IQR of 0.18 cm — the unfloored rule picks a bandwidth finer than the
#: measurement grid and draws the rounding as a comb of separate peaks, which is
#: a picture of the ruler rather than of the flowers.
# fmt: off
SETOSA_V0_KDE = (
    0.076, 0.1, 0.131, 0.174, 0.235, 0.318, 0.421, 0.543,
    0.673, 0.798, 0.902, 0.973, 1.0, 0.981, 0.919, 0.825,
    0.712, 0.591, 0.474, 0.368, 0.279, 0.21, 0.16, 0.126,
    0.1,
)
SETOSA_V3_KDE = (
    0.082, 0.105, 0.132, 0.17, 0.225, 0.302, 0.404, 0.525,
    0.654, 0.777, 0.881, 0.958, 1.0, 1.0, 0.954, 0.863,
    0.735, 0.589, 0.445, 0.32, 0.225, 0.161, 0.122, 0.1,
    0.086,
)
VERSICOLOR_V3_KDE = (
    0.089, 0.118, 0.154, 0.196, 0.241, 0.284, 0.326, 0.374,
    0.443, 0.544, 0.669, 0.788, 0.866, 0.894, 0.893, 0.897,
    0.927, 0.973, 1.0, 0.97, 0.867, 0.708, 0.531, 0.368,
    0.238,
)
VIRGINICA_V3_KDE = (
    0.149, 0.247, 0.393, 0.579, 0.77, 0.915, 0.982, 0.981,
    0.96, 0.961, 0.986, 1.0, 0.968, 0.886, 0.773, 0.651,
    0.531, 0.424, 0.339, 0.287, 0.263, 0.253, 0.237, 0.205,
    0.157,
)

#: Every petal length behind those silhouettes, which is what ``points="all"``
#: puts on the chart. Fifty flowers per variety, straight from the CSVs.
SETOSA_V0_VALUES = (
    1, 1.1, 1.2, 1.2, 1.3, 1.3, 1.3, 1.3, 1.3, 1.3, 1.3, 1.4,
    1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4, 1.4,
    1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5,
    1.5, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6, 1.7, 1.7, 1.7, 1.7,
    1.9, 1.9,
)
SETOSA_V3_VALUES = (
    1.6, 1.68, 1.76, 1.82, 1.88, 1.9, 1.9, 1.93, 1.93, 1.94, 1.95, 1.96,
    1.96, 1.97, 1.98, 2, 2, 2, 2.01, 2.02, 2.03, 2.04, 2.04, 2.09,
    2.1, 2.1, 2.1, 2.1, 2.11, 2.12, 2.13, 2.13, 2.14, 2.14, 2.14, 2.17,
    2.17, 2.17, 2.17, 2.19, 2.19, 2.19, 2.19, 2.24, 2.25, 2.25, 2.31, 2.33,
    2.53, 2.53,
)
VERSICOLOR_V3_VALUES = (
    3, 3.3, 3.3, 3.5, 3.5, 3.6, 3.7, 3.7, 3.9, 3.9, 3.9, 3.9,
    4, 4, 4, 4, 4.1, 4.1, 4.1, 4.1, 4.2, 4.2, 4.2, 4.2,
    4.3, 4.3, 4.4, 4.4, 4.4, 4.5, 4.5, 4.5, 4.5, 4.5, 4.6, 4.6,
    4.6, 4.7, 4.7, 4.7, 4.7, 4.7, 4.7, 4.7, 4.8, 4.8, 4.9, 4.9,
    5, 5.1,
)
VIRGINICA_V3_VALUES = (
    4.5, 4.8, 4.8, 4.9, 4.9, 4.9, 5, 5, 5, 5.1, 5.1, 5.1,
    5.1, 5.1, 5.1, 5.1, 5.2, 5.2, 5.3, 5.3, 5.4, 5.4, 5.5, 5.5,
    5.5, 5.6, 5.6, 5.6, 5.6, 5.6, 5.6, 5.7, 5.7, 5.7, 5.8, 5.8,
    5.8, 5.9, 5.9, 6, 6, 6.1, 6.1, 6.1, 6.3, 6.4, 6.6, 6.7,
    6.7, 6.9,
)

# fmt: on

BLUE_INK = "#4dabf7"
RED_INK = "#ff8787"
GREEN_INK = "#69db7c"
#: Plotly's first default trace colour: what every box comes back as when the
#: definition passes no ``color``. One flat colour against three is the cheapest
#: visible proof that the bottom row is running on defaults.
DEFAULT_INK = "#636efa"


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
    left, top = 372, 178
    cell_w, cell_h = 452, 264
    gap = 34
    grid_right = left + 2 * cell_w + gap
    grid_bottom = top + 2 * cell_h + gap

    # One value→y mapping shared by every cell. Per-cell autoscaling would
    # flatten 1.9 cm and 6.9 cm into two identically-sized shapes, destroying the
    # only thing the reader is here to compare. Both rows plot the same quantity
    # on the same scale, so a cell differs from its neighbour for exactly one
    # reason — which is the claim the grid is making.
    TOP_PAD, BOT_PAD = 60, 52
    DATA_MIN, DATA_MAX = 0.6, 7.2

    Series = tuple  # (label, stats, kde, values, colour)

    def draw_cell(
        col: int,
        row: int,
        fill: str,
        heading: str,
        note: str,
        *,
        kind: str,
        series: tuple[Series, ...],
    ) -> Box:
        x = left + col * (cell_w + gap)
        y = top + row * (cell_h + gap)
        cell = Box(x, y, cell_w, cell_h, fill, "")
        s.rect(cell)
        s.text(x + 16, y + 26, heading, size=17, anchor="start", weight="bold")
        s.text(x + 16, y + 46, note, size=13, colour=DIM, anchor="start")

        plot_top, plot_bottom = y + TOP_PAD, y + cell_h - BOT_PAD
        span_px = plot_bottom - plot_top

        def scale(value: float) -> float:
            frac = (value - DATA_MIN) / (DATA_MAX - DATA_MIN)
            return plot_bottom - frac * span_px

        axis_x = x + 80
        axis_w = cell_w - 80 - 26
        s.axes(
            axis_x,
            plot_top,
            axis_w,
            span_px,
            y_ticks=tuple((scale(v), str(v)) for v in (2, 4, 6)),
            y_title="petal.length",
        )
        # Fixed category slots, so a cell holding one variety reads as a cell
        # *missing* the other two rather than as a differently-spaced chart.
        slots = tuple(axis_x + axis_w * f for f in (0.2, 0.5, 0.8))
        for (label, stats, kde, values, colour), slot in zip(series, slots):
            if kind == "violin":
                s.violin(
                    slot,
                    width=36,
                    scale=scale,
                    span=(stats[0], stats[4]),
                    density=kde,
                    stats=stats,
                    values=values,
                    colour=colour,
                )
            else:
                s.boxplot(slot, plot_bottom, width=46, scale=scale, stats=stats, colour=DEFAULT_INK)
            s.text(slot, plot_bottom + 20, label, size=12, colour=DIM)
        s.text(axis_x + axis_w / 2, plot_bottom + 40, "variety", size=11.5, colour=DIM)
        return cell

    current_data = (
        ("Setosa", SETOSA_V3, SETOSA_V3_KDE, SETOSA_V3_VALUES, BLUE_INK),
        ("Versicolor", VERSICOLOR_V3, VERSICOLOR_V3_KDE, VERSICOLOR_V3_VALUES, RED_INK),
        ("Virginica", VIRGINICA_V3, VIRGINICA_V3_KDE, VIRGINICA_V3_VALUES, GREEN_INK),
    )
    past_data = (("Setosa", SETOSA_V0, SETOSA_V0_KDE, SETOSA_V0_VALUES, BLUE_INK),)

    live_live = draw_cell(
        0,
        0,
        GREY,
        "The live dashboard",
        "nothing pinned — the ordinary read",
        kind="violin",
        series=current_data,
    )
    live_past = draw_cell(
        1,
        0,
        BLUE,
        "Current layout, older data",
        "the dataset picker, one collection at a time",
        kind="violin",
        series=past_data,
    )
    past_live = draw_cell(
        0,
        1,
        ORANGE,
        "Older layout, current data",
        "compare mode's right-hand pane",
        kind="box",
        series=current_data,
    )
    # Not bound: unlike the other three, nothing is positioned relative to this
    # cell — it is the bottom-right corner of the grid.
    draw_cell(
        1,
        1,
        GREEN,
        "That version, as it was",
        "“Use this data”, and what ?version= opens",
        kind="box",
        series=past_data,
    )

    # The two axes drawn as axes: a spine, a tick at each cell centre, one
    # arrowhead. An arrow glyph inside a text label points at nothing in
    # particular, and leaves the reader to infer that the four cells are
    # coordinates rather than four separate panels.
    data_axis_y = top - 36
    s.arrow(left - 18, data_axis_y, grid_right + 8, data_axis_y)
    columns = ("current · v3, 150 rows", "a past version · v0, 50 rows")
    for cx, label in zip((live_live.cx, live_past.cx), columns):
        s.line(cx, data_axis_y - 7, cx, data_axis_y, amount=0.4, width=1.2, passes=1)
        s.text(cx, data_axis_y - 16, label, size=14, colour=DIM)
    s.text(grid_right + 20, data_axis_y + 6, "data", size=18, anchor="start", weight="bold")

    def_axis_x = left - 44
    s.arrow(def_axis_x, top - 10, def_axis_x, grid_bottom + 16)
    s.text(
        44,
        (top + grid_bottom) / 2,
        "plot definition and layout",
        size=18,
        weight="bold",
        rotate=-90,
    )

    # Each row's definition, spelled out as the ``dict_kwargs`` the demo's YAML
    # actually carries. The rendering already shows the difference — three
    # colours against one, a silhouette against a box, the points — but only the
    # list says *which* arguments produced it, and a reader who wants to
    # reproduce the picture needs the arguments.
    def gutter(
        centre: float, heading: str, kind_line: str, mode: str, params: tuple[tuple[str, str], ...]
    ) -> None:
        gx = def_axis_x - 16
        s.line(def_axis_x - 7, centre, def_axis_x, centre, amount=0.4, width=1.2, passes=1)
        s.text(gx, centre - 76, heading, size=15, anchor="end", weight="bold")
        s.text(gx, centre - 55, kind_line, size=13, colour=DIM, anchor="end")
        custom = mode == "custom"
        if custom:
            # Only the changed block is highlighted: the eye should land on the
            # three lines that moved, not read both blocks to find them.
            self_w = 186
            s._parts.append(
                f'<rect x="{gx - self_w:.1f}" y="{centre - 14:.1f}" width="{self_w + 8:.1f}" '
                f'height="{22 * len(params) + 8:.1f}" rx="5" fill="{YELLOW}"/>'
            )
        s.text(gx, centre - 22, f"dict_kwargs · {mode}", size=11.5, colour=DIM, anchor="end")
        for i, (key, value) in enumerate(params):
            y = centre + 4 + i * 22
            s.text(gx, y, f"{key}: {value}", size=12.5, colour=INK if custom else DIM, anchor="end")

    gutter(
        live_live.cy,
        "current",
        "violin, by variety",
        "custom",
        (("color", "variety"), ("box", "True"), ("points", "all")),
    )
    gutter(
        past_live.cy,
        "v1 Survey",
        "box plot, by variety",
        "defaults",
        (("color", "unset"), ("box", "unset"), ("points", "unset")),
    )

    s.text(
        58,
        AXES_H - 62,
        "read across a row and only the data moved; read down a column and only the chart did.",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        58,
        AXES_H - 36,
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
    s.text(490, 292, "definition_version: v1", size=14, anchor="start")
    s.text(490, 316, "→ the server reads v1's definition", size=13, colour=DIM, anchor="start")
    s.text(490, 348, "a definition in the body is refused", size=13, colour=RED, anchor="start")

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
