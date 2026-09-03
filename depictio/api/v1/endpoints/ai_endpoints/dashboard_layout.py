"""Deterministic funnel layout for a generated dashboard.

`layout_dashboard` takes a normalised `DashboardPlan` and the filled lite
component dicts and returns them with an explicit `layout: {x, y, w, h}` and
`section` in the shape `DashboardDataLite` consumes, plus the `filter_sections`
and `grid_sections` specs (`FilterSectionSpec` fields only).

Boxes follow what the builder gives each type by default
(`defaultLayoutForType` in packages/depictio-react-core/src/api.ts) and what
the seeded dashboards use, on the 8-column main grid:

- interactive: x=0, w=1, h=3, stacked in the left panel;
- text: w=8, h=1, first in its grid section (the section header);
- card: w=2, h=2 in rows of four; a short last row is widened so every row is
  full (3 left: 3/3/2, 2 left: 4/4, 1 left: 8);
- figure, map, image, multiqc: w=4, h=5 in pairs; a lone trailing one is
  widened to 8;
- advanced_viz: w=8, h=8;
- table: w=8, h=5, last in its section; a section holding nothing but tables
  (and their header) starts collapsed, the way the reference dashboards fold
  their raw-data table.

`y` is section-relative: the viewer draws one sub-grid per section
(`_recompact_main_grid` in dashboards_endpoints/routes.py packs the same way)
and the left panel orders each section's controls by their own `y`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from depictio.api.v1.endpoints.ai_endpoints.dashboard_plan import DashboardPlan, SectionSpec

GRID_COLS = 8

INTERACTIVE_BOX = {"w": 1, "h": 3}
TEXT_BOX = {"w": GRID_COLS, "h": 1}
CARD_BOX = {"w": 2, "h": 2}
CHART_BOX = {"w": 4, "h": 5}
ADVANCED_VIZ_BOX = {"w": GRID_COLS, "h": 8}
TABLE_BOX = {"w": GRID_COLS, "h": 5}

# Types laid out as half-width charts in pairs.
CHART_TYPES: frozenset[str] = frozenset({"figure", "map", "image", "multiqc"})

# Order the type groups take inside a grid section.
_GROUP_ORDER: tuple[str, ...] = ("text", "card", "chart", "advanced_viz", "table")

_DEFAULT_FILTER_SECTION = "Filters"
_DEFAULT_GRID_SECTION = "Overview"


def card_rows(n: int) -> list[list[int]]:
    """Widths per row for `n` cards on the 8-column grid, every row summing to 8.

    Full rows are four cards of w=2. The remainder is widened rather than
    left ragged: 3 cards become 3/3/2, 2 become 4/4, 1 becomes 8.
    """
    rows = [[CARD_BOX["w"]] * 4 for _ in range(n // 4)]
    rest = n % 4
    if rest == 3:
        rows.append([3, 3, 2])
    elif rest == 2:
        rows.append([4, 4])
    elif rest == 1:
        rows.append([GRID_COLS])
    return rows


def _group_of(component_type: str) -> str:
    if component_type in CHART_TYPES:
        return "chart"
    if component_type in ("text", "card", "advanced_viz", "table"):
        return component_type
    # Anything unknown is laid out as a half-width chart.
    return "chart"


def _layout_grid_section(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign section-relative boxes to one grid section's components, in group order."""
    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in _GROUP_ORDER}
    for comp in components:
        groups[_group_of(str(comp.get("component_type", "")))].append(comp)

    out: list[dict[str, Any]] = []
    y = 0

    for comp in groups["text"]:
        out.append(_boxed(comp, 0, y, **TEXT_BOX))
        y += TEXT_BOX["h"]

    cards = groups["card"]
    i = 0
    for widths in card_rows(len(cards)):
        x = 0
        for w in widths:
            out.append(_boxed(cards[i], x, y, w=w, h=CARD_BOX["h"]))
            x += w
            i += 1
        y += CARD_BOX["h"]

    charts = groups["chart"]
    for start in range(0, len(charts), 2):
        pair = charts[start : start + 2]
        if len(pair) == 2:
            out.append(_boxed(pair[0], 0, y, **CHART_BOX))
            out.append(_boxed(pair[1], CHART_BOX["w"], y, **CHART_BOX))
        else:
            out.append(_boxed(pair[0], 0, y, w=GRID_COLS, h=CHART_BOX["h"]))
        y += CHART_BOX["h"]

    for comp in groups["advanced_viz"]:
        out.append(_boxed(comp, 0, y, **ADVANCED_VIZ_BOX))
        y += ADVANCED_VIZ_BOX["h"]

    for comp in groups["table"]:
        out.append(_boxed(comp, 0, y, **TABLE_BOX))
        y += TABLE_BOX["h"]

    return out


