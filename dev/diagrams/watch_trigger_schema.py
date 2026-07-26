#!/usr/bin/env python3
"""Render the "Run now" watcher-trigger schema as a hand-drawn SVG (+ PNG).

The diagram summarises how a request made in the browser reaches a watcher that
the server cannot connect to, and what the resulting cycle leaves behind. It is
generated rather than drawn so it can be corrected in a diff when the flow
changes.

The look is Excalidraw's: every stroke is drawn twice along a jittered bezier,
and the text uses Virgil (Excalidraw's font) when it is installed locally.
Jitter comes from a fixed seed, so re-running produces a byte-identical file
instead of a spurious diff.

Usage:
    python dev/diagrams/watch_trigger_schema.py --out docs/images/v0.12/schema
    # writes <out>_watch_trigger.svg and, unless --no-png, _watch_trigger.png

PNG rendering needs Playwright (already a dev dependency) and a local Virgil GS;
without the font the SVG still renders, in whatever handwriting font the
fallback list finds.
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
BLUE = "#e7f5ff"
YELLOW = "#fff9db"
GREEN = "#ebfbee"
VIOLET = "#f3f0ff"
ORANGE = "#ffe8cc"

FONT = "Virgil GS, Virgil, Excalifont, Comic Sans MS, Bradley Hand, cursive"

W, H = 1180, 540


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

    def __init__(self, seed: int = 7) -> None:
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

    def svg(self) -> str:
        body = "\n  ".join(self._parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">\n'
            f'  <rect width="{W}" height="{H}" fill="#ffffff"/>\n  {body}\n</svg>\n'
        )


def build() -> str:
    s = Sketch()

    s.text(46, 52, "“Run now”: a request the server cannot deliver", size=25, anchor="start")
    s.text(
        46,
        78,
        "the watcher pulls, so it works from a login node the API can never reach",
        size=15,
        colour=DIM,
        anchor="start",
    )

    browser = Box(46, 118, 268, 92, BLUE, "Agents pane", ("Admin → Log & Task", "press “Run now”"))
    api = Box(
        430, 118, 300, 92, YELLOW, "API", ("POST …/agents/…/trigger", "records a flag, not a push")
    )
    records = Box(
        846,
        118,
        288,
        92,
        GREEN,
        "What it leaves behind",
        ("a run in Ingestion → History", "trigger “ui”, not “watch”"),
    )
    watcher = Box(
        430,
        368,
        300,
        104,
        VIOLET,
        "depictio data watch",
        ("polls …/claim every 5s", "claim clears it atomically", "→ honoured exactly once"),
    )
    cycle = Box(846, 368, 288, 104, ORANGE, "One cycle", ("scan → process", "steps stream in live"))

    for b in (browser, api, records, watcher, cycle):
        s.box(b)

    # Browser → API.
    s.arrow(browser.right + 8, browser.cy, api.x - 10, api.cy)

    # API → watcher: the direction that does not exist. Dashed, crossed out.
    s.line(api.cx - 42, api.bottom + 10, api.cx - 42, watcher.y - 12, dashed=True, colour="#c92a2a")
    s.line(api.cx - 62, 280, api.cx - 22, 260, colour="#c92a2a", amount=1.2, passes=1)
    s.line(api.cx - 62, 260, api.cx - 22, 280, colour="#c92a2a", amount=1.2, passes=1)
    s.text(api.cx - 74, 250, "no route in", size=14, colour="#c92a2a", anchor="end")

    # Watcher → API: the direction that does.
    s.arrow(watcher.cx + 46, watcher.y - 12, api.cx + 46, api.bottom + 10)
    s.text(api.cx + 60, 252, "claim", size=15, anchor="start")
    s.text(api.cx + 60, 272, "(a pull)", size=13, colour=DIM, anchor="start")

    # Watcher → cycle → records.
    s.arrow(watcher.right + 8, watcher.cy, cycle.x - 10, cycle.cy)
    s.arrow(cycle.cx, cycle.y - 12, records.cx, records.bottom + 10)
    s.text(cycle.cx - 16, 252, "the Delta commit", size=13, colour=DIM, anchor="end")
    s.text(cycle.cx - 16, 272, "carries the run id", size=13, colour=DIM, anchor="end")

    # Heartbeat: the watcher's own liveness loop, unrelated to any request.
    s.curve(
        [
            (watcher.x - 6, watcher.y + 34),
            (watcher.x - 78, watcher.y + 34),
            (watcher.x - 78, watcher.y + 78),
            (watcher.x - 6, watcher.y + 78),
        ]
    )
    s.text(watcher.x - 90, watcher.y + 44, "heartbeat", size=14, colour=DIM, anchor="end")
    s.text(watcher.x - 90, watcher.y + 64, "every 60s", size=13, colour=DIM, anchor="end")
    s.text(watcher.x - 90, watcher.y + 84, "(TTL 5 min)", size=13, colour=DIM, anchor="end")

    # Banding note: which side of the wire each row lives on.
    s.text(46, 232, "server", size=14, colour=DIM, anchor="start")
    s.text(46, 348, "the machine with the data", size=14, colour=DIM, anchor="start")
    s.line(46, 300, W - 46, 300, dashed=True, colour="#adb5bd", width=1.2, passes=1)

    s.text(
        W - 46,
        H - 26,
        "a request while a cycle runs is picked up when that cycle ends",
        size=14,
        colour=DIM,
        anchor="end",
    )

    return s.svg()


async def _render_png(svg_path: Path, png_path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        await page.goto(svg_path.resolve().as_uri())
        await page.wait_for_timeout(400)  # let the handwriting font load
        await page.screenshot(path=str(png_path))
        await browser.close()


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/schema"),
        "--out",
        help="Output prefix; '_watch_trigger.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the schema SVG (and PNG) under --out."""
    svg_path = out.with_name(f"{out.name}_watch_trigger.svg")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(build(), encoding="utf-8")
    typer.echo(f"→ {svg_path}")
    if png:
        png_path = svg_path.with_suffix(".png")
        asyncio.run(_render_png(svg_path, png_path))
        typer.echo(f"→ {png_path}")


if __name__ == "__main__":
    app()
