"""Which tables of a project a reader may label with session annotations.

Only a metadata table (a samplesheet or a metadata sheet) linked to the data
can be labelled: its labels reach the charts as selection groups on the link's
key column, which the server resolves to every linked collection. A table is
eligible when all of these hold:

1. it is a table;
2. it is the source of at least one enabled link; its key columns are the
   ``source_column``s of those links;
3. it is not the result of a join (nor otherwise derived);
4. it is not an input of a join: labels are keyed on one table, and a joined
   copy of its rows would not follow them;
5. its ``metatype`` is absent or "metadata" (a pipeline's samplesheet often
   declares none; "Aggregate" tables are results, not metadata);
6. it has at most ``MAX_EDITABLE_ROWS`` rows, the size the grid loads whole.

``classify_tables`` holds the rule and reads nothing; ``annotatable_tables``
adds the row counts from Delta.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.datacollections_endpoints.table_edit import MAX_EDITABLE_ROWS

#: Why a table cannot be labelled; ``code`` is stable, ``reason`` is shown.
_REASONS = {
    "not_linked": "Only a metadata table linked to the data can be labelled.",
    "derived_table": "This table is computed from other data and cannot be labelled.",
    "join_input": "This table is joined into another one; labels would not follow it.",
    "not_metadata": "Only a metadata table (a samplesheet or a metadata sheet) can be labelled.",
    "no_data": "This table has no data yet.",
}


def _too_large(rows: int) -> str:
    return f"This table has {rows} rows; only tables of up to {MAX_EDITABLE_ROWS} rows can be labelled."


def _id(value: Any) -> str:
    return str(value) if value is not None else ""


def _join_refs(project: dict[str, Any]) -> tuple[set[str], list[tuple[str, str | None]]]:
    """``(result ids, [(input ref, join workflow_name)])`` of the project's joins."""
    results: set[str] = set()
    inputs: list[tuple[str, str | None]] = []
    for join in project.get("joins") or []:
        if join.get("result_dc_id"):
            results.add(_id(join["result_dc_id"]))
        if join.get("id"):
            results.add(_id(join["id"]))
        for side in ("left_dc", "right_dc"):
            ref = join.get(side)
            if ref:
                inputs.append((str(ref), join.get("workflow_name")))
    return results, inputs


def _is_join_input(tag: str, workflow_name: str | None, inputs: list[tuple[str, str | None]]) -> bool:
    for ref, join_workflow in inputs:
        if "." in ref:
            if workflow_name and ref == f"{workflow_name}.{tag}":
                return True
        elif ref == tag and (join_workflow is None or join_workflow == workflow_name):
            return True
    return False


def _is_derived(config: dict[str, Any]) -> bool:
    return bool(
        config.get("join")
        or config.get("transform")
        or config.get("source") not in (None, "native")
    )


def classify_tables(
    project: dict[str, Any],
    row_count: Callable[[str], int | None],
) -> list[dict[str, Any]]:
    """Every table of ``project`` with whether it can be labelled and why not.

    ``row_count(dc_id)`` is asked only for tables passing every other rule;
    ``None`` means no readable data.
    """
    key_columns: dict[str, list[str]] = {}
    for link in project.get("links") or []:
        if link.get("enabled", True) is False:
            continue
        source = _id(link.get("source_dc_id"))
        column = link.get("source_column")
        if source and column and column not in key_columns.setdefault(source, []):
            key_columns[source].append(column)
    results, inputs = _join_refs(project)

    tables: list[dict[str, Any]] = []
    for workflow in project.get("workflows") or []:
        workflow_name = workflow.get("name")
        for dc in workflow.get("data_collections") or []:
            config = dc.get("config") or {}
            if str(config.get("type") or "").lower() != "table":
                continue
            dc_id = _id(dc.get("_id") or dc.get("id"))
            tag = dc.get("data_collection_tag") or ""
            keys = key_columns.get(dc_id, [])
            code: str | None = None
            if _is_derived(config) or dc_id in results:
                code = "derived_table"
            elif _is_join_input(tag, workflow_name, inputs):
                code = "join_input"
            elif not keys:
                code = "not_linked"
            elif str(config.get("metatype") or "metadata").strip().lower() != "metadata":
                code = "not_metadata"
            rows: int | None = None
            reason = _REASONS[code] if code else None
            if code is None:
                rows = row_count(dc_id)
                if rows is None:
                    code, reason = "no_data", _REASONS["no_data"]
                elif rows > MAX_EDITABLE_ROWS:
                    code, reason = "table_too_large", _too_large(rows)
            tables.append(
                {
                    "dc_id": dc_id,
                    "tag": tag,
                    "workflow_name": workflow_name,
                    "key_columns": keys,
                    "row_count": rows,
                    "eligible": code is None,
                    "code": code,
                    "reason": reason,
                }
            )
    return tables


def _delta_row_count(dc_id: str) -> int | None:
    from depictio.api.v1.endpoints.datacollections_endpoints.table_edit import _row_count
    from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
        _delta_location_for,
    )

    try:
        from deltalake import DeltaTable

        from depictio.api.v1.s3 import polars_s3_config

        location = _delta_location_for(dc_id)
        version = int(DeltaTable(location, storage_options=polars_s3_config).version())
        return _row_count(location, version)
    except Exception as exc:
        logger.info(f"Annotation tables: no readable Delta table for {dc_id}: {exc}")
        return None


def annotatable_tables(project: dict[str, Any]) -> list[dict[str, Any]]:
    """``classify_tables`` with row counts read from Delta."""
    return classify_tables(project, _delta_row_count)
