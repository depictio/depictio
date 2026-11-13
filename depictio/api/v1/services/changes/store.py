"""Reader marks storage: one document per (reader, dashboard family | project).

Writes are upserts on the unique key, so two tabs opening at once cannot
violate it. Nothing here touches the dashboard documents or their versions.
"""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import reader_marks_collection
from depictio.models.models.reader_marks import (
    DismissedComponent,
    MarkMode,
    ReaderBaseline,
    ReaderMark,
    ScopeKind,
)
from depictio.models.timestamps import utc_now_naive

PREFS_SCOPE_ID = "_"


def ensure_reader_marks_storage() -> None:
    """Create the indexes. Idempotent, never raises."""
    try:
        reader_marks_collection.create_index(
            [("user_id", ASCENDING), ("scope_kind", ASCENDING), ("scope_id", ASCENDING)],
            unique=True,
            name="reader_scope",
        )
        # Cascades on dashboard and project delete.
        reader_marks_collection.create_index(
            [("scope_kind", ASCENDING), ("scope_id", ASCENDING)], name="scope"
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"reader_marks: failed to ensure indexes: {exc}")


def _key(user_id: str, scope_kind: ScopeKind, scope_id: str) -> dict[str, Any]:
    return {"user_id": str(user_id), "scope_kind": scope_kind, "scope_id": str(scope_id)}


def get_mark(user_id: str, scope_kind: ScopeKind, scope_id: str) -> ReaderMark | None:
    doc = reader_marks_collection.find_one(_key(user_id, scope_kind, scope_id), {"_id": 0})
    if not doc:
        return None
    try:
        return ReaderMark.model_validate(doc)
    except Exception as exc:
        # A mark is a convenience: an unreadable one is a first visit, not an error.
        logger.warning(f"reader_marks: dropping unreadable mark {scope_kind}/{scope_id}: {exc}")
        return None


def set_baseline(
    user_id: str, scope_kind: ScopeKind, scope_id: str, baseline: ReaderBaseline, *, visit: bool
) -> None:
    now = utc_now_naive()
    fields: dict[str, Any] = {
        "baseline": baseline.model_dump(mode="python"),
        "dismissed": {},
        "updated_at": now,
    }
    if visit:
        fields["last_visit_at"] = now
    reader_marks_collection.update_one(
        _key(user_id, scope_kind, scope_id), {"$set": fields}, upsert=True
    )


def touch_visit(user_id: str, scope_kind: ScopeKind, scope_id: str) -> None:
    now = utc_now_naive()
    reader_marks_collection.update_one(
        _key(user_id, scope_kind, scope_id),
        {"$set": {"last_visit_at": now, "updated_at": now}},
        upsert=True,
    )


def dismiss(
    user_id: str, scope_kind: ScopeKind, scope_id: str, entries: dict[str, DismissedComponent]
) -> None:
    if not entries:
        return
    fields: dict[str, Any] = {f"dismissed.{k}": v.model_dump() for k, v in entries.items()}
    fields["updated_at"] = utc_now_naive()
    reader_marks_collection.update_one(
        _key(user_id, scope_kind, scope_id), {"$set": fields}, upsert=True
    )


def default_mark_mode() -> MarkMode:
    return settings.dashboard_versions.changes_since_mark_mode


def get_mark_mode(user_id: str | None) -> MarkMode:
    if user_id:
        doc = reader_marks_collection.find_one(_key(user_id, "prefs", PREFS_SCOPE_ID))
        mode = (doc or {}).get("mark_mode")
        if mode in ("sticky", "previous_visit"):
            return mode
    return default_mark_mode()


def set_mark_mode(user_id: str, mode: MarkMode) -> None:
    reader_marks_collection.update_one(
        _key(user_id, "prefs", PREFS_SCOPE_ID),
        {"$set": {"mark_mode": mode, "updated_at": utc_now_naive()}},
        upsert=True,
    )


def list_marks(user_id: str, limit: int = 50) -> list[ReaderMark]:
    out = []
    for doc in (
        reader_marks_collection.find(
            {"user_id": str(user_id), "scope_kind": {"$in": ["dashboard", "project"]}}, {"_id": 0}
        )
        .sort("last_visit_at", -1)
        .limit(limit)
    ):
        try:
            out.append(ReaderMark.model_validate(doc))
        except Exception:
            continue
    return out


def delete_marks_for(scope_kind: ScopeKind, scope_ids: list[str]) -> int:
    if not scope_ids:
        return 0
    try:
        result = reader_marks_collection.delete_many(
            {"scope_kind": scope_kind, "scope_id": {"$in": [str(s) for s in scope_ids]}}
        )
        return int(result.deleted_count)
    except Exception as exc:  # pragma: no cover - a cascade must not fail a delete
        logger.warning(f"reader_marks: cascade delete failed for {scope_kind}: {exc}")
        return 0
