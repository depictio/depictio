"""MongoDB persistence helpers for the monitoring ledger.

Thin CRUD over the ``task_events``, ``ingestion_runs`` and ``app_logs``
collections (handles defined in ``depictio/api/v1/db.py``). Mirrors the
plain-pymongo + dict-document style of ``multiqc_prerender_store``; no Beanie.

``ensure_monitoring_storage()`` is idempotent and called once at API startup to
create the task-events TTL index and the capped app-logs collection.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pymongo import DESCENDING

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    app_logs_collection,
    db,
    ingestion_runs_collection,
    task_events_collection,
)
from depictio.models.models.monitoring import (
    AppLogRecord,
    IngestionRun,
    derive_task_kind,
)


def ensure_monitoring_storage() -> None:
    """Create the TTL index and capped app-logs collection. Idempotent.

    Never raises — a storage-setup failure must not break API boot; the worst
    case is unbounded growth or a missing capped collection, both recoverable.
    """
    try:
        retention_seconds = max(1, settings.monitoring.retention_days) * 86_400
        task_events_collection.create_index("task_id", unique=True)
        # TTL on created_at: Mongo expires task_events automatically after the
        # configured retention window. Recreated only if the option changed.
        task_events_collection.create_index(
            "created_at", expireAfterSeconds=retention_seconds, name="created_at_ttl"
        )
        ingestion_runs_collection.create_index("run_id", unique=True)
        ingestion_runs_collection.create_index([("started_at", DESCENDING)])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"monitoring: failed to ensure task/ingestion indexes: {exc}")

    try:
        name = settings.mongodb.collections.app_logs_collection
        if name not in db.list_collection_names():
            db.create_collection(
                name,
                capped=True,
                size=max(1, settings.monitoring.app_log_capped_mb) * 1024 * 1024,
            )
            logger.info(f"monitoring: created capped collection '{name}'")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"monitoring: failed to ensure capped app_logs collection: {exc}")


# ── Task events ─────────────────────────────────────────────────────────────


def upsert_task_event(task_id: str, **fields: Any) -> None:
    """Create-or-update the task_events row keyed by ``task_id``.

    ``created_at`` is set only on insert (so the TTL clock starts at first
    sighting); ``updated_at`` is bumped on every call.
    """
    now = datetime.now()
    if "task_name" in fields and "kind" not in fields:
        fields["kind"] = derive_task_kind(fields.get("task_name"))
    set_fields: dict[str, Any] = {**fields, "updated_at": now}
    task_events_collection.update_one(
        {"task_id": task_id},
        {"$set": set_fields, "$setOnInsert": {"task_id": task_id, "created_at": now}},
        upsert=True,
    )


def append_task_logs(task_id: str, lines: list[str]) -> None:
    """Append captured log lines to a task_events row (no-op on empty)."""
    if not lines:
        return
    task_events_collection.update_one(
        {"task_id": task_id},
        {
            "$push": {"logs": {"$each": lines}},
            "$set": {"updated_at": datetime.now()},
            "$setOnInsert": {"task_id": task_id, "created_at": datetime.now()},
        },
        upsert=True,
    )


def query_task_events(
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 100,
    skip: int = 0,
) -> list[dict[str, Any]]:
    """Return task_events newest-first, with optional filters."""
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if kind:
        query["kind"] = kind
    if since:
        query["updated_at"] = {"$gte": since}
    cursor = (
        task_events_collection.find(query, {"_id": 0})
        .sort("updated_at", DESCENDING)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 500)))
    )
    return [_serialize(doc) for doc in cursor]


def get_task_event(task_id: str) -> Optional[dict[str, Any]]:
    doc = task_events_collection.find_one({"task_id": task_id}, {"_id": 0})
    return _serialize(doc) if doc else None


# ── Ingestion runs ──────────────────────────────────────────────────────────


def create_ingestion_run(run: IngestionRun) -> None:
    ingestion_runs_collection.update_one(
        {"run_id": run.run_id},
        {"$set": run.model_dump()},
        upsert=True,
    )


def finish_ingestion_run(run_id: str, **fields: Any) -> bool:
    """Patch a run on completion. Returns False if the run_id is unknown."""
    fields.setdefault("finished_at", datetime.now())
    result = ingestion_runs_collection.update_one({"run_id": run_id}, {"$set": fields})
    return result.matched_count > 0


def query_ingestion_runs(
    *,
    instance: Optional[str] = None,
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if instance:
        query["cli_instance_label"] = instance
    if status:
        query["status"] = status
    if project_id:
        query["project_id"] = project_id
    cursor = (
        ingestion_runs_collection.find(query, {"_id": 0})
        .sort("started_at", DESCENDING)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 500)))
    )
    return [_serialize(doc) for doc in cursor]


def get_ingestion_run(run_id: str) -> Optional[dict[str, Any]]:
    doc = ingestion_runs_collection.find_one({"run_id": run_id}, {"_id": 0})
    return _serialize(doc) if doc else None


# ── Application logs ────────────────────────────────────────────────────────


def insert_app_log(record: AppLogRecord) -> None:
    app_logs_collection.insert_one(record.model_dump())


def query_app_logs(
    *,
    level: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if level:
        query["level"] = level
    if source:
        query["source"] = source
    # Capped collections preserve insertion order; $natural reverse = newest-first.
    cursor = (
        app_logs_collection.find(query, {"_id": 0})
        .sort("$natural", DESCENDING)
        .limit(max(1, min(limit, 1000)))
    )
    return [_serialize(doc) for doc in cursor]


# ── helpers ─────────────────────────────────────────────────────────────────


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe dict: stringify datetimes so FastAPI can return them directly."""
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def task_event_seconds_ago(seconds: float) -> datetime:
    """Convenience for `since` filters."""
    return datetime.now() - timedelta(seconds=seconds)
