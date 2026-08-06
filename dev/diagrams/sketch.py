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
import base64
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

# When the TTF is embedded, the @font-face family must win over anything the
# viewer happens to have installed — otherwise a machine with Virgil GS renders
# from that instead, and "embedded so it looks the same everywhere" is not true.
EMBEDDED_FONT = "Virgil, Virgil GS, Excalifont, Comic Sans MS, Bradley Hand, cursive"

REPO_ROOT = Path(__file__).resolve().parents[2]
VIRGIL_TTF = REPO_ROOT / "depictio" / "viewer" / "src" / "assets" / "fonts" / "Virgil.ttf"


def font_face() -> str:
    """Inline the vendored Virgil TTF as a base64 ``@font-face``.

    ``FONT`` alone only asks for Virgil; it renders as handwriting solely on a
    machine that happens to have Virgil GS installed, which CI and containers do
    not. Embedding costs ~150 KB per SVG, so it is opt-in per sketch
    (``Sketch(..., embed_font=True)``) rather than the default.

    Falls back to a bare ``<defs/>`` when the TTF is missing: the drawing still
    renders, just in whatever the font stack resolves to next.
    """
    if not VIRGIL_TTF.exists():
        return "<defs/>"
    b64 = base64.b64encode(VIRGIL_TTF.read_bytes()).decode()
    return (
        "<defs><style>@font-face{font-family:'Virgil';"
        f"src:url(data:font/ttf;base64,{b64}) format('truetype');}}</style></defs>"
    )


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

    def __init__(
        self, width: float, height: float, seed: int = 7, *, embed_font: bool = False
    ) -> None:
        self.width = width
        self.height = height
        self.embed_font = embed_font
        self.font = EMBEDDED_FONT if embed_font else FONT
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

    def elbow(self, points: list[tuple[float, float]], *, colour: str = INK) -> None:
        """A multi-segment run with a single arrowhead on the final leg.

        For a connector that has to go sideways and then up or down: one
        straight arrow would cut diagonally across whatever sits between the
        two boxes.
        """
        for (x1, y1), (x2, y2) in zip(points[:-2], points[1:-1]):
            self.line(x1, y1, x2, y2, colour=colour, amount=1.4)
        (px, py), (qx, qy) = points[-2], points[-1]
        self.arrow(px, py, qx, qy, colour=colour)

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
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{self.font}" font-size="{size}" '
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

    def svg(self) -> str:
        body = "\n  ".join(self._parts)
        defs = f"  {font_face()}\n" if self.embed_font else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:g}" '
            f'height="{self.height:g}" viewBox="0 0 {self.width:g} {self.height:g}">\n'
            f"{defs}"
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
