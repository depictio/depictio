#!/usr/bin/env python3
"""Render the filter-persistence schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, each carrying one idea that is tedious to state in prose:

* ``one_array``   - the five filter levels converge on a single
  ``InteractiveFilter[]``, so persisting that one array captures the whole
  view; the three places it lives and when each is read back.
* ``mount_merge`` - who wins at mount: the synchronous three-source merge
  that makes the first fetch already filtered, and the async server
  reconcile with the four gates that keep it from clobbering the user.

Usage:
    python dev/diagrams/filter_persistence.py --out docs/images/filter_persistence
    # writes <out>_one_array.svg/.png and <out>_mount_merge.svg/.png

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
    ORANGE,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)


# --------------------------------------------------------------------------
# 1. One array, three homes.
# --------------------------------------------------------------------------

ARRAY_W, ARRAY_H = 1340, 660

LEVELS = (
    ("Filter panel", "Select, slider, switch, text"),
    ("Scatter box / lasso", "plotly selection"),
    ("Table rows", "checkbox selection"),
    ("Map selection", "grid or floating panel"),
    ("Image selection", "gallery picks"),
)

HOMES = (
    (
        BLUE,
        "localStorage",
        (
            "per-dashboard key, written on every change",
            "restores instantly at next visit, same browser",
            '"Remember filters" pin, per dashboard, default ON',
        ),
    ),
    (
        GREEN,
        "server, per user",
        (
            "dashboard_filter_states: one doc per (user, dashboard)",
            "PUT debounced 800 ms, pagehide keepalive flush",
            "roams across browsers; viewer permission suffices",
        ),
    ),
    (
        YELLOW,
        "#filters= share URL",
        (
            "readable v2 grammar, opaque v1 fallback",
            "consumed once on open, then stripped",
            "8k cap; anyone with the link sees the view",
        ),
    ),
)


def build_one_array() -> Sketch:
    s = Sketch(ARRAY_W, ARRAY_H)
    s.heading(
        40,
        52,
        "One array, three homes",
        "every filter level converges on the same InteractiveFilter[],"
        " so persisting that one array captures the whole view",
    )

    level_boxes = []
    for i, (title, sub) in enumerate(LEVELS):
        b = Box(50, 150 + i * 96, 240, 66, VIOLET, title, (sub,))
        s.box(b)
        level_boxes.append(b)

    centre = Box(
        450,
        314,
        300,
        138,
        WHITE,
        "InteractiveFilter[]",
        ("one array in App.tsx", "merged per (index, source)", "chart picks coexist with sliders"),
    )
    s.box(centre)

    for b in level_boxes:
        s.arrow(b.right + 6, b.cy, centre.x - 8, centre.cy + (b.cy - centre.cy) * 0.35)

    home_boxes = []
    for i, (fill, title, lines) in enumerate(HOMES):
        b = Box(880, 138 + i * 156, 420, 118, fill, title, lines)
        s.box(b)
        home_boxes.append(b)

    for b in home_boxes:
        s.arrow(centre.right + 8, centre.cy + (b.cy - centre.cy) * 0.35, b.x - 8, b.cy)

    s.text(
        815,
        ARRAY_H - 28,
        "reset all = an empty array, which also empties every home",
        size=15,
        colour=DIM,
    )
    return s


# --------------------------------------------------------------------------
# 2. Mount: who wins.
# --------------------------------------------------------------------------

MERGE_W, MERGE_H = 1340, 640

SOURCES = (
    (BLUE, "1 · localStorage state", ("only if the pin is ON", "last visit, this browser")),
    (
        VIOLET,
        "2 · floating-map seed",
        ("sessionStorage, cross-tab", "a selection surviving a tab switch"),
    ),
    (
        YELLOW,
        "3 · #filters= fragment",
        ("a share link being opened", "consumed once, then stripped"),
    ),
)


def build_mount_merge() -> Sketch:
    s = Sketch(MERGE_W, MERGE_H)
    s.heading(
        40,
        52,
        "Mount: who wins",
        "hydration is synchronous, in the useState initializer,"
        " so the very first fetch is already filtered",
    )

    src_boxes = []
    for i, (fill, title, lines) in enumerate(SOURCES):
        b = Box(70 + i * 380, 120, 330, 96, fill, title, lines)
        s.box(b)
        src_boxes.append(b)

    merged = Box(
        430,
        296,
        480,
        96,
        WHITE,
        "merged per (index, source)",
        ("ascending priority: a share link beats", "the map seed beats the stored state"),
    )
    s.box(merged)
    for b in src_boxes:
        s.arrow(b.cx, b.bottom + 6, merged.cx + (b.cx - merged.cx) * 0.55, merged.y - 8)

    view = Box(
        1030, 296, 250, 96, GREEN, "the view", ("first fetch filtered,", "no unfiltered flash")
    )
    s.box(view)
    s.arrow(merged.right + 8, merged.cy, view.x - 8, view.cy)

    fetch = Box(
        70,
        470,
        330,
        110,
        GREEN,
        "GET filter_state/{id}",
        ("per-user server copy", "async, never blocks first paint"),
    )
    s.box(fetch)

    gates = Box(
        480,
        452,
        430,
        146,
        ORANGE,
        "applied only when",
        (
            "persisted, and the pin is still ON",
            "newer than the localStorage copy",
            "no share link was consumed",
            "the user has not touched a filter yet",
        ),
    )
    s.box(gates, dashed=True)
    s.arrow(fetch.right + 8, fetch.cy, gates.x - 8, gates.cy)

    s.arrow(gates.right + 8, gates.y + 30, view.cx, view.bottom + 10)
    s.text(
        1105,
        gates.y + 4,
        "merge + sanitize",
        size=14,
        colour=DIM,
    )
    s.text(
        1105,
        gates.y + 22,
        "against stored_metadata",
        size=14,
        colour=DIM,
    )

    s.text(
        gates.cx,
        MERGE_H - 22,
        "any gate fails: the server copy is simply not applied, the user keeps what they see",
        size=15,
        colour=DIM,
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/filter_persistence"),
        "--out",
        help="Output prefix; '_<name>.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the two filter-persistence schemas under --out."""
    write(build_one_array(), out, "one_array", png=png)
    write(build_mount_merge(), out, "mount_merge", png=png)


if __name__ == "__main__":
    app()
