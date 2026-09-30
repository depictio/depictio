#!/usr/bin/env python3
"""Render why beanie was held at 2.0.0 as a hand-drawn sequence diagram (SVG + PNG).

beanie >= 2.1 asks the client ``callable(client.append_metadata)`` during
``init_beanie()``. motor answers yes by accident (its ``__getattr__`` hands back
a database named ``append_metadata``, whose ``__call__`` raises), pymongo's
``AsyncMongoClient`` answers yes because the method exists. The unit suite ran
on mongomock-motor, whose database is not callable, so beanie skipped the call
and the tests stayed green.

Usage:
    python dev/diagrams/pymongo_driver.py --out docs/images/pymongo-driver
    # writes <out>_append_metadata.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    GREY,
    INK,
    MONO,
    ORANGE,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)

W = 1360
OK = "#2b8a3e"  # green ink for the success marks
CODE_BG = "#f8f9fa"

# Lifeline x positions, shared by both panels so they read as one comparison.
X_LIFESPAN, X_BEANIE, X_CLIENT = 170, 500, 950
X_NOTE = 1050  # left edge of the right-hand annotation column
HEAD_W, HEAD_H = 250, 74
PANEL_H = 600


# -- local helpers built on the Sketch primitives ----------------------------


def rounded(s: Sketch, x: float, y: float, w: float, h: float, fill: str, rx: float = 12) -> None:
    """A flat rounded fill with no outline, for tinted panel and card backgrounds."""
    s._parts.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}"/>'
    )


def mono(s: Sketch, x: float, y: float, lines: list[tuple[str, str]], size: float = 18) -> None:
    """Pre-formatted monospace lines (indentation kept), each with its own colour."""
    for i, (line, colour) in enumerate(lines):
        s._parts.append(
            f'<text x="{x:.1f}" y="{y + i * size * 1.45:.1f}" font-family="{MONO}" '
            f'font-size="{size}" fill="{colour}" xml:space="preserve">{escape(line)}</text>'
        )


def lines_left(
    s: Sketch, x: float, y: float, lines: tuple[str, ...], size: float = 18, colour: str = INK
) -> None:
    for i, line in enumerate(lines):
        s.text(x, y + i * size * 1.35, line, size=size, colour=colour, anchor="start")


def badge(s: Sketch, cx: float, cy: float, label: str) -> None:
    """A numbered step marker."""
    s._parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="14" fill="{INK}"/>')
    s._parts.append(
        f'<text x="{cx:.1f}" y="{cy + 6:.1f}" font-family="{MONO}" font-size="17" '
        f'font-weight="bold" fill="#ffffff" text-anchor="middle">{label}</text>'
    )


def head(s: Sketch, cx: float, y: float, title: str, sub: str, fill: str) -> None:
    """A participant box at the top of a lifeline."""
    s.rect(Box(cx - HEAD_W / 2, y, HEAD_W, HEAD_H, fill, ""))
    s.text(cx, y + 32, title, size=22)
    s.text(cx, y + 58, sub, size=17, colour=DIM)


def lifeline(s: Sketch, x: float, y1: float, y2: float) -> None:
    s.line(x, y1, x, y2, colour=GREY, dashed=True, width=1.6, amount=0.8, passes=1)


def activation(s: Sketch, x: float, y1: float, y2: float) -> None:
    """The narrow bar that shows a participant is busy handling a call."""
    s.rect(Box(x - 9, y1, 18, y2 - y1, WHITE, ""))


def message(
    s: Sketch,
    x1: float,
    x2: float,
    y: float,
    label: str,
    *,
    step: str = "",
    dashed: bool = False,
    colour: str = INK,
    label_colour: str = INK,
) -> None:
    """A horizontal call (solid) or return (dashed) with its label above the arrow."""
    s.arrow(x1, y, x2, y, dashed=dashed, colour=colour)
    s.text((x1 + x2) / 2, y - 13, label, size=19, colour=label_colour)
    if step:
        badge(s, min(x1, x2) + 22, y - 44, step)


def check(s: Sketch, cx: float, cy: float, size: float = 16) -> None:
    kx, ky = cx - size / 3, cy + size * 0.8
    s.line(cx - size, cy, kx, ky, colour=OK, width=3.4, amount=1, passes=1)
    s.line(kx, ky, cx + size, cy - size, colour=OK, width=3.4, amount=1, passes=1)


def burst(s: Sketch, cx: float, cy: float, r: float = 34) -> None:
    """A jagged star: the call blew up here."""
    pts = []
    for i in range(18):
        rad = r if i % 2 == 0 else r * 0.55
        a = math.pi * 2 * i / 18 - math.pi / 2
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    s.poly(pts, fill="#ffd8a8", colour=RED, amount=0.8)
    s.text(cx, cy + 9, "!", size=26, colour=RED, weight="bold")


def cylinder(s: Sketch, cx: float, y: float, w: float, h: float) -> None:
    """A database drum, with the usual hand-drawn double stroke."""
    rx, ry = w / 2, 12
    x0, x1 = cx - rx, cx + rx
    body = (
        f"M{x0:.1f},{y + ry:.1f} L{x0:.1f},{y + h - ry:.1f} "
        f"A{rx:.1f},{ry} 0 0 0 {x1:.1f},{y + h - ry:.1f} L{x1:.1f},{y + ry:.1f} "
        f"A{rx:.1f},{ry} 0 0 0 {x0:.1f},{y + ry:.1f} Z"
    )
    s._parts.append(f'<path d="{body}" fill="{WHITE}" stroke="none"/>')
    for dx in (0, 1.2):
        s._parts.append(
            f'<path d="{body}" fill="none" stroke="{INK}" stroke-width="1.7" '
            f'transform="translate({dx},{dx})"/>'
        )
        s._parts.append(
            f'<ellipse cx="{cx + dx:.1f}" cy="{y + ry + dx:.1f}" rx="{rx:.1f}" ry="{ry}" '
            f'fill="none" stroke="{INK}" stroke-width="1.7"/>'
        )


def note(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    lines: tuple[str, ...],
    fill: str,
    size: float = 18,
    *,
    title: str = "",
    min_h: float = 0,
) -> float:
    """A sticky note with a folded corner and an optional bold title; returns its bottom."""
    pad = size * 1.7 if title else 0
    h = max(min_h, 24 + pad + len(lines) * size * 1.35)
    fold = 18
    s.poly(
        [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)],
        fill=fill,
        colour=DIM,
        amount=1.0,
    )
    s.line(x + w - fold, y, x + w - fold, y + fold, colour=DIM, amount=0.6, passes=1)
    s.line(x + w - fold, y + fold, x + w, y + fold, colour=DIM, amount=0.6, passes=1)
    if title:
        s.text(x + 16, y + 34, title, size=size + 2, anchor="start", weight="bold")
    lines_left(s, x + 16, y + 32 + pad, lines, size=size)
    return y + h


def leader(s: Sketch, x1: float, y1: float, x2: float, y2: float) -> None:
    """A thin dotted pointer from a note to what it explains."""
    s._parts.append(
        f'<path d="M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}" stroke="{DIM}" stroke-width="1.6" '
        f'stroke-dasharray="2 6" stroke-linecap="round" fill="none"/>'
    )
    s._parts.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="4" fill="{DIM}"/>')


# -- the two panels ----------------------------------------------------------


def panel(s: Sketch, top: float, *, after: bool) -> None:
    tint, accent = ("#f4fcf5", OK) if after else ("#fff5f5", RED)
    rounded(s, 24, top, W - 48, PANEL_H, tint, rx=16)
    title = "After: pymongo (this PR)" if after else "Before: motor"
    s.text(48, top + 46, title, size=30, anchor="start", colour=accent)
    s.text(
        W - 48,
        top + 44,
        "beanie 2.2.0, pymongo 4.17" if after else "beanie held at 2.0.0 to avoid this",
        size=19,
        colour=DIM,
        anchor="end",
    )

    hy = top + 76
    head(s, X_LIFESPAN, hy, "`lifespan()`", "FastAPI startup", BLUE)
    head(s, X_BEANIE, hy, "`init_beanie()`", "beanie >= 2.1", VIOLET)
    head(
        s,
        X_CLIENT,
        hy,
        "`AsyncMongoClient`" if after else "`AsyncIOMotorClient`",
        "pymongo async driver" if after else "motor 3.7, deprecated",
        GREEN if after else PINK,
    )
    y1 = hy + HEAD_H + 70  # step 1
    y2 = y1 + 84  # step 2, the probe
    y2r = y2 + 56  # step 2, its answer
    y3 = y2r + 84  # step 3, the call
    y4 = y3 + 80  # outcome, back at lifespan
    for x in (X_LIFESPAN, X_BEANIE, X_CLIENT):
        lifeline(s, x, hy + HEAD_H, y4 + 26)

    activation(s, X_LIFESPAN, y1 - 20, y4 + 16)
    activation(s, X_BEANIE, y1, y4 + 8)
    activation(s, X_CLIENT, y2, y2r)
    activation(s, X_CLIENT, y3, y3 + 36)

    message(s, X_LIFESPAN + 9, X_BEANIE - 9, y1, "`init_beanie(database=db)`", step="1")
    message(s, X_BEANIE + 9, X_CLIENT - 9, y2, "`callable(client.append_metadata)`", step="2")
    message(s, X_CLIENT - 9, X_BEANIE + 9, y2r, "`True`", dashed=True, colour=DIM)
    message(s, X_BEANIE + 9, X_CLIENT - 9, y3, '`append_metadata(DriverInfo("beanie"))`', step="3")

    # Why the probe answers True, in the right-hand column.
    nw = W - 48 - X_NOTE - 16
    if after:
        ny = y2 - 30
        nb = note(s, X_NOTE, ny, nw, ("a real method,", "added in pymongo 4.14"), GREEN)
    else:
        ny = y2 - 70
        nb = note(
            s,
            X_NOTE,
            ny,
            nw,
            (
                "`__getattr__` returns a",
                "MotorDatabase named",
                "`append_metadata`, and",
                "its `__call__` only raises",
            ),
            YELLOW,
        )
    leader(s, X_NOTE, (ny + nb) / 2, X_CLIENT + 12, (y2 + y2r) / 2)

    if after:
        # The call succeeds: the driver info rides on the next handshake.
        dx = X_NOTE + 190
        cylinder(s, dx, y3 - 22, 90, 66)
        s.arrow(X_CLIENT + 12, y3 + 12, dx - 54, y3 + 12, dashed=True, colour=DIM)
        s.text(
            X_CLIENT + 26, y3 + 44, "handshake names beanie", size=17, colour=DIM, anchor="start"
        )
        s.text(dx, y3 + 64, "MongoDB", size=17, colour=DIM)
        message(
            s,
            X_BEANIE - 9,
            X_LIFESPAN + 9,
            y4,
            "models registered",
            dashed=True,
            colour=OK,
            label_colour=OK,
        )
        check(s, X_LIFESPAN - 70, y4 - 4, size=18)
        s.text(X_LIFESPAN - 110, y4 + 50, "startup completes", size=22, colour=OK, anchor="start")
    else:
        burst(s, X_CLIENT + 64, y3 + 16, r=32)
        lines_left(
            s,
            X_CLIENT + 110,
            y3 + 6,
            ("`TypeError`: MotorDatabase", "object is not callable"),
            size=19,
            colour=RED,
        )
        message(
            s,
            X_BEANIE - 9,
            X_LIFESPAN + 9,
            y4,
            "`TypeError` propagates",
            dashed=True,
            colour=RED,
            label_colour=RED,
        )
        s.cross(X_LIFESPAN - 70, y4, size=15)
        s.text(X_LIFESPAN - 110, y4 + 50, "API startup fails", size=22, colour=RED, anchor="start")


def build() -> Sketch:
    code_y, code_h, code_w = 132, 236, 800
    p1 = code_y + code_h + 36
    p2 = p1 + PANEL_H + 28
    s = Sketch(W, p2 + PANEL_H + 28)

    s.text(
        40,
        58,
        "Why beanie was stuck at 2.0.0, and why pymongo unsticks it",
        size=32,
        anchor="start",
    )
    s.text(
        40,
        98,
        "beanie >= 2.1 probes the client inside `init_beanie()`; motor answers the probe wrongly",
        size=20,
        colour=DIM,
        anchor="start",
    )

    # The probe itself, quoted from beanie/odm/utils/init.py.
    rounded(s, 40, code_y, code_w, code_h, CODE_BG)
    rounded(s, 40, code_y, code_w, 42, "#e9ecef", rx=10)
    s.rect(Box(40, code_y, code_w, code_h, "none", ""), colour=GREY)
    s.text(
        60,
        code_y + 29,
        "beanie `odm/utils/init.py`, `Initializer.__init__`",
        size=18,
        colour=DIM,
        anchor="start",
    )
    mono(
        s,
        62,
        code_y + 82,
        [
            ("# append_metadata was added in PyMongo 4.14 and", "#868e96"),
            ("# is a valid database name prior to that version", "#868e96"),
            ("elif database is not None and callable(", INK),
            ("    database.client.append_metadata", "#5f3dc4"),
            ("):", INK),
            ("    database.client.append_metadata(_DRIVER_METADATA)", "#5f3dc4"),
        ],
        size=18,
    )

    # Why the unit suite never saw it.
    nx = 40 + code_w + 28
    note(
        s,
        nx,
        code_y,
        W - 40 - nx,
        (
            "They run on mongomock-motor. Its",
            "client also answers with a database,",
            "but that mock database has no",
            "`__call__`: the probe is `False`,",
            "beanie skips the call, tests pass.",
        ),
        ORANGE,
        size=20,
        title="Why the unit tests stayed green",
        min_h=code_h,
    )
    panel(s, p1, after=False)
    panel(s, p2, after=True)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/pymongo-driver"),
        "--out",
        help="Output prefix; <out>_append_metadata.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the append_metadata schema under --out."""
    write(build(), out, "append_metadata", png=png)


if __name__ == "__main__":
    app()
