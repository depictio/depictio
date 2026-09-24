#!/usr/bin/env python3
"""Render the container-free server's two schemas as hand-drawn SVGs (+ PNGs).

* ``same_code`` — one server, two ways to run it: the API, worker and viewer are
  the same code in both columns, only where MongoDB, Redis and MinIO come from
  and how the processes are started differs.
* ``up_flow``   — what `depictio local up` does between the command and a
  dashboard, what it leaves under ~/.depictio/local, and how it fails.

Usage:
    python dev/diagrams/local_server.py --out docs/images/v1.4/local/schema
    # writes <out>_same_code.svg/.png and <out>_up_flow.svg/.png

See sketch.py for the drawing primitives and the PNG rendering requirements.
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
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)


# --------------------------------------------------------------------------
# 1. One server, two ways to run it.
# --------------------------------------------------------------------------

SAME_W, SAME_H = 1400, 760


def build_same_code() -> Sketch:
    s = Sketch(SAME_W, SAME_H)
    s.heading(
        46,
        52,
        "One server, two ways to run it",
        "only configuration differs: every service is reached through the existing `DEPICTIO_*` variables",
    )

    code = Box(
        450,
        110,
        500,
        165,
        YELLOW,
        "the same code",
        (
            "`depictio.api`: FastAPI + Beanie",
            "`depictio.api.celery_worker`: Celery",
            "`depictio/viewer/dist`: React SPA",
            "`depictio.models`: shared models",
            "`depictio run`: template ingestion",
        ),
    )
    s.box(code)

    s.text(340, 372, "Docker / Kubernetes", size=21, weight="bold")
    s.text(1057, 372, "`depictio local up`", size=21, weight="bold")
    s.arrow(code.x + 90, code.bottom, 340, 350)
    s.arrow(code.right - 90, code.bottom, 1057, 350)

    docker = [
        ("MongoDB", ("`mongo:8.0.14` image",)),
        ("Redis", ("`redis` image",)),
        ("MinIO", ("`minio` image",)),
        ("API", ("gunicorn, 4 workers",)),
        ("viewer", ("nginx, or Vite in dev",)),
        ("auth", ("multi-user, public", "or single-user")),
    ]
    local = [
        ("MongoDB", ("`mongodb 8.0.*`", "conda-forge")),
        ("Redis", ("`redis-server`", "conda-forge")),
        ("MinIO", ("`minio-server`", "conda-forge")),
        ("API", ("uvicorn, 1 worker", "on 127.0.0.1")),
        ("viewer", ("`dist/` in the wheel,", "served by FastAPI")),
        ("auth", ("single-user",)),
    ]
    for origin, items, fill in ((60, docker, BLUE), (775, local, GREEN)):
        for i, (title, lines) in enumerate(items):
            col, row = i % 3, i // 3
            s.box(Box(origin + col * 195, 400 + row * 112, 175, 96, fill, title, lines))

    notes_left = (
        "one container per service, images from a registry",
        "the viewer container talks to the API over the network",
    )
    notes_right = (
        "binaries installed once by `py-rattler` (pixi's library)",
        "into `~/.depictio/local/env`: no conda, no Docker",
        "data, logs, keys and secrets under `~/.depictio/local`",
    )
    for i, line in enumerate(notes_left):
        s.text(60, 655 + i * 22, line, size=14, colour=DIM, anchor="start")
    for i, line in enumerate(notes_right):
        s.text(775, 655 + i * 22, line, size=14, colour=DIM, anchor="start")

    s.line(700, 360, 700, 720, dashed=True, colour=GREY)
    return s


# --------------------------------------------------------------------------
# 2. What `depictio local up` does.
# --------------------------------------------------------------------------

FLOW_W, FLOW_H = 1420, 610


def build_up_flow() -> Sketch:
    s = Sketch(FLOW_W, FLOW_H)
    s.heading(
        46,
        52,
        "What `depictio local up` does",
        "from a bare machine with uv to a dashboard: ~40 s the first time, ~20 s after",
    )

    steps = [
        ("`uvx`", BLUE, ("resolves", "`depictio[local]`", "~2 GB env, cached")),
        ("binaries", ORANGE, ("`py-rattler` →", "conda-forge", "first run only, 8 s")),
        ("ports, secrets", WHITE, ("8058 27018 6379 9000", "or any free port", "`secrets.json` 0600")),
        ("services", GREEN, ("`mongod`", "`redis-server`", "`minio server`")),
        ("server", YELLOW, ("`uvicorn`, 1 worker", "`celery`, 2 processes", "wait for `/health`")),
        ("ingest", VIOLET, ("`depictio run`", "`--template --data-root`", "then `/dashboards`")),
    ]
    boxes = []
    for i, (title, fill, lines) in enumerate(steps):
        box = Box(40 + i * 230, 120, 190, 132, fill, title, lines)
        s.box(box)
        boxes.append(box)
    for left, right in zip(boxes, boxes[1:]):
        s.arrow(left.right, left.cy, right.x, right.cy)

    s.text(
        (boxes[3].x + boxes[4].right) / 2,
        boxes[3].bottom + 26,
        "each one waited for (TCP port, health endpoint), then for `cli/admin_config.yaml`",
        size=13,
        colour=DIM,
    )

    layout = Box(
        40,
        320,
        420,
        205,
        WHITE,
        "`~/.depictio/local`",
        (
            "`env/`: mongod, redis, minio (~360 MB)",
            "`mongo/` `redis/` `minio/`: data",
            "`keys/` + `cli/admin_config.yaml`",
            "`logs/<service>.log`",
            "`screenshots/`: thumbnails, off the package",
            "`state.json`: pids and ports",
            "`secrets.json`: generated, mode 0600",
        ),
    )
    s.box(layout)

    lifecycle = Box(
        500,
        320,
        420,
        205,
        WHITE,
        "`status` · `down` · `wipe`",
        (
            "`status`: each service, its pid and port",
            "`down`: SIGTERM each process group,",
            "in reverse start order",
            "`wipe`: delete the data, keep the binaries",
            "",
            "a second `up` while running only ingests,",
            "the server is reused as is",
        ),
    )
    s.box(lifecycle)

    failures = Box(
        960,
        320,
        420,
        205,
        PINK,
        "when something goes wrong",
        (
            "a process exits during startup:",
            "stop what was started, name its log",
            "",
            "a default port is taken: pick a free one",
            "`--port` is taken: refuse, say which",
            "",
            "no Chromium: thumbnails off, not errors",
        ),
    )
    s.box(failures)

    s.text(
        40,
        FLOW_H - 30,
        "measured on linux-64: cold uv + conda caches 41 s with the nf-core/rnaseq megatest, warm 20 s, iris example 8 s",
        size=14,
        colour=DIM,
        anchor="start",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v1.4/local/schema"),
        "--out",
        help="Output prefix; <out>_<name>.svg and .png are written next to it.",
    ),
    png: bool = typer.Option(True, help="Also render PNGs through Playwright."),
) -> None:
    """Write the same-code and up-flow schemas under --out."""
    write(build_same_code(), out, "same_code", png=png)
    write(build_up_flow(), out, "up_flow", png=png)


if __name__ == "__main__":
    app()
