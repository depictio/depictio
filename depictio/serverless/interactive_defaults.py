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
from typing import Any

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
