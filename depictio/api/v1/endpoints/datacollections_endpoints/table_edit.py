"""Cell edits on a table a user added, like a spreadsheet (typically a sample sheet).

Only a table a user added is editable: an uploaded file, or a plain table added
from a folder. A table a pipeline run or a template produced stays read-only,
because the next ingest would overwrite the edit and the source of truth is the
pipeline. Owners and editors of the project may edit; a viewer may read the
state. A published project is read-only (409).

The write goes through ``table_manage.commit_table_frame``, the same path as
append and replace: a new Delta commit, a new ``aggregation_version`` (which salts
every DataFrame cache key, so every worker reads the new table) and cache
invalidation.

Rows are addressed by their position in the Delta version the client read.
``base_version`` is that Delta version: a table that moved on since answers 409
instead of applying positions to different rows.
"""

from __future__ import annotations

import math
import threading
from datetime import date, datetime, time, timezone
from typing import Any

import polars as pl
from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import projects_collection
from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
    _CLI_AUGMENTED_COLUMNS,
    _delta_location_for,
    commit_table_frame,
)
from depictio.api.v1.endpoints.projects_endpoints.publish_lock import (
    LOCKED_DETAIL,
    assert_project_unlocked,
    is_project_locked,
)
from depictio.api.v1.permissions import get_user_group_ids, has_permission
from depictio.api.v1.s3 import polars_s3_config

#: A table with more rows than this is refused: the editor loads the whole table
#: into the browser and the server rewrites it on every save.
MAX_EDITABLE_ROWS = 10_000
#: Cells a single save may change.
MAX_EDITS_PER_REQUEST = 5_000

#: ``config.origin.kind`` values of a table a user added. ``run``, ``manifest``
#: (pipeline and template output) and ``url`` (re-read from its source) are not.
EDITABLE_ORIGIN_KINDS = frozenset({"upload", "folder"})

#: Prefix of the temp dir ``create_from_upload`` writes the file to; tables
#: uploaded before ``config.origin`` existed keep it in their scan filename.
LEGACY_UPLOAD_DIR_PREFIX = "depictio_upload_"

# Bookkeeping columns the ingest adds; never shown, never editable.
_HIDDEN_COLUMNS = frozenset(_CLI_AUGMENTED_COLUMNS)

