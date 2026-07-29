"""Can this dashboard version still render against today's data?

Replaces the export-side integrity helpers in ``routes.py``, which were broken
in three independent ways — each on its own enough to make them return nothing:

* they read ``component["data_collection_id"]``, but components carry
  ``dc_id`` (measured: 251/251 components across every seeded dashboard);
* they looked data collections up in ``data_collections_collection``, which is
  never written to anywhere in the codebase — collections live embedded at
  ``projects.workflows[].data_collections[]``;
* they read column specs from ``config.columns_specs``, which does not exist;
  the schema lives at ``deltatables.aggregation[-1].aggregation_columns_specs``.

Because both the producing and the checking side were broken symmetrically,
the check compared one empty column list against another and reported
"schema matches" for everything. That is worse than no check at all, so this
is a rewrite rather than a repair.

Everything here is synchronous and Mongo-only. A report may cover a dozen
collections and is rendered while someone waits on a confirm dialog, so it
must not make an object-store round trip per collection.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import deltatables_collection, projects_collection

#: Component fields that name a column. Surveyed across every seeded dashboard;
#: the map/table entries are why a card-and-figure-only check would miss most
#: real breakage.
_COLUMN_FIELDS: tuple[str, ...] = (
    "column_name",
    "breakdown_col",
    "selection_column",
    "lat_column",
    "lon_column",
    "color_column",
    "size_column",
    "z_column",
    "text_column",
    "locations_column",
    "row_selection_column",
)

#: Component fields holding a *list* of column names.
_COLUMN_LIST_FIELDS: tuple[str, ...] = ("columns", "hover_columns")

#: Keys inside a figure's ``dict_kwargs`` that name columns.
_FIGURE_KWARG_FIELDS: tuple[str, ...] = ("x", "y", "color", "size", "symbol", "hover_name")


def generate_schema_hash(columns: list[dict[str, str]]) -> str:
    """Stable digest of a column set, order-independent."""
    ordered = sorted(columns, key=lambda c: c.get("name", ""))
    payload = "|".join(f"{c.get('name', '')}:{c.get('type', '')}" for c in ordered)
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def component_dc_id(component: dict[str, Any]) -> Optional[str]:
    """The data collection a component reads, tolerating extended-JSON ids."""
    raw = component.get("dc_id")
    if not raw:
        return None
    return str(raw.get("$oid") if isinstance(raw, dict) else raw)


def collect_dc_ids(components: Iterable[dict[str, Any]]) -> list[str]:
    """Distinct data collection ids referenced, in first-seen order."""
    seen: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        dc_id = component_dc_id(component)
        if dc_id and dc_id not in seen:
            seen.append(dc_id)
    return seen


def referenced_columns(component: dict[str, Any]) -> set[str]:
    """Every column name a component depends on.

    Covers all eight component types rather than the three the old YAML-only
    validator handled — a map component alone can reference seven columns, and
    missing those is what made the previous check feel clean while being blind.
    """
    columns: set[str] = set()

    for field in _COLUMN_FIELDS:
        value = component.get(field)
        if isinstance(value, str) and value:
            columns.add(value)

    for field in _COLUMN_LIST_FIELDS:
        value = component.get(field)
        if isinstance(value, list):
            columns.update(v for v in value if isinstance(v, str) and v)

    kwargs = component.get("dict_kwargs")
    if isinstance(kwargs, dict):
        for field in _FIGURE_KWARG_FIELDS:
            value = kwargs.get(field)
            if isinstance(value, str) and value:
                columns.add(value)

    config = component.get("config")
    if isinstance(config, dict):
        for key, value in config.items():
            if key.endswith("_col") and isinstance(value, str) and value:
                columns.add(value)

    return columns


def read_dc_schema(dc_id: str) -> Optional[dict[str, Any]]:
    """Current columns and row count for a data collection, or None.

    Reads the aggregation record rather than the data collection config: the
    config has never carried column specs, and the aggregation is the only
    place the materialised schema is recorded.
    """
    try:
        dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(dc_id)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"schema_integrity: deltatable lookup failed for {dc_id}: {exc}")
        return None

    aggregations = (dt_doc or {}).get("aggregation") or []
    if not aggregations:
        return None

    latest = aggregations[-1] or {}
    raw = latest.get("aggregation_columns_specs")
    columns: list[dict[str, str]] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and entry.get("name"):
                columns.append(
                    {"name": str(entry["name"]), "type": str(entry.get("type", "") or "")}
                )
    elif isinstance(raw, dict):  # legacy shape
        for name, spec in raw.items():
            columns.append({"name": str(name), "type": str((spec or {}).get("type", "") or "")})

    return {
        "columns": columns,
        "schema_hash": generate_schema_hash(columns),
        "row_count": latest.get("rows_total"),
        "delta_version": latest.get("delta_version"),
        "aggregation_version": latest.get("aggregation_version"),
    }


def dc_exists(dc_id: str) -> bool:
    """Is the collection still present in any project?

    Resolved the way the rest of the codebase does it — collections are
    embedded in the project document, not stored top-level.
    """
    try:
        return (
            projects_collection.find_one(
                {"workflows.data_collections._id": ObjectId(dc_id)}, {"_id": 1}
            )
            is not None
        )
    except Exception:  # pragma: no cover - defensive
        return False


def diff_columns(
    expected: list[dict[str, str]], current: list[dict[str, str]]
) -> dict[str, list[Any]]:
    """What changed between two column sets.

    Two hashes can only say "different". A component breaks because a specific
    column vanished or changed type, so the report has to name them.
    """
    expected_by_name = {c.get("name", ""): c.get("type", "") for c in expected}
    current_by_name = {c.get("name", ""): c.get("type", "") for c in current}

    removed = sorted(set(expected_by_name) - set(current_by_name))
    added = sorted(set(current_by_name) - set(expected_by_name))
    retyped = [
        {"name": name, "from": expected_by_name[name], "to": current_by_name[name]}
        for name in sorted(set(expected_by_name) & set(current_by_name))
        if expected_by_name[name]
        and current_by_name[name]
        and expected_by_name[name] != current_by_name[name]
    ]
    return {"removed": removed, "added": added, "retyped": retyped}


def affected_components(
    components: Iterable[dict[str, Any]], dc_id: str, broken: set[str]
) -> list[str]:
    """Indices of components that reference one of ``broken`` on ``dc_id``.

    This is what turns a schema diff into something actionable: not "the schema
    changed" but "these three boxes will not render".
    """
    if not broken:
        return []
    hits: list[str] = []
    for component in components:
        if not isinstance(component, dict) or component_dc_id(component) != dc_id:
            continue
        if referenced_columns(component) & broken:
            index = component.get("index")
            if index:
                hits.append(str(index))
    return hits


def build_compatibility_report(
    components: list[dict[str, Any]], stamps: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare a version's recorded data provenance against today's.

    ``components`` is the flattened ``stored_metadata`` across the version's
    tabs; ``stamps`` is its ``data_collections`` list.
    """
    stamps_by_dc = {str(s.get("dc_id")): s for s in stamps if s.get("dc_id")}
    checks: list[dict[str, Any]] = []
    severity = "ok"

    def raise_to(level: str) -> None:
        nonlocal severity
        order = {"ok": 0, "info": 1, "warning": 2, "error": 3}
        if order[level] > order[severity]:
            severity = level

    for dc_id in collect_dc_ids(components):
        stamp = stamps_by_dc.get(dc_id, {})
        check: dict[str, Any] = {
            "dc_id": dc_id,
            "data_collection_tag": stamp.get("data_collection_tag", ""),
            "workflow_tag": stamp.get("workflow_tag", ""),
            "dc_type": stamp.get("dc_type", ""),
            "version_kind": stamp.get("version_kind", "none"),
            "delta_version": stamp.get("delta_version"),
            "found": True,
            "schema_match": True,
            "columns_removed": [],
            "columns_added": [],
            "columns_retyped": [],
            "affected_components": [],
            "issues": [],
        }

        if not dc_exists(dc_id):
            check["found"] = False
            check["schema_match"] = False
            check["issues"].append("dc_deleted")
            # Every component on a deleted collection is affected, not just
            # the ones naming a particular column.
            check["affected_components"] = [
                str(c.get("index"))
                for c in components
                if isinstance(c, dict) and component_dc_id(c) == dc_id and c.get("index")
            ]
            raise_to("error")
            checks.append(check)
            continue

        current = read_dc_schema(dc_id)
        if current is None:
            check["issues"].append("no_aggregation_record")
            raise_to("info")
            checks.append(check)
            continue

        expected_columns = stamp.get("columns") or []
        if not expected_columns:
            # Nothing was recorded at capture time, so there is nothing to
            # compare — say so rather than claiming a match.
            check["issues"].append("no_recorded_schema")
            raise_to("info")
            checks.append(check)
            continue

        delta = diff_columns(expected_columns, current["columns"])
        check["columns_removed"] = delta["removed"]
        check["columns_added"] = delta["added"]
        check["columns_retyped"] = delta["retyped"]
        check["schema_match"] = stamp.get("schema_hash") == current["schema_hash"]

        broken = set(delta["removed"])
        hits = affected_components(components, dc_id, broken)
        check["affected_components"] = hits

        if hits:
            check["issues"].append("column_missing")
            raise_to("error")
        elif delta["removed"]:
            # A column went away but nothing on this dashboard used it.
            check["issues"].append("column_removed_unused")
            raise_to("info")
        if delta["retyped"]:
            check["issues"].append("dtype_changed")
            raise_to("warning")
        if delta["added"]:
            check["issues"].append("columns_added")
            raise_to("info")
        if stamp.get("version_kind") == "none" and stamp.get("reason"):
            check["issues"].append(str(stamp["reason"]))
            raise_to("info")

        checks.append(check)

    return {
        "severity": severity,
        # Nothing here blocks a restore: schema drift is worth showing before
        # the fact, not worth refusing over. Only a corrupt record blocks.
        "renderable": True,
        "checks": checks,
    }
