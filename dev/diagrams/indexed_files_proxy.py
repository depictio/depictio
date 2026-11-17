#!/usr/bin/env python3
"""Render the two ways a browser reaches an indexed file's bytes, as a
hand-drawn SVG (+ PNG).

* ``modes`` — ``presigned`` (the default): the manifest hands out presigned S3
  URLs and the browser reads byte ranges from the store's public URL. ``proxy``
  (``DEPICTIO_S3_BROWSER_ACCESS=proxy``): the store is internal only, so the
  manifest hands out signed API URLs and the API reads each range from S3 and
  streams it back. Beside them, the failure that motivated the proxy (a
  presigned URL on an internal-only store) and how Helm picks the mode.

Usage:
    python dev/diagrams/indexed_files_proxy.py --out docs/images/indexed-files-proxy
    # writes <out>_modes.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    GREY,
    INK,
    LIGHT_GREY,
    ORANGE,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    tick,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1700, 1190
OK = "#2b8a3e"

# Lifeline x of the three actors, shared by both panels.
BROWSER_X, API_X, S3_X = 210, 650, 1010


# -- local helpers built on the Sketch primitives ----------------------------


def actor(
    s: Sketch,
    cx: float,
    y: float,
    w: float,
    title: str,
    line: str,
    fill: str,
    bottom: float,
    *,
    dashed: bool = False,
) -> None:
    """An actor's header box and its dashed lifeline down to ``bottom``."""
    box = Box(cx - w / 2, y, w, 62, fill, title)
    s.rect(box, dashed=dashed, colour=DIM if dashed else INK)
    s.text(cx, y + 26, title, size=18, weight="bold")
    s.text(cx, y + 49, line, size=13.5, colour=DIM)
    s.line(cx, y + 66, cx, bottom, colour=GREY, dashed=True, amount=0.8, passes=1, width=1.4)


def msg(
    s: Sketch,
    x1: float,
    x2: float,
    y: float,
    label: str,
    *,
    reply: bool = False,
    colour: str = INK,
    size: float = 14.5,
) -> None:
    """A message between two lifelines; a reply is dashed."""
    pad = 8 if x2 > x1 else -8
    s.arrow(x1 + pad, y, x2 - pad, y, dashed=reply, colour=colour)
    s.text((x1 + x2) / 2, y - 11, label, size=size, colour=colour)


def panel(s: Sketch, y: float, h: float, fill: str, title: str, subtitle: str) -> None:
    s.shade(40, y, 1120, h, fill=fill, opacity=0.45, colour=GREY)
    s.text(64, y + 34, title, size=21, weight="bold", anchor="start")
    s.text(64, y + 58, subtitle, size=14, colour=DIM, anchor="start")


# -- the schema ---------------------------------------------------------------


