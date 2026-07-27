#!/usr/bin/env python3
"""Render the component-export schema as a hand-drawn SVG (+ PNG).

The diagram summarises what a caller gets from the export endpoint: one component,
one URL, and two formats whose coverage differs on purpose. It is generated rather
than drawn so it can be corrected in a diff when the flow changes.

The look is Excalidraw's: every stroke is drawn twice along a jittered bezier, and
the text uses Virgil (Excalidraw's font). Jitter comes from a fixed seed, so
re-running produces a byte-identical file instead of a spurious diff.

Unlike its sibling `watch_trigger_schema.py`, this one **inlines Virgil** from the
copy already vendored at ``depictio/viewer/src/assets/fonts/Virgil.ttf`` as a base64
``@font-face``. Relying on a locally installed Virgil GS means the SVG silently
renders in whatever cursive the fallback list finds — on a machine without the font
(CI, a container) the result does not look hand-drawn at all. Embedding costs ~150 KB
and makes the file portable.

The ``Sketch`` primitives are duplicated from `watch_trigger_schema.py` on purpose:
that module is not on `main` yet, and importing across two open branches would make
this diagram depend on an unmerged one. Once both have landed they should be lifted
into a shared `dev/diagrams/_sketch.py`.

Usage:
    python dev/diagrams/component_export_schema.py --out docs/images/v0.12/react/schema
    # writes <out>_component_export.svg and, unless --no-png, .png
"""

from __future__ import annotations

import asyncio
import base64
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

FONT = "Virgil, Virgil GS, Excalifont, Comic Sans MS, Bradley Hand, cursive"

REPO_ROOT = Path(__file__).resolve().parents[2]
VIRGIL_TTF = REPO_ROOT / "depictio" / "viewer" / "src" / "assets" / "fonts" / "Virgil.ttf"

W, H = 1240, 620


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

    def __init__(self, seed: int = 11) -> None:
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

    def elbow(
        self,
        points: list[tuple[float, float]],
        *,
        colour: str = INK,
    ) -> None:
        """A multi-segment run with a single arrowhead on the final leg.

        The fork out of the endpoint box needs to go sideways then up/down; one
        straight arrow would cut diagonally across the annotations.
        """
        for (x1, y1), (x2, y2) in zip(points[:-2], points[1:-1]):
            self.line(x1, y1, x2, y2, colour=colour, amount=1.4)
        (px, py), (qx, qy) = points[-2], points[-1]
        self.arrow(px, py, qx, qy, colour=colour)

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
            f"  {_font_face()}\n"
            f'  <rect width="{W}" height="{H}" fill="#ffffff"/>\n  {body}\n</svg>\n'
        )


def _font_face() -> str:
    """Inline Virgil so the SVG renders identically without a local install.

    Falls back to a bare ``<defs/>`` when the vendored TTF is missing, in which case
    the font stack in ``FONT`` still applies — the drawing renders, just not in
    Excalidraw's handwriting.
    """
    if not VIRGIL_TTF.exists():
        return "<defs/>"
    b64 = base64.b64encode(VIRGIL_TTF.read_bytes()).decode()
    return (
        "<defs><style>@font-face{font-family:'Virgil';"
        f"src:url(data:font/ttf;base64,{b64}) format('truetype');}}</style></defs>"
    )