# One save at a time per collection inside a worker. The version check is what
# protects against another worker.
_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(dc_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(dc_id, threading.Lock())


class CellEdit(BaseModel):
    """One cell: ``row`` is 0-based in the Delta version the client read."""

    row: int = Field(ge=0)
    column: str
    #: Typed text from the editor, or a JSON scalar; null or "" clears the cell.
    value: Any = None


class CellEditsRequest(BaseModel):
    base_version: int = Field(ge=0, description="Delta version the client read.")
    edits: list[CellEdit] = Field(min_length=1, max_length=MAX_EDITS_PER_REQUEST)


# ----------------------------------------------------------------------------
# What may be edited
# ----------------------------------------------------------------------------


def _not_editable(code: str, message: str) -> dict[str, Any]:
    return {"editable": False, "code": code, "reason": message}


def table_edit_verdict(dc: dict[str, Any]) -> dict[str, Any]:
    """Whether the data collection document ``dc`` is a table a user added.

    ``{"editable": True}``, or ``{"editable": False, "code", "reason"}``. An
    absent marker means not editable, except for a table uploaded before
    ``config.origin`` existed, which the upload route left recognisable: its
    scan file sits in a ``depictio_upload_*`` temp dir (a CLI-made table never
    does, nor does a pipeline's).
    """
    config = dc.get("config") or {}
    if str(config.get("type") or "").lower() != "table":
        return _not_editable("not_a_table", "Only tables can be edited.")
    if (
        config.get("join")
        or config.get("transform")
        or config.get("source")
        not in (
            None,
            "native",
        )
    ):
        return _not_editable(
            "derived_table", "This table is computed from other data and cannot be edited."
        )

    origin = config.get("origin") or {}
    kind = origin.get("kind")
    if kind in EDITABLE_ORIGIN_KINDS:
        return {"editable": True}
    if kind in ("run", "manifest"):
        return _not_editable(
            "pipeline_table",
            "This table comes from a pipeline run or a template. "
            "Edit its source data and ingest it again.",
        )
    if kind == "url":
        return _not_editable(
            "url_table", "This table is read from a URL. Edit the file at its source."
        )
    if kind is None and _legacy_upload(config):
        return {"editable": True}
    return _not_editable(
        "not_user_added",
        "Only tables added from a file or a folder in Depictio can be edited here.",
    )


def _legacy_upload(config: dict[str, Any]) -> bool:
    scan = config.get("scan") or {}
    params = scan.get("scan_parameters") or {}
    filename = str(params.get("filename") or "").replace("\\", "/")
    if scan.get("mode") != "single" or not filename:
        return False
    return any(part.startswith(LEGACY_UPLOAD_DIR_PREFIX) for part in filename.split("/")[:-1])


# ----------------------------------------------------------------------------
# Lookup and permissions
# ----------------------------------------------------------------------------


def _find_dc(data_collection_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        dc_oid = ObjectId(data_collection_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid data collection id: {exc}")
    project = projects_collection.find_one({"workflows.data_collections._id": dc_oid})
    if project:
        for workflow in project.get("workflows") or []:
            for dc in workflow.get("data_collections") or []:
                if str(dc.get("_id") or dc.get("id")) == data_collection_id:
                    return project, dc
    raise HTTPException(status_code=404, detail="Data collection not found.")


def _role_flags(project: dict[str, Any], user: Any) -> tuple[bool, bool]:
    """``(can_view, can_edit)`` for ``user`` on ``project``."""
    group_ids = get_user_group_ids(getattr(user, "id", None))
    return (
        has_permission(project, user, "viewer", group_ids),
        has_permission(project, user, "editor", group_ids),
    )


def _resolve(data_collection_id: str, user: Any) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """``(project, dc, can_edit)``; 404 when the user cannot even see the collection."""
    project, dc = _find_dc(data_collection_id)
    can_view, can_edit = _role_flags(project, user)
    if not can_view:
        raise HTTPException(status_code=404, detail="Data collection not found.")
    return project, dc, can_edit


def _require_editable(data_collection_id: str, user: Any) -> dict[str, Any]:
    """The project, once ``user`` may edit this table: 403, 409 (published), 403."""
    project, dc, can_edit = _resolve(data_collection_id, user)
    if not can_edit:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "read_only_role",
                "message": "Only project owners and editors can edit this table.",
            },
        )
    assert_project_unlocked(project)
    verdict = table_edit_verdict(dc)
    if not verdict["editable"]:
        raise HTTPException(
            status_code=403,
            detail={"code": verdict["code"], "message": verdict["reason"]},
        )
    return project


# ----------------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------------


def _delta_version(location: str) -> int:
    from deltalake import DeltaTable

    try:
        return int(DeltaTable(location, storage_options=polars_s3_config).version())
    except Exception as exc:
        logger.warning(f"Table edit: no readable Delta table at {location}: {exc}")
        raise HTTPException(
            status_code=404, detail="This data collection has no data to edit yet."
        ) from exc


def _row_count(location: str, version: int) -> int:
    lazy = pl.scan_delta(location, version=version, storage_options=polars_s3_config)
    return int(lazy.select(pl.len()).collect().item())


def _read_frame(location: str, version: int) -> pl.DataFrame:
    return pl.read_delta(location, version=version, storage_options=polars_s3_config)


def column_kind(dtype: pl.DataType) -> str:
    """The editor's view of a polars dtype; ``other`` columns are shown, not editable."""
    if dtype == pl.Boolean:
        return "boolean"
    if dtype.is_integer():
        return "integer"
    if dtype.is_float():
        return "float"
    if dtype == pl.String:
        return "string"
    if dtype == pl.Date:
        return "date"
    if dtype == pl.Datetime:
        return "datetime"
    if dtype == pl.Time:
        return "time"
    return "other"


def table_edit_status(data_collection_id: str, user: Any) -> dict[str, Any]:
    """What the edit control should show. Reads Mongo only.

    ``table_editable``: a user added this table. ``can_edit``: and the caller is
    an owner/editor and the project is not published. ``role_can_edit``: the
    caller is an owner/editor (so a disabled control with ``reason`` is worth
    showing). ``code``/``reason`` say why a table cannot be edited right now.
    """
    project, dc, role_can_edit = _resolve(data_collection_id, user)
    verdict = table_edit_verdict(dc)
    code: str | None = None
    reason: str | None = None
    can_edit = bool(verdict["editable"] and role_can_edit)
    if not verdict["editable"]:
        code, reason = verdict["code"], verdict["reason"]
    elif role_can_edit and is_project_locked(project):
        can_edit, code, reason = False, "published_lock", LOCKED_DETAIL
    return {
        "data_collection_id": data_collection_id,
        "table_editable": verdict["editable"],
        "can_edit": can_edit,
        "role_can_edit": role_can_edit,
        "code": code,
        "reason": reason,
        "max_rows": MAX_EDITABLE_ROWS,
    }


def read_table_for_edit(data_collection_id: str, user: Any) -> dict[str, Any]:
    """The whole table with the Delta version it was read at, for an owner or editor."""
    _require_editable(data_collection_id, user)
    location = _delta_location_for(data_collection_id)
    version = _delta_version(location)
    total = _row_count(location, version)
    if total > MAX_EDITABLE_ROWS:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "table_too_large",
                "message": (
                    f"This table has {total} rows; only tables of up to "
                    f"{MAX_EDITABLE_ROWS} rows can be edited here."
                ),
            },
        )
    frame = _read_frame(location, version)
    shown = [c for c in frame.columns if c not in _HIDDEN_COLUMNS]

    from depictio.api.v1.endpoints.deltatables_endpoints.routes import _json_safe

    columns = []
    for name in shown:
        kind = column_kind(frame.schema[name])
        columns.append(
            {
                "name": name,
                "dtype": str(frame.schema[name]),
                "kind": kind,
                "editable": kind != "other",
            }
        )
    rows = [
        {name: _json_safe(value) for name, value in row.items()}
        for row in frame.select(shown).iter_rows(named=True)
    ]
    return {
        "data_collection_id": data_collection_id,
        "delta_version": version,
        "row_count": frame.height,
        "max_rows": MAX_EDITABLE_ROWS,
        "columns": columns,
        "rows": rows,
    }


