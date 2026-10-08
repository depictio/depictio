#!/usr/bin/env python3
"""Diagrams for the data-binding work: `--bind`, the s3_prefix scan, and sharing.

    python dev/diagrams/data_binding_schemas.py --out docs/images/data_binding

PNG rendering needs Playwright (already a dev dependency) and a local Virgil GS;
without the font the SVG still renders in whatever the fallback list finds.
See sketch.py for the drawing primitives.
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
    LIGHT_GREY,
    ORANGE,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    bucket,
    circle,
    ellipse,
    folder,
    magnifier,
    page,
    table_stack,
    terminal,
    write,
)

app = typer.Typer(add_completion=False)


# -- glyphs local to these diagrams -------------------------------------------


def globe(s: Sketch, cx: float, cy: float, r: float) -> None:
    """A circle with a meridian ellipse and an equator: the web."""
    circle(s, cx, cy, r, BLUE)
    ellipse(s, cx, cy, r * 0.42, r, "none", n=20)
    s.line(cx - r, cy, cx + r, cy, amount=0.4, passes=1, width=1.2)


def web_page(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """A browser window whose content is a globe."""
    browser(s, x, y, w, h)
    globe(s, x + w / 2, y + 28 + (h - 28) / 2, min(w, h - 28) * 0.32)


def clock(s: Sketch, cx: float, cy: float, r: float = 14) -> None:
    circle(s, cx, cy, r, YELLOW)
    s.line(cx, cy, cx, cy - r * 0.7, amount=0.3, passes=1, width=1.8)
    s.line(cx, cy, cx + r * 0.5, cy + r * 0.2, amount=0.3, passes=1, width=1.8)


def url_rows(s: Sketch, x: float, y: float, w: float, h: float, n: int = 3) -> None:
    """A manifest page: each row is a small globe and a line, one URL per row."""
    page(s, x, y, w, h, fill=VIOLET)
    for i in range(n):
        ry = y + 26 + i * (h - 34) / n
        circle(s, x + 12, ry, 4, BLUE)
        s.line(x + 20, ry, x + w - 8, ry, colour=GREY, amount=0.4, passes=1, width=1.4)


def folder_tree(s: Sketch, x: float, y: float) -> None:
    """A root folder with two sub-folders hanging off it."""
    folder(s, x + 14, y, 62, 32, GREEN)
    s.line(x + 24, y + 32, x + 24, y + 78, colour=GREY, amount=0.4, passes=1)
    for dy in (44, 78):
        s.line(x + 24, y + dy, x + 36, y + dy, colour=GREY, amount=0.4, passes=1)
        folder(s, x + 38, y + dy - 12, 48, 26, WHITE)


def mini_dashboard(s: Sketch, x: float, y: float, w: float, h: float, bars: list[float]) -> None:
    """A browser window holding a dashboard: two cards over a bar chart."""
    browser(s, x, y, w, h)
    inner = w - 24
    card = (inner - 12) / 2
    s.rect(Box(x + 12, y + 40, card, 28, GREEN, "", ()))
    s.rect(Box(x + 24 + card, y + 40, card, 28, YELLOW, "", ()))
    base = y + h - 14
    bw = inner / len(bars) - 6
    for i, v in enumerate(bars):
        bh = (h - 96) * v
        s.rect(Box(x + 12 + i * (bw + 6), base - bh, bw, bh, BLUE, "", ()))


def code(s: Sketch, x: float, y: float, content: str, *, size: float = 15, anchor: str = "start"):
    s.text(x, y, f"`{content}`", size=size, anchor=anchor)


def chip_box(s: Sketch, x: float, y: float, w: float, h: float, content: str, fill: str = WHITE):
    """The typed flag: a card holding monospace text."""
    box = Box(x, y, w, h, fill, "", ())
    s.rect(box)
    code(s, box.cx, box.cy + 5, content, size=16, anchor="middle")
    return box


def binding_matrix() -> Sketch:
    """What the user has -> what they type -> how it is read.

    The middle column is the only thing the user writes; the scan mode (and so
    the way the data is read) is inferred from its shape.
    """
    s = Sketch(1180, 860, seed=11)
    s.heading(
        60,
        56,
        "Five things you can point at",
        "`--bind TAG=LOCATION` infers the scan mode; a manifest stays explicit",
    )
    top, row_h, gap = 150, 100, 26
    s.text(60, top - 14, "what they have", size=12, anchor="start", colour=GREY)
    s.text(230, top - 14, "what they type", size=12, anchor="start", colour=GREY)
    s.text(680, top - 14, "how it is read", size=12, anchor="start", colour=GREY)
    s.text(1040, top - 14, "result", size=12, anchor="start", colour=GREY)

    chips = [
        "--bind samples=/scratch/run42",
        "--bind sheet=./samplesheet.csv",
        "--bind data=https://host/data.csv",
        "--bind samples=s3://bucket/run42/*.csv",
        "--manifest https://host/manifest.json",
    ]
    for i, content in enumerate(chips):
        y = top + i * (row_h + gap)
        cy = y + row_h / 2
        if i:
            s.line(60, y - gap / 2, 1120, y - gap / 2, colour=LIGHT_GREY, amount=0.3, passes=1)

        # 1. what they have
        if i == 0:
            folder_tree(s, 60, y + 8)
        elif i == 1:
            page(s, 78, y + 8, 60, 78, fill=WHITE)
        elif i == 2:
            web_page(s, 60, y + 8, 100, 78)
        elif i == 3:
            bucket(s, 120, y + 58, 100, 36, YELLOW)
        else:
            url_rows(s, 80, y + 4, 64, 88)

        # 2. what they type
        box = chip_box(s, 200, cy - 26, 400, 52, content, fill=VIOLET if i == 4 else WHITE)
        s.arrow(box.right + 6, cy, 650, cy)

        # 3. how it is read
        mx = 670
        if i == 0:
            folder(s, mx, cy - 16, 44, 30, GREEN)
            for k, dy in enumerate((-28, 0, 28)):
                s.arrow(mx + 48, cy - 2 + dy * 0.4, mx + 110, cy - 2 + dy)
                page(s, mx + 116, cy - 12 + dy, 20, 24)
            label = "scan: recursive, walks the tree"
        elif i == 1:
            s.arrow(mx, cy, mx + 90, cy)
            page(s, mx + 96, cy - 20, 32, 40)
            label = "scan: single, one read"
        elif i == 2:
            s.arrow(mx, cy, mx + 34, cy)
            s.rect(Box(mx + 40, cy - 26, 72, 52, ORANGE, "", ()))
            s.text(mx + 76, cy + 5, "gateway", size=13)
            s.arrow(mx + 116, cy, mx + 160, cy)
            globe(s, mx + 180, cy, 16)
            label = "scan: url, fetched server-side"
        elif i == 3:
            magnifier(s, mx + 16, cy - 8, 15)
            for k in range(3):
                page(s, mx + 70 + k * 34, cy - 20, 26, 36)
            label = "scan: s3_prefix, one listing of the prefix"
        else:
            page(s, mx, cy - 26, 40, 52, fill=VIOLET)
            for k, dy in enumerate((-26, 0, 26)):
                s.arrow(mx + 46, cy - 2 + dy * 0.3, mx + 100, cy + dy)
                globe(s, mx + 116, cy + dy, 9)
            label = "scan: manifest, one fetch per row"
        s.text(mx, y + row_h + 4, label, size=13, anchor="start", colour=DIM)

        # 4. result
        s.arrow(960, cy, 1030, cy)
        table_stack(s, 1040, cy - 14, 64, 34, GREEN)
    s.text(
        60,
        top + 5 * (row_h + gap) + 4,
        "The template author's choice of scan mode no longer dictates where the data lives.",
        size=14,
        anchor="start",
        colour=DIM,
    )
    return s


def before_after() -> Sketch:
    """Why remote data used to force a manifest, and why it no longer does."""
    s = Sketch(1180, 790, seed=5)
    s.heading(
        60,
        56,
        "Remote data without a manifest",
        "the manifest existed largely to compensate for a missing remote listing",
    )

    # -- before -----------------------------------------------------------
    s.text(60, 128, "Before", size=19, anchor="start", weight="bold")
    bucket(s, 130, 230, 130, 90, YELLOW)
    s.arrow(205, 205, 300, 205)
    s.text(252, 190, "write one", size=12, colour=DIM)
    s.text(252, 232, "row per file", size=12, colour=DIM)
    url_rows(s, 310, 150, 84, 108)
    clock(s, 410, 160)
    s.text(430, 138, "by hand", size=13, anchor="start", colour=RED)
    s.cross(352, 292, size=11)
    s.text(374, 297, "toil", size=15, anchor="start", colour=RED)
    s.arrow(402, 205, 520, 205)
    s.text(462, 190, "host it", size=12, colour=DIM)
    s.text(462, 232, "at a URL", size=12, colour=DIM)
    web_page(s, 530, 150, 150, 112)
    s.text(605, 284, "entries must be URLs", size=12, colour=DIM)
    s.arrow(690, 205, 790, 205)
    s.text(740, 190, "fetch", size=12, colour=DIM)
    terminal(s, 800, 150, 320, 110)
    code(s, 812, 200, "$ depictio ingest \\", size=14)
    code(s, 812, 224, "    --manifest <url>", size=14)

    # -- after ------------------------------------------------------------
    s.text(60, 384, "After", size=19, anchor="start", weight="bold")
    bucket(s, 130, 470, 130, 80, YELLOW)
    s.arrow(205, 440, 270, 440)
    chip_box(s, 280, 412, 440, 56, "--bind samples=s3://bucket/run42/*.samples.csv", ORANGE)
    s.arrow(724, 440, 790, 440)
    magnifier(s, 812, 432, 17)
    for k in range(3):
        page(s, 850 + k * 30, 420, 24, 34)
    s.text(868, 482, "one listing", size=12, colour=DIM)
    s.arrow(960, 440, 1010, 440)
    table_stack(s, 1020, 426, 84, 46, GREEN)
    s.text(1068, 510, "data collection", size=13, colour=DIM)

    # -- inset: the * is the join key --------------------------------------
    s.rect(Box(40, 576, 1100, 190, WHITE, "", ()), colour=GREY, dashed=True)
    s.text(60, 606, "The `*` in the glob is also the cross-DC join key", size=15, anchor="start")
    cw = 7.4  # monospace advance at size 14
    rows = [
        (640, "s3://bucket/run42/", ".samples.csv", 60),
        (690, "s3://bucket/qc/", ".qc.csv", 60 + 3 * cw),
    ]
    for y, pre, post, x0 in rows:
        hx = x0 + len(pre) * cw
        s.rect(Box(hx - 3, y - 17, 8 * cw + 6, 26, ORANGE, "", ()), colour=ORANGE)
        code(s, x0, y, pre, size=14)
        code(s, hx, y, "sample_A", size=14)
        code(s, hx + 8 * cw, y, post, size=14)
        s.arrow(hx + 8 * cw + len(post) * cw + 16, y - 5, 600, 662 if y < 660 else 686)
    join = Box(610, 636, 480, 72, VIOLET, "", ())
    s.rect(join)
    s.text(join.cx, join.y + 28, "same id on both sides: they cross-filter", size=14)
    code(s, join.cx, join.y + 54, "depictio_manifest_id = sample_A", size=15, anchor="middle")
    s.text(
        60,
        744,
        "two prefixes, no manifest, no join config",
        size=13,
        anchor="start",
        colour=DIM,
    )
    return s


def sharing_loop() -> Sketch:
    """Sharing a project so a colleague can run it on their own data."""
    s = Sketch(1180, 640, seed=3)
    s.heading(60, 56, "Sharing a project", "same structure, their data, their instance")

    # Row 1: your dashboard -> export -> a folder -> their terminal.
    mini_dashboard(s, 60, 120, 210, 150, [0.5, 0.8, 0.6, 0.9])
    s.text(165, 292, "your dashboard", size=13, colour=DIM)
    s.arrow(280, 190, 410, 190)
    code(s, 345, 172, "depictio template export", size=11, anchor="middle")
    folder(s, 420, 130, 130, 84, GREEN, "")
    s.text(485, 180, "template", size=14)
    page(s, 436, 226, 36, 44)
    page(s, 482, 226, 36, 44)
    code(s, 454, 290, "template.yaml", size=11, anchor="middle")
    code(s, 510, 306, "dashboards/*.yaml", size=11, anchor="middle")

    s.arrow(570, 175, 770, 175)
    s.text(670, 158, "git / zip / chat", size=14, colour=DIM)

    terminal(s, 780, 120, 350, 112)
    code(s, 792, 166, "$ depictio ingest ./their_data \\", size=13)
    code(s, 792, 190, "    --template ./folder \\", size=13)
    code(s, 792, 214, "    --bind samples=s3://their/*.csv", size=13)

    # Their data feeds the terminal from below.
    bucket(s, 950, 440, 120, 80, YELLOW)
    s.arrow(950, 380, 950, 240)
    folder_tree(s, 1050, 366)
    s.arrow(1095, 360, 1095, 240)
    s.text(1022, 360, "or", size=13, colour=DIM)
    s.text(1010, 540, "their data", size=14, colour=DIM)

    # Result: same layout, other numbers.
    s.arrow(800, 240, 690, 366)
    mini_dashboard(s, 470, 370, 210, 150, [0.9, 0.4, 0.7, 0.3])
    s.text(575, 542, "their dashboard: same layout, other data", size=13, colour=DIM)

    s.text(
        60,
        606,
        "No admin on your instance, no server-side install, no manifest required.",
        size=14,
        anchor="start",
        colour=DIM,
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(Path("docs/images/data_binding"), "--out", help="Output path stem"),
    png: bool = typer.Option(True, "--png/--no-png", help="Also render a PNG"),
) -> None:
    write(binding_matrix(), out, "matrix", png=png)
    write(before_after(), out, "no_manifest", png=png)
    write(sharing_loop(), out, "sharing", png=png)


if __name__ == "__main__":
    app()
