#!/usr/bin/env python3
"""A tiny hand-drawn SVG toolkit, shared by the diagrams in this directory.

The look is Excalidraw's: every stroke is drawn twice along a jittered bezier,
and the text uses Virgil (Excalidraw's font) when it is installed locally.
Jitter comes from a fixed seed, so re-running a diagram produces a
byte-identical file instead of a spurious diff.

Diagrams are generated rather than drawn so they can be corrected in a diff when
the flow they describe changes — a hand-made PNG goes stale silently.
"""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

# Excalidraw's default palette: near-black ink, pastel fills.
INK = "#1e1e1e"
DIM = "#5c5c5c"
RED = "#c92a2a"
GREY = "#adb5bd"
BLUE = "#e7f5ff"
YELLOW = "#fff9db"
GREEN = "#ebfbee"
VIOLET = "#f3f0ff"
ORANGE = "#ffe8cc"
PINK = "#ffe3e3"
WHITE = "#ffffff"

FONT = "Virgil GS, Virgil, Excalifont, Comic Sans MS, Bradley Hand, cursive"


def arc_points(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    start: float,
    end: float,
    steps: int = 22,
) -> list[tuple[float, float]]:
    """Points along an ellipse arc, angles in degrees, y growing downwards.

    Sampling the arc instead of emitting an SVG ``A`` command is what lets the
    same point list serve as both the fill outline and the wobbling stroke, so
    the two never drift apart.
    """
    span = end - start
    return [
        (
            cx + rx * math.cos(math.radians(start + span * i / steps)),
            cy + ry * math.sin(math.radians(start + span * i / steps)),
        )
        for i in range(steps + 1)
    ]


