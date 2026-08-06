#!/usr/bin/env python3
"""Diagrams for the data-binding work: `--bind`, the s3_prefix scan, and sharing.

    python dev/diagrams/data_binding_schemas.py --out docs/images/data_binding

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


def binding_matrix() -> Sketch:
    """What the user has -> what they type -> the scan mode that gets inferred.

    The point of the picture is that the middle column is the only thing the
    user writes: the right-hand column is derived, never typed.
    """
    s = Sketch(1180, 660, seed=11)
    s.heading(
        60,
        56,
        "One flag, five shapes",
        "--bind TAG=LOCATION  ·  the scan mode is inferred, never typed",
    )

    rows = [
        ("A pipeline output folder", "/scratch/run42", "recursive", GREEN, "walks the tree"),
        ("One known file", "./samplesheet.csv", "single", GREEN, ""),
        ("A file on the web", "https://host/data.csv", "url", BLUE, "fetched server-side"),
        ("A bucket prefix", "s3://bucket/run42/*.csv", "s3_prefix", ORANGE, "NEW: remote listing"),
        ("A heterogeneous list", "--manifest ...", "manifest", VIOLET, "stays explicit"),
    ]

    top = 140
    height = 74
    gap = 22
    # Column headers, said once rather than repeated on every row.
    s.text(60, top - 14, "what they have", size=12, anchor="start", colour=GREY)
    s.text(330, top - 14, "what they type", size=12, anchor="start", colour=GREY)
    s.text(812, top - 14, "what gets inferred", size=12, anchor="start", colour=GREY)

    for i, (has, types, mode, colour, note) in enumerate(rows):
        y = top + i * (height + gap)
        s.text(60, y + 43, has, size=16, anchor="start", colour=DIM)

        typed = Box(330, y, 340, height, WHITE, "", ())
        s.rect(typed)
        s.text(typed.cx, y + 44, types, size=17)

        s.arrow(typed.right + 8, y + height / 2, 800, y + height / 2)

        inferred = Box(812, y, 300, height, colour, "", ())
        s.rect(inferred)
        s.text(inferred.cx, y + (36 if note else 44), mode, size=17, weight="bold")
        if note:
            s.text(inferred.cx, y + 58, note, size=13, colour=DIM)

    s.text(
        60,
        640,
        "A template author's choice of scan mode no longer dictates where the data has to live.",
        size=14,
        anchor="start",
        colour=DIM,
    )
    return s


def before_after() -> Sketch:
    """Why remote data used to force a manifest, and why it no longer does."""
    s = Sketch(1180, 560, seed=5)
    s.heading(
        60,
        56,
        "Remote data without a manifest",
        "the manifest existed largely to compensate for a missing remote listing",
    )

    # -- before -----------------------------------------------------------
    s.text(60, 118, "Before", size=19, anchor="start", weight="bold")
    bucket_a = Box(60, 140, 250, 96, YELLOW, "s3://bucket/run42/", ("many files, one pattern",))
    s.box(bucket_a)
    s.arrow(bucket_a.right, bucket_a.cy, 400, bucket_a.cy)
    hand = Box(400, 140, 250, 96, PINK, "write a manifest", ("one row per file, by hand",))
    s.box(hand)
    s.arrow(hand.right, hand.cy, 740, hand.cy)
    host = Box(740, 140, 250, 96, PINK, "host it", ("entries must be URLs",))
    s.box(host)
    s.cross(1050, hand.cy, size=13, colour=RED)
    s.text(1075, hand.cy + 6, "toil", size=15, anchor="start", colour=RED)

    # -- after ------------------------------------------------------------
    s.text(60, 320, "After", size=19, anchor="start", weight="bold")
    bucket_b = Box(60, 342, 250, 96, YELLOW, "s3://bucket/run42/", ("many files, one pattern",))
    s.box(bucket_b)
    s.arrow(bucket_b.right, bucket_b.cy, 400, bucket_b.cy)
    bind = Box(400, 342, 340, 96, ORANGE, "--bind samples=", ("s3://bucket/run42/*.samples.csv",))
    s.box(bind)
    s.arrow(bind.right, bind.cy, 830, bind.cy)
    dc = Box(830, 342, 280, 96, GREEN, "data collection", ("listed + ingested",))
    s.box(dc)

    s.text(
        60,
        500,
        "The glob's * also becomes the cross-DC join key (depictio_manifest_id),",
        size=14,
        anchor="start",
        colour=DIM,
    )
    s.text(
        60,
        522,
        "so two prefixes cross-filter each other with no manifest and no join config.",
        size=14,
        anchor="start",
        colour=DIM,
    )
    return s


def sharing_loop() -> Sketch:
    """Sharing a project so a colleague can run it on their own data.

    The dashed hop is the one that used to be impossible: a received bundle had
    to be copied into the recipient's site-packages before --template saw it.
    """
    s = Sketch(1180, 560, seed=3)
    s.heading(60, 56, "Sharing a project", "same structure, their data, their instance")

    # Transport row. Labels sit above their arrows, clear of both boxes.
    author = Box(60, 150, 230, 100, BLUE, "your project", ("built interactively",))
    s.box(author)
    s.text(348, 188, "template export", size=13, colour=DIM)
    s.arrow(author.right, author.cy, 406, author.cy)

    bundle = Box(406, 150, 250, 100, WHITE, "a folder", ("template.yaml", "dashboards/*.yaml"))
    s.box(bundle)
    s.text(715, 188, "git / zip / chat", size=13, colour=DIM)
    s.arrow(bundle.right, bundle.cy, 830, bundle.cy)

    theirs = Box(830, 150, 260, 100, GREEN, "their CLI", ("--template ./folder",))
    s.box(theirs)

    # The binding hop, coming from below so it reads as a second input to the
    # CLI rather than as another step in the transport chain.
    data = Box(406, 350, 250, 96, ORANGE, "their data", ("local, or s3://",))
    s.box(data)
    s.text(742, 322, "--bind", size=15, colour=DIM)
    s.arrow(data.right, data.cy - 20, 890, theirs.bottom + 8)

    result = Box(830, 420, 260, 90, VIOLET, "their dashboard", ("same layout",))
    s.box(result)
    s.arrow(1050, theirs.bottom, 1050, result.y - 6)

    s.text(
        60,
        524,
        "No admin on your instance, no server-side install, no manifest required.",
        size=14,
        anchor="start",
        colour=DIM,
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/data_binding"), "--out", help="Output path stem"
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also render a PNG"),
) -> None:
    write(binding_matrix(), out, "matrix", png=png)
    write(before_after(), out, "no_manifest", png=png)
    write(sharing_loop(), out, "sharing", png=png)


if __name__ == "__main__":
    app()
