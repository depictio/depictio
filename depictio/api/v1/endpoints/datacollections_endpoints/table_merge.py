"""A file dropped on a table a user added: replace it, fill its gaps, or add columns.

The same call previews (``dry_run``) and applies, so what is shown is what gets
written. Rows are matched on one key column, chosen by the reader or found by
looking for a column unique in the file whose values also appear in the table.
A file row that matches nothing is reported and left out: a merge never adds rows.

Same rules as cell edits (``table_edit``): owners and editors of a table a user
added, not on a published project, and ``base_version`` guards against writing
over a table that moved on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import polars as pl
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints.table_edit import (
    _HIDDEN_COLUMNS,
    MAX_EDITABLE_ROWS,
    _BadValue,
    _delta_version,
    _find_dc,
    _is_blank,
    _lock_for,
    _read_frame,
    _require_editable,
    _row_count,
    _stale,
    coerce_cell,
    column_kind,
)
from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
    _align_and_concat,
    _delta_location_for,
    _read_uploaded_table,
    commit_table_frame,
)

MODES = ("replace", "fill_missing", "add_columns")

#: File extension -> the format ``_read_uploaded_table`` takes.
_FORMATS = {
    "csv": "csv",
    "tsv": "tsv",
    "tab": "tsv",
    "parquet": "parquet",
    "pq": "parquet",
    "xlsx": "xlsx",
    "xls": "xls",
}

#: Values that did not fit their column, listed in a preview.
_MAX_WARNINGS = 20
#: File rows that matched nothing, named in a preview.
_MAX_UNMATCHED_SAMPLE = 5


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _read_incoming(content: bytes, filename: str) -> pl.DataFrame:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_format = _FORMATS.get(extension)
    if file_format is None:
        raise _refuse(
            422, "unsupported_file", "Drop a CSV, TSV, Excel or Parquet file on the table."
        )
    incoming = _read_uploaded_table(content, filename, file_format, {})
    incoming = incoming.drop([c for c in incoming.columns if c in _HIDDEN_COLUMNS])
    if incoming.height == 0 or incoming.width == 0:
        raise _refuse(422, "empty_file", f"{filename} holds no rows.")
    return incoming


def _is_missing(value: Any) -> bool:
    return _is_blank(value) or (isinstance(value, float) and math.isnan(value))


def _as_key(value: Any) -> str | None:
    """A value as text, so 1, 1.0 and "1" are the same sample."""
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _keys(frame: pl.DataFrame, column: str) -> list[str | None]:
    return [_as_key(value) for value in frame[column].to_list()]


def _duplicate(keys: list[str | None]) -> str | None:
    seen: set[str] = set()
    for key in keys:
        if key is None:
            continue
        if key in seen:
            return key
        seen.add(key)
    return None


def key_candidates(table: pl.DataFrame, incoming: pl.DataFrame) -> list[dict[str, Any]]:
    """Shared columns that can link the file to the table, best first.

    One qualifies when its values are unique in the file (a row of the table
    must not have two answers) and at least one of them is in the table.
    """
    found = []
    for position, column in enumerate(table.columns):
        if column in _HIDDEN_COLUMNS or column not in incoming.columns:
            continue
        file_keys = _keys(incoming, column)
        if _duplicate(file_keys) is not None:
            continue
        known = {key for key in file_keys if key is not None}
        table_keys = [key for key in _keys(table, column) if key is not None]
        matched = sum(1 for key in table_keys if key in known)
        if matched == 0:
            continue
        found.append(
            {
                "column": column,
                "matched_rows": matched,
                "unique_in_table": len(set(table_keys)) == len(table_keys),
                "_position": position,
            }
        )
    found.sort(key=lambda c: (-c["matched_rows"], not c["unique_in_table"], c["_position"]))
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in found]


@dataclass
class _Plan:
    """What a mode would write, and what to tell the reader about it."""

    frame: pl.DataFrame
    changed: list[tuple[int, str]] = field(default_factory=list)
    new_columns: list[str] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    conflicts: int = 0
    warnings: list[str] = field(default_factory=list)
    reason: str | None = None


def _lookup(incoming: pl.DataFrame, key: str) -> dict[str, int]:
    return {k: i for i, k in enumerate(_keys(incoming, key)) if k is not None}


def _visible(table: pl.DataFrame) -> list[str]:
    return [c for c in table.columns if c not in _HIDDEN_COLUMNS]


def _plan_replace(table: pl.DataFrame, incoming: pl.DataFrame) -> _Plan:
    if incoming.height > MAX_EDITABLE_ROWS:
        raise _refuse(
            413,
            "table_too_large",
            f"This file has {incoming.height} rows; a table can be replaced here "
            f"with up to {MAX_EDITABLE_ROWS} rows.",
        )
    return _Plan(
        frame=_align_and_concat([incoming]),
        new_columns=[c for c in incoming.columns if c not in table.columns],
        removed_columns=[c for c in _visible(table) if c not in incoming.columns],
    )


def _plan_fill(table: pl.DataFrame, incoming: pl.DataFrame, key: str) -> _Plan:
    lookup = _lookup(incoming, key)
    table_keys = _keys(table, key)
    plan = _Plan(frame=table)
    for column in _visible(table):
        if column == key or column not in incoming.columns:
            continue
        dtype = table.schema[column]
        if column_kind(dtype) == "other":
            continue
        values = table[column].to_list()
        source = incoming[column].to_list()
        touched = False
        for row, row_key in enumerate(table_keys):
            match = lookup.get(row_key) if row_key is not None else None
            if match is None or _is_missing(source[match]):
                continue
            if not _is_missing(values[row]):
                plan.conflicts += _as_key(values[row]) != _as_key(source[match])
                continue
            try:
                values[row] = coerce_cell(source[match], dtype)
            except _BadValue as exc:
                plan.warnings.append(f"Row {row + 1}, column '{column}': {exc}")
                continue
            plan.changed.append((row, column))
            touched = True
        if touched:
            plan.frame = plan.frame.with_columns(pl.Series(column, values, dtype=dtype))
    if not plan.changed:
        plan.reason = "The file has nothing for the empty cells of this table."
    return plan


def _plan_add_columns(table: pl.DataFrame, incoming: pl.DataFrame, key: str) -> _Plan:
    lookup = _lookup(incoming, key)
    matches = [lookup.get(k) if k is not None else None for k in _keys(table, key)]
    plan = _Plan(
        frame=table,
        new_columns=[c for c in incoming.columns if c not in table.columns],
        ignored_columns=[c for c in incoming.columns if c in table.columns and c != key],
    )
    for column in plan.new_columns:
        source = incoming[column].to_list()
        values = [source[m] if m is not None else None for m in matches]
        plan.frame = plan.frame.with_columns(
            pl.Series(column, values, dtype=incoming.schema[column])
        )
    if not plan.new_columns:
        plan.reason = "Every column of the file is already in this table."
    return plan


def _suggested_mode(table: pl.DataFrame, incoming: pl.DataFrame, key: str | None) -> str:
    """The likeliest wish: new columns, else gaps to fill, else a new version."""
    if key is None:
        return "replace"
    if any(c not in table.columns for c in incoming.columns):
        return "add_columns"
    return "fill_missing" if _plan_fill(table, incoming, key).changed else "replace"


def _resolve_key(
    requested: str | None,
    candidates: list[dict[str, Any]],
    table: pl.DataFrame,
    incoming: pl.DataFrame,
) -> str | None:
    if not requested:
        return candidates[0]["column"] if candidates else None
    if requested not in _visible(table) or requested not in incoming.columns:
        raise _refuse(422, "invalid_key", f"Column '{requested}' is not in both tables.")
    duplicate = _duplicate(_keys(incoming, requested))
    if duplicate is not None:
        raise _refuse(
            422,
            "invalid_key",
            f"'{duplicate}' appears more than once in column '{requested}' of the file: "
            "a row of the table would have two answers.",
        )
    return requested


def _columns(plan: _Plan) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "dtype": str(plan.frame.schema[name]),
            "kind": column_kind(plan.frame.schema[name]),
            "editable": False,
            "is_new": name in plan.new_columns,
        }
        for name in _visible(plan.frame)
    ]


def merge_table_file(
    *,
    data_collection_id: str,
    content: bytes,
    filename: str,
    mode: str,
    key: str | None,
    base_version: int | None,
    dry_run: bool,
    current_user: Any,
) -> dict[str, Any]:
    """Preview or apply ``filename`` on the table; both answer the same report.

    ``mode`` is one of ``MODES`` or ``auto``. 422 (with a ``code``) for a file or
    a key that cannot be used, 409 when the table moved past ``base_version``,
    413 above the row limit.
    """
    if mode != "auto" and mode not in MODES:
        raise _refuse(422, "invalid_mode", f"Unknown mode '{mode}'.")
    if not dry_run and base_version is None:
        raise _refuse(422, "missing_version", "Applying a file needs the version previewed.")
    _require_editable(data_collection_id, current_user)
    _, dc = _find_dc(data_collection_id)
    location = _delta_location_for(data_collection_id)
    incoming = _read_incoming(content, filename)

    with _lock_for(data_collection_id):
        current = _delta_version(location)
        if base_version is not None and current != base_version:
            raise _stale(current, base_version)
        total = _row_count(location, current)
        if total > MAX_EDITABLE_ROWS:
            raise _refuse(
                413,
                "table_too_large",
                f"This table has {total} rows; only tables of up to "
                f"{MAX_EDITABLE_ROWS} rows can be updated here.",
            )
        table = _read_frame(location, current)
        candidates = key_candidates(table, incoming)
        chosen_key = _resolve_key(key, candidates, table, incoming)
        suggested = _suggested_mode(table, incoming, chosen_key)
        effective = suggested if mode == "auto" else mode

        if effective == "replace":
            plan = _plan_replace(table, incoming)
        elif chosen_key is None:
            plan = _Plan(
                frame=table,
                reason="No column links this file to the table: "
                "they need a column with the same name and matching values.",
            )
        elif effective == "fill_missing":
            plan = _plan_fill(table, incoming, chosen_key)
        else:
            plan = _plan_add_columns(table, incoming, chosen_key)

        report_version = current
        aggregation_version = None
        if not dry_run:
            if plan.reason:
                raise _refuse(422, "nothing_to_apply", plan.reason)
            aggregation_version, written = commit_table_frame(
                data_collection_id=data_collection_id,
                frame=plan.frame,
                current_user=current_user,
                write_mode="overwrite",
                trigger="ui",
                dc_for_specs=dc,
            )
            report_version = written if written is not None else current

    linked = effective != "replace" and chosen_key is not None
    table_keys = _keys(table, chosen_key) if linked else []
    file_keys = _keys(incoming, chosen_key) if linked else []
    known_file = {k for k in file_keys if k is not None}
    known_table = {k for k in table_keys if k is not None}
    unmatched_file = [k for k in file_keys if k is not None and k not in known_table]

    from depictio.api.v1.endpoints.deltatables_endpoints.routes import _json_safe

    shown = _visible(plan.frame)
    return {
        "success": True,
        "data_collection_id": data_collection_id,
        "dry_run": dry_run,
        "mode": effective,
        "suggested_mode": suggested,
        "key": chosen_key,
        "key_candidates": candidates,
        "delta_version": report_version,
        "aggregation_version": aggregation_version,
        "table_rows": table.height,
        "file_rows": incoming.height,
        "row_count": plan.frame.height,
        "matched_rows": sum(1 for k in table_keys if k in known_file),
        "unmatched_file_rows": len(unmatched_file),
        "unmatched_file_sample": unmatched_file[:_MAX_UNMATCHED_SAMPLE],
        "filled_cells": len(plan.changed),
        "conflicts": plan.conflicts,
        "new_columns": plan.new_columns,
        "ignored_columns": plan.ignored_columns,
        "removed_columns": plan.removed_columns,
        "warnings": plan.warnings[:_MAX_WARNINGS],
        "can_apply": plan.reason is None,
        "reason": plan.reason,
        "changed": [{"row": row, "column": column} for row, column in plan.changed],
        "columns": _columns(plan),
        "rows": [
            {name: _json_safe(value) for name, value in row.items()}
            for row in plan.frame.select(shown).iter_rows(named=True)
        ],
    }
