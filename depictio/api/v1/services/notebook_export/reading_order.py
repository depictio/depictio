"""Flatten a dashboard family's 2D grids into one reading order.

The rule follows the order the live grid draws a tab in (``DashboardGrid``,
``App.tsx``), so a tab's part of the document reads top to bottom the way the
tab does on screen:

1. each tab in ``tab_order`` (the main tab first): its title, then its
   opening text tiles (the unsectioned text at the top of its grid), then the
   persistent sections pinned ``top`` that it hosts, then the rest of its
   unsectioned tiles, then its own ``grid_sections`` in declared order, then
   sections its components mention but the tab never declared (first
   appearance), then the persistent sections pinned ``bottom`` it hosts;
2. a persistent section is drawn on *every* tab the dashboard does not exclude
   it from (``exclude_tabs``), but a document has one order, not one per tab:
   it is written once, in the first tab that shows it, at the edge it is
   pinned to. A section shown on every tab but the first (an "Overview" that
   excludes it) lands in the second tab rather than after the last one, where
   it would read as part of that tab only.

Inside the tab's unsectioned tiles and inside a section, tiles sort by
``(y, x)``: the ``layout`` a component carries, else its entry in the tab's
``right_panel_layout_data`` (``box-<index>``, what the seeded dashboards and
the editor store), else its stored order.

Interactive components are not tiles: wherever they are placed they become
the notebook's funnel stages and are left out here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Components that are filters rather than tiles.
FILTER_COMPONENT_TYPES: frozenset[str] = frozenset({"interactive"})

# A tab's stored icon is an Iconify id — except in the older YAML, where it is a
# path into Dash's `/assets/` mount. The SPA cannot serve those either, so its
# sidebar falls back to an icon guessed from the tab's name; the export follows
# the same table (`Sidebar.tsx: resolveTabIcon`) so a tab carries the icon the
# reader saw next to it, not a blank.
_IMAGE_PATH_RE = re.compile(r"^(/|https?://)|\.(png|jpe?g|svg|gif|webp)$", re.IGNORECASE)
_TITLE_ICON_HINTS: tuple[tuple[str, str], ...] = (
    ("multiqc", "mdi:chart-bar-stacked"),
    ("variant", "mdi:dna"),
    ("coverage", "mdi:chart-areaspline"),
    ("quality", "mdi:check-decagram"),
    ("qc", "mdi:check-decagram"),
    ("overview", "mdi:view-dashboard-outline"),
    ("summary", "mdi:view-dashboard-outline"),
    ("community", "mdi:bacteria-outline"),
    ("taxa", "mdi:bacteria-outline"),
    ("species", "mdi:bacteria-outline"),
)


# What the filter panel puts next to each active filter (`frame.tsx`'s
# `TYPE_ICONS` / `interactiveIcon`): the component's own icon when it has one,
# otherwise one per kind of control.
_INTERACTIVE_TYPE_ICONS: dict[str, str] = {
    "MultiSelect": "mdi:form-select",
    "Select": "mdi:form-select",
    "SegmentedControl": "mdi:toggle-switch",
    "RangeSlider": "bx:slider-alt",
    "Slider": "bx:slider-alt",
    "DatePicker": "mdi:calendar-range",
    "DateRangePicker": "mdi:calendar-range",
    "Checkbox": "mdi:checkbox-marked-outline",
    "Switch": "mdi:toggle-switch",
    "Timeline": "mdi:timeline-clock-outline",
}
FILTER_ICON_FALLBACK = "mdi:filter-variant"


def filter_icon_id(meta: dict[str, Any]) -> str:
    """The Iconify id the filter panel shows for one interactive component."""
    named = str(meta.get("icon_name") or "")
    if named:
        return named
    kind = str(meta.get("interactive_component_type") or "")
    return _INTERACTIVE_TYPE_ICONS.get(kind, FILTER_ICON_FALLBACK)


def tab_icon_id(tab: dict[str, Any]) -> str:
    """The Iconify id the live sidebar shows for this tab."""
    for key in ("tab_icon", "icon"):
        value = str(tab.get(key) or "")
        if value and not _IMAGE_PATH_RE.search(value):
            return value
    name = str(tab.get("main_tab_name") or tab.get("title") or "").lower()
    for needle, icon in _TITLE_ICON_HINTS:
        if needle in name:
            return icon
    return "mdi:view-dashboard" if _is_main(tab) else "mdi:tab"


@dataclass(frozen=True)
class MarkdownUnit:
    """A heading: a tab title (level 1/2) or a section title (level 2/3).

    ``icon``/``color`` carry the raw, unresolved spec (an Iconify id, a
    Mantine palette name) — same fields the live sidebar/section header read,
    so the generator can render the same identity without this module having
    to resolve an icon over the network or know what a Mantine palette name
    means. ``dashboard_id`` is only set for ``kind == "tab"``: each tab in a
    family is its own dashboard document, with its own possible brand
    override, keyed by this id in ``ExportPlan.tab_brands``.
    """

    level: int
    text: str
    kind: str  # "tab" | "section"
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    dashboard_id: str | None = None
    # The section's own default (``grid_sections[].collapsed``): the report
    # opens it folded, as the dashboard does.
    collapsed: bool = False
    # A persistent section, drawn on every tab but those it excludes.
    persistent: bool = False
    exclude_tabs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentUnit:
    """One tile, with the tab and section it belongs to."""

    meta: dict[str, Any]
    tab: dict[str, Any]
    section: str | None = None
    persistent: bool = False


Unit = MarkdownUnit | ComponentUnit


@dataclass
class _Section:
    name: str
    spec: dict[str, Any] = field(default_factory=dict)
    components: list[dict[str, Any]] = field(default_factory=list)


def _tab_title(tab: dict[str, Any]) -> str:
    # The main tab *is* the dashboard document, so its ``title`` is the
    # dashboard's — using it would print the export's own title a second time
    # as the first tab. ``main_tab_name`` is the label the sidebar shows for
    # it, and the one a reader recognises ("MultiQC", not the pipeline name).
    keys = ("main_tab_name", "title") if _is_main(tab) else ("title", "main_tab_name")
    for key in keys:
        value = str(tab.get(key) or "").strip()
        if value:
            return value
    return str(tab.get("dashboard_id") or "Tab")


def _is_main(tab: dict[str, Any]) -> bool:
    return bool(tab.get("is_main_tab")) or not tab.get("parent_dashboard_id")


def order_tabs(tabs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Main tab first, then children by ``tab_order`` (stable on ties)."""
    indexed = list(enumerate(tabs))
    indexed.sort(
        key=lambda it: (
            0 if _is_main(it[1]) else 1,
            it[1].get("tab_order") is None,
            it[1].get("tab_order") or 0,
            it[0],
        )
    )
    return [t for _, t in indexed]


