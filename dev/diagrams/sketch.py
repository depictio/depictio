#!/usr/bin/env python3
"""A tiny hand-drawn SVG toolkit, shared by the diagrams in this directory.

The look is Excalidraw's: every stroke is drawn twice along a jittered bezier,
and the text uses Virgil (Excalidraw's font) when it is installed locally.
Text in `backticks` is drawn in monospace instead, because handwriting turns
code into guesswork.
Jitter comes from a fixed seed, so re-running a diagram produces a
byte-identical file instead of a spurious diff.

Diagrams are generated rather than drawn so they can be corrected in a diff when
the flow they describe changes — a hand-made PNG goes stale silently.
"""

from __future__ import annotations

import asyncio
import math
import random
import re
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
# Stronger inks for marks that must read on top of the pastel fills.
GOLD = "#ffd43b"
BLUE_INK = "#4dabf7"
RED_INK = "#ff8787"
GREEN_INK = "#69db7c"

FONT = "Virgil GS, Virgil, Excalifont, Comic Sans MS, Bradley Hand, cursive"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace"

# Handwriting is unreadable for code: `--flag` becomes an em dash, `!x` reads as
# `lx`, `[main]` as `LmainJ`. Anything inside backticks is drawn in monospace.
_CODE = re.compile(r"`([^`]+)`")


