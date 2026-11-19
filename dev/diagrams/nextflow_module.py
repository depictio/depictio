#!/usr/bin/env python3
"""Render the Nextflow module's schemas as hand-drawn SVGs (+ PNGs).

Three diagrams for `docs/nextflow-module.md` and PR #1407:

* ``flow``        — from a pipeline's last task to a dashboard someone can open:
  the pipeline, the one subworkflow call, the task inside the all-in-one image
  (services preinstalled, nothing downloaded), and the two ways out.
* ``shared_node`` — what a task finds on an HPC node or under ``docker -u``:
  another user's stack, no home, a read-only image, and what the module and
  ``local up`` do about each.
* ``ci``          — what CI runs to hold that true: the image, both engines,
  nine nf-core releases and what each turned up.

Logos (nf-core and its pipelines, Nextflow, Docker, Apptainer, GitHub, MongoDB,
Redis, conda, Depictio) are embedded from ``dev/diagrams/logos/``; see its
README for where each comes from.

Usage:
    python dev/diagrams/nextflow_module.py --out docs/images/nextflow-module/schema
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from local_server import bucket as pail  # noqa: E402
from local_server import cylinder, gear, rack, stack  # noqa: E402
from sketch import (  # noqa: E402
    DIM,
    GREY,
    INK,
    ORANGE,
    PINK,
    RED,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    circle,
    folder,
    page,
    tick,
    warning,
    write,
)

app = typer.Typer(add_completion=False)

LOGOS = Path(__file__).parent / "logos"
SECTION = "#7048e8"
CODE_BG = "#1e1e1e"
CODE_INK = "#e9ecef"
CODE_KEY = "#b197fc"
CODE_STR = "#8ce99a"
CODE_DIM = "#868e96"


def logo(s: Sketch, name: str, x: float, y: float, w: float, h: float | None = None) -> None:
    s.image(LOGOS / name, x, y, w, h if h is not None else w)


def section(s: Sketch, x: float, y: float, label: str) -> None:
    s.text(x, y, label, size=17, colour=SECTION, anchor="start", weight="bold")


def code(
    s: Sketch, x: float, y: float, w: float, lines: list[tuple[str, str]], *, size: float = 14
) -> Box:
    """A dark code card: (text, colour) per line, monospace."""
    h = 40 + len(lines) * (size + 7)
    box = Box(x, y, w, h, CODE_BG, "")
    s.rect(box)
    for i, colour in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        circle(s, x + 16 + i * 15, y + 14, 4.5, colour)
    for i, (text, colour) in enumerate(lines):
        if not text:
            continue
        shown = text.replace(" ", " ")
        s.text(
            x + 16, y + 44 + i * (size + 7), f"`{shown}`", size=size, colour=colour, anchor="start"
        )
    return box


def note(
    s: Sketch,
    x: float,
    y: float,
    lines: tuple[str, ...],
    *,
    colour: str = DIM,
    size: float = 14,
) -> None:
    for i, line in enumerate(lines):
        s.text(x, y + i * (size + 6), line, size=size, colour=colour, anchor="start")


def person(s: Sketch, cx: float, top: float, fill: str) -> None:
    circle(s, cx, top + 12, 12, fill)
    s.poly(
        [(cx - 20, top + 54), (cx - 16, top + 32), (cx + 16, top + 32), (cx + 20, top + 54)],
        fill=fill,
        amount=0.8,
    )


def ship(s: Sketch, x: float, y: float, w: float, h: float, fill: str) -> None:
    """A shipping container's ribbed walls: the image."""
    s.rect(Box(x, y, w, h, fill, ""))
    for i in range(1, 16):
        rx = x + i * w / 16
        s.line(rx, y + 6, rx, y + 18, width=1.0, colour=DIM, passes=1)
        s.line(rx, y + h - 18, rx, y + h - 6, width=1.0, colour=DIM, passes=1)