def tile_sort_key(position: int, meta: dict[str, Any]) -> tuple[float, float, int]:
    layout = meta.get("layout") or {}
    y = layout.get("y")
    x = layout.get("x")
    return (
        float(y) if isinstance(y, (int, float)) else float("inf"),
        float(x) if isinstance(x, (int, float)) else float("inf"),
        position,
    )


def _layout_positions(tab: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{index: {"x", "y", "w", "h"}}`` from the tab's grid layout (``box-<index>``).

    The width is what lets the document draw a row of tiles side by side, as
    wide as the columns each takes on the dashboard's grid."""
    out: dict[str, dict[str, Any]] = {}
    for item in tab.get("right_panel_layout_data") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("i") or "")
        if key.startswith("box-"):
            key = key[4:]
        if key and key not in out:
            out[key] = {k: item.get(k) for k in ("x", "y", "w", "h") if item.get(k) is not None}
    return out


def _tiles(tab: dict[str, Any]) -> list[dict[str, Any]]:
    positions = _layout_positions(tab)
    out = []
    for m in tab.get("stored_metadata") or []:
        if not isinstance(m, dict):
            continue
        if (m.get("component_type") or "") in FILTER_COMPONENT_TYPES:
            continue
        pos = positions.get(str(m.get("index") or ""))
        if pos is not None and not m.get("layout"):
            m = {**m, "layout": pos}
        out.append(m)
    return out


