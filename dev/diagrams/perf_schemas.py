#!/usr/bin/env python3
"""Render the performance-pass schemas as hand-drawn SVGs (+ PNGs).

Three diagrams, each carrying one idea that is tedious to state in prose:

* ``perf_stages``      — what each stage used to materialise in full, and what
  bounds it now, across ingest → serve → render.
* ``multiqc_prerender`` — who builds a MultiQC figure and who serves it, and
  what the Redis presence marker spares a collection that never opted in.
* ``panel_loading``    — what a 30-panel dashboard actually fetches when it
  opens, before and after the viewport gate.

Usage:
    python dev/diagrams/perf_schemas.py --out docs/images/v0.12/react/schema
    # writes <out>_perf_stages.svg/.png and the other two

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
    ORANGE,
    PINK,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)


# --------------------------------------------------------------------------
# 1. Where the work got bounded.
# --------------------------------------------------------------------------

STAGES_W, STAGES_H = 1280, 700


def build_stages() -> Sketch:
    s = Sketch(STAGES_W, STAGES_H)

    s.heading(
        46,
        52,
        "Where the work got bounded",
        "the same three stages, each asked to carry less of the table at once",
    )

    cols = (210, 545, 880)
    width = 300

    before = [
        Box(
            cols[0],
            140,
            width,
            96,
            PINK,
            "the whole collection",
            ("parsed and concatenated,", "then written in one go"),
        ),
        Box(
            cols[1],
            140,
            width,
            96,
            PINK,
            "the whole frame",
            ("every row and column read,", "then filtered in Python"),
        ),
        Box(
            cols[2],
            140,
            width,
            96,
            PINK,
            "the whole bundle",
            ("plotly, ag-grid, cytoscape", "parsed before first paint"),
        ),
    ]
    stages = [
        Box(
            cols[0],
            296,
            width,
            100,
            BLUE,
            "CLI ingest",
            ("streamed Delta write", "parallel parse · clustering"),
        ),
        Box(
            cols[1],
            296,
            width,
            100,
            YELLOW,
            "API serve",
            ("aggregation pushdown", "links resolved once per fan-out"),
        ),
        Box(
            cols[2],
            296,
            width,
            100,
            VIOLET,
            "Viewer render",
            ("lazy routes and renderers", "viewport-gated mounting"),
        ),
    ]
    after = [
        Box(
            cols[0],
            452,
            width,
            104,
            GREEN,
            "chunks, not the table",
            ("peak RSS bounded, and", "per-phase timing recorded"),
        ),
        Box(
            cols[1],
            452,
            width,
            104,
            GREEN,
            "a bounded slice",
            ("row ceiling, scan-level paging,", "kind-aware reduction"),
        ),
        Box(
            cols[2],
            452,
            width,
            104,
            GREEN,
            "what is on screen",
            ("one route tree, heavy vendors", "as shared async chunks"),
        ),
    ]

    for row in (before, stages, after):
        for b in row:
            s.box(b)

    # The pipeline itself.
    for left, right in zip(stages, stages[1:]):
        s.arrow(left.right + 8, left.cy, right.x - 10, right.cy)

    # What each stage stopped doing, and what replaced it.
    for b, st, a in zip(before, stages, after):
        s.arrow(st.cx, b.bottom + 8, st.cx, st.y - 10, dashed=True, colour=DIM)
        s.arrow(st.cx, st.bottom + 8, st.cx, a.y - 10, dashed=True, colour=DIM)

    s.text(46, 182, "used to", size=15, colour=DIM, anchor="start")
    s.text(46, 202, "materialise", size=15, colour=DIM, anchor="start")
    s.text(46, 352, "the stage", size=15, colour=DIM, anchor="start")
    s.text(46, 498, "now bounded", size=15, colour=DIM, anchor="start")
    s.text(46, 518, "by", size=15, colour=DIM, anchor="start")

    s.text(
        46,
        STAGES_H - 40,
        "every heavier behaviour is opt-in — defaults unchanged",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        STAGES_W - 46,
        STAGES_H - 40,
        "measured end to end by the new benchmark/ harness",
        size=14,
        colour=DIM,
        anchor="end",
    )
    return s


# --------------------------------------------------------------------------
# 2. Who builds a MultiQC figure, and who serves it.
# --------------------------------------------------------------------------

MQC_W, MQC_H = 1400, 800


def build_prerender() -> Sketch:
    s = Sketch(MQC_W, MQC_H)

    s.heading(
        46,
        52,
        "A MultiQC figure: built at ingest, or built on demand",
        "the hand-off only works because both sides hash the cache key identically",
    )

    cli = Box(
        60,
        140,
        300,
        112,
        VIOLET,
        "depictio-cli",
        (
            "already parses every report",
            "for metadata — now builds",
            "the figures in the same pass",
        ),
    )
    s3 = Box(
        470,
        140,
        300,
        96,
        YELLOW,
        "S3 prerender prefix",
        ("s3://{bucket}/{dc_id}/", "prerender/ — gzipped"),
    )
    req = Box(60, 420, 250, 92, BLUE, "a panel asks", ("for one figure,", "light or dark"))
    marker = Box(
        370,
        420,
        290,
        112,
        ORANGE,
        "Redis presence marker",
        (
            "“has figures” for an hour,",
            "“has none” for five minutes",
            "— the CLI never notifies us",
        ),
    )
    probe = Box(
        720,
        420,
        250,
        92,
        YELLOW,
        "probe the prefix",
        ("a prefix listing, not", "an exists() on a key"),
    )
    hit = Box(
        1050,
        330,
        300,
        112,
        GREEN,
        "hit",
        ("warm Redis and the disk", "store, return the figure", "instead of a 202"),
    )
    miss = Box(
        1050,
        560,
        300,
        112,
        PINK,
        "miss",
        ("enqueue the Celery build,", "return 202, the panel polls", "— the path that always was"),
    )

    for b in (cli, s3, req, marker, probe, hit, miss):
        s.box(b)

    s.arrow(cli.right + 8, cli.cy, s3.x - 10, s3.cy)
    s.text(
        60, 286, "opt-in: DEPICTIO_INGEST_MULTIQC_PRERENDER=1", size=14, colour=DIM, anchor="start"
    )
    s.text(
        60,
        306,
        "fresh ingests only — on an append the local files cannot reproduce the aggregation",
        size=14,
        colour=DIM,
        anchor="start",
    )

    # The figure is already sitting there when the request arrives.
    s.arrow(s3.cx + 40, s3.bottom + 8, probe.cx - 30, probe.y - 10, dashed=True, colour=DIM)

    s.arrow(req.right + 8, req.cy, marker.x - 10, marker.cy)
    s.arrow(marker.right + 8, marker.cy, probe.x - 10, probe.cy)
    s.arrow(probe.right + 8, probe.cy - 18, hit.x - 10, hit.cy + 20)
    s.arrow(probe.right + 8, probe.cy + 18, miss.x - 10, miss.cy - 30)

    # A collection that never opted in never pays for the probe.
    s.curve(
        [
            (marker.cx, marker.bottom + 8),
            (marker.cx, 730),
            (miss.cx - 60, 730),
            (miss.cx - 60, miss.bottom + 10),
        ]
    )
    s.text(
        marker.cx + 16,
        710,
        "“has none” → skip the probe entirely: one Redis lookup, no S3 round-trip per panel",
        size=14,
        colour=DIM,
        anchor="start",
    )

    s.text(
        46,
        MQC_H - 44,
        "figure construction, the Plotly Mantine templates and the key hash now live in one shared module,",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        46,
        MQC_H - 24,
        "with the former API copies kept as re-exports and a golden-value test pinning the key.",
        size=14,
        colour=DIM,
        anchor="start",
    )
    return s


# --------------------------------------------------------------------------
# 3. What a dashboard actually fetches when it opens.
# --------------------------------------------------------------------------

PANEL_W, PANEL_H = 1300, 700

CELL_W, CELL_H = 52, 32
GAP_X, GAP_Y = 12, 10
COLS, ROWS = 5, 6
ABOVE_FOLD = 10  # the two rows a viewport actually shows


def _grid(s: Sketch, ox: float, oy: float, fetching: int) -> float:
    """Draw ROWS×COLS panels, the first ``fetching`` of them mid-fetch.

    An idle panel is dashed, so "waiting to be scrolled to" reads differently
    from "fetching" at a glance. Returns the y of the grid's bottom edge.
    """
    for i in range(ROWS * COLS):
        row, col = divmod(i, COLS)
        x = ox + col * (CELL_W + GAP_X)
        y = oy + row * (CELL_H + GAP_Y)
        busy = i < fetching
        s.rect(
            Box(x, y, CELL_W, CELL_H, ORANGE if busy else WHITE, ""),
            colour=DIM,
            dashed=not busy,
        )

    fold = oy + 2 * (CELL_H + GAP_Y) - GAP_Y / 2
    grid_w = COLS * CELL_W + (COLS - 1) * GAP_X
    s.line(ox - 22, fold, ox + grid_w + 22, fold, dashed=True, colour=GREY, width=1.4, passes=1)
    s.text(ox - 30, fold + 5, "fold", size=13, colour=DIM, anchor="end")
    return oy + ROWS * CELL_H + (ROWS - 1) * GAP_Y


def build_panel_loading() -> Sketch:
    s = Sketch(PANEL_W, PANEL_H)

    s.heading(
        46,
        52,
        "Opening a 30-panel dashboard",
        "an orange panel is one that has started fetching",
    )

    left_x, right_x = 130, 760
    grid_top = 168

    s.text(left_x, 140, "before", size=19, weight="bold", anchor="start")
    s.text(right_x, 140, "after", size=19, weight="bold", anchor="start")

    bottom = _grid(s, left_x, grid_top, 21)
    _grid(s, right_x, grid_top, ABOVE_FOLD)

    caption_y = bottom + 44
    for i, line in enumerate(
        (
            "~21 of 30 fetched at mount.",
            "The in-view check measured getBoundingClientRect()",
            "before react-grid-layout had positioned anything, so",
            "every panel sat at the grid origin and read as visible.",
        )
    ):
        s.text(left_x, caption_y + i * 22, line, size=15 if i else 16, colour=DIM, anchor="start")
    for i, line in enumerate(
        (
            "10 fetch; the rest wait to be scrolled to.",
            "IntersectionObserver is now the authority, with the",
            "rect check demoted to a delayed fallback for",
            "environments that throttle the first callback.",
        )
    ):
        s.text(right_x, caption_y + i * 22, line, size=15 if i else 16, colour=DIM, anchor="start")

    bar_y = caption_y + 118
    s.box(
        Box(
            left_x,
            bar_y,
            340,
            92,
            PINK,
            "a full-width bar",
            ("counted all 30, but only 4 ever", "start → pinned near empty"),
        )
    )
    s.box(
        Box(
            right_x,
            bar_y,
            340,
            92,
            GREEN,
            "a ring and a count",
            ("counts what reached the viewport", "→ completes, then hides"),
        )
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"),
        "--out",
        help="Output prefix; '_<name>.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the three performance schemas under --out."""
    write(build_stages(), out, "perf_stages", png=png)
    write(build_prerender(), out, "multiqc_prerender", png=png)
    write(build_panel_loading(), out, "panel_loading", png=png)


if __name__ == "__main__":
    app()
