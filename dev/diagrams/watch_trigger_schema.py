#!/usr/bin/env python3
"""Render the "Run now" watcher-trigger schema as a hand-drawn SVG (+ PNG).

The diagram summarises how a request made in the browser reaches a watcher that
the server cannot connect to, and what the resulting cycle leaves behind.

Usage:
    python dev/diagrams/watch_trigger_schema.py --out docs/images/v0.12/schema
    # writes <out>_watch_trigger.svg and, unless --no-png, _watch_trigger.png

PNG rendering needs Playwright (already a dev dependency) and a local Virgil GS;
without the font the SVG still renders, in whatever handwriting font the
fallback list finds. See sketch.py for the drawing primitives.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import BLUE, DIM, GREEN, ORANGE, VIOLET, YELLOW, Box, Sketch, write  # noqa: E402

app = typer.Typer(add_completion=False)

W, H = 1180, 540


def build() -> Sketch:
    s = Sketch(W, H)

    s.text(46, 52, "“Run now”: a request the server cannot deliver", size=25, anchor="start")
    s.text(
        46,
        78,
        "the watcher pulls, so it works from a login node the API can never reach",
        size=15,
        colour=DIM,
        anchor="start",
    )

    browser = Box(46, 118, 268, 92, BLUE, "Agents pane", ("Admin → Log & Task", "press “Run now”"))
    api = Box(
        430, 118, 300, 92, YELLOW, "API", ("POST …/agents/…/trigger", "records a flag, not a push")
    )
    records = Box(
        846,
        118,
        288,
        92,
        GREEN,
        "What it leaves behind",
        ("a run in Ingestion → History", "trigger “ui”, not “watch”"),
    )
    watcher = Box(
        430,
        368,
        300,
        104,
        VIOLET,
        "depictio watch",
        ("polls …/claim every 5s", "claim clears it atomically", "→ honoured exactly once"),
    )
    cycle = Box(846, 368, 288, 104, ORANGE, "One cycle", ("scan → process", "steps stream in live"))

    for b in (browser, api, records, watcher, cycle):
        s.box(b)

    # Browser → API.
    s.arrow(browser.right + 8, browser.cy, api.x - 10, api.cy)

    # API → watcher: the direction that does not exist. Dashed, crossed out.
    s.line(api.cx - 42, api.bottom + 10, api.cx - 42, watcher.y - 12, dashed=True, colour="#c92a2a")
    s.line(api.cx - 62, 280, api.cx - 22, 260, colour="#c92a2a", amount=1.2, passes=1)
    s.line(api.cx - 62, 260, api.cx - 22, 280, colour="#c92a2a", amount=1.2, passes=1)
    s.text(api.cx - 74, 250, "no route in", size=14, colour="#c92a2a", anchor="end")

    # Watcher → API: the direction that does.
    s.arrow(watcher.cx + 46, watcher.y - 12, api.cx + 46, api.bottom + 10)
    s.text(api.cx + 60, 252, "claim", size=15, anchor="start")
    s.text(api.cx + 60, 272, "(a pull)", size=13, colour=DIM, anchor="start")

    # Watcher → cycle → records.
    s.arrow(watcher.right + 8, watcher.cy, cycle.x - 10, cycle.cy)
    s.arrow(cycle.cx, cycle.y - 12, records.cx, records.bottom + 10)
    s.text(cycle.cx - 16, 252, "the Delta commit", size=13, colour=DIM, anchor="end")
    s.text(cycle.cx - 16, 272, "carries the run id", size=13, colour=DIM, anchor="end")

    # Heartbeat: the watcher's own liveness loop, unrelated to any request.
    s.curve(
        [
            (watcher.x - 6, watcher.y + 34),
            (watcher.x - 78, watcher.y + 34),
            (watcher.x - 78, watcher.y + 78),
            (watcher.x - 6, watcher.y + 78),
        ]
    )
    s.text(watcher.x - 90, watcher.y + 44, "heartbeat", size=14, colour=DIM, anchor="end")
    s.text(watcher.x - 90, watcher.y + 64, "every 60s", size=13, colour=DIM, anchor="end")
    s.text(watcher.x - 90, watcher.y + 84, "(TTL 5 min)", size=13, colour=DIM, anchor="end")

    # Banding note: which side of the wire each row lives on.
    s.text(46, 232, "server", size=14, colour=DIM, anchor="start")
    s.text(46, 348, "the machine with the data", size=14, colour=DIM, anchor="start")
    s.line(46, 300, W - 46, 300, dashed=True, colour="#adb5bd", width=1.2, passes=1)

    s.text(
        W - 46,
        H - 26,
        "a request while a cycle runs is picked up when that cycle ends",
        size=14,
        colour=DIM,
        anchor="end",
    )

    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/schema"),
        "--out",
        help="Output prefix; '_watch_trigger.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the schema SVG (and PNG) under --out."""
    write(build(), out, "watch_trigger", png=png)


if __name__ == "__main__":
    app()