def grid_columns(tab: dict[str, Any]) -> int:
    """How many columns the tab's grid has: the right edge of its widest row.

    The dashboards are laid out on an 8-column grid (12 for the older ones);
    the layout itself says which, so nothing assumes either."""
    edge = 0
    items = [m.get("layout") for m in tab.get("stored_metadata") or [] if isinstance(m, dict)]
    items += list(tab.get("right_panel_layout_data") or [])
    for item in items:
        if not isinstance(item, dict):
            continue
        x, w = item.get("x"), item.get("w")
        if isinstance(x, (int, float)) and isinstance(w, (int, float)):
            edge = max(edge, int(x + w))
    return edge


def tab_link_key(name: str) -> str:
    """``tabLinkKey``: how a tab name in ``exclude_tabs`` or ``tab:`` matches."""
    return " ".join(str(name).split()).lower()


def tab_display_name(tab: dict[str, Any]) -> str:
    """``tabDisplayName``: what ``exclude_tabs`` names a tab by."""
    return _tab_title(tab)


def _floating(meta: dict[str, Any]) -> bool:
    return meta.get("component_type") == "map" and meta.get("placement") == "floating"


def _excluded(spec: dict[str, Any], tab: dict[str, Any]) -> bool:
    names = {tab_link_key(n) for n in (spec.get("exclude_tabs") or []) if isinstance(n, str)}
    return tab_link_key(tab_display_name(tab)) in names