def dag(s: Sketch, x: float, y: float) -> None:
    """A pipeline's process graph, ending in MultiQC."""
    nodes = {
        "FASTQC": (x + 40, y + 20),
        "TRIM": (x + 40, y + 90),
        "STAR": (x + 140, y + 55),
        "SALMON": (x + 140, y + 125),
        "MULTIQC": (x + 250, y + 90),
    }
    edges = (
        ("FASTQC", "STAR"),
        ("TRIM", "STAR"),
        ("TRIM", "SALMON"),
        ("STAR", "MULTIQC"),
        ("SALMON", "MULTIQC"),
        ("FASTQC", "MULTIQC"),
    )
    for a, b in edges:
        (x1, y1), (x2, y2) = nodes[a], nodes[b]
        s.line(x1 + 14, y1, x2 - 14, y2, colour=GREY, width=1.4, amount=1.0, passes=1)
    for name, (cx, cy) in nodes.items():
        if name == "MULTIQC":
            circle(s, cx, cy, 20, WHITE)
            logo(s, "multiqc_icon_color.svg", cx - 14, cy - 14, 28)
            s.text(cx, cy + 38, name, size=11, colour=DIM)
        else:
            circle(s, cx, cy, 13, "#d3f9d8")
            s.text(cx, cy + 30, name, size=11, colour=DIM)


# --------------------------------------------------------------------------
# 1. From the pipeline's last task to a dashboard.
# --------------------------------------------------------------------------

FLOW_W, FLOW_H = 1760, 1080


