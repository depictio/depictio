"""Flatten a dashboard family's 2D grids into one reading order.

The rule (a product decision, stated in the RFC so it can be argued with):

1. each tab in ``tab_order`` (the main tab first): its title, then — under the
   first tab only — the persistent sections pinned ``top``
   (``PersistentSectionsHost``), in the order their owner declares them, then
   its own ``grid_sections`` in declared order, then sections its components
   mention but the tab never declared (first appearance), then unsectioned
   tiles;
2. persistent sections pinned ``bottom``.

Persistent sections are drawn above (or below) *every* tab's grid, but a
document has one order, not one per tab: they are written once, under the
first tab, so they still sit beneath a tab heading rather than ahead of every
one of them, where they would read as part of the export's own chrome.

Inside a section, tiles sort by ``(layout.y, layout.x)`` when they carry a
layout and keep their stored order otherwise — the seeded dashboards carry no
layout at all, so the fallback is the common case, not the exception.

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


def _tiles(tab: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in tab.get("stored_metadata") or []:
        if not isinstance(m, dict):
            continue
        if (m.get("component_type") or "") in FILTER_COMPONENT_TYPES:
            continue
        out.append(m)
    return out


def _sorted(components: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [m for _, m in sorted(components, key=lambda pm: tile_sort_key(pm[0], pm[1]))]


def ordered_units(tabs: list[dict[str, Any]]) -> list[Unit]:
    """The whole family, flattened."""
    tabs = order_tabs(tabs)
    seen: set[str] = set()
    top: list[Unit] = []
    bottom: list[Unit] = []
    body: list[Unit] = []

    # Persistent sections: declared by an owner tab, drawn on every tab.
    persistent: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for tab in tabs:
        for spec in tab.get("grid_sections") or []:
            if not isinstance(spec, dict) or not spec.get("persistent"):
                continue
            name = str(spec.get("name") or "")
            if name and name not in persistent:
                persistent[name] = (spec, tab)

    def emit_section(
        target: list[Unit],
        section: _Section,
        tab: dict[str, Any],
        level: int,
        *,
        is_persistent: bool,
    ) -> None:
        if not section.components:
            return
        target.append(
            MarkdownUnit(
                level=level,
                text=section.name,
                kind="section",
                description=(section.spec.get("description") or None),
                icon=(section.spec.get("icon") or None),
                color=(section.spec.get("color") or None),
            )
        )
        for meta in section.components:
            idx = str(meta.get("index") or "")
            if idx in seen:
                continue
            seen.add(idx)
            target.append(
                ComponentUnit(meta=meta, tab=tab, section=section.name, persistent=is_persistent)
            )

    for name, (spec, owner) in persistent.items():
        members = [
            (i, m) for i, m in enumerate(_tiles(owner)) if str(m.get("section") or "") == name
        ]
        section = _Section(name=name, spec=spec, components=_sorted(members))
        target = bottom if (spec.get("pin") or "top") == "bottom" else top
        emit_section(target, section, owner, level=2, is_persistent=True)

    for tab_pos, tab in enumerate(tabs):
        level = 1 if tab_pos == 0 else 2
        body.append(
            MarkdownUnit(
                level=level,
                text=_tab_title(tab),
                kind="tab",
                description=(tab.get("subtitle") or None) if tab_pos == 0 else None,
                # Sidebar precedence: a tab's own icon/colour first, falling
                # back to the dashboard's management-page icon.
                icon=tab_icon_id(tab),
                color=(tab.get("tab_icon_color") or tab.get("icon_color") or None),
                dashboard_id=(str(tab.get("dashboard_id") or "") or None),
            )
        )
        # A persistent section is drawn above every tab's grid, but it is
        # declared by one owner tab and the document needs it to sit *under* a
        # tab heading: ahead of the first one it reads as part of the export's
        # own chrome (the header, the filters) rather than as a section.
        if tab_pos == 0:
            body.extend(top)
            top = []
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
                continue  # rendered with its owner section above/below
            if not sec:
                unsectioned.append((pos, meta))
            elif sec in by_name:
                buckets[sec].append((pos, meta))
            else:
                undeclared.setdefault(sec, _Section(name=sec))
                buckets.setdefault(sec, []).append((pos, meta))
        for section in declared:
            section.components = _sorted(buckets[section.name])
            emit_section(body, section, tab, level=level + 1, is_persistent=False)
        for section in undeclared.values():
            section.components = _sorted(buckets[section.name])
            emit_section(body, section, tab, level=level + 1, is_persistent=False)
        for meta in _sorted(unsectioned):
            idx = str(meta.get("index") or "")
            if idx in seen:
                continue
            seen.add(idx)
            body.append(ComponentUnit(meta=meta, tab=tab, section=None))

    return [*top, *body, *bottom]
