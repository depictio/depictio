#!/usr/bin/env python3
"""Render the serverless-deployment schemas as hand-drawn SVGs.

Three diagrams, each carrying one idea that is tedious to state in prose:

* ``architecture``        — the whole shape: one manifest contract, three
  producers that write it, the real viewer running against a shimmed api, and
  the four tiers a component can land in.
* ``preflight_decides``   — why the export preflight used to answer "Undecided"
  for every figure, and what changed when it became the build's own decision
  path stopped early rather than a second, data-free guess.
* ``phylogeny_two_dcs``   — why a phylogenetic tile disappeared from bundles:
  it reads two data collections, and its own ``dc_id`` names the one that has
  no table by construction.

Usage:
    python dev/diagrams/serverless_schemas.py --out docs/images/serverless
    # writes <out>-preflight-decides.svg and <out>-phylogeny-two-dcs.svg

PNG rendering needs Playwright; pass ``--no-png`` when only the SVG is wanted
(the repo's node Playwright can rasterise them instead). Without a local
Virgil GS the SVG still renders in whatever the fallback list finds.
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
# 0. The whole shape: one contract, three producers, one runtime, four tiers.
# --------------------------------------------------------------------------

ARCH_W, ARCH_H = 1420, 860

CAPTION_ARCH = (
    "Three producers write one manifest; the real viewer runs against a shimmed api that answers "
    "from it, so a bundle is the same React app reading a file instead of a server. Each component "
    "lands in one of four tiers, and only the top one keeps its interactivity."
)


def _architecture() -> Sketch:
    s = Sketch(ARCH_W, ARCH_H, seed=5)
    s.heading(
        60, 52,
        "A dashboard that opens without Depictio",
        "one manifest contract · three producers · the real viewer, shimmed",
    )

    # ---- producers --------------------------------------------------------
    s.text(60, 122, "PRODUCERS", size=15, anchor="start", weight="bold", colour=DIM)
    pa = Box(60, 140, 300, 104, BLUE, "A — from an instance", ("Mongo + Delta + S3",))
    pb = Box(60, 262, 300, 104, BLUE, "B — from a spec", ("YAML + local Parquet",))
    pc = Box(60, 384, 300, 104, BLUE, "C — over the API", ("owner-gated, Celery job",))
    for box in (pa, pb, pc):
        s.box(box)

    # ---- contract ---------------------------------------------------------
    manifest = Box(470, 178, 380, 272, YELLOW, "BundleManifest", (
        "dashboard document (every tab)",
        "data_refs + inline Parquet",
        "bindings · prologues · links",
        "frozen payloads",
        "tiers + provenance",
    ))
    s.box(manifest)
    s.text(660, 476, "schema-pinned, validated both ways", size=14, colour=DIM)

    for box in (pa, pb, pc):
        s.arrow(box.right, box.cy, manifest.x - 8, manifest.cy + (box.cy - pb.cy) * 0.45)

    # ---- runtime ----------------------------------------------------------
    s.text(960, 122, "RUNTIME", size=15, anchor="start", weight="bold", colour=DIM)
    runtime = Box(960, 168, 400, 292, GREEN, "the real viewer", (
        "App.tsx, unmodified",
        "",
        "api.ts → shimmed at build time",
        "hyparquet reads the Parquet",
        "query kernels mirror Polars",
        "bind-and-refill redraws figures",
    ))
    s.box(runtime)
    s.arrow(manifest.right, manifest.cy, runtime.x - 8, runtime.cy)
    s.text(905, manifest.cy - 16, "one", size=13, colour=DIM)
    s.text(905, manifest.cy + 4, "file", size=13, colour=DIM)

    # ---- tiers ------------------------------------------------------------
    s.line(60, 560, 1360, 560, colour=GREY, width=1.2, amount=0.8, passes=1)
    s.text(60, 542, "FOUR TIERS — what a component keeps", size=15,
           anchor="start", weight="bold", colour=DIM)

    tiers = [
        (60, GREEN, "live", ("filters still work",), "184 of 205"),
        (395, BLUE, "partial", ("exact, but heavier",), "0"),
        (730, YELLOW, "frozen", ("a snapshot, and it says so",), "21"),
        (1065, PINK, "omitted", ("absent, with a reason",), "0"),
    ]
    for x, fill, title, lines, count in tiers:
        b = Box(x, 592, 295, 104, fill, title, lines)
        s.box(b)
        s.text(b.cx, 724, count, size=17, weight="bold")

    s.text(710, 768, "across the five reference dashboards, after this branch", size=14, colour=DIM)
    s.text(
        710, 800,
        "every bundle is zero-network: no fetch, no CDN, no tile server, no font host",
        size=14, colour=DIM,
    )
    return s


# --------------------------------------------------------------------------
# 1. One decision, reached twice, instead of two answers that could disagree.
# --------------------------------------------------------------------------

PRE_W, PRE_H = 1340, 700

CAPTION_PREFLIGHT = (
    "The export preflight used to be a second, data-free classifier: it called every "
    "ui-mode figure a binding miss and the modal showed them as Undecided. It is now the "
    "build's own decision path stopped before it produces anything, so a plan and a verdict "
    "cannot disagree."
)


def _preflight() -> Sketch:
    s = Sketch(PRE_W, PRE_H, seed=11)
    s.heading(60, 52, "The preflight decides", "one decision path, reached from two entry points")

    # ---- BEFORE band ------------------------------------------------------
    s.text(60, 116, "BEFORE", size=17, anchor="start", weight="bold", colour=DIM)
    s.line(150, 110, 1280, 110, colour=GREY, width=1.2, amount=0.8, passes=1)

    plan = Box(60, 136, 300, 118, PINK, "preflight", ("reads no data",
                                                      "classifies from metadata"))
    s.box(plan)
    guess = Box(430, 136, 330, 118, PINK, "every figure:", ("frozen / binding_miss",
                                                            "shown as “Undecided”"))
    s.box(guess)
    build = Box(950, 136, 330, 118, BLUE, "build", ("loads the data",
                                                    "binds, then decides"))
    s.box(build)

    s.arrow(plan.right, plan.cy, guess.x - 8, guess.cy)
    s.arrow(guess.right + 8, guess.cy, build.x - 8, build.cy, dashed=True, colour=DIM)
    # Above the dashed arrow, not across it: the stroke would otherwise strike
    # the second line through.
    s.text(855, guess.cy - 42, "…until the", size=14, colour=DIM)
    s.text(855, guess.cy - 22, "build says", size=14, colour=DIM)

    s.cross(855, guess.cy + 44, size=10)
    s.text(855, guess.cy + 76, "two answers", size=14, colour=RED)

    s.text(
        670, 292,
        "on the reference dashboards: 18 predicted binding misses, 5 real ones",
        size=15, colour=RED,
    )

    # ---- AFTER band -------------------------------------------------------
    s.text(60, 376, "AFTER", size=17, anchor="start", weight="bold", colour=DIM)
    s.line(140, 370, 1280, 370, colour=GREY, width=1.2, amount=0.8, passes=1)

    entry_pre = Box(60, 400, 270, 96, VIOLET, "preflight", ("viewer",))
    entry_build = Box(60, 528, 270, 96, BLUE, "build", ("owner",))
    s.box(entry_pre)
    s.box(entry_build)

    shared = Box(430, 424, 400, 176, GREEN, "decide_figure", (
        "load the data collection",
        "build the server figure",
        "match each trace to one group",
    ))
    s.box(shared)

    s.arrow(entry_pre.right, entry_pre.cy, shared.x - 8, shared.cy - 34)
    s.arrow(entry_build.right, entry_build.cy, shared.x - 8, shared.cy + 34)

    out_tiers = Box(930, 400, 350, 96, WHITE, "tier table", ("24 live · 2 frozen · 0 undecided",))
    out_bundle = Box(930, 528, 350, 96, WHITE, "bundle", ("the same verdicts, shipped",))
    s.box(out_tiers)
    s.box(out_bundle)

    s.arrow(shared.right, shared.cy - 34, out_tiers.x - 8, out_tiers.cy)
    s.arrow(shared.right, shared.cy + 34, out_bundle.x - 8, out_bundle.cy)

    s.text(
        630, 634,
        "the preflight stops here: no Parquet, no Celery compute, no manifest",
        size=14, colour=DIM,
    )
    s.text(
        630, 660,
        "penguins: the 2 survivors are a lowess trendline and a pandas .groupby()",
        size=14, colour=DIM,
    )
    return s


# --------------------------------------------------------------------------
# 2. A tile whose own dc_id names the collection that has no table.
# --------------------------------------------------------------------------

PHY_W, PHY_H = 1340, 660

CAPTION_PHYLOGENY = (
    "A phylogenetic tile reads two data collections, and its own dc_id names the tree — a "
    "Newick file with no Delta table by construction. The producer asked that one for tabular "
    "data, got a 404 and dropped the whole tile, so bundles shipped no tree at all."
)


def _phylogeny() -> Sketch:
    s = Sketch(PHY_W, PHY_H, seed=23)
    s.heading(60, 52, "One tile, two collections", "and its own dc_id names the wrong one")

    tile = Box(60, 120, 300, 130, VIOLET, "phylogeny tile", (
        "dc_id → the TREE",
        "config.metadata_dc_id",
        "→ the tip table",
    ))
    s.box(tile)

    tree = Box(560, 96, 330, 116, YELLOW, "tree collection", (
        "type: phylogeny — a Newick file",
        "no Delta table, by construction",
    ))
    s.box(tree)

    table = Box(560, 260, 330, 116, BLUE, "metadata collection", (
        "the tip table",
        "colours and labels only",
    ))
    s.box(table)

    # BEFORE: the tabular request went to the tree.
    s.arrow(tile.right, tile.cy - 26, tree.x - 8, tree.cy + 18, colour=RED)
    # Above the stroke: a label centred on an arrow gets struck through by it.
    s.text(462, 128, "asked for", size=14, colour=RED)
    s.text(462, 148, "tabular data", size=14, colour=RED)

    # The collection that actually holds the table was never consulted — draw
    # that, or the reader has to infer the bug from an unconnected box.
    s.arrow(tile.right, tile.cy + 34, table.x - 8, table.cy - 10, dashed=True, colour=GREY)
    s.text(462, 300, "never asked", size=14, colour=DIM)

    err = Box(960, 96, 320, 116, PINK, "404", (
        "no materialised Delta table",
        "→ the WHOLE tile omitted",
    ))
    s.box(err)
    s.arrow(tree.right, tree.cy, err.x - 8, err.cy, colour=RED)
    s.cross(1120, 236, size=12)
    s.text(1120, 268, "no tree in the bundle", size=14, colour=RED)

    # AFTER: mirror the renderer.
    s.line(60, 420, 1280, 420, colour=GREY, width=1.2, amount=0.8, passes=1)
    s.text(60, 402, "AFTER — mirror what the renderer has always done", size=17,
           anchor="start", weight="bold", colour=DIM)

    a_tree = Box(60, 452, 380, 100, GREEN, "tree ← tree_dc_id", ("the Newick, always fetched",))
    a_tab = Box(490, 452, 380, 100, GREEN, "tips ← metadata_dc_id", ("the table the renderer reads",))
    s.box(a_tree)
    s.box(a_tab)

    asym = Box(920, 452, 360, 100, WHITE, "failure is asymmetric", (
        "no table → the colours go",
        "no tree → fatal, and it says so",
    ))
    s.box(asym)

    s.text(
        670, 600,
        "one frozen payload answers both lookups — advancedVizIndexFor resolves either id",
        size=14, colour=DIM,
    )
    s.text(
        670, 626,
        "ampliseq: 166 265 characters of Newick, 11 994 tips × 9 columns",
        size=14, colour=DIM,
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(..., help="Output prefix, e.g. docs/images/serverless"),
    png: bool = typer.Option(True, help="Also rasterise each SVG (needs Playwright)."),
) -> None:
    """Render every serverless schema under the given prefix."""
    write(_architecture(), out, "architecture", png=png)
    write(_preflight(), out, "preflight-decides", png=png)
    write(_phylogeny(), out, "phylogeny-two-dcs", png=png)
    print("\ncaptions:")
    print(f"  architecture      : {CAPTION_ARCH}")
    print(f"  preflight-decides : {CAPTION_PREFLIGHT}")
    print(f"  phylogeny-two-dcs : {CAPTION_PHYLOGENY}")


if __name__ == "__main__":
    app()