def _spans(content: str, size: float) -> str:
    """Render `content`, with backticked runs in monospace.

    Both fonts sit in one <text> element on one baseline, so centring stays the
    renderer's job and no width has to be measured here. Monospace carries more
    ink per character than Virgil, hence the slightly smaller size.
    """
    out = []
    for i, part in enumerate(_CODE.split(content)):
        if not part:
            continue
        if i % 2:
            out.append(
                f'<tspan font-family="{MONO}" font-size="{size * 0.88:.1f}">{escape(part)}</tspan>'
            )
        else:
            out.append(escape(part))
    return "".join(out)


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
            f"{_spans(content, size)}</text>"
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

    # -- drawn figures ------------------------------------------------------
    #
    # Helpers that draw the *thing* instead of a box naming it: axes with
    # ticks, a dashboard as its tile grid, a ledger as a line of dots. Lifted
    # from the dataset-time-travel schemas and generalised so any generator can
    # use them. None of them touch the primitives above, so a diagram that does
    # not call them is byte-identical to what it was before.

    def frame(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = WHITE,
        colour: str = INK,
        dashed: bool = False,
    ) -> None:
        """A plain sketched panel with no title: a place to draw inside."""
        self.rect(Box(x, y, w, h, fill, ""), colour=colour, dashed=dashed)

    def text_rotated(
        self,
        x: float,
        y: float,
        content: str,
        *,
        rotate: float,
        size: float = 12,
        colour: str = DIM,
        anchor: str = "middle",
    ) -> None:
        """Text turned about its anchor, for a y-axis title."""
        self._parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'fill="{colour}" text-anchor="{anchor}" '
            f'transform="rotate({rotate:.0f} {x:.1f} {y:.1f})">{_spans(content, size)}</text>'
        )

    def tick(
        self,
        x: float,
        y: float,
        length: float = 8,
        *,
        vertical: bool = True,
        colour: str = INK,
        width: float = 1.3,
    ) -> None:
        """One short mark. Vertical ticks stand on (x, y) and rise; horizontal ones reach left."""
        if vertical:
            self.line(x, y, x, y - length, amount=0.4, width=width, colour=colour, passes=1)
        else:
            self.line(x - length, y, x, y, amount=0.4, width=width, colour=colour, passes=1)

    def axes(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        x_ticks: tuple[tuple[float, str], ...] = (),
        y_ticks: tuple[tuple[float, str], ...] = (),
        x_title: str = "",
        y_title: str = "",
    ) -> None:
        """Plot axes: left spine, baseline and the ticks that make them axes.

        Ticks are (pixel, label) pairs, already mapped through the caller's
        scale: a spine with no ticks is a pair of lines and leaves the reader to
        take the scale on trust instead of reading it off.
        """
        self.line(x, y, x, y + h, amount=1.2, width=1.4)
        self.line(x, y + h, x + w, y + h, amount=1.2, width=1.4)
        for ty, label in y_ticks:
            self.tick(x, ty, 6, vertical=False, width=1.2)
            self.text(x - 10, ty + 4, label, size=11, colour=DIM, anchor="end")
        for tx, label in x_ticks:
            self.tick(tx, y + h + 6, 6, width=1.2)
            self.text(tx, y + h + 22, label, size=11, colour=DIM)
        if y_title:
            self.text_rotated(x - 40, y + h / 2, y_title, rotate=-90, size=11.5)
        if x_title:
            self.text(x + w / 2, y + h + 40, x_title, size=11.5, colour=DIM)

    def time_axis(
        self,
        x0: float,
        x1: float,
        y: float,
        *,
        ticks: tuple[tuple[float, str], ...],
        size: float = 13,
    ) -> None:
        """A horizontal time axis with an arrowhead and labelled ticks below it."""
        self.arrow(x0 - 10, y, x1 + 14, y, colour=INK)
        for tx, label in ticks:
            self.line(tx, y - 6, tx, y + 6, amount=0.4, width=1.3, passes=1)
            if label:
                self.text(tx, y + 25, label, size=size, colour=DIM)

    def shade(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str,
        opacity: float = 0.6,
        colour: str | None = None,
        dashed: bool = False,
    ) -> None:
        """A translucent band, optionally outlined, for a span of time or a zone.

        Translucent so the marks underneath (ticks, dots, gridlines) stay
        readable, and so two bands can overlap without one hiding the other.
        """
        self._parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" '
            f'fill="{fill}" fill-opacity="{opacity}"/>'
        )
        if colour:
            for x1, y1, x2, y2 in (
                (x, y, x + w, y),
                (x + w, y, x + w, y + h),
                (x + w, y + h, x, y + h),
                (x, y + h, x, y),
            ):
                self.line(
                    x1, y1, x2, y2, amount=1.0, width=1.3, colour=colour, passes=1, dashed=dashed
                )

    def dot(
        self,
        cx: float,
        cy: float,
        r: float = 5,
        *,
        fill: str = WHITE,
        colour: str = INK,
        width: float = 1.4,
        dashed: bool = False,
        ring: bool = False,
    ) -> None:
        """A marker. ``ring`` adds the dashed halo that means "this one is chosen"."""
        dash = ' stroke-dasharray="3 3"' if dashed else ""
        self._parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}" fill="{fill}" '
            f'stroke="{colour}" stroke-width="{width}"{dash}/>'
        )
        if ring:
            self._parts.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r + 7:g}" fill="none" '
                f'stroke="{colour}" stroke-width="1.3" stroke-dasharray="3 3"/>'
            )

    def diamond(
        self, cx: float, cy: float, r: float = 8, *, fill: str = GOLD, colour: str = INK
    ) -> None:
        """A square marker turned on its corner: the deliberate, one-off event."""
        pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts) + " Z"
        self._parts.append(
            f'<path d="{d}" fill="{fill}" stroke="{colour}" stroke-width="1.5" '
            f'stroke-linejoin="round"/>'
        )

    def lock(self, cx: float, cy: float, size: float = 11, *, fill: str = VIOLET) -> None:
        """A padlock: sealed, kept, not to be touched."""
        w, h = size * 1.5, size * 1.1
        top = cy - h / 2 + size * 0.25
        r = w * 0.32
        self._parts.append(
            f'<path d="M{cx - r:.1f},{top:.1f} V{top - size * 0.45:.1f} '
            f'a{r:.1f},{r:.1f} 0 0 1 {2 * r:.1f},0 V{top:.1f}" fill="none" '
            f'stroke="{INK}" stroke-width="1.6" stroke-linecap="round"/>'
        )
        self._parts.append(
            f'<rect x="{cx - w / 2:.1f}" y="{top:.1f}" width="{w:.1f}" height="{h:.1f}" rx="2.5" '
            f'fill="{fill}" stroke="{INK}" stroke-width="1.5"/>'
        )
        self._parts.append(f'<circle cx="{cx:.1f}" cy="{top + h / 2:.1f}" r="1.6" fill="{INK}"/>')

    def arc(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        lift: float = -40,
        colour: str = INK,
        dashed: bool = False,
        head: bool = True,
    ) -> None:
        """A bowed arrow, for a relation that must hop over what lies between.

        ``lift`` is the sideways bulge of the middle, in pixels; negative bows
        upwards for a left-to-right arc.
        """
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1.0
        qx, qy = mx + lift * (-dy / norm), my + lift * (dx / norm)
        n = 24
        pts = [
            (
                (1 - t) ** 2 * x1 + 2 * (1 - t) * t * qx + t**2 * x2,
                (1 - t) ** 2 * y1 + 2 * (1 - t) * t * qy + t**2 * y2,
            )
            for t in (i / n for i in range(n + 1))
        ]
        dash = ' stroke-dasharray="9 7"' if dashed else ""
        for _ in range(2):
            d = " ".join(
                f"{'M' if i == 0 else 'L'}{px + self._jitter(1.1):.1f},{py + self._jitter(1.1):.1f}"
                for i, (px, py) in enumerate(pts)
            )
            self._parts.append(
                f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="1.7" '
                f'stroke-linecap="round" stroke-linejoin="round"{dash}/>'
            )
        if head:
            (ax, ay), (bx, by) = pts[-3], pts[-1]
            angle = math.atan2(by - ay, bx - ax)
            for sign in (1, -1):
                h = angle + sign * math.radians(28)
                self.line(
                    bx,
                    by,
                    bx - 14 * math.cos(h),
                    by - 14 * math.sin(h),
                    amount=1.0,
                    colour=colour,
                    passes=1,
                )

    def thumbnail(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        tiles: tuple[tuple[float, float, float, float], ...],
        fill: str,
        absent: bool = False,
    ) -> None:
        """A dashboard as its grid: an outer frame with tiles laid inside.

        ``tiles`` are fractions of the frame, so one layout can be redrawn at any
        size and two layouts compared by shape alone. ``absent`` draws the empty
        dashed slot a tab leaves when it does not exist in that state.
        """
        if absent:
            self.frame(x, y, w, h, colour=GREY, dashed=True)
            return
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
        """A log as a line of commits, one optionally ringed as chosen."""
        end = x + (len(labels) - 1) * spacing
        self.line(x - 16, y, end + 16, y, colour=DIM, amount=1.2, width=1.4)
        for i, label in enumerate(labels):
            cx = x + i * spacing
            chosen = i == selected
            self.dot(cx, y, 7 if chosen else 5, fill=GOLD if chosen else WHITE, ring=chosen)
            self.text(cx, y + 30, label, size=13, colour=DIM)

    def ledger_strip(
        self,
        x: float,
        y: float,
        entries: tuple[tuple[str, str, str], ...],
        *,
        spacing: float,
    ) -> list[float]:
        """A version ledger as a line of dots, one per entry, returning their x.

        Each entry is ``(label, caption, style)``. Styles: ``auto`` (open dot),
        ``explicit`` (gold diamond), ``restore`` (green dot), ``pinned`` (open dot
        under a padlock), ``chosen`` (gold dot, haloed) and ``ghost`` (dashed,
        not yet created). The kind is drawn as well as written, so the strip
        can be read without the captions.
        """
        end = x + (len(entries) - 1) * spacing
        self.line(x - 22, y, end + 22, y, colour=DIM, amount=1.2, width=1.4)
        xs: list[float] = []
        for i, (label, caption, style) in enumerate(entries):
            cx = x + i * spacing
            xs.append(cx)
            ghost = style == "ghost"
            if style == "explicit":
                self.diamond(cx, y, 9)
            elif style == "restore":
                self.dot(cx, y, 7, fill=GREEN_INK)
            elif style == "chosen":
                self.dot(cx, y, 7, fill=GOLD, ring=True)
            elif ghost:
                self.dot(cx, y, 6, colour=GREY, dashed=True)
            else:
                self.dot(cx, y, 6)
            if style == "pinned":
                self.lock(cx, y - 24, 9)
            self.text(cx, y + 30, label, size=15, colour=GREY if ghost else INK, weight="bold")
            self.text(cx, y + 50, caption, size=12.5, colour=GREY if ghost else DIM)
        return xs

    def svg(self) -> str:
        body = "\n  ".join(self._parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:g}" '
            f'height="{self.height:g}" viewBox="0 0 {self.width:g} {self.height:g}">\n'
            f'  <rect width="{self.width:g}" height="{self.height:g}" fill="#ffffff"/>\n'
            f"  {body}\n</svg>\n"
        )


