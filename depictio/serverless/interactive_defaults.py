"""The filter state a tab opens on: its interactive components' declared defaults.

The Python twin of ``depictio-react-core``'s ``interactiveDefaults.ts``
(``defaultFilterValue`` / ``withInteractiveDefaults``). A dashboard YAML can give
a filter a ``default_value`` or a ``default_range``; both reach the stored
component as ``default_state``, and the viewer — the static bundle's App
included — seeds its filter state with them, so a tab meant to open on "Q10
reads" opens filtered.

Producer A freezes its snapshots at that same state: a frozen tile computed with
no filter at all would show every row beside live tiles already narrowed to the
defaults, under a badge that says "default state". The entries are in the shape
the viewer sends (``InteractiveFilter``), so the endpoint bodies producer A
calls read them exactly as they read a browser's.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any

from depictio.models.models.serverless import InitialGrouping

if TYPE_CHECKING:
    from depictio.models.models.analysis_state import AnalysisState

_RANGE_TYPES = frozenset({"RangeSlider", "DateRangePicker", "DatePicker"})
_LIST_TYPES = frozenset({"Select", "MultiSelect"})
#: ``textFilter.MAX_PATTERN_LENGTH``.
_MAX_PATTERN_LENGTH = 512


def _number(value: Any) -> int | float | None:
    """JavaScript's ``Number(v)``, finite results only (``None`` otherwise)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return int(out) if out.is_integer() and not isinstance(value, float) else out


def _text_pattern(value: Any, match_mode: Any) -> str | None:
    """A TextInput default as the viewer seeds it: trimmed, and dropped when it
    is empty, over the length cap, or a regex that does not compile."""
    text = str(value).strip()
    if not text or len(text) > _MAX_PATTERN_LENGTH:
        return None
    if match_mode == "contains":
        return text
    try:
        re.compile(text)
    except re.error:
        return None
    return text


def default_filter_value(comp: dict[str, Any]) -> Any:
    """The value a renderer would emit for this component's declared default,
    or ``None`` when it declares none (or one that cannot apply)."""
    state = comp.get("default_state") or {}
    if not isinstance(state, dict):
        return None
    kind = comp.get("interactive_component_type") or ""
    if kind in _RANGE_TYPES:
        rng = state.get("default_range")
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            return None
        if kind == "RangeSlider":
            lo, hi = _number(rng[0]), _number(rng[1])
            return [lo, hi] if lo is not None and hi is not None else None
        return [None if v is None else str(v) for v in rng]
    value = state.get("default_value")
    if value is None:
        return None
    if kind in _LIST_TYPES:
        items = [str(v) for v in (value if isinstance(value, (list, tuple)) else [value])]
        return items or None
    if kind == "Slider":
        return _number(value)
    if kind in ("Checkbox", "Switch"):
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)
    if kind == "SegmentedControl":
        return str(value)
    if kind == "TextInput":
        return _text_pattern(value, comp.get("match_mode"))
    return None


