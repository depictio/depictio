#!/usr/bin/env python3
"""Render the notebook-export schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, each carrying one idea that is tedious to state in prose:

* ``notebook_export``        — one generator, four artefacts, and the rule that
  decides whether a tile arrives as code or is rendered through Depictio.
* ``notebook_report_render`` — what happens between "Render report" and a file
  in the reader's downloads: the API stages, a worker executes, S3 holds.

Usage:
    python dev/diagrams/notebook_export_schemas.py --out docs/images/v0.12/react/schema
    # writes <out>_notebook_export.svg/.png and <out>_notebook_report_render.svg/.png

PNG rendering needs Playwright (already a dev dependency) and a local Virgil GS.
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
    PINK,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)


# ---------------------------------------------------------------------------
# 1. One generator, four artefacts
# ---------------------------------------------------------------------------

EXPORT_W, EXPORT_H = 1400, 820


def build_export() -> Sketch:
    s = Sketch(EXPORT_W, EXPORT_H)

    s.heading(
        46,
        54,
        "A dashboard as a notebook: one generator, four artefacts",
        "the marimo file is canonical — every other form is derived from it, never written twice",
    )

    state = Box(
        50,
        130,
        290,
        128,
        BLUE,
        "AnalysisState",
        ("the view the reader has:", "filters, groups, funnel order,", "sent with the request"),
    )
    plan = Box(
        400,
        130,
        320,
        128,
        VIOLET,
        "build_export_plan",
        ("Mongo tabs, Delta schemas,", "and the same row counts", "the funnel view showed"),
    )
    builder = Box(
        780,
        130,
        290,
        128,
        YELLOW,
        "NotebookBuilder",
        ("cells in reading order:", "stages, then tiles,", "one name per result"),
    )

    for b in (state, plan, builder):
        s.box(b)
    s.arrow(state.right, state.cy, plan.x - 6, plan.cy)
    s.arrow(plan.right, plan.cy, builder.x - 6, builder.cy)

    marimo = Box(
        1120,
        130,
        230,
        128,
        GREEN,
        "marimo .py",
        ("canonical:", "reactive, and the", "source of the rest"),
    )
    s.box(marimo)
    s.arrow(builder.right, builder.cy, marimo.x - 6, marimo.cy)

    # The derivation chain, down the right-hand side.
    ipynb = Box(
        1120,
        320,
        230,
        112,
        GREEN,
        ".ipynb",
        ("marimo export ipynb", "— outputs excluded"),
    )
    quarto = Box(
        1120,
        482,
        230,
        112,
        GREEN,
        ".quarto.ipynb",
        ("the same cells plus", "a front-matter cell"),
    )
    report = Box(
        1120,
        644,
        230,
        124,
        ORANGE,
        "report.html",
        ("quarto render, here,", "on a worker —", "opt-in, next schema"),
    )
    for b in (ipynb, quarto, report):
        s.box(b)
    s.arrow(marimo.cx, marimo.bottom, ipynb.cx, ipynb.y - 6)
    s.arrow(ipynb.cx, ipynb.bottom, quarto.cx, quarto.y - 6)
    s.arrow(quarto.cx, quarto.bottom, report.cx, report.y - 6)

    # What a tile becomes, which is the product decision under all of it.
    s.text(50, 330, "Every tile takes one of two paths", size=20, anchor="start", weight="bold")

    code = Box(
        50,
        360,
        480,
        190,
        GREEN,
        "as code",
        (
            "interactive → a filter stage, in Polars",
            "card → the same reduction the server runs",
            "table → the page the dashboard shows",
            "figure, UI mode → the px.* call, rebuilt",
            "figure, code mode → the author's code, verbatim",
        ),
    )
    api = Box(
        50,
        580,
        480,
        190,
        BLUE,
        "rendered through Depictio",
        (
            "advanced viz, MultiQC, map, image, heatmap",
            "client.component(...) returns .figure / .data / .html",
            "the 15 React-drawn kinds come back from a",
            "headless browser reading the real renderer —",
            "same renderer, same numbers, no second one",
        ),
    )
    for b in (code, api):
        s.box(b)

    oracle = Box(
        590,
        360,
        460,
        190,
        YELLOW,
        "the row-count oracle",
        (
            "funnel_values already counts rows per stage.",
            "The test runs the generated notebook offline",
            "and asserts every stage's df.height equals it,",
            "for three stage orders: reordering changes the",
            "intermediate counts and never the final one.",
        ),
    )
    s.box(oracle)

    omitted = Box(
        590,
        580,
        460,
        190,
        PINK,
        "what the export refuses to guess",
        (
            "omitted is kept for the case no path serves:",
            "a collection with no Delta table behind it.",
            "An exhaustiveness test fails the build when a",
            "component type or a viz kind gains a member",
            "without a verdict, so nothing lands unclassified.",
        ),
    )
    s.box(omitted)

    return s


# ---------------------------------------------------------------------------
# 2. The rendered report is a job
# ---------------------------------------------------------------------------

RENDER_W, RENDER_H = 1400, 860


def build_render() -> Sketch:
    s = Sketch(RENDER_W, RENDER_H)

    s.heading(
        46,
        54,
        "The rendered report: a job, not a request",
        "minutes of work and a browser pass per rendered tile, so the client starts it and polls",
    )

    browser = Box(
        50,
        140,
        300,
        124,
        BLUE,
        "Export modal",
        ('the reader picks', '"Quarto report"', "and waits with a timer"),
    )
    api = Box(
        430,
        140,
        380,
        170,
        VIOLET,
        "API — POST .../render",
        (
            "builds the same .quarto.ipynb",
            "the download hands out, stages it",
            "in S3, mints a short-lived token",
            "for the caller, queues the job",
            "under the id it hands back",
        ),
    )
    worker = Box(
        890,
        140,
        460,
        170,
        YELLOW,
        "Worker — render_notebook_report",
        (
            "quarto render --execute, with",
            "QUARTO_PYTHON pinned to its own",
            "interpreter; the notebook calls this",
            "deployment back as the caller,",
            "one browser pass per rendered tile",
        ),
    )
    for b in (browser, api, worker):
        s.box(b)
    s.arrow(browser.right, browser.cy, api.x - 6, api.cy)
    s.arrow(api.right, api.cy, worker.x - 6, worker.cy)

    s3 = Box(
        620,
        420,
        400,
        150,
        GREEN,
        "S3, under the caller's own prefix",
        (
            "notebook-reports / user / job /",
            "the staged notebook goes in,",
            "the report comes out, and the",
            "notebook and the token are deleted",
        ),
    )
    s.box(s3)
    s.arrow(api.cx, api.bottom, s3.cx - 90, s3.y - 6)
    s.arrow(worker.cx, worker.bottom, s3.cx + 110, s3.y - 6)

    poll = Box(
        50,
        420,
        420,
        150,
        WHITE,
        "GET .../render/<job>",
        (
            "queued → running → ready,",
            "every three seconds; then",
            "GET .../download streams the",
            "file from the caller's prefix",
        ),
    )
    s.box(poll)
    s.arrow(s3.x - 6, s3.cy, poll.right, poll.cy)
    s.arrow(poll.cx, poll.y - 6, browser.cx, browser.bottom)

    s.text(
        50,
        632,
        "Three things this had to answer",
        size=20,
        anchor="start",
        weight="bold",
    )

    trust = Box(
        50,
        660,
        420,
        170,
        PINK,
        "whose code runs",
        (
            "Everything is generated except a",
            "code-mode figure, which is the author's",
            "Python. A dashboard carrying one is",
            "rendered only for its owners — anyone",
            "else downloads the notebook instead.",
        ),
    )
    silent = Box(
        510,
        660,
        420,
        170,
        ORANGE,
        "Quarto's two silent skips",
        (
            "It does not execute an .ipynb unless",
            "asked, and it skips execution when its",
            "interpreter has no Jupyter — writing an",
            "empty report and exiting 0 both times.",
            "The service reads the log before believing it.",
        ),
    )
    cost = Box(
        970,
        660,
        380,
        170,
        WHITE,
        "what it costs",
        (
            "45 s warm, about 4 minutes cold",
            "on the nf-core/viralrecon report.",
            "Quarto adds ~250 MB to the worker",
            "image, so the feature ships off",
            "by default.",
        ),
    )
    for b in (trust, silent, cost):
        s.box(b)

    s.text(
        1345,
        612,
        "a failed tile job is re-dispatched once",
        size=14,
        colour=DIM,
        anchor="end",
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
    """Write the two notebook-export schemas under --out."""
    write(build_export(), out, "notebook_export", png=png)
    write(build_render(), out, "notebook_report_render", png=png)


if __name__ == "__main__":
    app()
