#!/usr/bin/env python3
"""Diagrams for the Project Builder.

    python dev/diagrams/project_builder_schemas.py --out docs/images/project_builder

``--out`` is a directory here (it is created if missing); the files are
``<out>/project_builder_<name>.svg`` and ``.png``:

* ``placement`` — one builder, two doors: the same page, core and template
  format whether the builder runs inside a Depictio server or stands alone.
* ``one_rule``  — what you see is what gets ingested: the match panel and the
  scan resolve one draft through the same function, on a folder and on an
  ``s3://`` prefix alike.

PNG rendering needs Playwright (already a dev dependency); the PNG uses the Virgil
font shipped in ``depictio/viewer/src/assets/fonts`` (see sketch.py). Shared
drawing primitives and glyphs live in sketch.py.
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
    WHITE,
    YELLOW,
    Box,
    Sketch,
    bucket,
    dot,
    folder,
    page,
    write,
)

app = typer.Typer(add_completion=False)

# What both doors share (the page, the core, the template format) is the one
# thing drawn in this stronger violet; nothing else on the figure uses it.
SHARED = "#d0bfff"


# -- local glyphs --------------------------------------------------------------


def node(
    s: Sketch, box: Box, *, size: float = 18, sub: str = "", colour: str = INK, dashed: bool = False
) -> None:
    """A box whose title (and optional one-line caption) is centred vertically."""
    s.rect(box, dashed=dashed)
    if sub:
        s.text(box.cx, box.cy - 2, box.title, size=size, weight="bold", colour=colour)
        s.text(box.cx, box.cy + 19, sub, size=14, colour=DIM)
    else:
        s.text(box.cx, box.cy + size * 0.33, box.title, size=size, weight="bold", colour=colour)


def door_badge(s: Sketch, x: float, y: float, label: str) -> None:
    """A tab straddling a box's top edge: which door this is."""
    s.rect(Box(x, y, 68, 24, ORANGE, ""))
    s.text(x + 34, y + 17, label, size=14, weight="bold")


def window(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    url: str = "",
    title: str,
    caption: str,
) -> None:
    """The builder page: a browser window in the shared colour."""
    s.rect(Box(x, y, w, h, SHARED, ""))
    s.line(x, y + 28, x + w, y + 28, amount=0.8, passes=1)
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        dot(s, x + 16 + i * 16, y + 14, colour)
    if url:
        s.text(x + 72, y + 19, f"`{url}`", size=14, anchor="start", colour=DIM)
    body = y + 28 + (h - 28) / 2
    s.text(x + w / 2, body - 4, title, size=19, weight="bold")
    s.text(x + w / 2, body + 20, caption, size=14, colour=DIM)


def equals(s: Sketch, cx: float, cy: float) -> None:
    """An equals sign in a white disc: "this is the same list as that"."""
    s.dot(cx, cy, 15, fill=WHITE, width=1.6)
    s.line(cx - 7, cy - 4, cx + 7, cy - 4, amount=0.3, passes=1, width=2.2)
    s.line(cx - 7, cy + 4, cx + 7, cy + 4, amount=0.3, passes=1, width=2.2)


def lane_mark(s: Sketch, cx: float, cy: float, letter: str) -> None:
    s.dot(cx, cy, 13, fill=WHITE, width=1.5)
    s.text(cx, cy + 5, letter, size=15, weight="bold")


# ── figure 1: one builder, two doors ─────────────────────────────────────────

PLACE_W, PLACE_H = 1100, 900