def build_flow() -> Sketch:
    s = Sketch(FLOW_W, FLOW_H)
    s.heading(
        60,
        64,
        "From a pipeline's last task to a dashboard anyone can reopen",
        "one subworkflow call · one image · `-profile docker | singularity | apptainer` · nothing to configure",
    )
    s.line(60, 104, 1190, 104, colour=SECTION, width=2.4, amount=1.0, passes=1)

    # -- 1 · the pipeline -------------------------------------------------------
    section(s, 60, 160, "1 · ANY nf-core PIPELINE")
    card = Box(60, 180, 360, 470, WHITE, "")
    s.rect(card)
    logo(s, "nf-core.png", 80, 196, 54)
    logo(s, "nextflow.png", 140, 200, 46)
    s.text(200, 224, "`nf-core/rnaseq`, `sarek`, …", size=15, anchor="start")
    s.text(200, 246, "any version, any profile", size=13, colour=DIM, anchor="start")
    dag(s, 80, 280)
    s.text(330, 446, "→ `ch_done`", size=14, colour=SECTION)
    out = folder(s, 86, 470, 150, 92, "#ffec99", "")
    s.text(out.cx, out.y + 58, "`--outdir`", size=15)
    for i, sub in enumerate(("`pipeline_info/`", "`multiqc/`", "`star_salmon/`", "`input/`")):
        s.text(256, 488 + i * 22, sub, size=13, colour=DIM, anchor="start")
    s.text(card.cx, 600, "`params_<ts>.json` says which", size=13, colour=DIM)
    s.text(card.cx, 620, "route the run took (`--skip_*`…)", size=13, colour=DIM)

    # -- 2 · the call -------------------------------------------------------------
    section(s, 470, 160, "2 · ONE SUBWORKFLOW CALL")
    c = code(
        s,
        470,
        180,
        410,
        [
            ("include { DEPICTIO_PUBLISH }", CODE_KEY),
            ("  from './subworkflows/depictio/publish'", CODE_DIM),
            ("", CODE_INK),
            ("DEPICTIO_PUBLISH(", CODE_INK),
            ("  ch_multiqc_report,  // ch_done", CODE_INK),
            ("  params.outdir,", CODE_INK),
            ("  params.input,       // samplesheet", CODE_INK),
            ("  null, null, null,   // template…", CODE_DIM),
            ("  null )              // cli_config", CODE_DIM),
        ],
    )
    c2 = code(
        s,
        470,
        c.bottom + 20,
        410,
        [
            ("includeConfig '…/publish/nextflow.config'", CODE_STR),
            ("--depictio_project Liver   → --project 'Liver'", CODE_INK),
            ("--depictio_vars A=b,C=d    → --var 'A=b' --var 'C=d'", CODE_INK),
            ("--depictio_ingest_args …   → appended to ingest", CODE_INK),
            ("--depictio_local_args '--port 8123' → local up", CODE_INK),
            ("publishDir <outdir>/depictio · errorStrategy ignore", CODE_DIM),
        ],
        size=11.5,
    )
    note(
        s,
        480,
        c2.bottom + 34,
        (
            "waits for the run with `toList()`: an empty",
            "`ch_done` (`--skip_multiqc`) still publishes;",
            "reads no `params` itself, nf-core style",
        ),
        size=13,
    )
    s.arrow(card.right + 6, 300, 466, 300)

    # -- 3 · the task, in the image ---------------------------------------------
    section(s, 930, 160, "3 · ONE TASK IN ONE IMAGE")
    img = Box(930, 180, 470, 470, "#e7f5ff", "")
    ship(s, img.x, img.y, img.w, img.h, img.fill)
    logo(s, "docker.svg", 950, 198, 34)
    logo(s, "apptainer.png", 1350, 196, 36)
    s.text(img.cx, 222, "`depictio-allinone:<v>`", size=16, weight="bold")
    s.text(img.cx, 246, "`DEPICTIO_INGEST`, as the caller's uid", size=13, colour=DIM)

    cylinder(s, 1010, 278, 78, 96, "#b2f2bb")
    logo(s, "mongodb.svg", 997, 320, 26)
    s.text(1010, 398, "MongoDB", size=13)
    stack(s, 1120, 286, 80, 80, "#ffc9c9")
    s.text(1120, 398, "Redis", size=13)
    logo(s, "redis.svg", 1166, 286, 22)
    pail(s, 1240, 282, 86, 92, "#ffd8a8")
    s.text(1240, 398, "SeaweedFS", size=13)
    gear(s, 1345, 320, 26, "#d0bfff")
    s.text(1345, 398, "API", size=13)
    s.text(img.cx, 432, "preinstalled at `/opt/depictio-services`, checked", size=13, colour=DIM)
    s.text(img.cx, 450, "against the CLI's versions and platform", size=13, colour=DIM)

    code(
        s,
        950,
        466,
        430,
        [
            ("$ stage_into results/ .     # → data_root/", CODE_INK),
            ("$ depictio local up --no-open --examples none", CODE_STR),
            ("$ depictio ingest data_root/ --server local \\", CODE_STR),
            ("    --triggered-by nextflow --result-json …", CODE_STR),
            ("  # template + routes: pipeline_info/params_*.json", CODE_DIM),
            ("$ depictio local down", CODE_STR),
            ("$ mv stack/{mongo,s3,keys,cli} <run>_depictio/", CODE_INK),
        ],
        size=11,
    )
    s.arrow(c.right + 4, 300, img.x - 4, 300)

    cloud = Box(1460, 190, 170, 100, PINK, "")
    s.rect(cloud, dashed=True)
    logo(s, "anaconda.svg", 1474, 204, 26)
    s.text(1560, 224, "conda-forge", size=15, weight="bold")
    s.text(cloud.cx, 254, "MongoDB, Redis,", size=13, colour=DIM)
    s.text(cloud.cx, 272, "SeaweedFS", size=13, colour=DIM)
    s.line(img.right, 240, cloud.x, 240, dashed=True, colour=GREY)
    s.cross((img.right + cloud.x) / 2, 240, size=11)
    s.text(cloud.cx, 318, "never at task time:", size=14, colour=RED)
    s.text(cloud.cx, 338, "offline nodes work", size=14, colour=RED)

    for i, (head, sub) in enumerate(
        (
            ("read-only image", "data in the work dir"),
            ("no home? `$PWD/.home`", "`docker -u` gives `HOME=/`"),
            ("shared `/tmp`", "no Mongo socket, per-uid S3"),
        )
    ):
        y = 400 + i * 84
        b = Box(1450, y, 250, 70, "#f3f0ff", "")
        s.rect(b)
        s.text(1466, y + 28, head, size=14, anchor="start")
        s.text(1466, y + 52, sub, size=12, colour=DIM, anchor="start")

    # -- 4 · what comes out -------------------------------------------------------
    section(s, 210, 730, "4 · WHAT COMES OUT")
    art = folder(s, 60, 760, 250, 150, "#ffec99", "")
    s.text(art.cx, 808, "`<outdir>/depictio/`", size=15)
    s.text(art.cx, 832, "`<run>_depictio/`", size=14)
    s.text(art.cx, 856, "Mongo + S3 data + config", size=13, colour=DIM)
    s.text(art.cx, 878, "`<run>.depictio.json`", size=13, colour=DIM)
    s.curve([(img.x + 60, img.bottom), (img.x + 60, 700), (art.cx, 700), (art.cx, art.y)], colour=INK)
    s.arrow(art.cx, 720, art.cx, art.y)
    s.text(art.x, art.bottom + 30, "default: a self-contained artifact", size=14, anchor="start")
    s.text(
        art.x,
        art.bottom + 50,
        "no `env/`; an earlier one never re-ingested",
        size=13,
        colour=DIM,
        anchor="start",
    )

    rc = code(
        s,
        360,
        760,
        480,
        [
            ("docker run -p 8058:8058 \\", CODE_INK),
            ("  -v <run>_depictio:/data depictio-allinone", CODE_INK),
            ("", CODE_INK),
            ("apptainer run --containall \\", CODE_INK),
            ("  --bind <run>_depictio:/data depictio.sif", CODE_INK),
        ],
        size=13,
    )
    s.arrow(art.right + 4, 830, rc.x - 4, 830)
    s.text(rc.cx, rc.bottom + 30, "reopen anywhere, months later, with the same image", size=14)

    web = browser(s, 890, 750, 360, 240)
    logo(s, "depictio.png", 1222, 752, 22)
    s.text(1050, 769, "127.0.0.1:8058/dashboards", size=12, colour=DIM)
    for i, hgt in enumerate((60, 110, 80, 140, 50)):
        s.rect(Box(912 + i * 32, 966 - hgt, 24, hgt, "#a5d8ff", ""))
    s.rect(Box(1084, 790, 150, 64, "#f8f9fa", ""), colour=GREY)
    s.curve(
        [(1094, 840), (1120, 816), (1150, 828), (1180, 800), (1222, 812)], colour="#7048e8"
    )
    s.rect(Box(1084, 870, 150, 96, "#e5dbff", ""))
    logo(s, "multiqc_icon_color.svg", 1094, 880, 26)
    s.text(1176, 900, "MultiQC", size=12)
    s.text(1159, 940, "tracks, tables", size=12, colour=DIM)
    s.arrow(rc.right + 4, 860, web.x - 4, 860)

    srv = Box(1310, 750, 390, 240, "#fff4e6", "")
    s.rect(srv)
    s.text(srv.cx, 782, "or `cli_config`: a running server", size=15, weight="bold")
    rack(s, 1400, 806, 120, 74, WHITE)
    logo(s, "depictio.png", 1500, 806, 70)
    note(
        s,
        1336,
        916,
        (
            "the task ingests into it (URL + token from",
            "the file): no local stack, nothing to reopen,",
            "the dashboard link is the result",
        ),
        size=13,
    )
    s.curve(
        [(img.right - 30, img.bottom), (img.right - 30, 700), (srv.cx, 700), (srv.cx, srv.y)],
        colour=INK,
    )
    s.arrow(srv.cx, 720, srv.cx, srv.y)

    s.text(
        60,
        FLOW_H - 36,
        "`errorStrategy 'ignore'` in the shipped config: a failed publication is logged and never fails the pipeline (CI sets `terminate`).",
        size=13,
        colour=DIM,
        anchor="start",
    )
    return s