def _layout_filter_section(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    y = 0
    for comp in components:
        out.append(_boxed(comp, 0, y, **INTERACTIVE_BOX))
        y += INTERACTIVE_BOX["h"]
    return out


def _boxed(comp: dict[str, Any], x: int, y: int, *, w: int, h: int) -> dict[str, Any]:
    boxed = dict(comp)
    boxed["layout"] = {"x": x, "y": y, "w": w, "h": h}
    return boxed


def _section_dict(spec: SectionSpec, *, collapsed: bool = False) -> dict[str, Any]:
    """A `FilterSectionSpec`-shaped dict; None-valued keys are left out."""
    out: dict[str, Any] = {"name": spec.name}
    for key in ("icon", "color", "description"):
        value = getattr(spec, key)
        if value:
            out[key] = value
    if collapsed:
        out["collapsed"] = True
    return out


def layout_dashboard(
    plan: DashboardPlan, components: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Place every component and describe the sections, deterministically.

    Components are matched to the plan by `tag`; a component the plan does
    not know keeps its own `section` when it has one, else interactives go
    to the first filter section and tiles to the last grid section (a
    default section is created when the plan has none). Sections come out in
    the plan's order, then any section only the components named, in order
    of first appearance; sections nothing landed in are omitted.

    Returns `(components, filter_sections, grid_sections)`: deep copies of the
    inputs with `section` and `layout` set, emitted filter panel first and
    then grid section by grid section, plus the two section spec lists.
    """
    planned = {c.tag: c for c in plan.components}

    filter_specs: dict[str, SectionSpec] = {s.name: s for s in plan.filter_sections}
    grid_specs: dict[str, SectionSpec] = {s.name: s for s in plan.grid_sections}
    filter_members: dict[str, list[dict[str, Any]]] = {name: [] for name in filter_specs}
    grid_members: dict[str, list[dict[str, Any]]] = {name: [] for name in grid_specs}

    for original in components:
        comp = deepcopy(original)
        component_type = str(comp.get("component_type", ""))
        is_filter = component_type == "interactive"
        specs, members = (filter_specs, filter_members) if is_filter else (grid_specs, grid_members)

        entry = planned.get(str(comp.get("tag", "")))
        section = entry.section if entry is not None else str(comp.get("section") or "").strip()
        if not section:
            if specs:
                section = next(iter(specs)) if is_filter else list(specs)[-1]
            else:
                section = _DEFAULT_FILTER_SECTION if is_filter else _DEFAULT_GRID_SECTION
        if section not in specs:
            specs[section] = SectionSpec(name=section)
            members[section] = []
        comp["section"] = section
        members[section].append(comp)

    out_components: list[dict[str, Any]] = []
    out_filter_sections: list[dict[str, Any]] = []
    out_grid_sections: list[dict[str, Any]] = []

    for name, spec in filter_specs.items():
        section_components = filter_members[name]
        if not section_components:
            continue
        out_components.extend(_layout_filter_section(section_components))
        out_filter_sections.append(_section_dict(spec))

    for name, spec in grid_specs.items():
        section_components = grid_members[name]
        if not section_components:
            continue
        out_components.extend(_layout_grid_section(section_components))
        tiles = [c for c in section_components if c.get("component_type") != "text"]
        only_tables = bool(tiles) and all(c.get("component_type") == "table" for c in tiles)
        out_grid_sections.append(_section_dict(spec, collapsed=only_tables))

    return out_components, out_filter_sections, out_grid_sections