def build() -> str:
    s = Sketch()

    s.text(46, 52, "One component, two ways out", size=25, anchor="start")
    s.text(
        46,
        78,
        "the same URL returns a Plotly spec, or a page that needs nothing to render",
        size=15,
        colour=DIM,
        anchor="start",
    )

    component = Box(
        46,
        250,
        250,
        104,
        BLUE,
        "A dashboard component",
        ("figure · table · card · map", "multiqc · advanced viz", "image · text · interactive"),
    )
    endpoint = Box(
        356,
        250,
        286,
        104,
        YELLOW,
        "GET /export/…/{cid}",
        ("?format=json | html", "&theme= &filters=", "existing viewer permission"),
    )

    spec = Box(
        706,
        104,
        232,
        92,
        GREEN,
        "format=json",
        ("Python builds the figure", "{data, layout, config, meta}"),
    )
    consumer = Box(
        986,
        104,
        208,
        92,
        GREEN,
        "your plotly.js",
        ("figure · map · multiqc", "+ 6 advanced-viz kinds"),
    )

    page = Box(
        706,
        408,
        232,
        92,
        VIOLET,
        "format=html",
        ("the real React renderer,", "inlined into one file"),
    )
    iframe = Box(
        986,
        408,
        208,
        92,
        ORANGE,
        "iframe, any site",
        ("9 of 10 types —", "all but jbrowse"),
    )

    for b in (component, endpoint, spec, consumer, page, iframe):
        s.box(b)

    s.arrow(component.right + 8, component.cy, endpoint.x - 10, endpoint.cy)

    # The fork. Sideways out of the endpoint, then up to json / down to html.
    fork_x = endpoint.right + 34
    s.elbow(
        [
            (endpoint.right + 8, endpoint.cy),
            (fork_x, endpoint.cy),
            (fork_x, spec.cy),
            (spec.x - 10, spec.cy),
        ]
    )
    s.elbow(
        [
            (endpoint.right + 8, endpoint.cy),
            (fork_x, endpoint.cy),
            (fork_x, page.cy),
            (page.x - 10, page.cy),
        ]
    )

    s.arrow(spec.right + 8, spec.cy, consumer.x - 10, consumer.cy)
    s.arrow(page.right + 8, page.cy, iframe.x - 10, iframe.cy)

    # Which format a given component supports is a question with an answer.
    # Set below the endpoint box and broken in two so it stays clear of the fork's
    # vertical leg at fork_x — one long line would run straight through it.
    s.text(
        endpoint.x,
        endpoint.bottom + 42,
        "ask …/components first —",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        endpoint.x,
        endpoint.bottom + 63,
        "it lists the formats each one supports",
        size=14,
        colour=DIM,
        anchor="start",
    )

    # The gap in the json format, in the reference's red-for-what-does-not-work.
    s.text(
        706,
        232,
        "12 advanced-viz kinds still build in the browser",
        size=14,
        colour=RED,
        anchor="start",
    )
    s.text(706, 252, "→ 501, with the html_url that does work", size=13, colour=RED, anchor="start")

    # The property that makes the html format worth having.
    s.text(
        706,
        542,
        "zero network calls — opens straight from file://",
        size=14,
        colour=DIM,
        anchor="start",
    )

    s.text(
        W - 46,
        H - 26,
        "off by default — DEPICTIO_FASTAPI_EMBED_ENABLED",
        size=14,
        colour=DIM,
        anchor="end",
    )

    return s.svg()


async def _render_png(svg_path: Path, png_path: Path, chromium_path: str | None) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        launch: dict = {"executable_path": chromium_path} if chromium_path else {}
        browser = await p.chromium.launch(**launch)
        page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        await page.goto(svg_path.resolve().as_uri())
        await page.wait_for_timeout(400)  # let the handwriting font load
        await page.screenshot(path=str(png_path))
        await browser.close()


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"),
        "--out",
        help="Output prefix; '_component_export.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
    chromium_path: str = typer.Option(
        None,
        "--chromium-path",
        help="Chromium binary to rasterise with. Defaults to Playwright's own lookup.",
    ),
) -> None:
    """Write the schema SVG (and PNG) under --out."""
    svg_path = out.with_name(f"{out.name}_component_export.svg")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(build(), encoding="utf-8")
    typer.echo(f"→ {svg_path}")
    if png:
        png_path = svg_path.with_suffix(".png")
        asyncio.run(_render_png(svg_path, png_path, chromium_path))
        typer.echo(f"→ {png_path}")


if __name__ == "__main__":
    app()