def build_placement() -> Sketch:
    """Two doors over one core; the page, the core and the template are shared.

    Top door: the SPA page in a Depictio server. Bottom door: the same page,
    served by ``depictio project-builder`` with no server at all. Both reach
    the one core in the middle, which reads the user's data on the left; what
    comes out on the right is the template, handed to a server or kept as a file.
    """
    s = Sketch(PLACE_W, PLACE_H, seed=41)
    s.heading(
        40,
        52,
        "One builder, two doors",
        "with a server or without one, the page, the core and the template are the same",
    )
    s.rect(Box(800, 36, 26, 20, SHARED, ""))
    s.text(836, 52, "shared by both doors", size=15, anchor="start")

    # -- the user's data (left, level with the core) -----------------------------
    s.text(100, 372, "your data", size=15, colour=DIM, weight="bold")
    folder(s, 40, 390, 120, 72, YELLOW)
    s.text(100, 488, "a folder", size=15)
    s.text(100, 508, "on this computer", size=15)
    bucket(s, 100, 604, 130, 64, YELLOW)
    s.text(100, 698, "an `s3://` prefix", size=15)

    # -- door 1: the page inside a Depictio server -----------------------------
    server = Box(
        300, 130, 330, 235, BLUE, "Depictio server", ("`depictio local up` or a shared server",)
    )
    s.box(server)
    door_badge(s, server.x + 14, server.y - 12, "door 1")
    window(
        s,
        330,
        200,
        270,
        143,
        url="/projects/build",
        title="Project Builder",
        caption="browse, pick, preview",
    )

    s.text(30, 146, "two ways in", size=14, colour=DIM, anchor="start")
    enter_create = Box(30, 158, 230, 50, YELLOW, "")
    s.rect(enter_create)
    s.text(enter_create.cx, enter_create.cy + 5, "Create → Advanced project", size=14)
    enter_run = Box(30, 240, 230, 70, YELLOW, "")
    s.rect(enter_run)
    s.text(enter_run.cx, enter_run.y + 28, "Run folder: no template fits", size=13)
    s.text(enter_run.cx, enter_run.y + 50, "→ Define collections yourself", size=13)
    s.arrow(enter_create.right + 2, enter_create.cy, 326, 240)
    s.arrow(enter_run.right + 2, enter_run.cy, 326, 288)

    # -- the core, between the doors -----------------------------------------------
    core = Box(
        300,
        452,
        330,
        100,
        SHARED,
        "Project Builder core",
        ("over `DataRoot`", "a folder or an `s3://` prefix"),
    )
    s.box(core)

    s.arrow(560, 346, 560, 448)
    s.text(544, 388, "`POST /projects/builder/*`", size=14, anchor="end")
    s.text(544, 410, "tree · suggest · match · template", size=13, colour=DIM, anchor="end")

    s.arrow(166, 424, 296, 482)
    s.arrow(176, 596, 296, 530)

    # -- door 1 out: the page posts the template, the server ingests ---------------
    s.line(602, 215, 745, 215)
    s.arrow(745, 215, 745, 288)
    s.text(762, 241, "`POST /projects/from_run`", size=14, anchor="start")
    page(s, 764, 252, 22, 28, fill=SHARED)
    s.text(796, 272, "`{template}`", size=14, anchor="start")
    node(s, Box(700, 292, 370, 58, ORANGE, "project + Celery ingestion"))
    s.arrow(745, 352, 745, 392)
    node(s, Box(700, 396, 370, 58, GREEN, "dashboards (editor)"))

    # -- door 2: the same page, standalone ----------------------------------------------
    cli = Box(300, 610, 330, 200, LIGHT_GREY, "")
    s.rect(cli)
    s.line(cli.x, cli.y + 26, cli.right, cli.y + 26, amount=0.8, passes=1)
    # Window controls on the right, which leaves the corner to the door tab.
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        dot(s, cli.right - 44 + i * 14, cli.y + 13, colour)
    s.text(cli.x + 16, cli.y + 55, "`$ depictio project-builder <dir>`", size=16, anchor="start")
    s.text(cli.x + 16, cli.y + 84, "no MongoDB · Redis · S3", size=14, colour=DIM, anchor="start")
    window(s, 330, 706, 270, 92, title="same page", caption="standalone mode")
    door_badge(s, cli.x + 14, cli.y - 12, "door 2")

    s.arrow(560, 608, 560, 556)
    s.text(544, 588, "same `/projects/builder/*` routes", size=13, colour=DIM, anchor="end")

    # -- door 2 out: a file any server can ingest ----------------------------------
    s.arrow(cli.right + 2, 662, 718, 662)
    s.text(676, 650, "writes", size=14, colour=DIM)
    page(s, 722, 636, 46, 56, fill=SHARED)
    s.text(786, 656, "`.depictio/template/template.yaml`", size=14, anchor="start")
    s.text(786, 680, "the same format the page posts", size=13, colour=DIM, anchor="start")
    s.arrow(745, 696, 745, 726)
    ingest = Box(700, 730, 370, 56, LIGHT_GREY, "")
    s.rect(ingest)
    s.text(ingest.cx, ingest.cy + 6, "`depictio ingest <dir | s3://…> --template …`", size=14.5)
    s.arrow(745, 790, 745, 826)
    node(s, Box(700, 830, 370, 50, BLUE, "any Depictio server"))
    return s


# ── figure 2: one rule ────────────────────────────────────────────────────────

RULE_W, RULE_H = 1040, 800