def build_modes() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "Indexed files: where the browser gets its bytes",
        "`DEPICTIO_S3_BROWSER_ACCESS` picks the mode; requests are solid, replies dashed",
    )

    # ---- presigned ------------------------------------------------------------
    top, h = 110, 370
    panel(
        s,
        top,
        h,
        BLUE,
        "`presigned` (default)",
        "S3 is reachable from browsers",
    )
    bottom = top + h - 18
    ay = top + 80
    actor(s, BROWSER_X, ay, 250, "browser", "3D viewer / GenomeSpy", WHITE, bottom)
    actor(s, API_X, ay, 200, "API", "depictio backend", VIOLET, bottom)
    actor(s, S3_X, ay, 220, "S3", "public URL", GREEN, bottom)
    y = ay + 112
    msg(s, BROWSER_X, API_X, y, "`GET /files/indexed/{dc}`")
    y += 46
    msg(s, API_X, BROWSER_X, y, "manifest: presigned S3 URLs", reply=True)
    y += 46
    msg(s, BROWSER_X, S3_X, y, "`GET` presigned URL, `Range: bytes=…`")
    y += 46
    msg(s, S3_X, BROWSER_X, y, "the byte range, straight from S3", reply=True, colour=OK)

    # ---- proxy ----------------------------------------------------------------
    top, h = 510, 660
    panel(
        s,
        top,
        h,
        ORANGE,
        "`proxy` (`DEPICTIO_S3_BROWSER_ACCESS=proxy`)",
        "S3 is internal only: IP-only install, Serve app",
    )
    bottom = top + h - 18
    ay = top + 80
    actor(s, BROWSER_X, ay, 250, "browser", "3D viewer / GenomeSpy", WHITE, bottom)
    actor(s, API_X, ay, 200, "API", "depictio backend", VIOLET, bottom)
    actor(s, S3_X, ay, 220, "S3", "internal only", LIGHT_GREY, bottom, dashed=True)
    y = ay + 112
    msg(s, BROWSER_X, API_X, y, "`GET /files/indexed/{dc}`")
    y += 50
    msg(s, API_X, BROWSER_X, y, "manifest: signed API URLs", reply=True)
    s.text(
        (BROWSER_X + API_X) / 2,
        y + 24,
        "`/files/indexed/{dc}/object/{sample}/{name}?uid&exp&sig`",
        size=12.5,
        colour=DIM,
    )
    y += 74
    msg(s, BROWSER_X, API_X, y, "`GET` signed URL, `Range: bytes=…`")

    # The checks run on the API before anything is read from S3.
    checks = Box(API_X - 200, y + 22, 400, 136, YELLOW, "")
    s.rect(checks)
    s.text(checks.cx, checks.y + 28, "before reading anything", size=16, weight="bold")
    for i, line in enumerate(
        (
            "signature: one object, one user, 15 min",
            "the reader may open this data collection",
            "the key is registered for this collection",
        )
    ):
        ly = checks.y + 58 + i * 26
        tick(s, checks.x + 24, ly - 5, size=6)
        s.text(checks.x + 42, ly, line, size=14.5, anchor="start")

    y = checks.bottom + 46
    msg(s, API_X, S3_X, y, "read the byte range")
    y += 46
    msg(s, S3_X, API_X, y, "bytes", reply=True)
    y += 46
    msg(s, API_X, BROWSER_X, y, "`206`, streamed back", reply=True, colour=OK)

    # ---- the failure that motivated it ------------------------------------------
    fail = Box(1200, 110, 460, 370, PINK, "")
    s.rect(fail)
    s.text(fail.cx, fail.y + 34, "`presigned` on an internal-only S3", size=18, weight="bold")
    s.text(fail.cx, fail.y + 58, "what happened before the proxy", size=14, colour=DIM)
    browser(s, fail.x + 26, fail.y + 100, 120, 84)
    s.text(fail.x + 86, fail.y + 160, "viewer", size=14, colour=DIM)
    ax0, ax1, arrow_y = fail.x + 158, fail.right - 26, fail.y + 150
    s.arrow(ax0, arrow_y, ax1, arrow_y, colour=RED)
    s.text((ax0 + ax1) / 2, arrow_y - 28, "`https://serve-sim-minio./…`", size=14)
    s.cross((ax0 + ax1) / 2, arrow_y, size=12)
    s.text(fail.cx, fail.y + 240, "503 · Failed to fetch", size=22, weight="bold", colour=RED)
    s.text(fail.cx, fail.y + 276, "the store has no route outside", size=14.5, colour=DIM)
    s.text(fail.cx, fail.y + 298, "the cluster, so no browser can reach it", size=14.5, colour=DIM)

    # ---- how Helm picks the mode -------------------------------------------------
    helm = Box(1200, 510, 460, 250, WHITE, "")
    s.rect(helm)
    s.text(helm.x + 26, helm.y + 36, "Helm sets the mode", size=19, weight="bold", anchor="start")
    lines = (
        ("`proxy`", " when the chart does not route"),
        ("", "the S3 store (no ingress/gateway,"),
        ("", "or no `global.domain`)"),
        ("`presigned`", " otherwise"),
        ("`s3.browserAccess`", " forces it"),
    )
    for i, (code, rest) in enumerate(lines):
        ly = helm.y + 76 + i * 30 + (12 if i >= 3 else 0) + (12 if i >= 4 else 0)
        s.text(helm.x + 26, ly, f"{code}{rest}", size=15.5, anchor="start")
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/indexed-files-proxy"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render the PNG through Playwright."),
) -> None:
    """Write the two-modes schema under --out."""
    write(build_modes(), out, "modes", png=png)


if __name__ == "__main__":
    app()
