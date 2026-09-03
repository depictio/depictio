"""The dashboard plan: what the planner LLM proposes before any component is filled.

A plan names the dashboard, its filter-panel and main-grid sections, and one
entry per component (which section it lives in, which type it is, which data
collection backs it, what it should show). It is the contract between the one
planning call and the per-component fill calls of `/ai/generate-dashboard`.

Two entry points wrap the Pydantic models:

- `parse_plan` turns the raw JSON the model returned into a `DashboardPlan`,
  tolerating the shapes a model produces when it half-follows the schema (a
  single `sections` list, string sections, `type` for `component_type`, ...).
- `normalize_plan` clamps and repairs a parsed plan deterministically: counts,
  the funnel section order (cohort, metrics, analysis, reference), tag
  uniqueness, section membership, and the icon / colour allowlists. It never
  raises for a fixable plan; every repair is reported as a warning.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from depictio.api.v1.endpoints.ai_endpoints.schemas import ComponentType

# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

# Copied from SECTION_ICON_OPTIONS in
# depictio/viewer/src/components/sections/sectionIcons.ts. Only ids written as
# literals in the viewer source are bundled (the CSP blocks Iconify's network
# fallback), so a section icon outside this list renders blank in a built
# deployment. Keep the two lists in step.
SECTION_ICONS: tuple[str, ...] = (
    # Overview / summary
    "mdi:counter",
    "mdi:view-dashboard-outline",
    "mdi:information-outline",
    "mdi:star-outline",
    # Charts
    "mdi:chart-bell-curve",
    "mdi:chart-bar",
    "mdi:chart-line",
    "mdi:chart-scatter-plot",
    "mdi:chart-donut",
    "mdi:chart-box-outline",
    "mdi:chart-timeline-variant",
    # Data
    "mdi:table",
    "mdi:table-account",
    "mdi:database-outline",
    "mdi:set-merge",
    "mdi:relation-many-to-many",
    "mdi:file-document-outline",
    "mdi:folder-outline",
    # Quality / status
    "mdi:check-decagram",
    "mdi:shield-check-outline",
    "mdi:alert-outline",
    "mdi:filter-variant",
    "mdi:tune",
    # Science / domain
    "mdi:test-tube",
    "mdi:dna",
    "mdi:bacteria-outline",
    "mdi:virus",
    "mdi:family-tree",
    "mdi:stethoscope",
    "mdi:scale-balance",
    "mdi:waves",
    "mdi:microscope",
    "mdi:ruler",
    "mdi:shape-outline",
    "mdi:map-marker-outline",
    "mdi:calendar-outline",
    "mdi:account-group-outline",
)

FALLBACK_ICON = "mdi:view-dashboard-outline"

# The Mantine palette names the section colour picker offers
# (SECTION_COLOR_OPTIONS in sectionIcons.ts). None means "no override".
SECTION_COLORS: tuple[str, ...] = (
    "gray",
    "red",
    "pink",
    "grape",
    "violet",
    "indigo",
    "blue",
    "cyan",
    "teal",
    "green",
    "lime",
    "yellow",
    "orange",
)

# Every component type except text is bound to a data collection.
DATA_BOUND_TYPES: frozenset[str] = frozenset(
    {"figure", "card", "interactive", "table", "image", "multiqc", "map", "advanced_viz"}
)

# A section rationale is one sentence a reviewer reads at a glance, so a model
# that answers with a paragraph is cut here rather than dropped: a truncated
# reason still says more than no reason at all.
MAX_SECTION_RATIONALE = 240

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SectionSpec(BaseModel):
    """One filter-panel or main-grid section as the planner names it."""

    model_config = ConfigDict(extra="ignore")

    name: str
    icon: str | None = None
    color: str | None = None
    description: str | None = None
    # The planner's one sentence on why this section exists and what it holds.
    # Unlike `description`, which the server turns into the section header's
    # body text, this is never rendered into the dashboard: it is shown to
    # whoever reviews the draft, so the choice can be read back.
    rationale: str | None = None


class PlannedComponent(BaseModel):
    """One component the planner wants, before it is filled.

    `intent` is the natural-language brief handed to the fill call. `use` pins
    a catalog offer (advanced_viz) and `viz_kind` a ranked advanced_viz kind;
    both are optional hints the fill step honours when present.
    """

    model_config = ConfigDict(extra="ignore")

    tag: str
    section: str
    component_type: ComponentType
    data_collection_tag: str | None = None
    intent: str = ""
    use: str | None = None
    viz_kind: str | None = None


class DashboardPlan(BaseModel):
    """The planner's output: a titled dashboard, its sections, its components."""

    model_config = ConfigDict(extra="ignore")

    title: str
    subtitle: str | None = None
    filter_sections: list[SectionSpec] = Field(default_factory=list)
    grid_sections: list[SectionSpec] = Field(default_factory=list)
    components: list[PlannedComponent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Funnel ranking
# ---------------------------------------------------------------------------

RANK_COHORT, RANK_METRICS, RANK_ANALYSIS, RANK_REFERENCE = 0, 1, 2, 3
FUNNEL_ORDER: tuple[str, ...] = ("cohort", "metrics", "analysis", "reference")

# Section names are free text, so the funnel stage is read off keywords. A
# name matching several stages goes to the one with the most hits; ties go to
# the earlier stage.
_RANK_KEYWORDS: dict[int, tuple[str, ...]] = {
    RANK_COHORT: (
        "cohort",
        "sample",
        "samples",
        "filter",
        "filters",
        "subset",
        "population",
        "selection",
        "scope",
        "inclusion",
        "criteria",
        "who",
        "which",
    ),
    RANK_METRICS: (
        "metric",
        "metrics",
        "kpi",
        "kpis",
        "summary",
        "overview",
        "headline",
        "glance",
        "count",
        "counts",
        "total",
        "totals",
        "snapshot",
        "highlights",
        "key",
    ),
    RANK_ANALYSIS: (
        "analysis",
        "analyses",
        "analyse",
        "analyze",
        "distribution",
        "distributions",
        "comparison",
        "comparisons",
        "compare",
        "trend",
        "trends",
        "relationship",
        "relationships",
        "correlation",
        "correlations",
        "chart",
        "charts",
        "plot",
        "plots",
        "breakdown",
        "explore",
        "exploration",
        "pattern",
        "patterns",
        "composition",
    ),
    RANK_REFERENCE: (
        "reference",
        "raw",
        "table",
        "tables",
        "record",
        "records",
        "appendix",
        "browse",
        "lookup",
        "listing",
        "rows",
        "detail",
        "details",
    ),
}

_CHART_TYPES: frozenset[str] = frozenset({"figure", "advanced_viz", "map", "image", "multiqc"})

# Icon a section gets when the planner left it blank, by panel and stage.
_DEFAULT_FILTER_ICON: dict[int, str] = {
    RANK_COHORT: "mdi:filter-variant",
    RANK_METRICS: "mdi:tune",
    RANK_ANALYSIS: "mdi:tune",
    RANK_REFERENCE: "mdi:tune",
}
_DEFAULT_GRID_ICON: dict[int, str] = {
    RANK_COHORT: "mdi:account-group-outline",
    RANK_METRICS: "mdi:counter",
    RANK_ANALYSIS: "mdi:chart-box-outline",
    RANK_REFERENCE: "mdi:table",
}


def _words(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.casefold())


def keyword_rank(name: str) -> int | None:
    """Funnel stage read off a section name, None when no keyword matches."""
    words = set(_words(name))
    hits = {rank: sum(1 for kw in kws if kw in words) for rank, kws in _RANK_KEYWORDS.items()}
    best = max(hits.values(), default=0)
    if best == 0:
        return None
    return min(rank for rank, n in hits.items() if n == best)


def section_rank(name: str, types: set[str] | frozenset[str]) -> int:
    """Funnel stage of a section from its name and the component types it holds.

    Name keywords win; otherwise interactive-only sections come first,
    table-holding sections last, chart sections are analysis, card sections
    metrics, and anything else sits in the middle (analysis rank), so a stable
    sort keeps the planner's order among unknowns.
    """
    ranked = keyword_rank(name)
    if ranked is not None:
        return ranked
    if types and types <= {"interactive"}:
        return RANK_COHORT
    if "table" in types:
        return RANK_REFERENCE
    if types & _CHART_TYPES:
        return RANK_ANALYSIS
    if "card" in types:
        return RANK_METRICS
    return RANK_ANALYSIS


# ---------------------------------------------------------------------------
# parse_plan: tolerant JSON -> strict model
# ---------------------------------------------------------------------------

_FILTER_KINDS = frozenset({"filter", "filters", "left", "panel", "interactive"})
_GRID_KINDS = frozenset({"grid", "main", "right", "content"})
_COMPONENT_TYPE_ALIASES = {"type": "component_type", "kind": "component_type"}
_DC_ALIASES = ("data_collection_tag", "dc_tag", "data_collection", "dc", "collection", "source")
_INTENT_ALIASES = ("intent", "description", "purpose", "prompt", "brief", "what")


def _section_entry(raw: Any) -> dict[str, Any] | None:
    """A section as a dict with at least a non-empty name, or None."""
    if isinstance(raw, str):
        name = raw.strip()
        return {"name": name} if name else None
    if isinstance(raw, dict):
        name = raw.get("name") or raw.get("title") or raw.get("label")
        if not isinstance(name, str) or not name.strip():
            return None
        out: dict[str, Any] = {"name": name.strip()}
        for key in ("icon", "color", "description", "rationale"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
        kind = raw.get("kind") or raw.get("panel") or raw.get("type") or raw.get("placement")
        if isinstance(kind, str):
            out["_kind"] = kind.strip().casefold()
        return out
    return None


def _section_name(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        entry = _section_entry(raw)
        return entry["name"] if entry else ""
    if isinstance(raw, list) and raw:
        return _section_name(raw[0])
    return ""


def _component_entry(raw: Any, position: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for alias, canonical in _COMPONENT_TYPE_ALIASES.items():
        if canonical not in raw and alias in raw:
            out[canonical] = raw[alias]
    for key in ("component_type", "tag", "use", "viz_kind"):
        if key in raw:
            out[key] = raw[key]
    if not out.get("tag"):
        fallback = raw.get("id") or raw.get("name")
        out["tag"] = fallback if isinstance(fallback, str) and fallback.strip() else ""
    for alias in _DC_ALIASES:
        value = raw.get(alias)
        if isinstance(value, str) and value.strip():
            out["data_collection_tag"] = value.strip()
            break
    for alias in _INTENT_ALIASES:
        value = raw.get(alias)
        if isinstance(value, str) and value.strip():
            out["intent"] = value.strip()
            break
    out["section"] = _section_name(raw.get("section"))
    if isinstance(out.get("component_type"), str):
        out["component_type"] = out["component_type"].strip().casefold()
    if not out.get("tag"):
        out["tag"] = f"{out.get('component_type') or 'component'}-{position + 1}"
    return out


def parse_plan(raw: dict[str, Any]) -> DashboardPlan:
    """Build a `DashboardPlan` from the planner's JSON, mapping loose shapes onto the strict one.

    Tolerated deviations: a `plan` wrapper; one `sections` list instead of
    `filter_sections` / `grid_sections` (split by an explicit `kind` on the
    entry, else by the components each section holds: interactive-only goes
    to the filter panel, everything else to the grid, both when mixed);
    sections given as plain strings; `type` for `component_type`; `dc` /
    `data_collection` for `data_collection_tag`; `description` / `purpose`
    for `intent`; a component `section` given as a dict or one-item list.

    Raises `pydantic.ValidationError` when the result still does not fit the
    model (an unknown component type, no title), so the caller can feed the
    error back to the model.
    """
    data = raw
    if isinstance(data, dict) and isinstance(data.get("plan"), dict) and "title" not in data:
        data = data["plan"]
    if not isinstance(data, dict):
        data = {}

    raw_components = data.get("components")
    components: list[dict[str, Any]] = []
    for position, item in enumerate(raw_components if isinstance(raw_components, list) else []):
        entry = _component_entry(item, position)
        if entry is not None:
            components.append(entry)

    def section_list(key: str) -> list[dict[str, Any]]:
        items = data.get(key)
        if not isinstance(items, list):
            return []
        return [e for e in (_section_entry(x) for x in items) if e is not None]

    filter_sections = section_list("filter_sections")
    grid_sections = section_list("grid_sections")

    if not filter_sections and not grid_sections and isinstance(data.get("sections"), list):
        types_by_section: dict[str, set[str]] = {}
        for comp in components:
            types_by_section.setdefault(comp["section"], set()).add(
                str(comp.get("component_type") or "")
            )
        for entry in section_list("sections"):
            kind = entry.pop("_kind", None)
            types = types_by_section.get(entry["name"], set())
            if kind in _FILTER_KINDS or (kind not in _GRID_KINDS and types == {"interactive"}):
                filter_sections.append(entry)
            elif kind in _GRID_KINDS or "interactive" not in types:
                grid_sections.append(entry)
            else:
                filter_sections.append(dict(entry))
                grid_sections.append(dict(entry))

    for entry in (*filter_sections, *grid_sections):
        entry.pop("_kind", None)

    strict: dict[str, Any] = {
        "title": data.get("title"),
        "subtitle": data.get("subtitle") if isinstance(data.get("subtitle"), str) else None,
        "filter_sections": filter_sections,
        "grid_sections": grid_sections,
        "components": components,
    }
    if strict["title"] is None and isinstance(data.get("name"), str):
        strict["title"] = data["name"]
    return DashboardPlan.model_validate(strict)


# ---------------------------------------------------------------------------
# normalize_plan
# ---------------------------------------------------------------------------

_TAG_CLEAN_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _clean_tag(tag: str) -> str:
    return _TAG_CLEAN_RE.sub("-", tag.strip()).strip("-")


def _dedupe_sections(
    sections: list[SectionSpec], panel: str, warnings: list[str]
) -> list[SectionSpec]:
    seen: dict[str, str] = {}
    out: list[SectionSpec] = []
    for spec in sections:
        name = " ".join(spec.name.split())
        if not name:
            warnings.append(f"Dropped an unnamed {panel} section")
            continue
        key = name.casefold()
        if key in seen:
            warnings.append(f"Merged duplicate {panel} section '{name}' into '{seen[key]}'")
            continue
        seen[key] = name
        out.append(spec.model_copy(update={"name": name}))
    return out


def _canonical(name: str, sections: list[SectionSpec]) -> str | None:
    key = " ".join(name.split()).casefold()
    for spec in sections:
        if spec.name.casefold() == key:
            return spec.name
    return None


def normalize_plan(
    plan: DashboardPlan, *, max_components: int, max_sections: int
) -> tuple[DashboardPlan, list[str]]:
    """Clamp and repair a plan deterministically; returns the new plan and its warnings.

    In order: section names are trimmed and de-duplicated; components whose
    section is unknown, or whose data collection is missing for a data-bound
    type, are dropped; an interactive planned into a grid-only section (or a
    tile into a filter-only one) has that section copied to the right list;
    each section list is cut to `max_sections` in plan order and the
    components of cut sections go with them; the component list is cut to
    `max_components` in plan order; sections left empty are dropped; tags are
    cleaned and made unique with `-2`, `-3` suffixes; sections are stably
    sorted into the funnel order; icons and colours outside the allowlists
    are replaced (fallback icon, no colour) and blank icons get a stage
    default; section descriptions and rationales are whitespace-collapsed,
    dropped when they say nothing, and a rationale longer than
    `MAX_SECTION_RATIONALE` is cut to it.
    """
    warnings: list[str] = []

    title = " ".join(plan.title.split())
    if not title:
        title = "Generated dashboard"
        warnings.append("Plan had no title; using 'Generated dashboard'")
    subtitle = " ".join(plan.subtitle.split()) if plan.subtitle else None

    filter_sections = _dedupe_sections(plan.filter_sections, "filter", warnings)
    grid_sections = _dedupe_sections(plan.grid_sections, "grid", warnings)

    # Membership: known section, right panel, data collection present.
    components: list[PlannedComponent] = []
    for comp in plan.components:
        # Blank tags stay blank here; the dedupe pass below derives one from
        # the type and position. `tag` is only for the messages.
        tag = comp.tag.strip() or comp.component_type
        in_filter = _canonical(comp.section, filter_sections)
        in_grid = _canonical(comp.section, grid_sections)
        if in_filter is None and in_grid is None:
            warnings.append(f"Dropped '{tag}': section '{comp.section}' is not in the plan")
            continue
        if comp.component_type in DATA_BOUND_TYPES and not (comp.data_collection_tag or "").strip():
            warnings.append(f"Dropped '{tag}': {comp.component_type} needs a data_collection_tag")
            continue
        is_filter = comp.component_type == "interactive"
        if is_filter and in_filter is None:
            spec = next(s for s in grid_sections if s.name == in_grid)
            filter_sections.append(spec.model_copy())
            in_filter = spec.name
            warnings.append(
                f"Section '{spec.name}' holds the filter '{tag}'; added it to the filter panel"
            )
        elif not is_filter and in_grid is None:
            spec = next(s for s in filter_sections if s.name == in_filter)
            grid_sections.append(spec.model_copy())
            in_grid = spec.name
            warnings.append(f"Section '{spec.name}' holds the tile '{tag}'; added it to the grid")
        section = in_filter if is_filter else in_grid
        assert section is not None
        components.append(
            comp.model_copy(
                update={
                    "tag": comp.tag.strip(),
                    "section": section,
                    "data_collection_tag": (comp.data_collection_tag or "").strip() or None,
                    "intent": comp.intent.strip(),
                }
            )
        )

    # Section count, per list, in plan order.
    def clamp_sections(sections: list[SectionSpec], panel: str) -> list[SectionSpec]:
        if len(sections) <= max_sections:
            return sections
        cut = [s.name for s in sections[max_sections:]]
        warnings.append(
            f"Kept the first {max_sections} {panel} sections; dropped {', '.join(repr(c) for c in cut)}"
        )
        return sections[:max_sections]

    filter_sections = clamp_sections(filter_sections, "filter")
    grid_sections = clamp_sections(grid_sections, "grid")
    filter_names = {s.name for s in filter_sections}
    grid_names = {s.name for s in grid_sections}
    kept: list[PlannedComponent] = []
    for comp in components:
        names = filter_names if comp.component_type == "interactive" else grid_names
        if comp.section in names:
            kept.append(comp)
        else:
            warnings.append(f"Dropped '{comp.tag}' with its section '{comp.section}'")
    components = kept

    # Component count, in plan order.
    if len(components) > max_components:
        cut = [c.tag for c in components[max_components:]]
        warnings.append(
            f"Kept the first {max_components} components; dropped {', '.join(repr(c) for c in cut)}"
        )
        components = components[:max_components]

    # Sections nothing landed in.
    def drop_empty(sections: list[SectionSpec], used: set[str], panel: str) -> list[SectionSpec]:
        kept: list[SectionSpec] = []
        for spec in sections:
            if spec.name in used:
                kept.append(spec)
            else:
                warnings.append(f"Dropped empty {panel} section '{spec.name}'")
        return kept

    used_filter = {c.section for c in components if c.component_type == "interactive"}
    used_grid = {c.section for c in components if c.component_type != "interactive"}
    filter_sections = drop_empty(filter_sections, used_filter, "filter")
    grid_sections = drop_empty(grid_sections, used_grid, "grid")

    # Unique tags: cleaned to [A-Za-z0-9._-], duplicates suffixed -2, -3, ...
    seen_tags: set[str] = set()
    retagged: list[PlannedComponent] = []
    for i, comp in enumerate(components):
        base = _clean_tag(comp.tag) or f"{comp.component_type}-{i + 1}"
        tag, n = base, 1
        while tag in seen_tags:
            n += 1
            tag = f"{base}-{n}"
        if tag != comp.tag:
            warnings.append(f"Renamed tag '{comp.tag}' to '{tag}'")
        seen_tags.add(tag)
        retagged.append(comp.model_copy(update={"tag": tag}))
    components = retagged

    # Funnel order: stable sort on the stage rank.
    types_by_section: dict[tuple[str, str], set[str]] = {}
    for comp in components:
        panel = "filter" if comp.component_type == "interactive" else "grid"
        types_by_section.setdefault((panel, comp.section), set()).add(comp.component_type)

    def ranked(sections: list[SectionSpec], panel: str) -> list[tuple[int, SectionSpec]]:
        pairs = [
            (section_rank(s.name, types_by_section.get((panel, s.name), set())), s)
            for s in sections
        ]
        # Within one stage, a section whose name says what it is comes before
        # one whose stage was only inferred from the types it holds, so an
        # explicit "Cohort" leads the filter panel whatever the plan order.
        return sorted(
            pairs,
            key=lambda pair: (pair[0], 0 if keyword_rank(pair[1].name) is not None else 1),
        )

    # Allowlists.
    def styled(spec: SectionSpec, rank: int, defaults: dict[int, str]) -> SectionSpec:
        icon = (spec.icon or "").strip()
        if not icon:
            icon = defaults[rank]
        elif icon not in SECTION_ICONS:
            warnings.append(
                f"Section '{spec.name}': icon '{icon}' is not available; using '{FALLBACK_ICON}'"
            )
            icon = FALLBACK_ICON
        color = (spec.color or "").strip().casefold() or None
        if color is not None and color not in SECTION_COLORS:
            warnings.append(
                f"Section '{spec.name}': colour '{spec.color}' is not a palette name; dropped"
            )
            color = None
        description = " ".join(spec.description.split()) if spec.description else None
        rationale = " ".join(spec.rationale.split()) if spec.rationale else ""
        return spec.model_copy(
            update={
                "icon": icon,
                "color": color,
                "description": description or None,
                "rationale": rationale[:MAX_SECTION_RATIONALE].rstrip() or None,
            }
        )

    filter_sections = [
        styled(s, rank, _DEFAULT_FILTER_ICON) for rank, s in ranked(filter_sections, "filter")
    ]
    grid_sections = [
        styled(s, rank, _DEFAULT_GRID_ICON) for rank, s in ranked(grid_sections, "grid")
    ]

    normalized = DashboardPlan(
        title=title,
        subtitle=subtitle,
        filter_sections=filter_sections,
        grid_sections=grid_sections,
        components=components,
    )
    return normalized, warnings
