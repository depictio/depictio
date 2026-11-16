#!/usr/bin/env python3
"""Render the Nextflow module's two schemas as hand-drawn SVGs (+ PNGs).

Two diagrams for `docs/nextflow-module.md`:

* ``flow`` — from a pipeline's last task to a Depictio someone can open: the
  ``depictio/publish`` subworkflow, the ``depictio/ingest`` task inside the
  all-in-one image (services preinstalled, nothing downloaded), and the two
  ways out: an artifact reopened later by the same image, or a push to a
  server through ``cli_config``.
* ``ci``   — what CI runs to hold that true: the image, the engines, the
  nf-core pipelines, and the problems each pipeline turned up.

Usage:
    python dev/diagrams/nextflow_module.py --out docs/images/nextflow-module/schema
    # writes <out>_flow.svg/.png and <out>_ci.svg/.png

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
# 1. From the pipeline's last task to something someone can open.
# --------------------------------------------------------------------------

FLOW_W, FLOW_H = 1440, 900


def build_flow() -> Sketch:
    """Left to right: the pipeline, the subworkflow, the task, the two outputs.

    The task box is the part worth reading: everything it needs is in the
    image, so the line from it to conda-forge is crossed out.
    """
    s = Sketch(FLOW_W, FLOW_H)
    s.heading(
        46,
        52,
        "One image ingests the run, and the same image reopens it",
        "`depictio/publish` at the end of any pipeline; `-profile docker | singularity | apptainer`, nothing to configure",
    )

    # -- the pipeline -----------------------------------------------------------
    pipeline = Box(
        60,
        130,
        300,
        170,
        WHITE,
        "any nf-core pipeline",
        (
            "`nf-core/rnaseq`, `sarek`, `ampliseq`…",
            "its last process emits",
            "`ch_done` (MultiQC, a report…)",
            "`params.outdir` = the run's results",
        ),
    )
    s.box(pipeline)

    params = Box(
        60,
        340,
        300,
        150,
        YELLOW,
        "settings, two ways",
        (
            "inputs: `outdir`, `samplesheet`,",
            "`template`, `project_config`,",
            "`dashboards`, `cli_config`",
            "`params.depictio_*` → `ext.args`",
        ),
    )
    s.box(params)
    s.text(
        params.cx,
        params.bottom + 22,
        "`includeConfig` the subworkflow's",
        size=13,
        colour=DIM,
    )
    s.text(params.cx, params.bottom + 40, "`nextflow.config`: one line", size=13, colour=DIM)

    # -- the subworkflow --------------------------------------------------------
    publish = Box(
        430,
        130,
        300,
        200,
        BLUE,
        "`DEPICTIO_PUBLISH`",
        (
            "waits on `ch_done.collect()`",
            "stages `outdir` as `.`",
            "and the samplesheet as",
            "`input/samplesheet.<csv|tsv>`",
            "id = `workflow.runName`",
            "reads no `params` itself",
        ),
    )
    s.box(publish)
    s.arrow(pipeline.right, pipeline.cy, publish.x, publish.cy - 20)
    s.arrow(params.right, params.cy, publish.x + 40, publish.bottom)

    # -- the task ---------------------------------------------------------------
    task = Box(
        800,
        110,
        370,
        330,
        GREEN,
        "`DEPICTIO_INGEST`",
        (
            "`ghcr.io/depictio/depictio-allinone:<v>`",
            "",
            "`HOME` unwritable (`-u uid`, `HOME=/`)",
            "→ `$PWD/.home`",
            "template: `pipeline_info/` → `nf-core/x/<v>`",
            "variables: the run's `params_*.json`",
            "",
            "`local up` on `DEPICTIO_SERVICES_PREFIX`",
            "= `/opt/depictio-services` (checked:",
            "versions, platform, binaries)",
            "`ingest` → `local down`",
        ),
    )
    s.box(task)
    s.arrow(publish.right, publish.cy, task.x, task.y + 120)

    # nothing downloaded
    conda = Box(1250, 130, 150, 76, PINK, "conda-forge", ("MongoDB, Redis,", "SeaweedFS"))
    s.box(conda, dashed=True)
    s.line(task.right, conda.cy, conda.x, conda.cy, dashed=True, colour=GREY)
    s.cross((task.right + conda.x) / 2, conda.cy, size=10)
    s.text(conda.cx, conda.bottom + 22, "never at task time", size=13, colour=RED)

    ro = Box(
        1250,
        250,
        150,
        150,
        VIOLET,
        "runs as",
        ("the caller's uid", "read-only image", "tmpfs `/tmp`", "or Apptainer", "`--containall`"),
    )
    s.box(ro)
    s.line(task.right, ro.cy, ro.x, ro.cy, dashed=True, colour=GREY)

    # -- outputs ----------------------------------------------------------------
    artifact = Box(
        800,
        520,
        370,
        150,
        YELLOW,
        "artifact (default)",
        (
            "`<outdir>/depictio/<run>_depictio/`",
            "Mongo + S3 data + `cli/` config",
            "`<run>.depictio.json`: status, template,",
            "dashboards; no `env/` inside",
        ),
    )
    s.box(artifact)
    s.arrow(task.cx - 60, task.bottom, artifact.cx - 60, artifact.y)

    server = Box(
        430,
        520,
        300,
        150,
        ORANGE,
        "`cli_config` set",
        (
            "no local stack: the task",
            "ingests into a running server",
            "(its URL + token from the file)",
            "nothing left to reopen",
        ),
    )
    s.box(server)
    s.arrow(task.x + 40, task.bottom, server.right - 40, server.y)

    reopen = Box(
        1220,
        520,
        180,
        210,
        GREEN,
        "reopen",
        (
            "same image:",
            "`docker run`",
            "`-v art:/data`",
            "or `apptainer run`",
            "`--bind art:/data`",
            "→ `:8058`",
            "clean stop on TERM",
        ),
    )
    s.box(reopen)
    s.arrow(artifact.right, artifact.cy, reopen.x, artifact.cy)

    # -- rules ------------------------------------------------------------------
    s.text(
        60,
        760,
        "`errorStrategy 'ignore'` in the shipped config: a failed ingestion is logged in `.nextflow.log` and",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        60,
        782,
        "never fails the pipeline. CI sets `terminate` instead, so a broken module cannot pass.",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        60,
        FLOW_H - 40,
        "`DEPICTIO_SERVICES_PREFIX` unset: `local up` behaves as before (py-rattler into `<home>/env`); a mismatch is an error, never a fallback download",
        size=13,
        colour=DIM,
        anchor="start",
    )
    return s


# --------------------------------------------------------------------------
# 2. What CI runs.
# --------------------------------------------------------------------------

CI_W, CI_H = 1440, 820

PIPELINES = (
    ("rnaseq", "3.26.0", "full run, then reopen", GREEN),
    ("sarek", "3.11.0", "", GREEN),
    ("airrflow", "5.1.2", "needs the strict parser", GREEN),
    ("taxprofiler", "2.0.1", "", GREEN),
    ("funcscan", "4.0.0", "", GREEN),
    ("ampliseq", "2.18.0", "", GREEN),
    ("smrnaseq", "2.4.1", "parses only with v1 → retried", YELLOW),
    ("viralrecon", "3.0.0", "v1 parser + `--skip_pangolin`", YELLOW),
    ("scrnaseq", "4.2.0", "template wants a megatest layout", PINK),
)


def build_ci() -> Sketch:
    """Top: the image and the engines. Bottom: one row per pipeline."""
    s = Sketch(CI_W, CI_H)
    s.heading(
        46,
        52,
        "What CI runs on every change to the module or the image",
        "`build-images.yaml`: the image once, then every engine and nine nf-core releases through the subworkflow",
    )

    image = Box(60, 120, 260, 130, YELLOW, "build the image", ("amd64 + arm64", "build-time check of", "the services prefix"))
    s.box(image)

    docker = Box(
        380,
        110,
        300,
        150,
        GREEN,
        "Docker",
        ("iris: `local up` → ingest → down", "module, `-u uid`, `--read-only`", "`cli_config` → running instance", "reopen: 150 rows, clean stop"),
    )
    sif = Box(740, 110, 200, 150, BLUE, "`.sif` job", ("`docker-daemon://` →", "`apptainer build`", "artifact handed on,", "disk freed"))
    appt = Box(1000, 110, 380, 150, GREEN, "Apptainer", ("module under `-profile apptainer`", "reopen with `--containall`", "same assertions as Docker"))
    for b in (docker, sif, appt):
        s.box(b)
    s.arrow(image.right, image.cy, docker.x, docker.cy)
    s.arrow(docker.right, docker.cy, sif.x, sif.cy)
    s.arrow(sif.right, sif.cy, appt.x, appt.cy)

    s.text(60, 310, "nf-core releases, `-profile test,docker`, cloned with git (no GitHub API)", size=17, anchor="start")
    s.text(
        60,
        332,
        "each: pipeline → subworkflow → status `success`, expected template id, ≥ 1 dashboard, no `env/`, no root-owned file → reopen",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.arrow(image.cx, image.bottom, image.cx, 286)

    row_h, top = 46, 360
    for i, (name, version, note, fill) in enumerate(PIPELINES):
        y = top + i * row_h
        b = Box(60, y, 230, row_h - 8, fill, f"`{name}` {version}")
        s.rect(b)
        s.text(b.cx, y + 25, b.title, size=15)
        if note:
            s.text(b.right + 24, y + 25, note, size=14, colour=DIM if fill == GREEN else "#1e1e1e", anchor="start")
        if fill == PINK:
            s.cross(b.right + 330, y + 19, size=8)
            s.text(b.right + 350, y + 25, "out of the matrix: a template matter", size=14, colour=RED, anchor="start")

    legend_x = 900
    s.text(legend_x, 400, "what the pipelines turned up", size=17, anchor="start")
    for i, line in enumerate(
        (
            "Nextflow 26.10 parses strictly by default:",
            "a parse error, and only that, reruns with",
            "`NXF_SYNTAX_PARSER=v1` and a warning",
            "",
            "the shared runners exhaust GitHub's API:",
            "pipelines are cloned with git, and pangolin's",
            "database update is skipped (its collection",
            "is optional in the template)",
            "",
            "none of them was a fault in the module",
        )
    ):
        s.text(legend_x, 430 + i * 22, line, size=14, colour=DIM, anchor="start")
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/nextflow-module/schema"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render PNGs through Playwright."),
) -> None:
    """Write the flow and CI schemas under --out."""
    write(build_flow(), out, "flow", png=png)
    write(build_ci(), out, "ci", png=png)


if __name__ == "__main__":
    app()