def build_one_rule() -> Sketch:
    """One draft, two data roots, one function behind the preview and the scan."""
    s = Sketch(RULE_W, RULE_H, seed=53)
    s.heading(
        40,
        52,
        "What you see is what gets ingested",
        "one draft, two data roots, and a preview that runs the scan itself",
    )

    left, right = 40, 580
    col_w = 420
    left_c, right_c = left + col_w / 2, right + col_w / 2

    # -- the draft, in the builder -----------------------------------------------
    top, card_h = 112, 180
    draft = Box(left, top, col_w, card_h, WHITE, "")
    s.rect(draft)
    s.text(draft.cx, top + 29, "data collection draft", size=18, weight="bold")
    for i, (label, value) in enumerate(
        (("tag", "quant"), ("regex", r"^star/[^/]+/quant\.tsv$"), ("`max_depth`", "2"))
    ):
        y = top + 50 + i * 42
        s.text(left + 24, y + 20, label, size=15, colour=DIM, anchor="start")
        field = Box(left + 130, y, 270, 29, LIGHT_GREY, "")
        s.rect(field, colour=GREY)
        s.text(field.x + 10, y + 20, f"`{value}`", size=15, anchor="start")

    # -- the template line it becomes ----------------------------------------------
    template = Box(right, top, col_w, card_h, SHARED, "")
    s.rect(template)
    s.text(template.cx, top + 29, "template", size=18, weight="bold")
    for i, line in enumerate(
        (
            "locations: {DATA_ROOT}",
            "scan: recursive",
            r"pattern: ^star/[^/]+/quant\.tsv$",
            "max_depth: 2",
        )
    ):
        s.text(template.x + 28, top + 66 + i * 28, f"`{line}`", size=15, anchor="start")

    s.arrow(draft.right + 4, top + card_h / 2, template.x - 4, top + card_h / 2)
    s.text((draft.right + template.x) / 2, top + card_h / 2 - 16, "becomes", size=15, colour=DIM)

    # -- the same line, bound to two data roots ----------------------------------------
    fork_y = 328
    s.line(right_c, template.bottom + 2, right_c, fork_y)
    s.line(left_c, fork_y, right_c, fork_y)
    s.text(
        (left_c + right_c) / 2,
        fork_y - 12,
        "the same line, bound to two data roots",
        size=14,
        colour=DIM,
    )
    root_y, root_h = 366, 66
    scan_y, scan_h = 478, 88
    s.arrow(left_c, fork_y, left_c, root_y - 3)
    s.arrow(right_c, fork_y, right_c, root_y - 3)

    lanes = (
        (
            left,
            left_c,
            "a",
            BLUE,
            "`DATA_ROOT` = `/data/run42`",
            "a folder",
            "as written",
            "recursive scan",
            ("`iter_run_files` + bounds", "+ `basename-then-path` regex"),
        ),
        (
            right,
            right_c,
            "b",
            YELLOW,
            "`DATA_ROOT` = `s3://bucket/run42`",
            "an `s3://` prefix",
            "rewritten to `s3_prefix`",
            "`s3_prefix` scan",
            ("regex kept verbatim", "bounds not applied"),
        ),
    )
    scans: list[Box] = []
    for x, cx, letter, fill, root, root_sub, arrow_label, scan_title, scan_lines in lanes:
        chip = Box(x, root_y, col_w, root_h, fill, "")
        s.rect(chip)
        lane_mark(s, x + 28, chip.cy, letter)
        s.text(chip.cx + 10, root_y + 28, root, size=16)
        s.text(chip.cx + 10, root_y + 51, root_sub, size=14, colour=DIM)
        s.arrow(cx, chip.bottom, cx, scan_y - 3)
        s.text(cx + 16, root_y + root_h + 30, arrow_label, size=14, colour=DIM, anchor="start")
        scan = Box(x, scan_y, col_w, scan_h, WHITE, scan_title, scan_lines)
        s.box(scan)
        scans.append(scan)

    # -- the match panel: the same function, asked the same question -----------------
    panel = Box(140, 652, 760, 104, GREEN, "")
    link_y = (scan_y + scan_h + panel.y) / 2
    for scan in scans:
        s.line(scan.cx, scan.bottom, scan.cx, panel.y, dashed=True, colour=INK)
        equals(s, scan.cx, link_y)
    s.rect(panel)
    s.text(panel.cx, panel.y + 30, "Match panel  =  `scan_dc_hits()`", size=19, weight="bold")
    s.text(panel.cx, panel.y + 61, "the preview lists exactly the files the scan picks", size=17)
    s.text(panel.cx, panel.y + 87, "guarded by `test_scan_parity.py`", size=14, colour=DIM)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/project_builder"),
        "--out",
        help="Output directory; project_builder_<name>.svg and .png are written inside it.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also render PNGs through Playwright."),
) -> None:
    """Write the placement and one-rule schemas under --out."""
    stem = out / "project_builder"
    write(build_placement(), stem, "placement", png=png)
    write(build_one_rule(), stem, "one_rule", png=png)


if __name__ == "__main__":
    app()