# --------------------------------------------------------------------------
# 2. What a task finds on a shared node.
# --------------------------------------------------------------------------

NODE_W, NODE_H = 1760, 900


def build_shared_node() -> Sketch:
    s = Sketch(NODE_W, NODE_H, seed=11)
    s.heading(
        60,
        64,
        "What a task finds on a shared node, and what it does about it",
        "HPC under Apptainer, or `docker run -u $(id -u)`: other users, no home, a read-only image",
    )
    s.line(60, 104, 1190, 104, colour=SECTION, width=2.4, amount=1.0, passes=1)

    node = Box(60, 140, 1120, 690, "#f8f9fa", "")
    s.rect(node)
    s.text(90, 178, "one compute node", size=18, anchor="start", weight="bold")
    logo(s, "docker.svg", 1070, 154, 38)
    logo(s, "apptainer.png", 1118, 152, 42)

    for i, (uid, fill) in enumerate((("alice · uid 1001", "#a5d8ff"), ("bob · uid 1002", "#ffc9c9"))):
        x = 110 + i * 300
        person(s, x + 30, 200, fill)
        s.text(x + 90, 236, uid, size=13, colour=DIM, anchor="start")
        task = Box(x - 10, 270, 260, 190, WHITE, "")
        s.rect(task)
        s.text(task.cx, 298, "`DEPICTIO_INGEST`", size=14, weight="bold")
        cylinder(s, x + 40, 316, 52, 66, "#b2f2bb")
        pail(s, x + 122, 318, 58, 64, "#ffd8a8")
        stack(s, x + 200, 320, 48, 58, "#ffc9c9")
        s.text(task.cx, 420, "its own stack in its work dir,", size=12, colour=DIM)
        s.text(task.cx, 440, "ports picked free", size=12, colour=DIM)

    tmp = folder(s, 100, 500, 580, 300, "#fff9db", "")
    s.text(130, 546, "`/tmp`, the node's, shared by its users", size=16, anchor="start")
    rows = (
        ("`mongodb-27017.sock`", "bob's, stale: alice's mongod aborted", "cross", "now `--nounixsocket`"),
        ("`seaweedfs-s3-9000.sock`", "another uid's: cannot be removed", "cross", ""),
        ("`seaweedfs-u1001-s3-9000.sock`", "per-uid names, on every stack", "tick", ""),
        ("`seaweedfs-u1002-s3-9010.sock`", "", "tick", ""),
    )
    for i, (name, why, mark, fix) in enumerate(rows):
        y = 594 + i * 50
        page(s, 130, y - 22, 22, 28)
        s.text(166, y, name, size=14, anchor="start")
        if why:
            s.text(166, y + 19, why, size=12, colour=DIM, anchor="start")
        if mark == "cross":
            s.cross(648, y - 6, size=8)
        else:
            tick(s, 648, y - 6, size=8)
        if fix:
            s.text(470, y + 19, fix, size=12, colour=SECTION, anchor="start")

    ro = Box(720, 270, 430, 160, "#e7f5ff", "")
    s.rect(ro)
    s.lock(752, 304, 12)
    s.text(776, 310, "the image is read-only", size=16, anchor="start")
    note(
        s,
        748,
        342,
        (
            "nothing is written under `/opt`: the services",
            "run from the prefix, their data in `$PWD/stack`",
        ),
        size=13,
    )
    home = Box(720, 456, 430, 160, "#ebfbee", "")
    s.rect(home)
    s.text(748, 494, "`HOME=/`, not writable", size=16, anchor="start")
    note(
        s,
        748,
        526,
        (
            "a uid the image does not know has no home:",
            "the module points `HOME` at `$PWD/.home`",
        ),
        size=13,
    )
    net = Box(720, 642, 430, 158, PINK, "")
    s.rect(net)
    logo(s, "anaconda.svg", 740, 660, 26)
    s.text(776, 680, "no network to conda-forge", size=16, anchor="start")
    note(
        s,
        748,
        712,
        ("every service is in the image:", "the task never asks for one"),
        size=13,
    )

    checks = Box(1240, 140, 460, 690, WHITE, "")
    s.rect(checks)
    s.text(1268, 180, "held true in CI, on every change", size=18, anchor="start")
    logo(s, "githubactions.svg", 1644, 154, 36)
    items = (
        ("`docker -u $(id -u)` + `--read-only`", "and a private tmpfs `/tmp`"),
        ("Apptainer `--containall`", "from a `.sif` built in CI"),
        ("no `from conda-forge`", "in the task's log"),
        ("no file owned by another uid", "in the work directory"),
        ("no `env/` in the artifact", "only what a reopen reads"),
        ("reopen, then a clean stop", "no `mongod.lock` left behind"),
    )
    for i, (head, sub) in enumerate(items):
        y = 240 + i * 94
        tick(s, 1278, y - 6, size=9)
        s.text(1300, y, head, size=15, anchor="start")
        s.text(1300, y + 22, sub, size=13, colour=DIM, anchor="start")
    s.text(
        60,
        NODE_H - 34,
        "Not covered yet: stack data on NFS/Lustre work dirs (MongoDB needs working locks); a `scratch` or `$TMPDIR` home would avoid it.",
        size=13,
        colour=DIM,
        anchor="start",
    )
    return s


