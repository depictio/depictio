#!/usr/bin/env python3
"""Render the dashboard-versioning schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, because the feature has two questions worth a picture:

* *capture* — why a hundred autosaves do not become a hundred timeline
  entries, and which saves leave no trace at all;
* *restore* — why putting a past version back cannot lose the present, and
  which fields deliberately never come from the snapshot.

Generated rather than drawn, so a change in the flow shows up as a diff.
The look and the primitives are lifted from ``watch_trigger_schema.py``:
every stroke drawn twice along a jittered bezier, Virgil where installed,
and a fixed seed so re-running produces a byte-identical file.

Usage:
    python dev/diagrams/dashboard_versioning_schema.py --out docs/images/v0.12/react/schema
    # writes <out>_version_capture.{svg,png} and <out>_version_restore.{svg,png}
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

    def svg(self) -> str:
        body = "\n  ".join(self._parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}">\n'
            f'  <rect width="{self.w}" height="{self.h}" fill="#ffffff"/>\n  {body}\n</svg>\n'
        )


# ── diagram 1: how a save becomes (or does not become) a version ────────────

CAPTURE_W, CAPTURE_H = 1420, 700


def build_capture() -> str:
    s = Sketch(CAPTURE_W, CAPTURE_H)

    s.title(
        "One editing session, a readable timeline",
        "the editor saves on every drag — two gates decide what that leaves behind",
    )

    # One left-to-right spine, with each "yes" dropping straight down. Every
    # stroke is horizontal or vertical: a diagonal across the middle is what
    # made the first draft unreadable.
    editor = Box(
        60,
        190,
        250,
        118,
        BLUE,
        "Editor",
        ("a save per layout change", "500 ms client debounce", "Save button ⇒ “explicit”"),
    )
    hashed = Box(
        390,
        190,
        276,
        118,
        YELLOW,
        "Same content?",
        ("sha256 over the tab family", "ignores last_saved_ts", "and the dead Dash fields"),
    )
    window = Box(
        746,
        190,
        276,
        118,
        VIOLET,
        "Same session?",
        ("same author, window open,", "latest not pinned or named"),
    )
    ledger = Box(
        1102,
        190,
        258,
        118,
        GREEN,
        "A new version",
        ("seq++, pruned later —", "pins are never pruned"),
    )

    nothing = Box(
        390,
        520,
        276,
        112,
        GREY,
        "Nothing written",
        ("a no-op save leaves no trace,", "the screenshot task included"),
    )
    fold = Box(
        746,
        520,
        276,
        112,
        ORANGE,
        "Folded into the latest",
        ("save_count++,", "“12 saves over 4 min”"),
    )

    for b in (editor, hashed, window, ledger, nothing, fold):
        s.box(b)

    s.arrow(editor.right + 10, editor.cy, hashed.x - 12, hashed.cy)
    s.arrow(hashed.right + 10, hashed.cy, window.x - 12, window.cy)
    s.arrow(window.right + 10, window.cy, ledger.x - 12, ledger.cy)
    s.text(1062, 232, "no", size=16, anchor="middle")

    s.arrow(hashed.cx, hashed.bottom + 12, nothing.cx, nothing.y - 14)
    s.text(hashed.cx + 16, 420, "yes", size=16, anchor="start")

    s.arrow(window.cx, window.bottom + 12, fold.cx, fold.y - 14)
    s.text(window.cx + 16, 420, "yes", size=16, anchor="start")

    s.text(60, 396, "why the window is anchored", size=16, anchor="start", weight="bold")
    s.text(60, 424, "a sliding window never lapses", size=14, colour=DIM, anchor="start")
    s.text(60, 448, "while you keep working, so a", size=14, colour=DIM, anchor="start")
    s.text(60, 472, "long session would collapse into", size=14, colour=DIM, anchor="start")
    s.text(60, 496, "one entry you cannot step back", size=14, colour=DIM, anchor="start")
    s.text(60, 520, "through.", size=14, colour=DIM, anchor="start")

    s.text(
        CAPTURE_W - 60,
        CAPTURE_H - 30,
        "a version covers the whole tab family — so adding or deleting a tab is undoable",
        size=15,
        colour=DIM,
        anchor="end",
    )

    return s.svg()


# ── diagram 2: restore, and the boundary it does not cross ──────────────────

RESTORE_W, RESTORE_H = 1240, 620


def build_restore() -> str:
    s = Sketch(RESTORE_W, RESTORE_H, seed=23)

    s.title(
        "Restore puts the past back without losing the present",
        "the state being replaced is captured first, so the restore itself is undoable",
    )

    picked = Box(
        60,
        180,
        250,
        112,
        VIOLET,
        "v12 — pinned",
        ("“Before the Q3 re-run”", "content only"),
    )
    capture = Box(
        390,
        180,
        272,
        112,
        YELLOW,
        "Capture the present",
        ("current state → a version,", "before a single write"),
    )
    apply = Box(
        742,
        180,
        272,
        112,
        GREEN,
        "Write the content",
        ("per tab: update · recreate", "· delete tabs added since"),
    )
    point = Box(
        1064,
        180,
        116,
        112,
        ORANGE,
        "Mark",
        ("kind =", "“restore”"),
    )

    snapshot = Box(
        742,
        450,
        272,
        112,
        PINK,
        "permissions · is_public",
        ("never come from a snapshot —", "TabSnapshot cannot hold them"),
    )

    for b in (picked, capture, apply, point, snapshot):
        s.box(b)

    s.arrow(picked.right + 10, picked.cy, capture.x - 12, capture.cy)
    s.arrow(capture.right + 10, capture.cy, apply.x - 12, apply.cy)
    s.arrow(apply.right + 10, apply.cy, point.x - 12, point.cy)

    # The one edge that deliberately does not exist — a single clean vertical,
    # crossed out, exactly as the watcher schema marks its missing route.
    s.line(apply.cx, apply.bottom + 14, apply.cx, snapshot.y - 14, dashed=True, colour=RED)
    s.cross(apply.cx, 372)
    s.text(apply.cx - 34, 366, "never written", size=15, colour=RED, anchor="end")

    s.text(60, 348, "the boundary", size=17, anchor="start", weight="bold")
    s.text(60, 378, "restoring a months-old version must", size=14, colour=DIM, anchor="start")
    s.text(60, 402, "never bring back access that has", size=14, colour=DIM, anchor="start")
    s.text(60, 426, "since been revoked — a restore is", size=14, colour=DIM, anchor="start")
    s.text(60, 450, "not a way to escalate.", size=14, colour=DIM, anchor="start")

    s.text(
        60,
        RESTORE_H - 58,
        "undo a restore by restoring the version it captured on the way in",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        60,
        RESTORE_H - 30,
        "deleting a version needs owner — the one action a restore cannot reverse",
        size=15,
        colour=DIM,
        anchor="start",
    )

    return s.svg()


SCENES: dict[str, tuple[str, int, int]] = {
    "version_capture": ("build_capture", CAPTURE_W, CAPTURE_H),
    "version_restore": ("build_restore", RESTORE_W, RESTORE_H),
}


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
        help="Output prefix; '_version_capture' / '_version_restore' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write both versioning schema SVGs (and PNGs) under --out."""
    builders = {"version_capture": build_capture, "version_restore": build_restore}
    for name, (_, width, height) in SCENES.items():
        svg_path = out.with_name(f"{out.name}_{name}.svg")
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(builders[name](), encoding="utf-8")
        typer.echo(f"→ {svg_path}")
        if png:
            png_path = svg_path.with_suffix(".png")
            asyncio.run(_render_png(svg_path, png_path, width, height))
            typer.echo(f"→ {png_path}")


if __name__ == "__main__":
    app()
