#!/usr/bin/env python3
"""Render the whole-dashboard generation and its draft review as hand-drawn SVGs.

Two diagrams, each carrying one idea the prose in `docs/ai-assistant.md` needs
several paragraphs for:

* ``generation_pipeline`` — the one SSE run behind `POST /ai/generate-dashboard`:
  a grounded inventory, one planning call, the gate where the plan can stop and
  be judged before anything is paid for, then the fill / check / layout / save
  chain with its repair loop and its budget.
* ``draft_review``       — what a generated dashboard is until somebody says
  otherwise: where the review state lives, which surface writes it, and the two
  exits.

Usage:
    python dev/diagrams/ai_dashboard_generation.py --out docs/images/v1.4/ai/schema
    # writes <out>_generation_pipeline.svg/.png and <out>_draft_review.svg/.png

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
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

# GREEN in sketch.py is a pastel fill; the write-back needs an ink that
# carries across a wide diagram, since it is the claim being made.
WRITE_INK = "#2f9e44"

app = typer.Typer(add_completion=False)


# --------------------------------------------------------------------------
# 1. The run: grounded, gated, checked.
# --------------------------------------------------------------------------

PIPE_W, PIPE_H = 1340, 760


def build_pipeline() -> Sketch:
    """The generation run, drawn as two rows with the plan gate between them.

    The point is that only one step is a free-form model call. Everything
    before it is read off the project, everything after it is validated
    against the same grammar the CLI import uses, and the gate in the middle
    is where a run can be stopped and judged before it is paid for.
    """
    s = Sketch(PIPE_W, PIPE_H, seed=11)
    s.heading(50, 56, "Generating a whole dashboard", "POST /ai/generate-dashboard, one SSE run")

    inventory = Box(
        50,
        110,
        290,
        160,
        BLUE,
        "inventory",
        (
            "table collections + joins",
            "schemas, redacted samples",
            "ranked viz kinds",
            "catalog offers",
        ),
    )
    plan = Box(
        390,
        110,
        290,
        160,
        YELLOW,
        "plan  (1 LLM call)",
        (
            "strict JSON, then clamped:",
            "sections, funnel order,",
            "one intent per component",
            "icons + colours allowlisted",
        ),
    )
    gate = Box(
        730,
        110,
        250,
        160,
        VIOLET,
        "judge the plan?",
        ("plan_only stops here", "the plan comes back", "for a verdict"),
    )
    stopped = Box(
        1030,
        110,
        260,
        160,
        WHITE,
        "status: planned",
        ("nothing saved,", "one call paid for.", "Build this plan sends", "it back to fill"),
    )
    for b in (inventory, plan, gate, stopped):
        s.box(b)
    s.arrow(inventory.right, inventory.cy, plan.x, plan.cy)
    s.arrow(plan.right, plan.cy, gate.x, gate.cy)
    s.arrow(gate.right, gate.cy, stopped.x, stopped.cy, dashed=True)

    fill = Box(
        50,
        400,
        290,
        180,
        YELLOW,
        "fill  (per component)",
        (
            "the intent + its collection",
            "catalog offer reproduced",
            "text and advanced viz:",
            "no LLM at all",
        ),
    )
    check = Box(
        390,
        400,
        290,
        180,
        GREEN,
        "check",
        (
            "validate_single grammar",
            "schema: columns, dtypes,",
            "aggregations, companions",
            "render probe, in process",
        ),
    )
    layout = Box(
        730,
        400,
        250,
        180,
        BLUE,
        "layout",
        ("deterministic, 8 columns", "funnel order, full card rows", "filters grouped left"),
    )
    save = Box(
        1030,
        400,
        260,
        180,
        PINK,
        "save",
        (
            "the import path itself,",
            "plus ai_generation:",
            "model, prompt, run id,",
            "status = draft",
        ),
    )
    for b in (fill, check, layout, save):
        s.box(b)
    s.arrow(fill.right, fill.cy, check.x, check.cy)
    s.arrow(check.right, check.cy, layout.x, layout.cy)
    s.arrow(layout.right, layout.cy, save.x, save.cy)

    # The approved plan drops out of the gate and starts the second row.
    s.curve([(gate.cx, gate.bottom), (gate.cx, 330), (195, 330), (195, fill.y)], colour=DIM)
    s.arrow(195, fill.y - 26, 195, fill.y, colour=DIM)
    s.text(500, 318, "the approved plan, re-parsed and re-normalised", size=15, colour=DIM)

    # The repair loop: what a failing component costs before it is given up on.
    s.curve(
        [(check.cx, check.bottom), (check.cx, 630), (fill.cx, 630), (fill.cx, fill.bottom)],
        colour=RED,
    )
    s.arrow(fill.cx, fill.bottom + 26, fill.cx, fill.bottom, colour=RED)
    s.text(
        365, 655, "invalid: one repair round per component, then it is dropped", size=15, colour=RED
    )

    budget = Box(
        50,
        690,
        1240,
        56,
        ORANGE,
        "",
        (),
    )
    s.rect(budget, dashed=True)
    s.text(
        670,
        724,
        "budget: tokens, wall clock, repairs. Exhausted, the rest are dropped with reason "
        '"budget" and the run still saves what it has.',
        size=15,
    )
    return s


# --------------------------------------------------------------------------
# 2. The draft: who writes the review, and the two exits.
# --------------------------------------------------------------------------

REVIEW_W, REVIEW_H = 1340, 720


def build_review() -> Sketch:
    """The draft review, drawn around the field that holds it.

    The point is that one field on the document carries the whole review, one
    route writes it, and autosave cannot: the editor is a full editor on a
    draft, so nothing it saves may accidentally mark a tile as judged.
    """
    s = Sketch(REVIEW_W, REVIEW_H, seed=5)
    s.heading(50, 56, "Reviewing the draft", "editor-only, until somebody promotes or discards it")

    doc = Box(
        50,
        110,
        300,
        200,
        PINK,
        "ai_generation",
        (
            "status: draft | promoted",
            "model, prompt, run id",
            "warnings, section reasons",
            "reviewed: [tags]",
        ),
    )
    banner = Box(
        420,
        110,
        280,
        200,
        VIOLET,
        "banner",
        ("provenance + warnings", "reviewed n of m", "Review n components"),
    )
    panel = Box(
        760,
        110,
        280,
        200,
        BLUE,
        "review panel",
        (
            "the editor's aside:",
            "the canvas narrows,",
            "folds by tab and section,",
            "Keep / Regenerate / Remove",
        ),
    )
    route = Box(
        1090,
        110,
        200,
        200,
        GREEN,
        "review route",
        (
            "keep, unkeep,",
            "keep-all, unkeep-all.",
            "The only writer of",
            "reviewed[], and it",
            "keeps only the tags",
            "still on the page",
        ),
    )
    for b in (doc, banner, panel, route):
        s.box(b)
    s.arrow(doc.right, doc.cy, banner.x, doc.cy, colour=DIM)
    s.arrow(banner.right, doc.cy, panel.x, doc.cy)
    s.arrow(panel.right, doc.cy, route.x, doc.cy)

    # The write-back, around the outside: the route is the only arrow that
    # reaches the document, which is the whole claim of the diagram.
    s.curve(
        [(route.cx, route.bottom), (route.cx, 372), (22, 372), (22, doc.cy + 40)],
        colour=WRITE_INK,
    )
    s.arrow(22, doc.cy + 14, 22, doc.cy, colour=WRITE_INK)
    s.arrow(22, doc.cy, doc.x, doc.cy, colour=WRITE_INK)

    autosave = Box(
        50,
        470,
        300,
        160,
        WHITE,
        "editor autosave",
        ("edits the dashboard", "like any other,", "ai_generation stripped"),
    )
    s.box(autosave, dashed=True)
    s.line(doc.cx, doc.bottom, doc.cx, autosave.y, colour=RED, dashed=True)
    s.cross(doc.cx, 408)
    s.text(doc.cx + 26, 414, "never marks a tile", size=15, colour=RED, anchor="start")

    exits = Box(
        420,
        470,
        280,
        160,
        GREEN,
        "the two exits",
        ("Promote: status =", "promoted, provenance stays", "Discard: the dashboard goes"),
    )
    s.box(exits)
    s.arrow(banner.cx, banner.bottom, exits.cx, exits.y, colour=DIM)

    regenerate = Box(
        760,
        470,
        280,
        160,
        YELLOW,
        "regenerate",
        ("one tile or one section:", "the same fill and check,", "replaced in place"),
    )
    s.box(regenerate)
    s.arrow(panel.cx, panel.bottom, regenerate.cx, regenerate.y, colour=DIM)

    s.text(560, 668, "promoting with tiles unjudged asks first", size=15, colour=DIM)
    s.text(900, 668, "the boxes stay where they were", size=15, colour=DIM)
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v1.4/ai/schema"),
        "--out",
        help="Output prefix; '_<name>.svg' / '.png' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the generation and review schemas under --out."""
    write(build_pipeline(), out, "generation_pipeline", png=png)
    write(build_review(), out, "draft_review", png=png)


if __name__ == "__main__":
    app()
