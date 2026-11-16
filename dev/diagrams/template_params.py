#!/usr/bin/env python3
"""Render the ``from_params`` schema as a hand-drawn SVG (+ PNG).

One diagram for the template docs: how a run's own ``params.json`` becomes the
variables a template's conditionals read, without anyone passing ``--var``.

Usage:
    python dev/diagrams/template_params.py --out docs/images/template-params/schema
    # writes <out>_from_params.svg/.png

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

W, H = 1440, 860


def build() -> Sketch:
    """Left to right: the run, the rules, the variables, what they switch."""
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "The run says which route it took; the template listens",
        "`from_params` rules read the run's `pipeline_info/params_*.json`; an explicit `--var` always wins",
    )

    run = Box(
        60,
        130,
        300,
        220,
        WHITE,
        "the run's outdir",
        (
            "`pipeline_info/params_<ts>.json`",
            "newest first: a resumed run",
            "leaves one per attempt",
            "",
            "none at the root →",
            "the first `run_*/pipeline_info/`",
            "(sequencing-run projects)",
        ),
    )
    s.box(run)

    example = Box(
        60,
        390,
        300,
        170,
        YELLOW,
        "e.g. rnaseq",
        (
            '`"skip_alignment": true`',
            '`"skip_qc": "true"`',
            '`"aligner": "star_salmon"`',
            "bool, string or list:",
            "`\"true\"`, `\"a,b\"`, `[\"a\"]` all read",
        ),
    )
    s.box(example)
    s.line(run.cx, run.bottom, example.cx, example.y, dashed=True, colour=GREY)

    rules = Box(
        430,
        130,
        400,
        300,
        BLUE,
        "`template.yaml` variables",
        (
            "`PSEUDOALIGNER_ONLY:`",
            "  `from_params: {param: skip_alignment}`",
            "`SKIP_MULTIQC:`",
            "  `from_params: {any: [{param: skip_multiqc},`",
            "                `{param: skip_qc}]}`",
            "",
            "tests: bare (on/off), `is`, `equals`,",
            "`not_equals`, `contains`, `not_contains`,",
            "nested `any` / `all`",
            "`extra=forbid`: a typo is a load error",
        ),
    )
    s.box(rules)
    s.arrow(run.right, run.cy, rules.x, rules.cy - 40)

    variables = Box(
        900,
        130,
        240,
        170,
        GREEN,
        "variables",
        (
            "`PSEUDOALIGNER_ONLY=true`",
            "`SKIP_MULTIQC=true`",
            "",
            "a rule that does not",
            "hold sets nothing",
        ),
    )
    s.box(variables)
    s.arrow(rules.right, variables.cy, variables.x, variables.cy)

    explicit = Box(1200, 130, 190, 120, ORANGE, "`--var X=…`", ("set by the user:", "never overridden"))
    s.box(explicit)
    s.arrow(explicit.x, explicit.cy, variables.right, explicit.cy)

    cond = Box(
        900,
        360,
        490,
        200,
        VIOLET,
        "the template's conditionals",
        (
            "`if_var_present: SKIP_MULTIQC` → drop the MultiQC DCs",
            "`if_var_present: PSEUDOALIGNER_ONLY` → drop the tracks,",
            "re-point the sample overview",
            "the same template now fits a default run,",
            "a pseudo-aligner run, a run without QC…",
            "without anyone passing a flag",
        ),
    )
    s.box(cond)
    s.arrow(variables.cx, variables.bottom, cond.cx - 100, cond.y)

    # -- the guards around it --------------------------------------------------
    guard = Box(
        430,
        480,
        400,
        170,
        PINK,
        "held true by",
        (
            "every shipped template parses (pytest)",
            "`check_template_params.py`: each rule's param",
            "exists in that release's `nextflow_schema.json`",
            "(CI: `template-params.yaml`)",
            "51 rules in 18 templates",
        ),
    )
    s.box(guard)
    s.line(rules.cx, rules.bottom, guard.cx, guard.y, dashed=True, colour=GREY)

    s.cross(80, 720, size=9)
    s.text(
        100,
        726,
        "a renamed param in a new release would make a rule silently never hold:",
        size=14,
        colour=RED,
        anchor="start",
    )
    s.text(
        100,
        748,
        "the schema check fails instead, at the template's version, before any ingestion",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        46,
        H - 36,
        "introspection of the outputs still runs after the rules, for what params cannot tell (phylogeny, pplacer, metadata file)",
        size=13,
        colour=DIM,
        anchor="start",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/template-params/schema"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render PNGs through Playwright."),
) -> None:
    """Write the from_params schema under --out."""
    write(build(), out, "from_params", png=png)


if __name__ == "__main__":
    app()