def wave_points(
    x: float, y: float, dx: float, amp: float, steps: int = 20
) -> list[tuple[float, float]]:
    """One sine period across ``dx``: the torn bottom edge of a sheet."""
    return [
        (x + dx * i / steps, y + amp * math.sin(2 * math.pi * i / steps)) for i in range(steps + 1)
    ]


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

    def __init__(self, width: float, height: float, seed: int = 7) -> None:
        self.width = width
        self.height = height
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

    def rect(self, box: Box, *, colour: str = INK, dashed: bool = False) -> None:
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
            self.line(x1, y1, x2, y2, amount=1.6, colour=colour, dashed=dashed)

    def poly(
        self,
        points: list[tuple[float, float]],
        *,
        fill: str,
        colour: str = INK,
        edges: tuple[int, ...] | None = None,
        amount: float = 1.6,
    ) -> None:
        """A filled polygon with hand-drawn edges.

        ``edges`` selects which sides get an outline by their start-point
        index; the default outlines all of them. Leaving a side bare is what
        lets adjacent shapes read as one continuous band rather than as a row
        of separate cells.
        """
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points) + " Z"
        self._parts.append(f'<path d="{d}" fill="{fill}" stroke="none"/>')
        pairs = list(zip(points, points[1:] + points[:1]))
        for i, ((x1, y1), (x2, y2)) in enumerate(pairs):
            if edges is None or i in edges:
                self.line(x1, y1, x2, y2, amount=amount, colour=colour)

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

    def cross(self, cx: float, cy: float, *, size: float = 11, colour: str = RED) -> None:
        """The "this does not happen" mark."""
        self.line(cx - size, cy - size, cx + size, cy + size, colour=colour, amount=1.2, passes=1)
        self.line(cx - size, cy + size, cx + size, cy - size, colour=colour, amount=1.2, passes=1)

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

    def box(self, box: Box, *, colour: str = INK, dashed: bool = False) -> None:
        self.rect(box, colour=colour, dashed=dashed)
        self.text(box.cx, box.y + 27, box.title, size=18, weight="bold")
        for i, line in enumerate(box.lines):
            self.text(box.cx, box.y + 51 + i * 21, line, size=14, colour=DIM)

    def heading(self, x: float, y: float, title: str, subtitle: str = "") -> None:
        self.text(x, y, title, size=25, anchor="start")
        if subtitle:
            self.text(x, y + 26, subtitle, size=15, colour=DIM, anchor="start")

    def stroke(
        self,
        points: list[tuple[float, float]],
        *,
        colour: str = INK,
        width: float = 1.7,
        amount: float = 1.2,
        dashed: bool = False,
        passes: int = 2,
    ) -> None:
        """A polyline where every segment gets the pen's wobble."""
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            self.line(
                x1,
                y1,
                x2,
                y2,
                width=width,
                colour=colour,
                amount=amount,
                dashed=dashed,
                passes=passes,
            )

    def fill(self, points: list[tuple[float, float]], colour: str) -> None:
        """The flat wash under a shape, closed and unstroked."""
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points) + " Z"
        self._parts.append(f'<path d="{d}" fill="{colour}" stroke="none"/>')

    def cylinder(
        self, x: float, y: float, w: float, h: float, *, fill: str, cap: float = 15
    ) -> None:
        """A store: the shape everyone already reads as a database."""
        rx, cx = w / 2, x + w / 2
        top, bottom = y + cap, y + h - cap
        self.fill([(x, top)] + arc_points(cx, bottom, rx, cap, 180, 0) + [(x + w, top)], fill)
        self._parts.append(
            f'<ellipse cx="{cx:.1f}" cy="{top:.1f}" rx="{rx:.1f}" ry="{cap:.1f}" fill="{fill}"/>'
        )
        self.line(x, top, x, bottom, amount=1.2)
        self.line(x + w, top, x + w, bottom, amount=1.2)
        self.stroke(arc_points(cx, bottom, rx, cap, 0, 180), amount=0.8)
        self.stroke(arc_points(cx, top, rx, cap, 0, 360, 30), amount=0.8)

    def document(
        self, x: float, y: float, w: float, h: float, *, fill: str, wave: float = 11
    ) -> None:
        """A sheet with a torn bottom: something written, not something running."""
        base = y + h - wave
        bottom = wave_points(x + w, base, -w, wave)
        self.fill([(x, y), (x + w, y), (x + w, base)] + bottom, fill)
        self.line(x, y, x + w, y, amount=1.4)
        self.line(x + w, y, x + w, base, amount=1.4)
        self.stroke(bottom, amount=0.6)
        self.line(x, base, x, y, amount=1.4)

    def diamond(self, cx: float, cy: float, w: float, h: float, *, fill: str) -> None:
        """A question with two answers."""
        self.poly(
            [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)], fill=fill
        )

    def chip(
        self,
        cx: float,
        cy: float,
        label: str,
        *,
        fill: str,
        w: float = 0.0,
        h: float = 26.0,
        size: float = 13.0,
        colour: str = INK,
    ) -> float:
        """A control, at the size a control is: label inside, nothing around it."""
        w = w or max(52.0, 8.2 * len(label) + 24)
        self.rect(Box(cx - w / 2, cy - h / 2, w, h, fill, ""), colour=colour)
        self.text(cx, cy + size * 0.36, label, size=size)
        return w

    def stack(self, box: Box, *, n: int = 3, dx: float = 9.0, dy: float = -9.0) -> None:
        """``n`` of the same thing: ghosts behind, the readable one in front."""
        for i in range(n - 1, 0, -1):
            self.rect(Box(box.x + dx * i, box.y + dy * i, box.w, box.h, box.fill, ""), colour=GREY)
        self.box(box)

    def tick(self, x: float, y: float, *, size: float = 7.0, colour: str = INK) -> None:
        """The mark a reviewer leaves."""
        self.line(
            x - size,
            y,
            x - size * 0.3,
            y + size * 0.8,
            colour=colour,
            width=2.0,
            amount=0.5,
            passes=1,
        )
        self.line(
            x - size * 0.3,
            y + size * 0.8,
            x + size,
            y - size * 0.9,
            colour=colour,
            width=2.0,
            amount=0.5,
            passes=1,
        )

    def gauge(self, x: float, y: float, w: float, h: float, frac: float, *, fill: str) -> None:
        """How much of a bound is gone, drawn as the bar the UI actually shows."""
        self._parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{h / 2:.1f}" fill="{WHITE}"/>'
        )
        self._parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w * frac:.1f}" height="{h:.1f}" '
            f'rx="{h / 2:.1f}" fill="{fill}"/>'
        )
        self.rect(Box(x, y, w, h, "none", ""), colour=DIM)

    def svg(self) -> str:
        body = "\n  ".join(self._parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:g}" '
            f'height="{self.height:g}" viewBox="0 0 {self.width:g} {self.height:g}">\n'
            f'  <rect width="{self.width:g}" height="{self.height:g}" fill="#ffffff"/>\n'
            f"  {body}\n</svg>\n"
        )


async def _render_png(svg_path: Path, png_path: Path, width: float, height: float) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": int(width), "height": int(height)}, device_scale_factor=2
        )
        await page.goto(svg_path.resolve().as_uri())
        await page.wait_for_timeout(400)  # let the handwriting font load
        await page.screenshot(path=str(png_path))
        await browser.close()


def write(sketch: Sketch, out: Path, name: str, *, png: bool = True) -> Path:
    """Write ``<out>_<name>.svg`` (and its PNG), returning the SVG path."""
    svg_path = out.with_name(f"{out.name}_{name}.svg")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(sketch.svg(), encoding="utf-8")
    print(f"→ {svg_path}")
    if png:
        png_path = svg_path.with_suffix(".png")
        asyncio.run(_render_png(svg_path, png_path, sketch.width, sketch.height))
        print(f"→ {png_path}")
    return svg_path