def _sorted(components: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [m for _, m in sorted(components, key=lambda pm: tile_sort_key(pm[0], pm[1]))]


def ordered_units(tabs: list[dict[str, Any]]) -> list[Unit]:
    """The whole family, flattened."""
    tabs = order_tabs(tabs)
    seen: set[str] = set()
    body: list[Unit] = []

    # Persistent sections: declared by an owner tab, drawn on every tab it
    # does not exclude; written once, in the first of those.
    persistent: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for tab in tabs:
        for spec in tab.get("grid_sections") or []:
            if not isinstance(spec, dict) or not spec.get("persistent"):
                continue
            name = str(spec.get("name") or "")
            if name and name not in persistent:
                persistent[name] = (spec, tab)
    hosted: dict[int, list[str]] = {}
    for name, (spec, owner) in persistent.items():
        host = next((i for i, t in enumerate(tabs) if not _excluded(spec, t)), None)
        if host is None:
            host = next(i for i, t in enumerate(tabs) if t is owner)
        hosted.setdefault(host, []).append(name)

    tab_level = [1]

    def section_unit(section: _Section, *, is_persistent: bool) -> MarkdownUnit:
        spec = section.spec
        return MarkdownUnit(
            level=tab_level[0] + 1,
            text=section.name,
            kind="section",
            description=(spec.get("description") or None),
            icon=(spec.get("icon") or None),
            color=(spec.get("color") or None),
            collapsed=bool(spec.get("collapsed")),
            persistent=is_persistent,
            exclude_tabs=tuple(str(t) for t in (spec.get("exclude_tabs") or []) if t),
        )

    def emit_tiles(target: list[Unit], metas: list[dict[str, Any]], tab, section, persistent_):
        for meta in metas:
            idx = str(meta.get("index") or "")
            if idx in seen:
                continue
            seen.add(idx)
            target.append(
                ComponentUnit(meta=meta, tab=tab, section=section, persistent=persistent_)
            )

    def emit_section(section: _Section, tab: dict[str, Any], *, is_persistent: bool) -> None:
        if not section.components:
            return
        body.append(section_unit(section, is_persistent=is_persistent))
        emit_tiles(body, section.components, tab, section.name, is_persistent)

    def emit_persistent(names: list[str]) -> None:
        for name in names:
            spec, owner = persistent[name]
            members = [
                (i, m) for i, m in enumerate(_tiles(owner)) if str(m.get("section") or "") == name
            ]
            emit_section(
                _Section(name=name, spec=spec, components=_sorted(members)),
                owner,
                is_persistent=True,
            )

    for tab_pos, tab in enumerate(tabs):
        level = 1 if tab_pos == 0 else 2
        tab_level[0] = level
        body.append(
            MarkdownUnit(
                level=level,
                text=_tab_title(tab),
                kind="tab",
                # The tab's own subtitle (the question a child tab answers, in
                # the sidebar's tooltip): the factual lead-in to its part. A
                # child repeating the main tab's says nothing new.
                description=(
                    (tab.get("subtitle") or None)
                    if tab_pos == 0 or tab.get("subtitle") != tabs[0].get("subtitle")
                    else None
                ),
                # Sidebar precedence: a tab's own icon/colour first, falling
                # back to the dashboard's management-page icon.
                icon=tab_icon_id(tab),
                color=(tab.get("tab_icon_color") or tab.get("icon_color") or None),
                dashboard_id=(str(tab.get("dashboard_id") or "") or None),
            )
        )
        here = hosted.get(tab_pos, [])
        top = [n for n in here if (persistent[n][0].get("pin") or "top") != "bottom"]
        bottom = [n for n in here if (persistent[n][0].get("pin") or "top") == "bottom"]

        tiles = list(enumerate(_tiles(tab)))
        declared: list[_Section] = []
        declared_names: set[str] = set()
        for spec in tab.get("grid_sections") or []:
            if not isinstance(spec, dict) or spec.get("persistent"):
                continue
            name = str(spec.get("name") or "")
            if not name or name in declared_names:
                continue
            declared_names.add(name)
            declared.append(_Section(name=name, spec=spec))
        undeclared: dict[str, _Section] = {}
        unsectioned: list[tuple[int, dict[str, Any]]] = []
        by_name = {s.name: s for s in declared}
        buckets: dict[str, list[tuple[int, dict[str, Any]]]] = {s.name: [] for s in declared}
        for pos, meta in tiles:
            sec = str(meta.get("section") or "")
            if sec in persistent:
                continue  # written once, in the tab that hosts it
            if not sec:
                unsectioned.append((pos, meta))
            elif sec in by_name:
                buckets[sec].append((pos, meta))
            else:
                undeclared.setdefault(sec, _Section(name=sec))
                buckets.setdefault(sec, []).append((pos, meta))

        # The tab's opening text first (its title, its intro), then what is
        # pinned to the top of every tab, then the rest of its loose tiles —
        # DashboardGrid's lead bucket / `beforeSections` / rest bucket.
        loose = _sorted(unsectioned)
        lead = 0
        while lead < len(loose) and loose[lead].get("component_type") == "text":
            lead += 1
        # A floating map is not on the grid at all: the dashboard docks it
        # beside every tab. It follows the tab's loose tiles, ahead of its
        # sections: after them it would read as the last section's content.
        floating = [m for m in loose[lead:] if _floating(m)]
        rest = [m for m in loose[lead:] if not _floating(m)]
        emit_tiles(body, loose[:lead], tab, None, False)
        emit_persistent(top)
        emit_tiles(body, [*rest, *floating], tab, None, False)
        for section in [*declared, *undeclared.values()]:
            section.components = _sorted(buckets[section.name])
            emit_section(section, tab, is_persistent=False)
        emit_persistent(bottom)

    return body
