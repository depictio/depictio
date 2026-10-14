#!/usr/bin/env python3
"""Render the AI analysis-mode schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, each carrying one idea that is tedious to state in prose:

* ``ai_modes``         — one ``/ai/analyze`` endpoint, two exclusive loops:
  the mutating chat that may propose dashboard actions, and the read-only
  analysis whose actions are stripped server-side, so no surface ever has
  to guess whether an Apply button belongs there.
* ``ai_analysis_loop`` — the budgeted loop behind a report: multi-DC scope,
  the killable sandbox child, the observation (with cardinalities) feeding
  back with a countdown, and the evidence gate between findings and steps.

Usage:
    python dev/diagrams/ai_analysis_schemas.py --out docs/images/v1.4/ai/schema
    # writes <out>_ai_modes.svg/.png and <out>_ai_analysis_loop.svg/.png

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


# --------------------------------------------------------------------------
# 1. One endpoint, two exclusive loops.
# --------------------------------------------------------------------------

MODES_W, MODES_H = 1320, 620


def build_modes() -> Sketch:
    """The mode contract: what each loop may produce, drawn as two lanes.

    The point is the asymmetry — both lanes start at the same endpoint, but
    only the top lane ever reaches an Apply affordance, and the bottom lane's
    ``actions`` die at the server boundary (the red cross), not in the UI.
    """
    s = Sketch(MODES_W, MODES_H)

    s.heading(
        46,
        52,
        "POST /ai/analyze — one endpoint, two exclusive loops",
        'the request declares {"mode": "mutate" | "analyze"}; the server routes and enforces',
    )

    entry = Box(60, 250, 250, 110, WHITE, "AnalyzeRequest", ("dashboard_id, prompt", "mode, filters[]"))
    s.box(entry)

    # -- mutate lane -------------------------------------------------------
    lane_y = 130
    s.text(360, lane_y - 14, 'mode: "mutate" (default)', size=17, weight="bold", anchor="start")
    loop = Box(360, lane_y, 280, 120, VIOLET, "short chat loop", ("1 code step, 1 answer", "single default DC"))
    acts = Box(690, lane_y, 280, 120, PINK, "actions", ("filter proposals resolved", "server-side (quantiles too)"))
    apply_ = Box(1020, lane_y, 250, 120, GREEN, "Apply / chips", ("visible, removable,", "reversible in one click"))
    s.box(loop)
    s.box(acts)
    s.box(apply_)
    s.arrow(entry.right, entry.cy - 20, loop.x, loop.cy)
    s.arrow(loop.right, loop.cy, acts.x, acts.cy)
    s.arrow(acts.right, acts.cy, apply_.x, apply_.cy)

    # -- analyze lane ------------------------------------------------------
    lane_y = 400
    s.text(360, lane_y - 14, 'mode: "analyze" (read-only)', size=17, weight="bold", anchor="start")
    loop2 = Box(360, lane_y, 280, 120, BLUE, "budgeted loop", ("up to 20 steps, all DCs,", "killable sandbox"))
    strip = Box(690, lane_y, 280, 120, WHITE, "actions?", ("stripped at the server,", "recorded as a warning"))
    report = Box(1020, lane_y, 250, 120, GREEN, "AnalysisReport", ("narrative + findings,", "persisted in ai_analyses"))
    s.box(loop2)
    s.box(strip)
    s.box(report)
    s.arrow(entry.right, entry.cy + 20, loop2.x, loop2.cy)
    s.arrow(loop2.right, loop2.cy, strip.x, strip.cy)
    s.arrow(strip.right, strip.cy, report.x, report.cy)
    s.cross(strip.cx, strip.y + 82, colour=RED)
    s.text(strip.cx, strip.bottom + 24, "no Apply surface exists in this mode", size=14, colour=DIM)

    return s


# --------------------------------------------------------------------------
# 2. The budgeted loop behind a report.
# --------------------------------------------------------------------------

LOOP_W, LOOP_H = 1320, 700


def build_analysis_loop() -> Sketch:
    """One analysis run, from the multi-DC scope to the evidence gate.

    Two things carry the diagram: the loop arrow (observation + countdown back
    into the next turn) and the evidence arrows from findings down to steps —
    a claim with no arrow to a step does not survive validation.
    """
    s = Sketch(LOOP_W, LOOP_H)

    s.heading(
        46,
        52,
        "A read-only analysis run",
        "the loop ends at the first exhausted bound: steps, total tokens, or wall clock",
    )

    ctx = Box(
        60,
        140,
        300,
        130,
        GREEN,
        "DashboardDataContext",
        ('dc["obs"], dc["meta"], ...', "schemas + row counts", "declared joins from project.yaml"),
    )
    llm = Box(
        470,
        140,
        300,
        130,
        VIOLET,
        "LLM turn",
        ("plan (first turn), thought,", "code or final answer", "+ findings"),
    )
    sandbox = Box(
        880,
        140,
        320,
        130,
        BLUE,
        "sandbox child (process)",
        ("holds every frame, loads them", "itself (specs, not pickles)", "deadline -> kill + respawn"),
    )
    s.box(ctx)
    s.box(llm)
    s.box(sandbox)
    s.arrow(ctx.right, ctx.cy, llm.x, llm.cy)
    s.arrow(llm.right, llm.cy, sandbox.x, sandbox.cy)
    s.cross(sandbox.right - 26, sandbox.bottom - 18, size=9, colour=RED)

    # The observation loops back into the next turn, budget attached.
    obs = Box(
        700,
        360,
        300,
        110,
        YELLOW,
        "observation",
        ("output + rows_in -> rows_out", "budget left: steps, tokens, s"),
    )
    s.box(obs)
    # Sandbox result drops into the observation...
    s.curve([(sandbox.cx, sandbox.bottom), (sandbox.cx, obs.cy)])
    s.arrow(sandbox.cx, obs.cy, obs.right, obs.cy, colour=DIM)
    # ...which feeds the next turn: left, then up into the LLM box.
    s.curve([(obs.x, obs.cy), (560, obs.cy)])
    s.arrow(560, obs.cy, 560, llm.bottom + 4, colour=DIM)
    s.text(obs.cx, obs.bottom + 26, "loops until the model concludes or a bound trips", size=14, colour=DIM)

    # The artifact, with the evidence gate drawn as arrows.
    rep = Box(
        110,
        520,
        400,
        150,
        GREEN,
        "AnalysisReport  (ai_analyses)",
        ("narrative_md", "findings: [{claim, evidence_step_ids[]}]", "budget_spent {steps, tokens, seconds}"),
    )
    steps = Box(
        770,
        520,
        430,
        150,
        WHITE,
        "steps[]",
        ("n, dc_tag, code, output", "rows_in -> rows_out, seconds", "status: success | error"),
    )
    s.box(rep)
    s.box(steps)
    s.arrow(llm.x + 20, llm.bottom, rep.cx + 40, rep.y, colour=DIM)
    s.text(310, 420, "final turn", size=14, colour=DIM, anchor="end")

    # Evidence arrows: every finding must land on a successful step.
    s.arrow(rep.right, 585, steps.x, 580, colour=GREY)
    s.arrow(rep.right, 620, steps.x, 640, colour=GREY)
    gap_cx = (rep.right + steps.x) / 2
    s.text(gap_cx, 555, "evidence_step_ids", size=15, weight="bold")
    s.text(gap_cx, 675, "no arrow -> the claim is dropped", size=13, colour=DIM)

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
    """Write the two AI analysis schemas under --out."""
    write(build_modes(), out, "ai_modes", png=png)
    write(build_analysis_loop(), out, "ai_analysis_loop", png=png)


if __name__ == "__main__":
    app()
