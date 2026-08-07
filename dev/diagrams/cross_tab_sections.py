#!/usr/bin/env python3
"""Render the persistent cross-tab section schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, each carrying one idea that prose states badly:

* ``fanout``   — who owns a persistent section, what the family request returns,
  and where each half of it lands on a sibling tab.
* ``survival`` — why a value picked in a persistent filter is still applied
  after a tab switch, when the switch is a full page navigation.

Usage:
    python dev/diagrams/cross_tab_sections.py --out docs/images/cross-tab-sections
    # writes <out>_fanout.svg/.png and <out>_survival.svg/.png

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
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)


# --------------------------------------------------------------------------
# 1. One flag, one request, two landing places.
# --------------------------------------------------------------------------

FANOUT_W, FANOUT_H = 1340, 600


def build_fanout() -> Sketch:
    """Left: who owns the flag. Middle: the one request. Right: where it lands.

    The two right-hand boxes are what the diagram exists for — a persistent
    section splits by kind, and the two halves reach a sibling tab by different
    routes (a host above the grid, and the tab's own filter panel).
    """
    s = Sketch(FANOUT_W, FANOUT_H)

    s.heading(
        46,
        52,
        "A section marked persistent belongs to the tab family",
        "one request per page load; the owner tab keeps editing rights",
    )

    owner = Box(
        60,
        132,
        330,
        124,
        VIOLET,
        "Overview (main tab)",
        (
            "Raw Data · grid section",
            "Variety · filter section",
            "both persistent: true",
        ),
    )
    sibling = Box(
        60,
        340,
        330,
        104,
        WHITE,
        "Iris Petal Analysis (tab)",
        ("its own sections only,", "nothing marked persistent"),
    )
    s.box(owner)
    s.box(sibling)
    s.line(owner.cx, owner.bottom, sibling.cx, sibling.y, dashed=True, colour=GREY, width=1.4)
    s.text(owner.cx + 12, 300, "parent_dashboard_id", size=13, colour=DIM, anchor="start")

    request = Box(
        450,
        196,
        400,
        184,
        YELLOW,
        "GET /cross_tab_components/{id}",
        (
            "_resolve_tab_family → parent + siblings",
            "→ { floating, persistent_sections }",
            "",
            "useCrossTabComponents: one fetch",
            "per page load, whichever tab is open",
        ),
    )
    s.box(request)
    s.arrow(owner.right, owner.cy + 20, request.x, request.y + 46)
    s.arrow(sibling.right, sibling.cy - 10, request.x, request.bottom - 46)

    host = Box(
        910,
        128,
        380,
        136,
        GREEN,
        "PersistentSectionsHost",
        (
            "the owner's grid section, pinned",
            "above the viewing tab's own grid,",
            "read-only; members fetched",
            "against the owner tab's id",
        ),
    )
    panel = Box(
        910,
        318,
        380,
        126,
        BLUE,
        "The tab's filter panel",
        (
            "the persistent section's controls",
            "join the panel of every sibling,",
            "carrying the same values",
        ),
    )
    s.box(host)
    s.box(panel)
    s.arrow(request.right, request.y + 54, host.x, host.cy + 10)
    s.arrow(request.right, request.bottom - 54, panel.x, panel.cy - 10)

    # The v1 limitation, drawn rather than buried in the body text.
    s.cross(request.x + 24, 486, size=9)
    s.text(
        request.x + 46,
        492,
        "card members are skipped in the fan-out: bulk compute is per-dashboard",
        size=14,
        colour=DIM,
        anchor="start",
    )

    s.text(
        46,
        FANOUT_H - 34,
        "the flag lives on FilterSectionSpec, so a tabless dashboard is unaffected",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        FANOUT_W - 46,
        FANOUT_H - 34,
        "/floating_components still answers, on the same family helper",
        size=14,
        colour=DIM,
        anchor="end",
    )
    return s


# --------------------------------------------------------------------------
# 2. Why the value is still applied after the switch.
# --------------------------------------------------------------------------

SURVIVAL_W, SURVIVAL_H = 1340, 470
LANE_Y = 190


def build_survival() -> Sketch:
    """Four steps along one lane: pick, store, navigate, hydrate.

    The point is the middle span: a tab switch is a full page navigation, so
    in-memory filter state does not cross it and something outside React has to.
    """
    s = Sketch(SURVIVAL_W, SURVIVAL_H)

    s.heading(
        46,
        52,
        "A value picked in a persistent filter survives the tab switch",
        "tabs are separate documents, so the switch reloads the page",
    )

    pick = Box(
        60,
        LANE_Y - 56,
        290,
        112,
        VIOLET,
        "Overview tab",
        ("Variety = Virginica,", "picked in the persistent", "filter section"),
    )
    store = Box(
        470,
        LANE_Y - 84,
        360,
        170,
        YELLOW,
        "sessionStorage",
        (
            "depictio:cross-tab-filters",
            "{ parentDashboardId, filters }",
            "",
            "dies with the browser tab, so it",
            "never leaks into a fresh visit",
        ),
    )
    land = Box(
        950,
        LANE_Y - 56,
        330,
        112,
        GREEN,
        "Iris Petal Analysis tab",
        ("opens already filtered", "on Virginica: the table", "and the figures agree"),
    )
    for b in (pick, store, land):
        s.box(b)

    s.arrow(pick.right, LANE_Y, store.x, LANE_Y)
    s.text((pick.right + store.x) / 2, LANE_Y - 18, "write", size=14, colour=DIM)

    s.arrow(store.right, LANE_Y, land.x, LANE_Y)
    s.text((store.right + land.x) / 2, LANE_Y - 30, "full page", size=14, colour=DIM)
    s.text((store.right + land.x) / 2, LANE_Y - 12, "navigation", size=14, colour=DIM)

    # What the resolve step throws away, hung under the landing box.
    s.line(land.cx, land.bottom, land.cx, LANE_Y + 116, dashed=True, colour=GREY, width=1.3)
    s.cross(land.cx - 128, LANE_Y + 150, size=9)
    s.text(
        land.cx - 108,
        LANE_Y + 156,
        "a control re-pointed at another",
        size=14,
        colour=DIM,
        anchor="start",
    )
    s.text(
        land.cx - 108,
        LANE_Y + 176,
        "dc / column is pruned at resolve",
        size=14,
        colour=DIM,
        anchor="start",
    )

    s.text(
        46,
        SURVIVAL_H - 34,
        "the same storage the floating map panel already used, generalised",
        size=15,
        colour=DIM,
        anchor="start",
    )
    s.text(
        SURVIVAL_W - 46,
        SURVIVAL_H - 34,
        "only these filters are stored; every other filter still dies on the switch",
        size=14,
        colour=DIM,
        anchor="end",
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/cross-tab-sections"),
        "--out",
        help="Output stem; each diagram appends its own name.",
    ),
    png: bool = typer.Option(True, help="Also render a PNG next to each SVG."),
) -> None:
    write(build_fanout(), out, "fanout", png=png)
    write(build_survival(), out, "survival", png=png)


if __name__ == "__main__":
    app()