#: Virgil ships in the repo for the viewer, so the PNG can use the real
#: Excalidraw hand instead of whatever cursive the rendering host has (on a clean
#: container, a serif, which undoes the whole hand-drawn look). Override the
#: location with ``DEPICTIO_VIRGIL_TTF`` when the script runs outside the repo.
_VIRGIL_REL = Path("depictio/viewer/src/assets/fonts/Virgil.ttf")


def _virgil_ttf() -> Path | None:
    import os

    override = os.environ.get("DEPICTIO_VIRGIL_TTF")
    candidates = [Path(override)] if override else []
    candidates += [Path(__file__).resolve().parents[2] / _VIRGIL_REL, _VIRGIL_REL]
    return next((c for c in candidates if c.is_file()), None)


def _font_face_css() -> str:
    """A base64 ``@font-face`` for Virgil, or '' when the file is missing.

    Injected into the rasterising page rather than into the SVG: the committed
    SVG stays small and names the font, while the PNG always gets the real hand.
    """
    import base64

    ttf = _virgil_ttf()
    if ttf is None:
        return ""
    encoded = base64.b64encode(ttf.read_bytes()).decode("ascii")
    return (
        "@font-face{font-family:'Virgil';font-style:normal;font-weight:400;"
        f"src:url(data:font/ttf;base64,{encoded}) format('truetype');}}"
    )


