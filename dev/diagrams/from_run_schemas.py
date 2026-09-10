#!/usr/bin/env python3
"""Diagrams for creating a project from a run folder on S3.

    python dev/diagrams/from_run_schemas.py --out docs/images/from_run

PNG rendering needs Playwright (already a dev dependency) and a local Virgil GS;
without the font the SVG still renders in whatever the fallback list finds.
See sketch.py for the drawing primitives; the glyphs below (browser window,
bucket, magnifier, folder, hourglass, tick) are composed from them.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    DIM,
    GREEN,
    GREY,
    INK,
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

GREEN_INK = "#2f9e44"
ORANGE_INK = "#e8590c"
LIGHT_GREY = "#f1f3f5"


# ── glyphs ───────────────────────────────────────────────────────────────────


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


def tick(s: Sketch, cx: float, cy: float, *, size: float = 8, colour: str = GREEN_INK) -> None:
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


# ── figure 1: the flow ───────────────────────────────────────────────────────


def run_folder_flow() -> Sketch:
    """Browser on the left, bucket on the right, workers underneath.

    The preview is the loop at the top: the listing is read once, the browser
    sees what every collection will get, and only then does Create fan out.
    """
    s = Sketch(1180, 760, seed=17)
    s.heading(
        60,
        56,
        "From a run folder",
        "a template, an s3:// prefix, and the listing of that prefix replaces the filesystem",
    )

    # The browser, with the tab as the user sees it.
    win = browser(s, 60, 120, 380, 330)
    s.text(
        win.x + 70,
        win.y + 18,
        "Create project  ·  From a run folder",
        size=12,
        anchor="start",
        colour=DIM,
    )
    field(s, win.x + 18, win.y + 40, 344, "Template", "nf-core/ampliseq/latest")
    field(
        s,
        win.x + 18,
        win.y + 92,
        344,
        "Run folder",
        "s3://nf-core-awsmegatests/ampliseq/results-3d5c7e…",
    )
    table_bottom = mini_table(
        s,
        win.x + 18,
        win.y + 150,
        344,
        [
            ("samplesheet", "1", "ok"),
            ("metadata", "1", "ok"),
            ("multiqc_general_stats", "1", "ok"),
            ("asv_table", "1", "ok"),
            ("phylogenetic_tree", "0", "skipped"),
        ],
    )
    create = button(s, win.x + 18, table_bottom + 8, 120, "Create", enabled=True)
    s.text(
        create.right + 12,
        create.cy + 5,
        "enabled: something matched",
        size=11,
        anchor="start",
        colour=DIM,
    )

    # The bucket, and the one listing that answers every question.
    s.text(1000, 128, "the listing is the filesystem:", size=13, colour=DIM)
    s.text(1000, 146, "exists, glob, match, runs, read", size=13, colour=DIM)
    bucket(s, 980, 210, 220, 150, YELLOW)
    magnifier(s, 848, 232, 30)
    s.text(
        1120,
        396,
        "s3://nf-core-awsmegatests/ampliseq/results-3d5c7e…/",
        size=12,
        anchor="end",
        colour=DIM,
    )
    s.text(1120, 414, "2 900 objects, listed once (3 calls)", size=12, anchor="end", colour=DIM)

    # Request out, preview back.
    s.arrow(win.right + 4, 180, 850, 180)
    s.text(645, 168, "POST projects/from_run, dry run", size=13, colour=DIM)
    s.curve([(870, 262), (760, 276), (620, 276), (win.right + 8, 276)], colour=INK)
    s.arrow(win.right + 40, 276, win.right + 6, 276)
    s.text(
        645,
        300,
        "one row per collection: files found, missing sources, status",
        size=13,
        colour=DIM,
    )

    # Create: fan out to workers, the run document keeps score, the browser polls it.
    s.arrow(create.cx, create.bottom + 4, create.cx, 520)
    s.text(
        create.cx + 14,
        500,
        "Create: one Celery task per collection",
        size=12,
        anchor="start",
        colour=DIM,
    )
    s.line(create.cx, 520, 1060, 520, amount=1.0)
    chips = []
    for i, (label, fill) in enumerate(
        (
            ("samplesheet", ORANGE),
            ("metadata", ORANGE),
            ("taxonomy_rel_abundance", ORANGE),
            ("taxonomy_heatmap", YELLOW),
            ("embedding_pcoa", YELLOW),
        )
    ):
        x = 220 + i * 176
        w = 160
        s.arrow(x + w / 2, 520, x + w / 2, 546)
        chips.append(chip(s, x, 550, w, label, fill=fill))
    hourglass(s, chips[3].x + 84, chips[3].y - 14)
    s.text(
        chips[3].cx + 30,
        chips[3].y - 6,
        "waits for its dc_ref",
        size=11,
        anchor="start",
        colour=DIM,
    )
    hourglass(s, chips[4].x + 84, chips[4].y - 14)

    # Where it lands: tables on S3, steps in Mongo. The run document sits under
    # the browser so the poll is one straight dashed line.
    table_stack(s, 600, 660, 110, 46, GREEN)
    s.text(655, 730, "Delta tables on S3", size=12, colour=DIM)
    for c in chips:
        s.arrow(c.cx, c.bottom, 655 + (c.cx - 655) * 0.12, 652)

    page(s, 60, 640, 74, 78, fill=VIOLET)
    for i, colour in enumerate((GREEN_INK, GREEN_INK, GREEN_INK, "#fab005", GREY)):
        dot(s, 72, 656 + i * 12, colour)
    s.text(
        60,
        738,
        "IngestionRun in Mongo: one step per collection, success / failed / skipped",
        size=12,
        anchor="start",
        colour=DIM,
    )
    s.arrow(chips[0].x + 30, chips[0].bottom, 140, 660)
    s.text(200, 704, "each step, as it finishes", size=11, anchor="start", colour=DIM)
    s.arrow(97, 636, 97, win.bottom + 6, dashed=True)
    s.text(106, 600, "poll by run id", size=12, anchor="start", colour=DIM)
    return s


# ── figure 2: dependency order as a timeline ─────────────────────────────────


def dependency_order() -> Sketch:
    """Two timelines of the same five collections: unordered, then ordered."""
    s = Sketch(1180, 750, seed=23)
    s.heading(
        60,
        56,
        "Ingest in dependency order",
        "a recipe that reads another collection's table waits for that collection's step to finish",
    )

    t0 = 340
    rows = [
        ("metadata", "url, from the listing"),
        ("taxonomy_composition", "recipe, from the listing"),
        ("taxonomy_rel_abundance", "reads metadata (optional)"),
        ("taxonomy_heatmap", "reads taxonomy_rel_abundance"),
        ("embedding_pcoa", "reads taxonomy_heatmap"),
    ]

    def panel(top: float, title: str, colour: str) -> list[float]:
        s.text(60, top, title, size=17, anchor="start", weight="bold", colour=colour)
        ys = []
        for i, (name, note) in enumerate(rows):
            y = top + 30 + i * 44
            s.text(60, y + 15, name, size=13, anchor="start")
            s.text(60, y + 30, note, size=10, anchor="start", colour=GREY)
            s.line(t0, y + 12, 1120, y + 12, colour=LIGHT_GREY, amount=0.2, passes=1, width=1)
            ys.append(y)
        return ys

    def bar(y: float, x1: float, x2: float, fill: str) -> None:
        s.rect(Box(x1, y, x2 - x1, 24, fill, "", ()))

    def waiting(y: float, x1: float, x2: float) -> None:
        s.line(x1, y + 12, x2 - 4, y + 12, dashed=True, colour=GREY, amount=0.4, passes=1)
        hourglass(s, x1 + 14, y + 12, size=7)

    # -- unordered --------------------------------------------------------
    ys = panel(110, "Unordered fan-out", RED)
    bar(ys[0], t0, 560, YELLOW)
    tick(s, 578, ys[0] + 12)
    bar(ys[1], t0, 640, YELLOW)
    tick(s, 658, ys[1] + 12)
    bar(ys[2], t0, 500, GREEN)
    warning(s, 522, ys[2] + 12)
    s.text(
        542,
        ys[2] + 17,
        "metadata not there yet: ungrouped, silently",
        size=12,
        anchor="start",
        colour=ORANGE_INK,
    )
    bar(ys[3], t0, 380, PINK)
    s.cross(398, ys[3] + 12, size=8)
    s.text(
        418,
        ys[3] + 17,
        "Failed to read dc_ref taxonomy_rel_abundance: table not written yet",
        size=12,
        anchor="start",
        colour=RED,
    )
    bar(ys[4], t0, 380, PINK)
    s.cross(398, ys[4] + 12, size=8)
    s.text(418, ys[4] + 17, "same, one level further", size=12, anchor="start", colour=RED)

    # -- ordered ----------------------------------------------------------
    ys = panel(390, "In dependency order", GREEN_INK)
    bar(ys[0], t0, 560, YELLOW)
    tick(s, 578, ys[0] + 12)
    bar(ys[1], t0, 640, YELLOW)
    tick(s, 658, ys[1] + 12)
    waiting(ys[2], t0, 560)
    bar(ys[2], 560, 720, GREEN)
    tick(s, 738, ys[2] + 12)
    s.text(758, ys[2] + 17, "grouped by habitat", size=12, anchor="start", colour=DIM)
    waiting(ys[3], t0, 720)
    bar(ys[3], 720, 860, GREEN)
    tick(s, 878, ys[3] + 12)
    waiting(ys[4], t0, 860)
    bar(ys[4], 860, 980, GREEN)
    tick(s, 998, ys[4] + 12)

    # Time axis and legend.
    axis_y = 390 + 30 + 5 * 44 + 6
    s.arrow(t0, axis_y, 1120, axis_y, colour=DIM)
    s.text(1120, axis_y + 18, "time", size=12, anchor="end", colour=DIM)
    hourglass(s, 72, axis_y + 40, size=7)
    s.text(
        90,
        axis_y + 45,
        "queued: the task carries depends_on and retries every 10 s until each one is terminal",
        size=12,
        anchor="start",
        colour=DIM,
    )
    s.text(
        60,
        axis_y + 70,
        "The CLI ingests in template order and never raced; the fan-out now restores that parity.",
        size=12,
        anchor="start",
        colour=DIM,
    )
    return s


# ── figure 3: the preview at the wrong level ─────────────────────────────────


def wrong_level() -> Sketch:
    """The same template pointed one level too high: the preview says so first."""
    s = Sketch(1180, 520, seed=31)
    s.heading(
        60,
        56,
        "The preview runs before anything exists",
        "the same template, two prefixes: zeros on every row mean the wrong level, not an empty run",
    )

    def tree(
        x: float, top: float, root: str, children: list[tuple[str, bool | None]], root_fill: str
    ) -> None:
        folder(s, x, top, 230, 54, root_fill, root)
        trunk_x = x + 24
        s.line(
            trunk_x,
            top + 54,
            trunk_x,
            top + 54 + len(children) * 46 - 22,
            colour=GREY,
            amount=0.4,
            passes=1,
        )
        for i, (name, expected) in enumerate(children):
            y = top + 70 + i * 46
            s.line(trunk_x, y + 12, trunk_x + 20, y + 12, colour=GREY, amount=0.4, passes=1)
            folder(s, trunk_x + 24, y - 6, 150, 34, WHITE, name)
            if expected is True:
                tick(s, trunk_x + 196, y + 12)
            elif expected is False:
                s.cross(trunk_x + 196, y + 12, size=7)

    def expects(x: float, top: float, lines: list[tuple[str, bool]]) -> None:
        s.text(x, top, "the template expects", size=12, anchor="start", colour=GREY)
        for i, (line, found) in enumerate(lines):
            y = top + 22 + i * 22
            s.text(x + 22, y + 5, line, size=12, anchor="start", colour=INK if found else DIM)
            if found:
                tick(s, x + 6, y, size=6)
            else:
                s.cross(x + 6, y, size=5)

    # -- right level ------------------------------------------------------
    s.text(60, 118, "results-3d5c7e…/", size=15, anchor="start", weight="bold")
    s.text(60, 136, "the run folder itself", size=12, anchor="start", colour=DIM)
    tree(
        60,
        150,
        "results-3d5c7e…",
        [("input", True), ("pipeline_info", True), ("qiime2", True), ("multiqc", True)],
        GREEN,
    )
    expects(
        330,
        160,
        [
            ("input/*sheet*.tsv", True),
            ("pipeline_info/params*.json", True),
            ("qiime2/barplot/level-*.csv", True),
            ("multiqc/multiqc_data/*.parquet", True),
        ],
    )
    bottom = mini_table(
        s,
        330,
        280,
        250,
        [
            ("samplesheet", "1", "ok"),
            ("metadata", "1", "ok"),
            ("asv_table", "1", "ok"),
            ("multiqc_general_stats", "1", "ok"),
        ],
    )
    button(s, 330, bottom + 10, 110, "Create", enabled=True)

    # -- one level up -----------------------------------------------------
    s.text(640, 118, "ampliseq/", size=15, anchor="start", weight="bold")
    s.text(640, 136, "one level too high: the folder of runs", size=12, anchor="start", colour=DIM)
    tree(
        640,
        150,
        "ampliseq",
        [
            ("results-3d5c7e…", None),
            ("results-1e76f1…", None),
            ("results-8a02c4…", None),
            ("results-…", None),
        ],
        PINK,
    )
    expects(
        910,
        160,
        [
            ("input/*sheet*.tsv", False),
            ("pipeline_info/params*.json", False),
            ("qiime2/barplot/level-*.csv", False),
            ("multiqc/multiqc_data/*.parquet", False),
        ],
    )
    bottom = mini_table(
        s,
        910,
        280,
        250,
        [
            ("samplesheet", "0", "empty"),
            ("metadata", "0", "empty"),
            ("asv_table", "0", "empty"),
            ("multiqc_general_stats", "0", "empty"),
        ],
    )
    off = button(s, 910, bottom + 10, 110, "Create", enabled=False)
    s.text(
        off.right + 10, off.cy + 5, "disabled: nothing matched", size=11, anchor="start", colour=RED
    )

    s.text(
        60,
        496,
        "Locally the wrong level ingested nothing and reported success. Here it cannot get past the preview.",
        size=14,
        anchor="start",
        colour=DIM,
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(Path("docs/images/from_run"), "--out", help="Output path stem"),
    png: bool = typer.Option(True, "--png/--no-png", help="Also render a PNG"),
) -> None:
    write(run_folder_flow(), out, "flow", png=png)
    write(dependency_order(), out, "dependency_order", png=png)
    write(wrong_level(), out, "wrong_level", png=png)


if __name__ == "__main__":
    app()