def default_filters(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One filter entry per interactive component that declares a default:
    ``withInteractiveDefaults([], components)``."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for comp in components:
        index = str(comp.get("index") or "")
        if comp.get("component_type") != "interactive" or index in seen:
            continue
        value = default_filter_value(comp)
        if value is None:
            continue
        seen.add(index)
        kind = comp.get("interactive_component_type")
        metadata: dict[str, Any] = {
            "dc_id": str(comp["dc_id"]) if comp.get("dc_id") else None,
            "column_name": comp.get("column_name"),
            "interactive_component_type": kind,
        }
        if comp.get("slider_mode"):
            metadata["slider_mode"] = comp["slider_mode"]
        if kind == "TextInput":
            if comp.get("case_sensitive") is True:
                metadata["case_sensitive"] = True
            if comp.get("match_mode") == "contains":
                metadata["match_mode"] = "contains"
        entry: dict[str, Any] = {
            "index": index,
            "value": value,
            "column_name": comp.get("column_name"),
            "interactive_component_type": kind,
        }
        if comp.get("filter_expr"):
            entry["filter_expr"] = comp["filter_expr"]
        entry["metadata"] = metadata
        out.append(entry)
    return out


def filters_for_state(
    components: list[dict[str, Any]], state: AnalysisState | None
) -> list[dict[str, Any]]:
    """The filter state a tab's tiles freeze at under an exported ``AnalysisState``.

    ``None`` is the pre-state contract: the tab's own interactive defaults
    (:func:`default_filters`). With a state, an entry the state holds for one
    of ``components`` wins (it is the value the viewer showed when the export
    was asked for), an interactive component the state does not mention keeps
    its declared default, and a state entry naming no component here is
    dropped: another tab's, or a component this tab no longer has. The
    projections of the state's selection groups (``source == "group_filter"``)
    ride along on every tab: the runtime derives the same filters from the
    groups it opens with (``initial_grouping``), so a frozen tile agrees with
    the live ones.
    """
    if state is None:
        return default_filters(components)
    known = {str(comp.get("index") or "") for comp in components}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in state.filters_as_payload():
        index = str(entry.get("index") or "")
        if entry.get("source") == "group_filter":
            out.append(entry)
            continue
        if index not in known:
            continue
        out.append(entry)
        seen.add(index)
    # The declared defaults fill in what the state does not cover, exactly as
    # ``withInteractiveDefaults`` fills an empty filter store.
    return out + default_filters(
        [comp for comp in components if str(comp.get("index") or "") not in seen]
    )


def grouping_for_state(state: AnalysisState | None) -> InitialGrouping | None:
    """The selection groups, colour-by and split the runtime opens on, or ``None``.

    Copied from the analysis state as it is: the runtime seeds the viewer's own
    group store from it and derives the figures' colouring and panels itself.
    ``None`` when the state holds neither a group nor a colour-by, so a bundle
    built without them stays byte-identical to what it was.
    """
    if state is None:
        return None
    grouping = InitialGrouping(
        groups=list(state.groups),
        color_by=state.color_by,
        display_mode=state.display_mode,
        show_other=state.show_other,
        show_overall=state.show_overall,
        split_panels=list(state.split_panels),
    )
    return grouping if grouping.active else None


def grouping_columns(state: AnalysisState | None) -> set[str]:
    """Columns the grouping reads: every group's, and the colour-by column.

    Folded into the columns a bundle keeps, whichever collection holds them
    (the same rule as an interactive filter's column), so a group made on a
    column no tile references still has its rows to match.
    """
    if state is None:
        return set()
    columns = {g.column_name for g in state.groups}
    if state.color_by.kind == "column" and state.color_by.column_name:
        columns.add(state.color_by.column_name)
    return columns


def grouping_render_body(state: AnalysisState | None) -> dict[str, Any]:
    """The grouping fields of a ``render_figure`` request body for ``state``.

    What the viewer would send for the same state, minus a palette it computes
    from the column's universe: an export has none, so a colour-by-column
    request is mapless (the template's colours). Empty when nothing colours.
    """
    if state is None:
        return {}
    body: dict[str, Any] = {}
    if state.color_by.kind == "groups" and state.groups:
        body = {
            "groups": [
                {
                    "name": g.name,
                    "column_name": g.column_name,
                    "values": list(g.values),
                    "color": g.color,
                    **({"dc_id": g.dc_id} if g.dc_id else {}),
                }
                for g in state.groups
                if g.values
            ],
            "color_by_group": True,
        }
        if not body["groups"]:
            return {}
        if not state.show_other:
            body["include_other"] = False
    elif state.color_by.kind == "column" and state.color_by.column_name:
        body = {"color_by_column": {"column_name": state.color_by.column_name}}
    else:
        return {}
    if state.display_mode == "facet":
        body["grouping_display"] = "facet"
    return body