def _chromium_executable() -> str | None:
    """An explicit Chromium path when the bundled build is not the one on disk.

    CI images and dev containers often ship a pinned Chromium under
    ``PLAYWRIGHT_BROWSERS_PATH`` whose build number differs from the one the
    installed ``playwright`` expects, which makes ``launch()`` ask for
    ``playwright install`` although a perfectly good browser is present.
    """
    import os

    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not root.is_dir():
        return None
    for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome")):
        if candidate.is_file():
            return str(candidate)
    return None
# Extra tones used by the glyphs below. TICK_GREEN is darker than GREEN_INK,
# which fills shapes: a tick is a thin stroke and has to read on white.
TICK_GREEN = "#2f9e44"
ORANGE_INK = "#e8590c"
LIGHT_GREY = "#f1f3f5"


# -- glyphs -------------------------------------------------------------------
# Small pictograms composed from the primitives above. Signatures are shared with
# from_run_schemas.py so that script can import them unchanged.


def ellipse(
    s: Sketch, cx: float, cy: float, rx: float, ry: float, fill: str, *, n: int = 28
) -> None:
    pts = [
        (cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    s.poly(pts, fill=fill, amount=0.8)


def circle(s: Sketch, cx: float, cy: float, r: float, fill: str) -> None:
    ellipse(s, cx, cy, r, r, fill)


def dot(s: Sketch, cx: float, cy: float, colour: str) -> None:
    """A solid status dot; no outline so it reads as ink, not as a shape."""
    s._parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{colour}"/>')


def tick(
    s: Sketch, cx: float, cy: float, *, size: float = 8, colour: str = TICK_GREEN
) -> None:
    s.line(cx - size, cy, cx - size / 3, cy + size * 0.8, colour=colour, width=2.2, passes=1)
    s.line(cx - size / 3, cy + size * 0.8, cx + size, cy - size, colour=colour, width=2.2, passes=1)


def warning(s: Sketch, cx: float, cy: float, *, size: float = 11) -> None:
    s.poly(
        [(cx, cy - size), (cx + size, cy + size * 0.8), (cx - size, cy + size * 0.8)],
        fill=YELLOW,
        colour=ORANGE_INK,
        amount=0.8,
    )
    s.text(cx, cy + size * 0.55, "!", size=13, weight="bold", colour=ORANGE_INK)


def hourglass(s: Sketch, cx: float, cy: float, *, size: float = 9) -> None:
    s.poly([(cx - size, cy - size), (cx + size, cy - size), (cx, cy)], fill=YELLOW, amount=0.8)
    s.poly([(cx, cy), (cx + size, cy + size), (cx - size, cy + size)], fill=YELLOW, amount=0.8)


def page(s: Sketch, x: float, y: float, w: float, h: float, fill: str = WHITE) -> None:
    """A sheet with a folded corner and a few ruled lines."""
    fold = min(10.0, w * 0.3)
    s.poly(
        [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)],
        fill=fill,
        amount=0.8,
    )
    s.line(x + w - fold, y, x + w - fold, y + fold, amount=0.6, passes=1)
    s.line(x + w - fold, y + fold, x + w, y + fold, amount=0.6, passes=1)
    for i in range(3):
        ly = y + h * 0.4 + i * (h * 0.18)
        if ly < y + h - 4:
            s.line(x + 4, ly, x + w - 5, ly, colour=GREY, amount=0.4, passes=1, width=1.2)


def folder(s: Sketch, x: float, y: float, w: float, h: float, fill: str, label: str = "") -> Box:
    tab = 9
    s.poly(
        [
            (x, y + tab),
            (x + w * 0.34, y + tab),
            (x + w * 0.40, y),
            (x + w * 0.62, y),
            (x + w * 0.68, y + tab),
            (x + w, y + tab),
            (x + w, y + h),
            (x, y + h),
        ],
        fill=fill,
        amount=1.0,
    )
    if label:
        s.text(x + w / 2, y + h / 2 + tab / 2 + 5, label, size=13)
    return Box(x, y, w, h, fill, label, ())


def bucket(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """A pail: a trapezoid body under an elliptical rim, files peeking out."""
    body = [
        (cx - w / 2, top),
        (cx + w / 2, top),
        (cx + w / 2 - 14, top + h),
        (cx - w / 2 + 14, top + h),
    ]
    s.poly(body, fill=fill, edges=(1, 2, 3), amount=1.2)
    ellipse(s, cx, top, w / 2, 12, fill)
    for i, (dx, dy, pw, ph) in enumerate(
        ((-58, -34, 34, 44), (-16, -44, 36, 50), (28, -30, 32, 42))
    ):
        page(s, cx + dx, top + dy, pw, ph, fill=WHITE if i != 1 else LIGHT_GREY)


def magnifier(s: Sketch, cx: float, cy: float, r: float) -> None:
    circle(s, cx, cy, r, "#ffffffaa")
    s.line(cx + r * 0.72, cy + r * 0.72, cx + r * 1.7, cy + r * 1.7, width=5, amount=0.8, passes=1)


def browser(s: Sketch, x: float, y: float, w: float, h: float) -> Box:
    frame = Box(x, y, w, h, WHITE, "", ())
    s.rect(frame)
    s.line(x, y + 28, x + w, y + 28, amount=0.8, passes=1)
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        dot(s, x + 16 + i * 16, y + 14, colour)
    return frame


def field(s: Sketch, x: float, y: float, w: float, label: str, value: str) -> None:
    s.text(x, y + 14, label, size=11, anchor="start", colour=DIM)
    box = Box(x, y + 20, w, 26, LIGHT_GREY, "", ())
    s.rect(box, colour=GREY)
    s.text(x + 8, y + 38, value, size=12, anchor="start")


def mini_table(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    rows: list[tuple[str, str, str]],
    *,
    row_h: float = 20,
) -> float:
    """rows = (collection, files, status) where status is ok / empty / skipped."""
    s.text(x, y + 12, "collection", size=10, anchor="start", colour=GREY)
    s.text(x + w - 62, y + 12, "files", size=10, anchor="start", colour=GREY)
    s.line(x, y + 17, x + w, y + 17, colour=GREY, amount=0.4, passes=1, width=1)
    for i, (name, files, status) in enumerate(rows):
        ry = y + 20 + i * row_h
        count_colour = INK if status == "ok" else RED if status == "empty" else DIM
        s.text(x, ry + 13, name, size=12, anchor="start")
        s.text(x + w - 62, ry + 13, files, size=12, anchor="start", colour=count_colour)
        if status == "ok":
            tick(s, x + w - 10, ry + 9, size=5)
        elif status == "empty":
            s.cross(x + w - 10, ry + 9, size=5)
        else:
            dot(s, x + w - 10, ry + 9, GREY)
    return y + 20 + len(rows) * row_h


def button(s: Sketch, x: float, y: float, w: float, label: str, *, enabled: bool) -> Box:
    box = Box(x, y, w, 30, GREEN if enabled else LIGHT_GREY, "", ())
    s.rect(box, colour=INK if enabled else GREY)
    s.text(box.cx, y + 20, label, size=13, weight="bold", colour=INK if enabled else GREY)
    return box


def chip(s: Sketch, x: float, y: float, w: float, label: str, fill: str = ORANGE) -> Box:
    """A worker task: a small card with a cog in the corner."""
    box = Box(x, y, w, 46, fill, "", ())
    s.rect(box)
    cx, cy = x + w - 14, y + 13
    circle(s, cx, cy, 6, WHITE)
    for k in range(6):
        a = k * math.pi / 3
        s.line(
            cx + 6 * math.cos(a),
            cy + 6 * math.sin(a),
            cx + 9 * math.cos(a),
            cy + 9 * math.sin(a),
            amount=0.3,
            passes=1,
            width=1.4,
        )
    s.text(x + 8, y + 31, label, size=12, anchor="start")
    return box


def table_stack(s: Sketch, x: float, y: float, w: float, h: float, fill: str, n: int = 3) -> None:
    for i in range(n - 1, -1, -1):
        s.rect(Box(x + i * 6, y - i * 6, w, h, fill, "", ()))
    for i in range(1, 4):
        s.line(
            x + 6,
            y + i * h / 4,
            x + w - 6,
            y + i * h / 4,
            colour=GREY,
            amount=0.4,
            passes=1,
            width=1,
        )
    s.line(x + w / 2, y + 4, x + w / 2, y + h - 4, colour=GREY, amount=0.4, passes=1, width=1)


def terminal(s: Sketch, x: float, y: float, w: float, h: float, prompt: str = "") -> Box:
    """A terminal window: a title bar with three dots, a dark-on-white prompt line."""
    frame = Box(x, y, w, h, LIGHT_GREY, "", ())
    s.rect(frame)
    s.line(x, y + 24, x + w, y + 24, amount=0.8, passes=1)
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        dot(s, x + 14 + i * 14, y + 12, colour)
    if prompt:
        s.text(x + 12, y + 46, f"`$ {prompt}`", size=13, anchor="start")
    return frame


async def _render_png(svg_path: Path, png_path: Path, width: float, height: float) -> None:
    from playwright.async_api import async_playwright

    # The SVG is inlined in a page that carries the font: a file:// SVG cannot
    # pull in a sibling font, and without it the hand-drawn look collapses.
    page_html = (
        "<!doctype html><meta charset='utf-8'>"
        f"<style>{_font_face_css()}"
        "html,body{margin:0;padding:0;background:#fff}</style>"
        f"{svg_path.read_text(encoding='utf-8')}"
    )
    html_path = svg_path.with_suffix(".render.html")
    html_path.write_text(page_html, encoding="utf-8")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=_chromium_executable())
            page = await browser.new_page(
                viewport={"width": int(width), "height": int(height)}, device_scale_factor=2
            )
            await page.goto(html_path.resolve().as_uri())
            await page.evaluate("document.fonts.ready")
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(png_path))
            await browser.close()
    finally:
        html_path.unlink(missing_ok=True)


