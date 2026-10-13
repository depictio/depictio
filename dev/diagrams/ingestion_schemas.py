#!/usr/bin/env python3
"""Hand-drawn schemas for the incremental-ingestion work.

Four diagrams, each answering one question a reader of the PR or of
``docs/automated-ingestion.md`` would otherwise have to reconstruct from prose:

* ``cycle_cost``     — what a cycle used to do per collection, and what it does now
* ``write_decision`` — how each write is chosen, and what sends it back to a full rebuild
* ``column_drift``   — what happens when a column moves between two scans
* ``missing_runs``   — why "was not scanned" and "is no longer there" are different questions

Usage:
    python dev/diagrams/ingestion_schemas.py --out docs/images/v0.12/react/schema
    python dev/diagrams/ingestion_schemas.py --only column_drift --no-png

See sketch.py for the drawing primitives and the reason these are generated.
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


# -- 1. what a cycle costs ---------------------------------------------------


def cycle_cost() -> Sketch:
    s = Sketch(1280, 764, seed=11)
    s.heading(
        46,
        52,
        "What one cycle costs, per data collection",
        "the old path did all of this whether or not a single file had moved",
    )

    left_x, right_x, col_w = 70, 640, 480
    s.text(left_x, 112, "Before", size=19, weight="bold", anchor="start")
    s.text(left_x + 92, 112, "every collection, every cycle", size=14, colour=DIM, anchor="start")
    s.text(right_x, 112, "After", size=19, weight="bold", anchor="start")
    s.text(right_x + 76, 112, "opt-in, and it falls back", size=14, colour=DIM, anchor="start")

    gate = Box(
        right_x,
        126,
        col_w,
        76,
        GREEN,
        "Did anything move?",
        ("no → none of the five happen at all",),
    )
    s.box(gate)

    before = [
        ("Does the table exist?", "a full pl.read_delta, result discarded"),
        ("Fetch every registered file", "File.from_mongo + os.path.exists on each"),
        ("Parse every source file", ""),
        ("Rewrite the whole table", ""),
        ("Upsert", "reads the table again, hashes every row"),
    ]
    after = [
        ("Probe the table", "_delta_log only — no rows read", GREEN),
        ("Fetch the changed runs' files", "filtered before the File objects exist", GREEN),
        ("Parse those files", "", GREEN),
        ("replaceWhere on those runs", "one partition, one atomic commit", GREEN),
        ("Upsert", "still reads the whole table", ORANGE),
    ]

    top, height, pitch = 222, 68, 84
    for i, ((lt, ls), (rt, rs, fill)) in enumerate(zip(before, after)):
        y = top + i * pitch
        s.box(Box(left_x, y, col_w, height, PINK, lt, (ls,) if ls else ()))
        s.box(Box(right_x, y, col_w, height, fill, rt, (rs,) if rs else ()))
        if i:
            s.arrow(left_x + col_w / 2, y - pitch + height + 4, left_x + col_w / 2, y - 6)
            s.arrow(right_x + col_w / 2, y - pitch + height + 4, right_x + col_w / 2, y - 6)
    s.arrow(gate.cx, gate.bottom + 6, gate.cx, top - 6)
    s.text(gate.cx + 14, top - 14, "yes", size=14, colour=DIM, anchor="start")

    # The skip lane: around all five steps, not into them.
    bottom = top + 4 * pitch + height
    s.curve(
        [
            (gate.right + 8, gate.cy),
            (1210, gate.cy),
            (1210, bottom + 16),
            (right_x + col_w / 2, bottom + 16),
        ],
        colour=DIM,
    )
    s.text(1170, gate.cy - 14, "nothing moved", size=14, colour=DIM)

    s.text(
        left_x,
        bottom + 52,
        "a new Delta version every cycle, forever",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        right_x,
        bottom + 52,
        "one partition, or nothing at all",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        46,
        732,
        "the orange one is the gap left open: the API still recomputes column specs "
        "from the whole table on every upsert",
        size=14,
        colour=DIM,
        anchor="start",
    )
    return s


# -- 2. how a write is chosen ------------------------------------------------


def write_decision() -> Sketch:
    s = Sketch(1060, 800, seed=23)
    s.heading(
        46,
        52,
        "How each write is chosen",
        "every fall-back does more work than the path it replaces, never less",
    )

    signal = Box(
        360,
        108,
        340,
        96,
        BLUE,
        "What the scan reports",
        ("changed_dcs · covered_dcs", "removed_runs · complete"),
    )
    moved = Box(360, 254, 340, 76, YELLOW, "Did this collection move?")
    skip = Box(760, 254, 262, 76, GREEN, "Leave it alone", ("no read, no parse, no commit",))
    scoped_q = Box(360, 404, 340, 76, VIOLET, "Can the write be scoped?")
    full = Box(46, 404, 262, 76, YELLOW, "Rebuild in full", ("read and rewrite everything",))
    scoped = Box(
        360,
        556,
        340,
        122,
        GREEN,
        "Write only those runs",
        (
            "replaceWhere on the changed runs",
            "schema_mode = merge",
            "rows_total left unset, not faked",
        ),
    )
    for b in (signal, moved, skip, scoped_q, full, scoped):
        s.box(b)

    s.arrow(signal.cx, signal.bottom + 6, moved.cx, moved.y - 8)
    s.arrow(moved.right + 8, moved.cy, skip.x - 10, skip.cy)
    s.text(moved.right + 32, moved.cy - 12, "no", size=14, colour=DIM, anchor="start")
    s.arrow(moved.cx, moved.bottom + 6, scoped_q.cx, scoped_q.y - 8)
    s.text(moved.cx + 14, moved.bottom + 32, "yes", size=14, colour=DIM, anchor="start")
    s.arrow(scoped_q.x - 10, scoped_q.cy, full.right + 8, full.cy)
    s.text(full.right + 34, scoped_q.cy - 12, "no", size=14, colour=DIM, anchor="start")
    s.arrow(scoped_q.cx, scoped_q.bottom + 6, scoped.cx, scoped.y - 8)
    s.text(scoped_q.cx + 14, scoped_q.bottom + 32, "yes", size=14, colour=DIM, anchor="start")

    declines = Box(
        46,
        528,
        262,
        190,
        PINK,
        "…it declines on",
        (
            "a removed run",
            "an incomplete scan",
            "an uncovered collection",
            "an unpartitioned table",
            "an emptied run",
            "a column type change",
        ),
    )
    s.box(declines)
    s.line(
        full.cx, full.bottom + 6, declines.cx, declines.y - 6, colour=GREY, dashed=True, width=1.4
    )

    s.text(
        46,
        768,
        "decided before the file list is filtered — so a subset can never reach the "
        "full-overwrite fall-back",
        size=14,
        colour=DIM,
        anchor="start",
    )
    return s


# -- 3. a column moves between two scans -------------------------------------


def column_drift() -> Sketch:
    s = Sketch(1160, 600, seed=31)
    s.heading(
        46,
        52,
        "A column moves between two scans",
        "measured on deltalake 0.24 and 1.6.1, writing one partition of a partitioned table",
    )

    label_x, col1_x, col2_x, col_w = 46, 380, 770, 350
    s.text(col1_x + col_w / 2, 138, 'schema_mode = "merge"', size=18, weight="bold")
    s.text(col1_x + col_w / 2, 158, "what a scoped write now uses", size=13, colour=DIM)
    s.text(col2_x + col_w / 2, 138, 'schema_mode = "overwrite"', size=18, weight="bold")
    s.text(col2_x + col_w / 2, 158, "what the code used to use", size=13, colour=DIM)

    rows = [
        (
            "The subset adds a column",
            (GREEN, ("absorbed into the schema;", "other runs read back null")),
            (GREEN, ("also fine",)),
        ),
        (
            "The subset lacks a column",
            (GREEN, ("kept; the rewritten rows", "are null for it")),
            (PINK, ("1.6.1 — dropped for every run", "0.24 — table unreadable")),
        ),
        (
            "A column's type changed",
            (YELLOW, ("fails loudly:", "DeltaError: Cannot cast")),
            (PINK, ('"succeeds" —', "table left unreadable")),
        ),
    ]

    top, height, pitch = 180, 106, 118
    for i, (label, (fill1, lines1), (fill2, lines2)) in enumerate(rows):
        y = top + i * pitch
        s.text(label_x, y + 58, label, size=17, anchor="start")
        for x, fill, lines in ((col1_x, fill1, lines1), (col2_x, fill2, lines2)):
            cell = Box(x, y, col_w, height, fill, "")
            s.rect(cell)
            for j, line in enumerate(lines):
                s.text(cell.cx, y + 48 + j * 24, line, size=15)
        if fill2 is PINK:
            s.cross(col2_x + col_w - 26, y + 24, size=9)

    s.text(
        46,
        556,
        "so a scoped write always merges — and a type conflict is caught before the write, "
        "and rebuilds in full",
        size=15,
        colour=DIM,
        anchor="start",
    )
    return s


# -- 4. which runs are gone --------------------------------------------------


def missing_runs() -> Sketch:
    s = Sketch(1180, 620, seed=43)
    s.heading(
        46,
        52,
        "Which runs are gone?",
        'the cache does not rescan an unchanged run — so "not scanned" and "not there" '
        "are different questions",
    )

    def chip(cx: float, y: float, label: str, *, fill: str = WHITE, colour: str = INK) -> None:
        s.rect(Box(cx - 62, y, 124, 34, fill, ""), colour=colour)
        s.text(cx, y + 23, label, size=15, colour=colour)

    columns = [
        (60, BLUE, "Registered in the DB", ("run_A", "run_B", "run_C"), ""),
        (
            450,
            YELLOW,
            "Scanned this cycle",
            ("run_C",),
            "A and B were unchanged,\nso the cache skipped them",
        ),
        (840, GREEN, "Present on disk", ("run_A", "run_B", "run_C"), ""),
    ]
    for x, fill, title, chips, note in columns:
        panel = Box(x, 118, 280, 198, fill, "")
        s.rect(panel)
        s.text(panel.cx, 148, title, size=17, weight="bold")
        for i, label in enumerate(chips):
            chip(panel.cx, 170 + i * 46, label)
        for i, line in enumerate(note.split("\n") if note else []):
            s.text(panel.cx, 240 + i * 20, line, size=13, colour=DIM)

    before = Box(
        60,
        372,
        1060,
        94,
        PINK,
        "Before — registry minus scanned",
        ("{run_A, run_B} deleted, with every one of their files, from the second cycle onwards",),
    )
    after = Box(
        60,
        488,
        1060,
        94,
        GREEN,
        "After — registry minus present on disk",
        ("nothing is deleted; a run only disappears when its directory does",),
    )
    s.box(before)
    s.box(after)
    s.cross(before.right - 40, before.cy - 8, size=13)
    s.text(
        before.right - 68,
        before.cy + 32,
        "reproduced before it was fixed",
        size=13,
        colour=RED,
        anchor="end",
    )
    return s


DIAGRAMS = {
    "cycle_cost": cycle_cost,
    "write_decision": write_decision,
    "column_drift": column_drift,
    "missing_runs": missing_runs,
}


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"),
        "--out",
        help="Output prefix; '_<name>.svg' / '.png' are appended.",
    ),
    only: str = typer.Option("", "--only", help=f"One of: {', '.join(DIAGRAMS)}"),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the ingestion schemas (SVG, and PNG unless --no-png) under --out."""
    if only and only not in DIAGRAMS:
        raise typer.BadParameter(f"unknown diagram {only!r}; pick one of {', '.join(DIAGRAMS)}")
    for name, build in DIAGRAMS.items():
        if only and name != only:
            continue
        write(build(), out, name, png=png)


if __name__ == "__main__":
    app()