# --------------------------------------------------------------------------
# 3. What CI runs.
# --------------------------------------------------------------------------

CI_W, CI_H = 1760, 1000

PIPELINES = (
    ("rnaseq", "3.26.0", "full run; also feeds Apptainer", "ok"),
    ("sarek", "3.11.0", "", "ok"),
    ("airrflow", "5.1.2", "needs the strict parser", "ok"),
    ("taxprofiler", "2.0.1", "", "ok"),
    ("funcscan", "4.0.0", "", "ok"),
    ("ampliseq", "2.18.0", "", "ok"),
    ("smrnaseq", "2.4.1", "parses with v1 only: retried", "warn"),
    ("viralrecon", "3.0.0", "v1 parser, `--skip_pangolin`", "warn"),
    ("scrnaseq", "4.2.0", "template wants a megatest", "out"),
)


def build_ci() -> Sketch:
    s = Sketch(CI_W, CI_H, seed=5)
    s.heading(
        60,
        64,
        "What CI runs on every change to the module, the subworkflow or the image",
        "`.github/workflows/build-images.yaml`: the image per arch, both engines, nine nf-core releases",
    )
    s.line(60, 104, 1190, 104, colour=SECTION, width=2.4, amount=1.0, passes=1)
    logo(s, "github.svg", 1596, 40, 44)
    logo(s, "githubactions.svg", 1652, 40, 44)

    section(s, 60, 160, "1 · THE IMAGE, ON BOTH ENGINES")
    build = Box(60, 180, 300, 230, "#fff9db", "")
    s.rect(build)
    s.text(build.cx, 212, "build the image", size=17)
    logo(s, "docker.svg", 84, 244, 70)
    for i, arch in enumerate(("amd64", "arm64")):
        b = Box(190, 236 + i * 50, 140, 38, WHITE, "")
        s.rect(b, colour=GREY)
        s.text(b.cx, b.y + 25, arch, size=14)
    s.text(build.cx, 366, "build-time check of the", size=13, colour=DIM)
    s.text(build.cx, 386, "preinstalled services", size=13, colour=DIM)

    dk = Box(420, 180, 420, 230, "#e7f5ff", "")
    s.rect(dk)
    logo(s, "docker.svg", 440, 194, 36)
    s.text(488, 220, "Docker, as nf-core runs it", size=17, anchor="start")
    for i, (line, sub) in enumerate(
        (
            ("iris: `local up` → ingest → down", "runner's uid, read-only"),
            ("the module, `-profile docker`", "Nextflow 26.10, `-u uid`"),
            ("`cli_config` → running instance", "no artifact"),
            ("reopen: 150 rows, clean stop", ""),
        )
    ):
        y = 264 + i * 38
        tick(s, 446, y - 5, size=7)
        s.text(464, y, line, size=14, anchor="start")
        if sub:
            s.text(826, y, sub, size=11, colour=DIM, anchor="end")

    sif = Box(900, 180, 240, 230, WHITE, "")
    s.rect(sif)
    s.text(sif.cx, 214, "`.sif` job", size=17)
    page(s, sif.cx - 30, 236, 60, 76, "#d0bfff")
    s.text(sif.cx, 296, "`.sif`", size=14)
    s.text(sif.cx, 344, "`docker-daemon://` →", size=13, colour=DIM)
    s.text(sif.cx, 364, "`apptainer build`, handed on", size=13, colour=DIM)
    s.text(sif.cx, 384, "as an artifact, disk freed", size=13, colour=DIM)

    ap = Box(1200, 180, 500, 230, "#ebfbee", "")
    s.rect(ap)
    logo(s, "apptainer.png", 1218, 192, 40)
    s.text(1268, 220, "Apptainer, as a cluster runs it", size=17, anchor="start")
    for i, line in enumerate(
        (
            "rnaseq's results through the subworkflow",
            "`-profile apptainer`, the user's uid",
            "reopen with `--containall`, clean stop",
        )
    ):
        y = 268 + i * 42
        tick(s, 1226, y - 5, size=7)
        s.text(1244, y, line, size=14, anchor="start")
    s.arrow(build.right + 4, 295, dk.x - 4, 295)
    s.arrow(dk.right + 4, 295, sif.x - 4, 295)
    s.arrow(sif.right + 4, 295, ap.x - 4, 295)

    section(s, 60, 480, "2 · NINE nf-core RELEASES THROUGH THE SUBWORKFLOW")
    logo(s, "nf-core.png", 640, 450, 42)
    s.text(
        60,
        510,
        "`-profile test,docker`, cloned with git (not GitHub's API) → `DEPICTIO_PUBLISH` → asserted: status `success`, the expected template id,",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.text(
        60, 530, "≥ 1 dashboard, no `env/`, no root-owned file → reopen", size=13, colour=DIM, anchor="start"
    )
    cw, ch = 360, 110
    fills = {"ok": "#ebfbee", "warn": "#fff9db", "out": PINK}
    for i, (name, version, why, state) in enumerate(PIPELINES):
        col, row = i % 3, i // 3
        x, y = 60 + col * (cw + 24), 556 + row * (ch + 22)
        b = Box(x, y, cw, ch, fills[state], "")
        s.rect(b)
        logo(s, f"nf-core-{name}.webp", x + 14, y + 12, 140, 59)
        s.text(x + 168, y + 48, version, size=17, anchor="start")
        if why:
            s.text(x + 16, y + 94, why, size=13, colour=DIM, anchor="start")
        if state == "ok":
            tick(s, x + cw - 30, y + 38, size=11)
        elif state == "warn":
            tick(s, x + cw - 30, y + 38, size=11)
            warning(s, x + cw - 66, y + 40, size=11)
        else:
            s.cross(x + cw - 30, y + 38, size=11)

    turned = Box(1220, 556, 480, 374, WHITE, "")
    s.rect(turned)
    s.text(1244, 592, "what the matrix turned up", size=17, anchor="start")
    s.text(1244, 616, "none of it a fault in the module", size=13, colour=SECTION, anchor="start")
    blocks = (
        (
            "Nextflow 26.10 parses strictly",
            ("a parse error, and only that, reruns", "with `NXF_SYNTAX_PARSER=v1` + a warning"),
        ),
        (
            "GitHub's API rate limit",
            ("pipelines cloned with git; pangolin's", "database update skipped (optional DC)"),
        ),
        (
            "a template for a megatest",
            ("scrnaseq needs `aligner_cellranger/`;", "one test run (STAR) never has it"),
        ),
    )
    for i, (head, lines) in enumerate(blocks):
        y = 664 + i * 90
        if i < 2:
            warning(s, 1256, y - 6, size=10)
        else:
            s.cross(1256, y - 6, size=9)
        s.text(1280, y, head, size=15, anchor="start")
        note(s, 1280, y + 24, lines, size=13)
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
    """Write the flow, shared-node and CI schemas under --out."""
    write(build_flow(), out, "flow", png=png)
    write(build_shared_node(), out, "shared_node", png=png)
    write(build_ci(), out, "ci", png=png)


if __name__ == "__main__":
    app()