def _quantize(png_path: Path) -> None:
    """Shrink a PNG with ImageMagick (256 colours, no metadata); a no-op without it.

    Flat pastel fills and ink strokes lose nothing visible at 256 colours, and a
    2x capture of a busy diagram is otherwise several hundred KB.
    """
    import shutil
    import subprocess

    magick = shutil.which("magick")
    if magick is None:
        print(f"! magick not found, left {png_path} unquantized")
        return
    tmp = png_path.with_suffix(".q.png")
    subprocess.run(
        [
            magick,
            str(png_path),
            "-strip",
            "-colors",
            "256",
            "-define",
            "png:compression-level=9",
            str(tmp),
        ],
        check=True,
    )
    tmp.replace(png_path)


def write(
    sketch: Sketch, out: Path, name: str, *, png: bool = True, quantize: bool = False
) -> Path:
    """Write ``<out>_<name>.svg`` (and its PNG), returning the SVG path."""
    svg_path = out.with_name(f"{out.name}_{name}.svg")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(sketch.svg(), encoding="utf-8")
    print(f"→ {svg_path}")
    if png:
        png_path = svg_path.with_suffix(".png")
        asyncio.run(_render_png(svg_path, png_path, sketch.width, sketch.height))
        if quantize:
            _quantize(png_path)
        print(f"→ {png_path}")
    return svg_path
