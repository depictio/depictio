"""Deterministic grid layout for a composed dashboard.

Every component gets an explicit ``layout`` box: without one the importer falls
back to the legacy 48-column auto layout, which on the 8-column grid makes
12-row tiles. The rules follow the shipped templates and the AI generator's
layout (#1028), so a composed dashboard reads like a hand-written one:

- each section restarts at ``y: 0`` (the viewer packs sections separately);
- inside a section: text, then cards in full rows (4 x w2, the remainder
  3/3/2, 4/4 or one wide), then figures and MultiQC plots in pairs (a lone one
  widened), then advanced visualisations full width, then tables full width;
- filters stack in the 1-column left panel.
"""

from __future__ import annotations

from collections.abc import Iterable

GRID_COLS = 8
CARD = (2, 2)
CHART = (4, 5)
ADVANCED = (8, 7)
TABLE = (8, 5)
FILTER = (1, 3)
TEXT_CHARS_PER_ROW = 300  # the shipped-YAML test's budget for a text tile's height

_ORDER = {"text": 0, "card": 1, "figure": 2, "multiqc": 2, "advanced_viz": 3, "table": 4}


def card_row_widths(n: int) -> list[int]:
    """Widths for ``n`` cards so every row is full: rows of four, then 3/3/2, 4/4 or 8."""
    widths: list[int] = []
    full, rest = divmod(n, 4)
    widths += [CARD[0]] * (4 * full)
    widths += {0: [], 1: [8], 2: [4, 4], 3: [3, 3, 2]}[rest]
    return widths


def text_height(body: str) -> int:
    return max(1, -(-len(body) // TEXT_CHARS_PER_ROW))


def _set(component: dict, x: int, y: int, w: int, h: int) -> None:
    component["layout"] = {"x": x, "y": y, "w": w, "h": h}


def layout_section(components: list[dict]) -> int:
    """Lay one grid section out in place, ordered by kind; returns its height."""
    ordered = sorted(components, key=lambda c: _ORDER.get(c["component_type"], 5))
    y = 0
    texts = [c for c in ordered if c["component_type"] == "text"]
    cards = [c for c in ordered if c["component_type"] == "card"]
    charts = [c for c in ordered if c["component_type"] in ("figure", "multiqc")]
    advanced = [c for c in ordered if c["component_type"] == "advanced_viz"]
    tables = [c for c in ordered if c["component_type"] == "table"]
    other = [
        c
        for c in ordered
        if c["component_type"] not in ("text", "card", "figure", "multiqc", "advanced_viz", "table")
    ]

    for text in texts:
        h = text_height(str(text.get("body") or ""))
        _set(text, 0, y, GRID_COLS, h)
        y += h

    x = 0
    for card, w in zip(cards, card_row_widths(len(cards)), strict=True):
        if x + w > GRID_COLS:
            x, y = 0, y + CARD[1]
        _set(card, x, y, w, CARD[1])
        x += w
    if cards:
        y += CARD[1]

    for i in range(0, len(charts), 2):
        pair = charts[i : i + 2]
        if len(pair) == 1:
            _set(pair[0], 0, y, GRID_COLS, CHART[1])
        else:
            _set(pair[0], 0, y, CHART[0], CHART[1])
            _set(pair[1], CHART[0], y, CHART[0], CHART[1])
        y += CHART[1]

    for comp in [*advanced, *other]:
        _set(comp, 0, y, *ADVANCED)
        y += ADVANCED[1]

    for table in tables:
        _set(table, 0, y, *TABLE)
        y += TABLE[1]

    components[:] = ordered
    return y


def layout_filters(components: Iterable[dict]) -> None:
    """Stack filter controls in the left panel."""
    y = 0
    for component in components:
        _set(component, 0, y, *FILTER)
        y += FILTER[1]


def layout_dashboard(dashboard: dict) -> None:
    """Lay out every section of one dashboard (or tab) document in place."""
    # A filter section and a grid section may share a name (the import keys them
    # by kind and name): a filter is an interactive component of a filter section.
    filter_names = {s["name"] for s in dashboard.get("filter_sections") or []}
    by_section: dict[tuple[bool, str | None], list[dict]] = {}
    for component in dashboard.get("components") or []:
        section = component.get("section")
        is_filter = component.get("component_type") == "interactive" and section in filter_names
        by_section.setdefault((is_filter, section), []).append(component)
    for (is_filter, _), members in by_section.items():
        if is_filter:
            layout_filters(members)
        else:
            layout_section(members)
