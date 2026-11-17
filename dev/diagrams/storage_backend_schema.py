#!/usr/bin/env python3
"""Render the instance storage schema (#1358) as a hand-drawn SVG (+ PNG).

One diagram for the PR and ``docs/google-cloud-storage.md``. Everything in it is
the real thing: the callers that reach the instance bucket and the method each
one calls, the two ``.env`` spellings, the registry, what each backend stores
and how it authenticates and commits, the whole ``StorageBackend`` contract,
what adding Azure takes, and the suites that check it.

Logos are embedded from ``dev/diagrams/logos/``; see its README.

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
    DIM,
    GREEN,
    GREY,
    INK,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    bucket,
    dot,
    tick,
    write,
)
from template_params import (  # noqa: E402
    CODE_DIM,
    CODE_INK,
    CODE_KEY,
    CODE_NUM,
    CODE_STR,
    SECTION,
    TICK,
    code,
    logo,
    mono,
    section,
)

app = typer.Typer(add_completion=False)

W, H = 1760, 1300
OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "images" / "storage-backend"


def _store_card(
    s: Sketch,
    box: Box,
    logos: tuple[str, ...],
    title: str,
    subtitle: str,
    location: str,
    facts: tuple[tuple[str, str], ...],
) -> None:
    """A store: its logos and name, a bucket, where a table lands, and how it is reached."""
    s.rect(box)
    for i, name in enumerate(logos):
        logo(s, name, box.x + 16 + i * 38, box.y + 14, 30)
    tx = box.x + 24 + len(logos) * 38
    s.text(tx, box.y + 34, title, size=16, weight="bold", anchor="start")
    s.text(tx, box.y + 54, subtitle, size=12.5, colour=DIM, anchor="start")
    bucket(s, box.x + 78, box.y + 128, 96, 56, WHITE)
    mono(s, box.x + 150, box.y + 96, location, size=12.5, colour=SECTION)
    for i, (label, value) in enumerate(facts):
        y = box.y + 128 + i * 28
        tick(s, box.x + 156, y - 4, size=5)
        s.text(box.x + 170, y, label, size=12.5, colour=DIM, anchor="start")
        s.text(box.x + 262, y, value, size=12.5, anchor="start")


def build() -> Sketch:
    s = Sketch(W, H)
    s.heading(
        60,
        64,
        "One storage interface for the instance's bucket: S3 or Google Cloud Storage",
        "`DEPICTIO_STORAGE_BACKEND` picks the backend; every read and write of Depictio's own objects goes through it (#1358)",
    )
    s.line(60, 104, 1250, 104, colour=SECTION, width=2.4, amount=1.0, passes=1)

    # -- 1 · who asks -----------------------------------------------------------------
    section(s, 60, 160, "1 · WHAT READS AND WRITES THE BUCKET")
    callers = Box(60, 180, 440, 470, WHITE, "")
    s.rect(callers)
    logo(s, "depictio.png", 78, 194, 34)
    s.text(122, 218, "server, worker and CLI alike", size=13, colour=DIM, anchor="start")
    rows = (
        ("API cleanup", "delete_prefix(dc_id)", "project, collection and table deletes"),
        ("files & tracks", "iter_chunks · presign_get", "images, 3D structures, genome tracks"),
        ("ingest (Celery, CLI)", "backend.url(dc_id)", "where each Delta table is written"),
        ("Polars / delta-rs", "instance_polars_options()", "the same bucket, in their spelling"),
        ("CLI uploads", "upload_file(key, path)", "images, tracks, GeoJSON, MultiQC"),
        ("startup", 'check(["bucket", "write"])', "a broken bucket stops the boot"),
    )
    for i, (label, call, what) in enumerate(rows):
        y = 258 + i * 67
        s.text(78, y, label, size=14, weight="bold", anchor="start")
        mono(s, 78, y + 21, call, size=12.5, colour=SECTION)
        s.text(78, y + 40, what, size=12, colour=DIM, anchor="start")
        if i:
            s.line(78, y - 19, 482, y - 19, colour=GREY, width=0.8, amount=0.3, passes=1)

    # -- 2 · one setting --------------------------------------------------------------
    section(s, 540, 160, "2 · ONE SETTING PICKS THE BACKEND")
    env_s3 = code(
        s,
        540,
        180,
        284,
        [
            ("DEPICTIO_STORAGE_BACKEND=s3", CODE_NUM),
            ("DEPICTIO_S3_BUCKET=depictio-bucket", CODE_INK),
            ("DEPICTIO_S3_ROOT_USER=…", CODE_DIM),
            ("DEPICTIO_S3_ROOT_PASSWORD=…", CODE_DIM),
        ],
        size=11.5,
        title=".env (default)",
    )
    env_gcs = code(
        s,
        838,
        180,
        284,
        [
            ("DEPICTIO_STORAGE_BACKEND=gcs", CODE_NUM),
            ("DEPICTIO_GCS_BUCKET=my-bucket", CODE_INK),
            ("# no key: ADC, Workload", CODE_STR),
            ("# Identity on GKE", CODE_STR),
        ],
        size=11.5,
        title=".env (GCS)",
    )
    factory = Box(
        620,
        340,
        420,
        86,
        YELLOW,
        "`instance_storage(settings | CLI_config)`",
        ("the backend the setting names, from the registry", "clients are built on first use"),
    )
    s.box(factory)
    s.arrow(env_s3.cx, env_s3.bottom + 8, factory.x + 110, factory.y - 10)
    s.arrow(env_gcs.cx, env_gcs.bottom + 8, factory.right - 110, factory.y - 10)
    s.arrow(callers.right + 8, 330, factory.x - 10, factory.cy)

    reg = Box(540, 460, 580, 190, WHITE, "")
    s.rect(reg)
    cols = (558, 640, 736, 1010)
    for x, head in zip(cols, ("name", "scheme", "class", "library")):
        s.text(x, 488, head, size=13, colour=DIM, anchor="start")
    s.line(552, 498, 1108, 498, colour=GREY, width=1.0, amount=0.4, passes=1)
    registry = (
        ("s3", "s3://", "S3Backend", "boto3", True),
        ("gcs", "gs://", "GCSBackend(ObstoreBackend)", "obstore", True),
        ("azure", "az://", "AzureBackend(ObstoreBackend)", "obstore", False),
    )
    reg_rows: list[float] = []
    for i, (name, scheme, cls, lib, shipped) in enumerate(registry):
        y = 528 + i * 34
        reg_rows.append(y - 4)
        colour = INK if shipped else GREY
        mono(s, cols[0], y, name, size=12.5, colour=colour)
        mono(s, cols[1], y, scheme, size=12.5, colour=SECTION if shipped else GREY)
        mono(s, cols[2], y, cls, size=12.5, colour=colour)
        mono(s, cols[3], y, lib, size=12.5, colour=colour)
        if shipped:
            tick(s, 1090, y - 4, size=6)
        else:
            dot(s, 1090, y - 4, GREY)
    s.text(
        558,
        632,
        "`object_schemes()` feeds every location validator: a new scheme needs no edit there",
        size=12,
        colour=DIM,
        anchor="start",
    )
    s.arrow(factory.cx, factory.bottom + 8, factory.cx, reg.y - 8)

    # -- 3 · where the bytes land -----------------------------------------------------
    section(s, 1160, 160, "3 · WHERE THE BYTES LAND")
    s3_card = Box(1160, 180, 540, 225, GREEN, "")
    _store_card(
        s,
        s3_card,
        ("amazons3.svg", "minio.svg"),
        "S3-compatible",
        "bundled SeaweedFS · MinIO · AWS · NetApp",
        "s3://depictio-bucket/<dc_id>/",
        (
            ("auth", "key pair, DEPICTIO_S3_ROOT_*"),
            ("commits", "single writer (unsafe rename)"),
            ("signed URLs", "SigV4, on the public URL"),
        ),
    )
    gcs_card = Box(1160, 425, 540, 225, VIOLET, "")
    _store_card(
        s,
        gcs_card,
        ("googlecloudstorage.svg",),
        "Google Cloud Storage",
        "native gs://, through obstore (Rust object_store)",
        "gs://my-bucket/<dc_id>/",
        (
            ("auth", "no key: ADC, GKE Workload Identity"),
            ("commits", "GCS preconditions, atomic"),
            ("signed URLs", "key file, or IAM signBlob"),
        ),
    )
    s.arrow(1122, reg_rows[0], s3_card.x - 10, s3_card.bottom - 40)
    s.arrow(1122, reg_rows[1], gcs_card.x - 10, gcs_card.cy)

    # -- 4 · the contract ------------------------------------------------------------
    section(s, 60, 712, "4 · THE CONTRACT EVERY BACKEND FULFILS")
    contract = Box(60, 732, 1060, 270, WHITE, "")
    s.rect(contract)
    groups = (
        ("addresses", "url · key_of", "<scheme>://bucket/key, and back to the key"),
        (
            "reads",
            "list_objects · list_folders · head · read_bytes · read_range · iter_chunks",
            "S3 prefix semantics on every store; StorageNotFound is a FileNotFoundError",
        ),
        (
            "writes",
            "put_bytes · upload_file · delete_keys · delete_prefix",
            "multipart=False for one PUT; bulk delete falls back to one by one",
        ),
        (
            "bucket",
            "bucket_exists · ensure_bucket · check",
            "GCS checks only: a bucket needs a project and a location",
        ),
        (
            "hand-off",
            "presign_get · storage_options · filesystem",
            "browsers, Polars / delta-rs, fsspec",
        ),
    )
    for i, (group, methods, meaning) in enumerate(groups):
        y = 768 + i * 48
        s.text(80, y + 8, group, size=14, weight="bold", anchor="start")
        mono(s, 200, y, methods, size=12.5, colour=SECTION)
        s.text(200, y + 20, meaning, size=12, colour=DIM, anchor="start")
        if i:
            s.line(76, y - 16, 1104, y - 16, colour=GREY, width=0.8, amount=0.3, passes=1)

    # -- 5 · adding azure -------------------------------------------------------------
    section(s, 1160, 712, "5 · ADDING AZURE LATER")
    azure = code(
        s,
        1160,
        732,
        540,
        [
            ("@register_backend", CODE_KEY),
            ("class AzureBackend(ObstoreBackend):", CODE_INK),
            ('    name, scheme = "azure", "az"', CODE_STR),
            ("    def _make_store(self):", CODE_INK),
            ("        return AzureStore(self.bucket, ...)", CODE_DIM),
            ("    def storage_options(self): ...", CODE_INK),
        ],
        size=12.5,
        title="models/storage/azure.py",
    )
    checks = (
        "one settings section (DEPICTIO_AZURE_*) and one test fixture (Azurite)",
        "no caller changes: a guard test fails if code names a backend class",
    )
    for i, line in enumerate(checks):
        y = azure.bottom + 30 + i * 28
        tick(s, 1172, y - 4, size=6)
        s.text(1188, y, line, size=12.5, anchor="start")

    # -- 6 · checked ------------------------------------------------------------------
    section(s, 60, 1062, "6 · CHECKED AGAINST REAL STORES")
    code(
        s,
        60,
        1082,
        1060,
        [
            (
                "$ docker run -d -p 4443:4443 tustvold/fake-gcs-server -scheme http -backend memory",
                CODE_INK,
            ),
            (
                "$ DEPICTIO_TEST_GCS_EMULATOR=http://localhost:4443 DEPICTIO_TEST_GCS_PUBLIC=1 \\",
                CODE_INK,
            ),
            ("    pytest depictio/tests/storage          # CI: the storage-gcs job", CODE_INK),
            (
                "✓ put · read · range · stream · listing as S3 prefixes · bulk delete · fsspec",
                CODE_STR,
            ),
            ("✓ Delta write → append → read → vacuum at backend.url(dc_id)", CODE_STR),
            ("✓ anonymous reads of gs://gcp-public-data--broad-references", CODE_STR),
            ("12 passed · gcs_live, on a real bucket: concurrent commits, signed URLs", CODE_DIM),
        ],
        size=12.5,
        title="terminal",
    )
    still = Box(1160, 1082, 540, 176, PINK, "")
    s.rect(still, dashed=True, colour=RED)
    s.text(1180, 1112, "still S3-only, on purpose", size=15, weight="bold", anchor="start")
    for i, line in enumerate(("project migration bundles", "S3-to-S3 backups")):
        y = 1144 + i * 26
        s.cross(1186, y - 4, size=5)
        s.text(1200, y, line, size=13, anchor="start")
    s.text(
        1180,
        1214,
        "on a GCS instance they refuse with a clear message",
        size=12.5,
        colour=DIM,
        anchor="start",
    )
    s.text(
        1180,
        1236,
        "(`require_s3_instance`), never write to S3",
        size=12.5,
        colour=DIM,
        anchor="start",
    )
    s.text(
        W - 60,
        H - 14,
        "the instance bucket only: run folders and remote reads keep their own S3 access",
        size=12.5,
        colour=TICK,
        anchor="end",
    )
    return s


@app.command()
def main(
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
) -> None:
    """Write the schema SVG (and PNG) under docs/images."""
    write(build(), OUT, "layers", png=png)


if __name__ == "__main__":
    app()
