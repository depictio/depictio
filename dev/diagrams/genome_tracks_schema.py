#!/usr/bin/env python3
"""Render the genome-browser schema as a hand-drawn SVG (+ PNG).

One diagram: how a ``genomic_tracks`` collection feeds the ``jbrowse``
component. The manifest is a table of track files; the dashboard filters pick
its rows, which become the browser's tracks; the files themselves, uploaded or
read in place, reach the browser only through the API's track proxy; a click in
the browser filters the dashboard back.

Usage:
    python dev/diagrams/genome_tracks_schema.py --out docs/images/genome-browser
    # writes <out>_tracks.svg/.png

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
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    bucket,
    folder,
    write,
)

app = typer.Typer(add_completion=False)

W, H = 1340, 660


def build_tracks() -> Sketch:
    """Top lane: rows (manifest, collection, component). Bottom lane: bytes.

    The split is the point: the browser learns *which* tracks from the
    collection's rows under the dashboard filters, and reads *what is in them*
    through the proxy, never from storage directly.
    """
    s = Sketch(W, H)
    s.heading(
        46,
        52,
        "A genomic_tracks collection feeds the jbrowse component",
        "rows say which tracks open; bytes come through the API",
    )

    # -- top lane: rows ------------------------------------------------------
    manifest = Box(
        60,
        130,
        290,
        150,
        WHITE,
        "tracks.tsv (manifest)",
        (
            "one row per track file:",
            "`S1 · bigwig · cov/S1.bw`",
            "`S1 · bam · bam/S1.bam`",
            "`S2 · vcf · s3://run/S2.vcf.gz`",
        ),
    )
    collection = Box(
        440,
        130,
        330,
        150,
        YELLOW,
        "genomic_tracks collection",
        (
            "a Delta table, like any table:",
            "filtered, linked, versioned",
            "`assembly`, `remote_base_uri`,",
            "`display_defaults`, `presets`",
        ),
    )
    component = Box(
        880,
        112,
        400,
        210,
        WHITE,
        "",
        (),
    )
    s.box(manifest)
    s.box(collection)
    frame = browser(s, component.x, component.y, component.w, component.h)
    s.text(frame.cx, frame.y + 56, "jbrowse component", size=18, weight="bold")
    for i, (label, colour) in enumerate(
        (("S1 coverage", BLUE), ("S1 reads", GREEN), ("genes (assembly)", VIOLET))
    ):
        y = frame.y + 80 + i * 36
        s.rect(Box(frame.x + 24, y, frame.w - 48, 26, colour, "", ()), colour=GREY)
        s.text(frame.x + 36, y + 18, label, size=13, anchor="start")
    s.text(
        frame.cx, frame.bottom - 12, "`locus_from` moves it to a picked row", size=13, colour=DIM
    )

    s.arrow(manifest.right, manifest.cy, collection.x, collection.cy)
    s.text((manifest.right + collection.x) / 2, manifest.cy - 12, "ingest", size=13, colour=DIM)
    s.arrow(collection.right, collection.cy, component.x, collection.cy)
    s.text(
        (collection.right + component.x) / 2,
        collection.cy - 12,
        "rows that match",
        size=13,
        colour=DIM,
    )

    # -- dashboard filters, both ways -------------------------------------------
    filters = Box(
        440,
        360,
        330,
        92,
        ORANGE,
        "Dashboard filters",
        ("a sample, a table row, a lasso:", "reach the collection over links"),
    )
    s.box(filters)
    s.arrow(filters.cx, filters.y, collection.cx, collection.bottom)
    s.arrow(
        component.x + 60,
        component.bottom,
        filters.right,
        filters.cy,
        dashed=True,
    )
    s.text(905, 398, "a click on a feature filters", size=13, colour=DIM, anchor="start")
    s.text(905, 417, "the dashboard on its sample", size=13, colour=DIM, anchor="start")

    # -- bottom lane: bytes ------------------------------------------------------
    folder(s, 80, 330, 120, 80, GREEN, "run files")
    s.text(140, 434, "internal: uploaded", size=13, colour=DIM)
    bucket(s, 140, 540, 110, 64, BLUE)
    s.text(140, 630, "external: s3:// https://", size=13, colour=DIM)

    proxy = Box(
        700,
        500,
        330,
        104,
        VIOLET,
        "API track proxy",
        ("signed URLs, read access re-checked,", "allow-listed hosts and buckets"),
    )
    s.box(proxy)
    s.arrow(200, 405, proxy.x, proxy.y + 26)
    s.arrow(200, 575, proxy.x, proxy.bottom - 26)
    s.arrow(proxy.right, proxy.cy, component.x + 300, component.bottom)
    s.text(proxy.right + 50, proxy.y + 10, "byte ranges", size=13, colour=DIM, anchor="start")
    return s


@app.command()
def main(
    out: Path = typer.Option(..., help="Output prefix, e.g. docs/images/genome-browser"),
    png: bool = typer.Option(True, help="Also render a PNG"),
) -> None:
    write(build_tracks(), out, "tracks", png=png)


if __name__ == "__main__":
    app()
