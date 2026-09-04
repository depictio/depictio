#!/usr/bin/env python3
"""Render the Nextflow trigger's two schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, each carrying one idea that `docs/nextflow-trigger.md` needs a
page for:

* ``trigger_flow`` — what happens between a pipeline's last task and a link
  someone can click: where the handler comes from, the three guards that make
  it return without a word, the argv it assembles from params and manifest, the
  CLI's eight steps, and why the pipeline's own exit status is never touched.
* ``stack``        — the three pull requests as layers, read bottom-up: what
  each one had to make true before the one above it could exist.

Usage:
    python dev/diagrams/nextflow_trigger.py --out docs/images/v1.4/nextflow/schema
    # writes <out>_trigger_flow.svg/.png and <out>_stack.svg/.png

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
# 1. From the last task to a link.
# --------------------------------------------------------------------------

FLOW_W, FLOW_H = 1400, 820


def build_flow() -> Sketch:
    """Left to right: where the handler comes from, what it checks, what it runs.

    The three guard lines under the handler box are the part worth drawing:
    each is a reason to say nothing at all, and the red cross on the return
    arrow is the rule the whole file exists for. The pipeline's exit status is
    the one thing the handler never writes to.
    """
    s = Sketch(FLOW_W, FLOW_H)

    s.heading(
        46,
        52,
        "The pipeline runs depictio-cli itself when it finishes",
        "one handler, three ways in, three reasons to stay silent, never a changed exit status",
    )

    # -- how the handler gets loaded ------------------------------------------
    per_run = Box(
        60,
        120,
        300,
        88,
        WHITE,
        "per run",
        ("nextflow run … -c $(depictio-cli", "config nextflow)"),
    )
    per_machine = Box(
        60,
        228,
        300,
        108,
        WHITE,
        "per machine",
        (
            "depictio-cli config nextflow --install",
            "→ ~/.depictio/nextflow.config",
            "← includeConfig in ~/.nextflow/config",
        ),
    )
    per_pipeline = Box(
        60,
        356,
        300,
        88,
        WHITE,
        "per pipeline",
        ("includeConfig '…/depictio.config'", "in the pipeline's nextflow.config"),
    )
    for b in (per_run, per_machine, per_pipeline):
        s.box(b)

    handler = Box(
        440,
        196,
        330,
        148,
        YELLOW,
        "workflow.onComplete",
        (
            "depictio.config, assigned:",
            "a second include replaces the",
            "first, so two includes ingest once",
            "",
            "reads every param HERE, at completion",
        ),
    )
    s.box(handler)
    for b in (per_run, per_machine, per_pipeline):
        s.arrow(b.right, b.cy, handler.x, handler.cy)

    for i, line in enumerate(
        (
            "the --install copy lives outside the virtualenv:",
            "a dead includeConfig is a parse failure for every",
            "pipeline on the machine, not a Depictio warning",
        )
    ):
        s.text(per_machine.x, 470 + i * 18, line, size=13, colour=DIM, anchor="start")

    # -- the guards -------------------------------------------------------------
    guards = Box(
        440,
        392,
        330,
        118,
        PINK,
        "returns without a word when",
        (
            "workflow == null  (script never compiled)",
            "!workflow.success  (partial output)",
            "depictio_enabled == false",
        ),
    )
    s.box(guards)
    s.line(handler.cx, handler.bottom, guards.cx, guards.y, dashed=True, colour=GREY)

    # -- what it assembles ------------------------------------------------------
    argv = Box(
        850,
        120,
        300,
        224,
        BLUE,
        "argv it builds",
        (
            "--CLI-config-path  ~/.depictio/CLI.yaml",
            "--data-root  params.outdir",
            "--triggered-by nextflow",
            "--pipeline-id  manifest.name/version",
            "--project-config-path / --template",
            "--dashboard  params.depictio_dashboard",
            "--attach-run | --update-config",
            "env: DEPICTIO_DATA_ROOT",
        ),
    )
    s.box(argv)
    s.arrow(handler.right, handler.cy, argv.x, argv.cy)

    cli = Box(
        850,
        392,
        300,
        150,
        GREEN,
        "depictio-cli run",
        (
            "child process, stdout+stderr merged,",
            "drained line by line into the log",
            "8 steps: server, S3, validate, sync,",
            "scan, process, joins, dashboards",
        ),
    )
    s.box(cli)
    s.arrow(argv.cx, argv.bottom, cli.cx, cli.y)

    # -- what comes out ---------------------------------------------------------
    api = Box(1230, 172, 130, 92, VIOLET, "API", ("project", "+ delta tables"))
    viewer = Box(1230, 302, 130, 110, VIOLET, "viewer", ("project page", "dashboard", "ingestion badge"))
    s.box(api)
    s.box(viewer)
    s.arrow(cli.right, cli.y + 40, api.x, api.cy)
    s.arrow(api.cx, api.bottom, viewer.cx, viewer.y)

    summary = Box(
        850,
        640,
        510,
        104,
        WHITE,
        "run summary, last lines of the pipeline log",
        (
            "📘 Project:   http://…/projects/<id>",
            "📘 Dashboard: http://…/dashboard/<id>",
        ),
    )
    s.box(summary)
    s.arrow(cli.cx, cli.bottom, summary.x + 120, summary.y)

    # -- the rule -------------------------------------------------------------------
    s.cross(per_run.x + 12, 600, size=9)
    s.text(
        per_run.x + 34,
        606,
        "no path from the handler to the pipeline's exit status:",
        size=14,
        colour=RED,
        anchor="start",
    )
    for i, line in enumerate(
        (
            "a missing CLI, a refused server, a failed step",
            "log a warning and the pipeline stays [SUCCESS]",
        )
    ):
        s.text(per_run.x + 34, 626 + i * 18, line, size=13, colour=DIM, anchor="start")
    s.text(
        46,
        FLOW_H - 34,
        "every [depictio] line carries its prefix: the console concatenates handler output when redirected, .nextflow.log keeps the lines",
        size=13,
        colour=DIM,
        anchor="start",
    )
    return s


# --------------------------------------------------------------------------
# 2. Three PRs, read bottom-up.
# --------------------------------------------------------------------------

STACK_W, STACK_H = 1400, 620


def build_stack() -> Sketch:
    """Three layers. Each names what it made true, and what above it needed that.

    Drawn as a stack because the dependency is not cosmetic: the trigger cannot
    re-run without the verdict fixed in the base PR, and it cannot name its
    template without the identity read in the middle one.
    """
    s = Sketch(STACK_W, STACK_H)

    s.heading(
        46,
        52,
        "Three pull requests, one dependency each",
        "read from the bottom: each layer is what the one above could not exist without",
    )

    lane_x, lane_w = 60, 820
    top = Box(
        lane_x,
        110,
        lane_w,
        136,
        GREEN,
        "#1037  the Nextflow onComplete trigger",
        (
            "depictio.config + config nextflow (--print / --install / --uninstall)",
            "example pipeline with a dashboard and a catalog recipe, published CLI image",
            "run summary links, ingestion badge with the pipeline's identity",
        ),
    )
    mid = Box(
        lane_x,
        272,
        lane_w,
        124,
        BLUE,
        "#1036  which pipeline produced this directory",
        (
            "WorkflowRunInfo + a priority registry of readers (nextflow 100, snakemake 50)",
            "reads pipeline_info/: identity, engine version, tools; picks the template ≤ run version",
            "stamps engine_name / pipeline_version / tools_executed on the WorkflowConfig",
        ),
    )
    base = Box(
        lane_x,
        422,
        lane_w,
        136,
        YELLOW,
        "#1035  auth without a secret in the file, and a second run that does not abort",
        (
            "DEPICTIO_CLI_TOKEN / _API_BASE_URL / _CONFIG_PATH overrides",
            "sync returns created / updated / exists instead of raising typer.Exit(0)",
            "--attach-run: union of locations, ids kept, single-file DCs protected",
        ),
    )
    for b in (top, mid, base):
        s.box(b)

    # what each layer hands up
    s.arrow(mid.cx, mid.y, top.cx, top.bottom)
    s.arrow(base.cx, base.y, mid.cx, mid.bottom)

    notes_x = lane_x + lane_w + 50
    s.text(notes_x, top.cy - 22, "needs:", size=14, colour=DIM, anchor="start")
    s.text(notes_x, top.cy, "--pipeline-id resolved to a template", size=15, anchor="start")
    s.text(notes_x, top.cy + 22, "provenance read without a template", size=15, anchor="start")

    s.text(notes_x, mid.cy - 22, "needs:", size=14, colour=DIM, anchor="start")
    s.text(notes_x, mid.cy, "a run.py that reaches step 4 twice", size=15, anchor="start")
    s.text(notes_x, mid.cy + 22, "a WorkflowConfig with room for it", size=15, anchor="start")

    s.text(notes_x, base.cy - 12, "base = main", size=14, colour=DIM, anchor="start")
    s.text(notes_x, base.cy + 10, "the only PR the unit-test CI runs on", size=15, anchor="start")
    s.text(notes_x, base.cy + 32, "(pull_request: branches: [main])", size=13, colour=DIM, anchor="start")

    s.text(
        46,
        STACK_H - 34,
        "supersedes #811 (registry) and #813 (config, docs): ported, not rebased, 740 commits behind main",
        size=14,
        colour=DIM,
        anchor="start",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v1.4/nextflow/schema"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render PNGs through Playwright."),
) -> None:
    """Write the trigger flow and the stack schemas under --out."""
    write(build_flow(), out, "trigger_flow", png=png)
    write(build_stack(), out, "stack", png=png)


if __name__ == "__main__":
    app()
