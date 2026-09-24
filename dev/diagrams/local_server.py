#!/usr/bin/env python3
"""Render the container-free server's two schemas as hand-drawn SVGs (+ PNGs).

* ``same_code`` — one server, two ways to run it: the same wheel feeds the
  Docker containers and the processes `depictio local up` starts on a laptop.
* ``up_flow``   — the reviewer's path from a terminal to a dashboard, with the
  measured durations drawn to scale.

Usage:
    python dev/diagrams/local_server.py --out docs/images/v1.4/local/schema
    # writes <out>_same_code.svg/.png and <out>_up_flow.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
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

# Stronger fills for the pictograms, still in Excalidraw's pastel family.
MONGO = "#b2f2bb"
REDIS = "#ffc9c9"
MINIO = "#ffd8a8"
BAR_BLUE = "#a5d8ff"
BAR_VIOLET = "#d0bfff"
SCREEN = "#f8f9fa"
STEEL = "#ced4da"


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


def cylinder(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """A database: a body with a rounded bottom, capped by a lighter ellipse."""
    rx, ry = w / 2, h * 0.14
    body = [(cx - rx, top + ry)]
    body += _ellipse(cx, top + h - ry, rx, ry, math.pi, 0)
    body += [(cx + rx, top + ry)]
    s.poly(body, fill=fill, edges=tuple(range(len(body) - 1)))
    s.poly(_ellipse(cx, top + ry, rx, ry, 0, 2 * math.pi)[:-1], fill=WHITE, amount=0.8)
    for k in (0.38, 0.62):
        s.curve(_ellipse(cx, top + ry + (h - 2 * ry) * k, rx, ry, math.pi, 0, 10), colour=INK)


def bucket(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """Object storage: a pail wider at the rim than at the base, with its handle."""
    rx, ry, base = w / 2, h * 0.13, w * 0.36
    body = [(cx - rx, top + ry)]
    body += _ellipse(cx, top + h - ry * 0.7, base, ry * 0.7, math.pi, 0)
    body += [(cx + rx, top + ry)]
    s.poly(body, fill=fill, edges=tuple(range(len(body) - 1)))
    s.poly(_ellipse(cx, top + ry, rx, ry, 0, 2 * math.pi)[:-1], fill=WHITE, amount=0.8)
    s.curve(_ellipse(cx, top + ry - 2, rx * 1.02, ry * 3.2, math.pi, 2 * math.pi, 10), colour=INK)


def stack(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """A key-value store: three stacked slabs."""
    slab = h / 3.4
    for i in range(3):
        y = top + i * (slab + 4)
        s.rect(Box(cx - w / 2, y, w, slab, fill, ""))
        circle(s, cx - w / 2 + 12, y + slab / 2, 3.5, INK)


def gear(s: Sketch, cx: float, cy: float, r: float, fill: str) -> None:
    teeth = 8
    points = []
    for i in range(teeth * 4):
        a = 2 * math.pi * i / (teeth * 4)
        rr = r if (i % 4) in (0, 1) else r * 0.74
        points.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    s.poly(points, fill=fill, amount=0.6)
    circle(s, cx, cy, r * 0.3, WHITE)


def rack(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """A server: two stacked units with their status lights."""
    unit = (h - 6) / 2
    for i in range(2):
        y = top + i * (unit + 6)
        s.rect(Box(cx - w / 2, y, w, unit, fill, ""))
        circle(s, cx + w / 2 - 14, y + unit / 2, 4, "#51cf66")
        s.line(cx - w / 2 + 10, y + unit / 2, cx + w / 2 - 30, y + unit / 2, width=1.3, passes=1)


def browser(s: Sketch, x: float, y: float, w: float, h: float, *, url: str = "") -> None:
    """A browser window showing a dashboard: bars, a line chart, a KPI card."""
    s.rect(Box(x, y, w, h, WHITE, ""))
    s.line(x, y + 26, x + w, y + 26, amount=1.0)
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        circle(s, x + 16 + i * 16, y + 13, 5, colour)
    if url:
        s.text(x + 72, y + 18, url, size=12, colour=DIM, anchor="start")
    pad = 16
    bx, by, bw, bh = x + pad, y + 44, w * 0.42, h - 70
    s.rect(Box(bx, by, bw, bh, SCREEN, ""), colour=GREY)
    heights = (0.45, 0.8, 0.6, 0.95, 0.35)
    step = (bw - 20) / len(heights)
    for i, frac in enumerate(heights):
        bar_h = (bh - 20) * frac
        s.rect(Box(bx + 13 + i * step, by + bh - 10 - bar_h, step - 8, bar_h, BAR_BLUE, ""))
    lx, ly, lw, lh = x + w * 0.5, y + 44, w * 0.5 - pad, (h - 80) / 2
    s.rect(Box(lx, ly, lw, lh, SCREEN, ""), colour=GREY)
    values = (0.2, 0.5, 0.35, 0.8, 0.6, 0.9, 0.7)
    points = [(lx + 10 + i * (lw - 20) / 6, ly + lh - 12 - (lh - 24) * v) for i, v in enumerate(values)]
    s.curve(points, colour="#7048e8")
    ky = ly + lh + 10
    s.rect(Box(lx, ky, lw, lh, BAR_VIOLET, ""))
    s.text(lx + lw / 2, ky + lh / 2 + 9, "8 → 2", size=24, weight="bold")


def terminal(s: Sketch, x: float, y: float, w: float, h: float, lines: tuple[str, ...]) -> None:
    s.rect(Box(x, y, w, h, INK, ""))
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        circle(s, x + 16 + i * 16, y + 14, 5, colour, colour=colour)
    for i, line in enumerate(lines):
        shown = line.replace(" ", "\u00a0")
        s.text(x + 18, y + 52 + i * 26, f"`{shown}`", size=17, colour="#e9ecef", anchor="start")


def laptop(s: Sketch, x: float, y: float, w: float, h: float) -> Box:
    """Draw a laptop and return its screen, for whatever runs on it."""
    screen = Box(x, y, w, h, SCREEN, "")
    s.rect(screen)
    s.poly(
        [(x - 40, y + h + 26), (x + w + 40, y + h + 26), (x + w, y + h), (x, y + h)],
        fill="#dee2e6",
    )
    return screen


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
    s.line(tape, cy - h + d, tape + d, cy - h, width=3, passes=1, colour=RED)
    s.line(tape, cy - h + d, tape, cy - h + d + size * 0.3, width=3, passes=1, colour=RED)


def container(s: Sketch, x: float, y: float, w: float, h: float, fill: str, label: str) -> None:
    """A shipping container: ribbed walls, a label on the door."""
    s.rect(Box(x, y, w, h, fill, ""))
    for i in range(1, 7):
        s.line(x + i * w / 7, y + 6, x + i * w / 7, y + h - 6, width=1.0, colour=DIM, passes=1)
    s.rect(Box(x + w / 2 - 52, y + h / 2 - 15, 104, 30, WHITE, ""))
    s.text(x + w / 2, y + h / 2 + 6, label, size=15)


def pill(s: Sketch, cx: float, cy: float, text: str, fill: str, *, w: float = 150) -> None:
    s.rect(Box(cx - w / 2, cy - 17, w, 34, fill, ""))
    s.text(cx, cy + 6, text, size=16, weight="bold")


# --------------------------------------------------------------------------
# 1. One server, two ways to run it.
# --------------------------------------------------------------------------

SAME_W, SAME_H = 1500, 860


def build_same_code() -> Sketch:
    s = Sketch(SAME_W, SAME_H)
    s.heading(
        46,
        52,
        "One server, two ways to run it",
        "the same wheel everywhere; only where MongoDB, Redis and MinIO come from changes",
    )

    code = Box(520, 105, 460, 215, YELLOW, "")
    s.rect(code)
    s.text(code.cx, code.y + 34, "depictio  (one wheel)", size=22, weight="bold")
    rack(s, code.x + 85, code.y + 62, 90, 74, WHITE)
    gear(s, code.cx, code.y + 99, 38, STEEL)
    bx = code.right - 140
    s.rect(Box(bx, code.y + 62, 110, 76, WHITE, ""))
    s.line(bx, code.y + 78, bx + 110, code.y + 78, amount=0.8, passes=1)
    for i, frac in enumerate((0.5, 0.9, 0.65)):
        s.rect(Box(bx + 18 + i * 28, code.y + 132 - 44 * frac, 18, 44 * frac, BAR_BLUE, ""))
    for x, label in ((code.x + 85, "API"), (code.cx, "worker"), (bx + 55, "viewer")):
        s.text(x, code.y + 172, label, size=17)
    s.text(code.cx, code.y + 200, "configured only by `DEPICTIO_*` variables", size=14, colour=DIM)

    s.text(360, 405, "Docker  /  Kubernetes", size=24, weight="bold")
    s.rect(Box(60, 425, 600, 330, BLUE, ""), dashed=True, colour=DIM)
    fills = (MONGO, REDIS, MINIO, YELLOW, YELLOW, YELLOW)
    for i, label in enumerate(("mongo", "redis", "minio", "api", "worker", "viewer")):
        col, row = i % 2, i // 2
        container(s, 90 + col * 290, 450 + row * 98, 250, 78, fills[i], label)
    s.text(360, 790, "one container per service, images from a registry", size=15, colour=DIM)

    s.text(1115, 405, "`depictio local up`", size=24, weight="bold")
    screen = laptop(s, 860, 440, 510, 280)
    cylinder(s, screen.x + 85, screen.y + 40, 90, 105, MONGO)
    stack(s, screen.x + 255, screen.y + 45, 100, 100, REDIS)
    bucket(s, screen.x + 425, screen.y + 48, 104, 100, MINIO)
    for x, label in (
        (screen.x + 85, "mongod"),
        (screen.x + 255, "redis-server"),
        (screen.x + 425, "minio"),
    ):
        s.text(x, screen.y + 175, label, size=15)
    pill(s, screen.x + 165, screen.y + 225, "uvicorn", YELLOW)
    pill(s, screen.x + 345, screen.y + 225, "celery", YELLOW)
    s.text(1115, 800, "plain processes on 127.0.0.1, state in `~/.depictio/local`", size=15, colour=DIM)

    cube(s, 1400, 185, 72, MINIO)
    s.text(1400, 258, "conda-forge", size=16, weight="bold")
    s.curve([(1395, 275), (1385, 330), (1350, 395)], colour=INK)
    s.arrow(1350, 395, 1335, 432)
    s.text(1300, 320, "`py-rattler`", size=14, anchor="end")
    s.text(1300, 340, "first run only", size=13, colour=DIM, anchor="end")

    s.arrow(code.x + 40, code.bottom, 360, 380)
    s.arrow(code.right - 40, code.bottom, 1115, 380)
    s.line(750, 400, 750, 820, dashed=True, colour=GREY)
    return s


# --------------------------------------------------------------------------
# 2. From a terminal to a dashboard.
# --------------------------------------------------------------------------

FLOW_W, FLOW_H = 1560, 780


def build_up_flow() -> Sketch:
    s = Sketch(FLOW_W, FLOW_H)
    s.heading(
        46,
        52,
        "From a terminal to a dashboard",
        "a reviewer with nothing but `uv` installed, on their own nf-core results",
    )

    terminal(
        s,
        46,
        120,
        360,
        190,
        (
            "$ uvx --from depictio[local] \\",
            "    depictio local up \\",
            "    --template nf-core/rnaseq \\",
            "    --data-root results/",
        ),
    )
    s.text(226, 380, "1 · one command", size=19, weight="bold")

    cube(s, 520, 175, 64, BAR_BLUE)
    s.text(520, 238, "PyPI", size=15, weight="bold")
    cube(s, 625, 175, 64, MINIO)
    s.text(625, 238, "conda-forge", size=15, weight="bold")
    s.text(572, 270, "Python env · MongoDB,", size=14, colour=DIM)
    s.text(572, 289, "Redis, MinIO binaries", size=14, colour=DIM)
    s.text(572, 380, "2 · first run only", size=19, weight="bold")

    screen = laptop(s, 745, 120, 330, 190)
    cylinder(s, screen.x + 60, screen.y + 24, 62, 76, MONGO)
    stack(s, screen.x + 165, screen.y + 28, 70, 68, REDIS)
    bucket(s, screen.x + 270, screen.y + 34, 70, 66, MINIO)
    gear(s, screen.x + 115, screen.y + 148, 24, STEEL)
    gear(s, screen.x + 215, screen.y + 148, 24, STEEL)
    s.text(910, 380, "3 · services start", size=19, weight="bold")

    browser(s, 1165, 110, 350, 210, url="127.0.0.1:8058/dashboards")
    s.text(1340, 380, "4 · dashboard opens", size=19, weight="bold")

    for x1, x2 in ((414, 470), (672, 718), (1112, 1155)):
        s.arrow(x1, 215, x2, 215)

    s.text(46, 440, "measured wall time, drawn to scale", size=20, weight="bold", anchor="start")
    scale = 26
    bars = (
        ("first run, empty caches, rnaseq megatest", 41, BAR_BLUE),
        ("next run, fresh data, rnaseq megatest", 20, BAR_VIOLET),
        ("iris example, warm caches", 8, MONGO),
    )
    for i, (label, seconds, fill) in enumerate(bars):
        y = 470 + i * 84
        s.rect(Box(46, y, seconds * scale, 44, fill, ""))
        s.text(46 + seconds * scale + 16, y + 31, f"{seconds} s", size=22, weight="bold", anchor="start")
        s.text(56, y + 66, label, size=14, colour=DIM, anchor="start")
    for sec in (0, 10, 20, 30, 40):
        x = 46 + sec * scale
        s.line(x, 728, x, 738, width=1.2, colour=DIM, passes=1)
        s.text(x, 758, f"{sec} s", size=12, colour=DIM)

    for i, text in enumerate(("no Docker", "no conda install", "no git clone")):
        cx, cy = 1370, 480 + i * 84
        s.rect(Box(cx - 130, cy - 26, 260, 52, PINK, ""))
        s.cross(cx - 100, cy, size=10)
        s.text(cx + 12, cy + 7, text, size=19, weight="bold")
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v1.4/local/schema"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render PNGs through Playwright."),
) -> None:
    """Write the same-code and up-flow schemas under --out."""
    write(build_same_code(), out, "same_code", png=png)
    write(build_up_flow(), out, "up_flow", png=png)


if __name__ == "__main__":
    app()