# ----------------------------------------------------------------------------
# Casting
# ----------------------------------------------------------------------------


class _BadValue(ValueError):
    """A value that cannot become the column's type; the message is for the user."""


_TRUE = {"true", "yes", "y", "1", "t"}
_FALSE = {"false", "no", "n", "0", "f"}


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        raise _BadValue("expected a whole number")
    if isinstance(value, int):
        return value
    try:
        if isinstance(value, float):
            number = value
        else:
            text = str(value).strip()
            try:
                return int(text)
            except ValueError:
                number = float(text)
    except (TypeError, ValueError):
        raise _BadValue("expected a whole number")
    if not math.isfinite(number) or not number.is_integer():
        raise _BadValue("expected a whole number")
    return int(number)


def _to_float(value: Any) -> float:
    if isinstance(value, bool):
        raise _BadValue("expected a number")
    try:
        number = float(value if isinstance(value, int | float) else str(value).strip())
    except (TypeError, ValueError):
        raise _BadValue("expected a number")
    if not math.isfinite(number):
        raise _BadValue("expected a finite number")
    return number


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise _BadValue("expected true or false")


def _to_datetime(value: Any, dtype: pl.DataType) -> datetime:
    text = str(value).strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _BadValue("expected a date and time such as 2025-03-14 09:30:00")
    zone = getattr(dtype, "time_zone", None)
    if zone is None and parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    elif zone is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def coerce_cell(value: Any, dtype: pl.DataType) -> Any:
    """``value`` as a Python value of ``dtype``, or ``_BadValue``.

    Null and blank text clear the cell for every type, as ingest reads a blank
    as missing.
    """
    kind = column_kind(dtype)
    if kind == "other":
        raise _BadValue(f"columns of type {dtype} cannot be edited here")
    if _is_blank(value):
        return None
    try:
        if kind == "string":
            if isinstance(value, bool):
                return "true" if value else "false"
            return value if isinstance(value, str) else str(value)
        if kind == "integer":
            converted: Any = _to_int(value)
        elif kind == "float":
            converted = _to_float(value)
        elif kind == "boolean":
            converted = _to_bool(value)
        elif kind == "date":
            try:
                converted = date.fromisoformat(str(value).strip())
            except ValueError:
                raise _BadValue("expected a date such as 2025-03-14")
        elif kind == "datetime":
            converted = _to_datetime(value, dtype)
        else:  # time
            try:
                converted = time.fromisoformat(str(value).strip())
            except ValueError:
                raise _BadValue("expected a time such as 09:30:00")
        # Range checks (an Int8 cannot hold 300) happen when polars builds the cell.
        return pl.Series([converted], dtype=dtype, strict=True).to_list()[0]
    except _BadValue:
        raise
    except Exception:
        raise _BadValue(f"does not fit the column type {dtype}")


