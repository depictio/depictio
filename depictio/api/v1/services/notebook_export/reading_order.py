"""Flatten a dashboard family's 2D grids into one reading order.

The rule (a product decision, stated in the RFC so it can be argued with):

1. persistent sections pinned ``top`` (``PersistentSectionsHost``), owner tab
   first, in the order the owner declares them;
2. each tab in ``tab_order`` (the main tab first): its title, then its own
   ``grid_sections`` in declared order, then sections its components mention
   but the tab never declared (first appearance), then unsectioned tiles;
3. persistent sections pinned ``bottom``.

Inside a section, tiles sort by ``(layout.y, layout.x)`` when they carry a
layout and keep their stored order otherwise — the seeded dashboards carry no
layout at all, so the fallback is the common case, not the exception.

Interactive components are not tiles: wherever they are placed they become
the notebook's funnel stages and are left out here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Components that are filters rather than tiles.
FILTER_COMPONENT_TYPES: frozenset[str] = frozenset({"interactive"})


@dataclass(frozen=True)
class MarkdownUnit:
    """A heading: a tab title (level 1/2) or a section title (level 2/3)."""

    level: int
    text: str
    kind: str  # "tab" | "section"
    description: str | None = None


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
    return str(tab.get("title") or tab.get("main_tab_name") or tab.get("dashboard_id") or "Tab")


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
            )
        )
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
