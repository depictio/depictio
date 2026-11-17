#!/usr/bin/env python3
"""The instance storage interface (#1358), as a hand-drawn schema.

Callers on the left ask ``instance_storage(cfg)`` for the instance's backend;
the registry maps ``DEPICTIO_STORAGE_BACKEND`` to a backend class, and each
backend brings its own URL scheme. S3 is what ships today, GCS is the next
backend, Azure the one this shape keeps cheap to add.

Usage::

    python dev/diagrams/storage_backend_schema.py            # docs/images/storage-backend_layers.{svg,png}
    python dev/diagrams/storage_backend_schema.py --no-png   # svg only
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
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    bucket,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1320, 700
OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "images" / "storage-backend"


def build() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "One storage interface for the instance's own bucket",
        "callers never branch on the backend: the configuration picks it, the registry builds it",
    )

    # -- callers -------------------------------------------------------------
    callers = [
        Box(46, 130, 250, 78, BLUE, "API routes", ("deletes, presigned URLs",)),
        Box(46, 228, 250, 78, BLUE, "CLI + Celery ingest", ("`backend.url(dc_id)`",)),
        Box(46, 326, 250, 78, BLUE, "Polars / delta-rs", ("`storage_options()`",)),
        Box(46, 424, 250, 78, BLUE, "MultiQC (fsspec)", ("`filesystem()`",)),
    ]
    for b in callers:
        s.box(b)

    # -- factory + registry --------------------------------------------------
    factory = Box(
        388,
        200,
        280,
        120,
        YELLOW,
        "`instance_storage(cfg)`",
        ("`settings` or `CLIConfig`", "`DEPICTIO_STORAGE_BACKEND`", "(default `s3`)"),
    )
    registry = Box(
        388,
        360,
        280,
        112,
        YELLOW,
        "registry",
        ("name → class, one scheme each", "`object_schemes()` feeds", "the URL validators"),
    )
    s.box(factory)
    s.box(registry)
    for b in callers:
        s.arrow(b.right + 8, b.cy, factory.x - 10, factory.cy + (b.cy - factory.cy) * 0.25)
    s.arrow(factory.cx, factory.bottom + 8, registry.cx, registry.y - 10)

    # -- backends ------------------------------------------------------------
    s3 = Box(770, 130, 250, 104, GREEN, "S3Backend", ("boto3 · `s3://`", "SeaweedFS, MinIO, AWS"))
    gcs = Box(770, 270, 250, 104, VIOLET, "GCSBackend", ("obstore · `gs://`", "ADC / Workload Identity"))
    az = Box(770, 410, 250, 104, WHITE, "AzureBackend", ("obstore · `az://`", "a thin subclass, later"))
    s.box(s3)
    s.box(gcs)
    s.box(az, dashed=True)
    for b, dashed in ((s3, False), (gcs, False), (az, True)):
        s.arrow(registry.right + 8, registry.cy, b.x - 10, b.cy, dashed=dashed)

    s.text(s3.right + 14, s3.y + 18, "this PR", size=14, colour="#2b8a3e", anchor="start")
    s.text(gcs.right + 14, gcs.y + 18, "next", size=14, colour=DIM, anchor="start")
    s.text(az.right + 14, az.y + 18, "follow-up", size=14, colour=GREY, anchor="start")

    # -- stores --------------------------------------------------------------
    for b, fill in ((s3, GREEN), (gcs, VIOLET), (az, WHITE)):
        bucket(s, 1215, b.y + 36, 92, 52, fill)

    # -- the contract --------------------------------------------------------
    contract = Box(
        46,
        556,
        W - 92,
        104,
        ORANGE,
        "StorageBackend: the whole contract",
        (
            "`url` · `key_of` · `list_objects` · `head` · `read_bytes` · `read_range` · `put_bytes`"
            " · `upload_file` · `delete_keys` · `delete_prefix`",
            "`bucket_exists` · `ensure_bucket` · `presign_get` · `storage_options` · `filesystem`"
            "   (names follow `DataRoot` where they overlap)",
        ),
    )
    s.box(contract)
    return s


@app.command()
def main(
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the schema SVG (and PNG) under docs/images."""
    write(build(), OUT, "layers", png=png)


if __name__ == "__main__":
    app()