def _invalid(errors: list[dict[str, Any]]) -> HTTPException:
    first = errors[0]
    suffix = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    return HTTPException(
        status_code=422,
        detail={
            "code": "invalid_cells",
            "message": f"Row {first['row'] + 1}, column '{first['column']}': {first['message']}{suffix}",
            "errors": errors,
        },
    )


# ----------------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------------


def _stale(current: int, base: int) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "stale_version",
            "message": (
                "Someone else changed this table since you opened it. "
                "Reload to see the current data; your unsaved edits were not applied."
            ),
            "current_version": current,
            "base_version": base,
        },
    )


def apply_cell_edits(
    data_collection_id: str, body: CellEditsRequest, current_user: Any
) -> dict[str, Any]:
    """Apply ``body.edits`` to the table in one new Delta version, or change nothing.

    422 names the first bad row and column and lists every bad cell; 409 when the
    table is no longer at ``base_version``; 413 above ``MAX_EDITABLE_ROWS``.
    """
    _require_editable(data_collection_id, current_user)
    location = _delta_location_for(data_collection_id)

    with _lock_for(data_collection_id):
        current = _delta_version(location)
        if current != body.base_version:
            raise _stale(current, body.base_version)
        total = _row_count(location, current)
        if total > MAX_EDITABLE_ROWS:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "table_too_large",
                    "message": (
                        f"This table has {total} rows; only tables of up to "
                        f"{MAX_EDITABLE_ROWS} rows can be edited here."
                    ),
                },
            )
        frame = _read_frame(location, current)

        errors: list[dict[str, Any]] = []
        changes: dict[str, dict[int, Any]] = {}
        for edit in body.edits:
            if edit.column not in frame.columns or edit.column in _HIDDEN_COLUMNS:
                errors.append({"row": edit.row, "column": edit.column, "message": "no such column"})
                continue
            if edit.row >= frame.height:
                errors.append({"row": edit.row, "column": edit.column, "message": "no such row"})
                continue
            try:
                changes.setdefault(edit.column, {})[edit.row] = coerce_cell(
                    edit.value, frame.schema[edit.column]
                )
            except _BadValue as exc:
                errors.append({"row": edit.row, "column": edit.column, "message": str(exc)})
        if errors:
            raise _invalid(errors)

        updated = frame
        changed_cells = 0
        for column, by_row in changes.items():
            values = frame[column].to_list()
            for row, value in by_row.items():
                if values[row] != value:
                    values[row] = value
                    changed_cells += 1
            updated = updated.with_columns(
                pl.Series(column, values, dtype=frame.schema[column], strict=True)
            )

        if changed_cells == 0:
            return {
                "success": True,
                "data_collection_id": data_collection_id,
                "changed_cells": 0,
                "delta_version": current,
                "aggregation_version": None,
                "row_count": frame.height,
            }

        aggregation_version, new_delta_version = commit_table_frame(
            data_collection_id=data_collection_id,
            frame=updated,
            current_user=current_user,
            write_mode="overwrite",
            trigger="ui",
        )

    return {
        "success": True,
        "data_collection_id": data_collection_id,
        "changed_cells": changed_cells,
        "delta_version": new_delta_version,
        "aggregation_version": aggregation_version,
        "row_count": updated.height,
    }
