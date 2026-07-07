"""Build a dashboard's column reuse-contract from its ``stored_metadata``.

Every dashboard component binds to a data collection by ``data_collection_tag`` and
references columns by *literal name* (``dict_kwargs.x``, ``column_name``,
``lat_column``, ...). To reuse a dashboard against another dataset the target DCs
must expose those same columns — so we enumerate, per DC, exactly which columns the
dashboard needs. This manifest (``ColumnContract``) is bundled with a shared template
(Phase 0 of the reusability plan): the importer validates it against the target DCs'
``aggregation_columns_specs`` and pre-fills column-rename suggestions when a name is
absent.

Extraction is per component-type and deliberately explicit — e.g. the ``image``
component's ``columns`` field is a grid-column *count* (an int), not a data column,
so a naive "any field named *column*" scan would be wrong.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from depictio.api.v1.services.figure.px_columns import (
    _PX_COLUMN_LIST_PARAMS,
    _PX_COLUMN_PARAMS,
)
from depictio.models.models.templates import ColumnContract, ColumnRequirement

# Plain single-column string fields, keyed by component_type -> {field: role}.
_SINGLE_COLUMN_FIELDS: dict[str, dict[str, str]] = {
    "card": {"column_name": "card:aggregation", "breakdown_col": "card:breakdown"},
    "interactive": {"column_name": "interactive:filter"},
    "table": {"row_selection_column": "table:selection"},
    "image": {"image_column": "image:path"},
    "map": {
        "lat_column": "map:lat",
        "lon_column": "map:lon",
        "color_column": "map:color",
        "size_column": "map:size",
        "text_column": "map:text",
        "z_column": "map:z",
        "locations_column": "map:locations",
        "selection_column": "map:selection",
    },
}

# List-of-column-string fields, keyed by component_type -> {field: role}.
_LIST_COLUMN_FIELDS: dict[str, dict[str, str]] = {
    "table": {"columns": "table:column"},
    "map": {"hover_columns": "map:hover"},
}

# Fields whose sibling ``column_type`` should be attached to the column requirement.
_TYPED_COLUMN_FIELDS: dict[str, str] = {"card": "column_name", "interactive": "column_name"}


def _iter_strings(value: Any) -> Iterator[str]:
    """Yield column-name strings from a list field (JSON string, list, or scalar)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return
    if isinstance(value, dict):
        for k in value:
            if isinstance(k, str) and k:
                yield k
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str) and item:
                yield item


def _figure_columns(comp: dict[str, Any]) -> Iterator[tuple[str, str, str | None]]:
    """Columns referenced by a figure component (skips code-mode figures)."""
    if (comp.get("mode") or "ui") == "code":
        # Arbitrary user code can reference any column — not enumerable.
        return
    dict_kwargs = comp.get("dict_kwargs")
    if isinstance(dict_kwargs, dict):
        for key, value in dict_kwargs.items():
            if key in _PX_COLUMN_PARAMS:
                if isinstance(value, str) and value:
                    yield value, f"figure:{key}", None
            elif key in _PX_COLUMN_LIST_PARAMS:
                for col in _iter_strings(value):
                    yield col, f"figure:{key}", None
    selection = comp.get("selection_column")
    if isinstance(selection, str) and selection:
        yield selection, "figure:selection", None


def _advanced_viz_columns(comp: dict[str, Any]) -> Iterator[tuple[str, str, str | None]]:
    """Columns bound by an advanced_viz component (``<role>_col`` / ``<role>_cols``)."""
    config = comp.get("config")
    if not isinstance(config, dict):
        return
    for key, value in config.items():
        if not isinstance(key, str):
            continue
        if key.endswith("_col") and isinstance(value, str) and value:
            yield value, f"advanced_viz:{key}", None
        elif key.endswith("_cols"):
            for col in _iter_strings(value):
                yield col, f"advanced_viz:{key}", None


def _component_columns(comp: dict[str, Any]) -> Iterator[tuple[str, str, str | None]]:
    """Yield (column_name, role, declared_type) for every column a component binds."""
    ctype = comp.get("component_type")
    if ctype == "figure":
        yield from _figure_columns(comp)
    elif ctype == "advanced_viz":
        yield from _advanced_viz_columns(comp)

    typed_field = _TYPED_COLUMN_FIELDS.get(ctype or "")

    for field, role in _SINGLE_COLUMN_FIELDS.get(ctype or "", {}).items():
        value = comp.get(field)
        if isinstance(value, str) and value:
            col_type = comp.get("column_type") if field == typed_field else None
            yield value, role, col_type

    for field, role in _LIST_COLUMN_FIELDS.get(ctype or "", {}).items():
        for col in _iter_strings(comp.get(field)):
            yield col, role, None


def build_column_contract(stored_metadata: list[dict[str, Any]] | None) -> ColumnContract:
    """Enumerate the columns each data collection must expose for a dashboard.

    Aggregates across all components: a column used by several components yields a
    single ``ColumnRequirement`` whose ``roles`` list records each usage, and whose
    ``type`` is set to the first declared ``column_type`` seen.

    Args:
        stored_metadata: The dashboard's persisted component list.

    Returns:
        A ``ColumnContract`` keyed by ``data_collection_tag``.
    """
    # dc_tag -> column_name -> {"type": str | None, "roles": list[str]}
    acc: dict[str, dict[str, dict[str, Any]]] = {}

    for comp in stored_metadata or []:
        if not isinstance(comp, dict):
            continue
        dc_tag = comp.get("data_collection_tag") or comp.get("dc_tag")
        if not dc_tag or not isinstance(dc_tag, str):
            continue
        for col, role, col_type in _component_columns(comp):
            columns = acc.setdefault(dc_tag, {})
            entry = columns.setdefault(col, {"type": None, "roles": []})
            if role not in entry["roles"]:
                entry["roles"].append(role)
            if col_type and not entry["type"]:
                entry["type"] = col_type

    collections = {
        dc_tag: [
            ColumnRequirement(name=col, type=info["type"], roles=info["roles"])
            for col, info in columns.items()
        ]
        for dc_tag, columns in acc.items()
    }
    return ColumnContract(collections=collections)
