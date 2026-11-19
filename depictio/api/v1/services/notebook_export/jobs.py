"""Who asked for which export job, how many each user runs, how long anything stays.

Two kinds of job leave the API for a worker: a rendered report (``render``) and a
headless figure extraction (``extract``). Each is recorded here when it is
queued, under the user who asked, so that:

* only that user can poll it or download what it made, in *every* state (a
  Celery result alone says nothing about its owner until it has succeeded);
* a user has a bounded number running and a bounded number per hour (429);
* the record expires with what it points at (a TTL index on ``expires_at``).

A worker slot is a separate, deployment-wide bound (``acquire_slot``): a report
holds its worker for minutes while the passes it waits on need workers of
their own, so the reports running at once must stay below the pool's size.

Plain pymongo, like ``api/v1/jobs/store.py``. The admission check counts, then
inserts: two requests in the same instant can both pass, which a rate limit
can afford.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import db
from depictio.models.timestamps import utc_now_naive

RENDER = "render"
EXTRACT = "extract"

jobs_collection = db["notebook_export_jobs"]
slots_collection = db["notebook_export_slots"]

_indexed = False


def _ensure_indexes() -> None:
    global _indexed
    if _indexed:
        return
    try:
        jobs_collection.create_index("expires_at", expireAfterSeconds=0, name="ttl")
        jobs_collection.create_index([("user_id", 1), ("kind", 1), ("created_at", -1)])
        _indexed = True
    except Exception as exc:  # noqa: BLE001 - an index is an optimisation, never a failure
        logger.warning(f"notebook export jobs: could not ensure indexes: {exc}")


def _retention() -> timedelta:
    return timedelta(hours=max(1, settings.notebook_export.report_retention_hours))


def admit(user_id: str, kind: str, *, max_active: int, max_per_hour: int, window_s: int) -> None:
    """Refuse (429) a job past the user's concurrency or hourly budget.

    ``window_s`` bounds how long an unfinished job counts as active: a worker
    that died mid-job never marks it finished, and must not block its owner
    for good.
    """
    _ensure_indexes()
    now = utc_now_naive()
    base = {"user_id": user_id, "kind": kind}
    active = jobs_collection.count_documents(
        {**base, "finished_at": None, "created_at": {"$gt": now - timedelta(seconds=window_s)}}
    )
    if active >= max_active:
        raise HTTPException(
            status_code=429,
            detail=f"{active} {kind} job(s) of yours are still running; wait for one to finish.",
        )
    recent = jobs_collection.count_documents(
        {**base, "created_at": {"$gt": now - timedelta(hours=1)}}
    )
    if recent >= max_per_hour:
        raise HTTPException(
            status_code=429, detail=f"Too many {kind} jobs in the last hour; try again later."
        )


def record(
    job_id: str, user_id: str, kind: str, *, keep_s: int | None = None, **extra: Any
) -> None:
    """The job, bound to the user who asked for it, kept ``keep_s`` (default:
    as long as a rendered report)."""
    _ensure_indexes()
    now = utc_now_naive()
    keep = timedelta(seconds=keep_s) if keep_s else _retention()
    jobs_collection.insert_one(
        {
            "_id": job_id,
            "user_id": user_id,
            "kind": kind,
            "created_at": now,
            "finished_at": None,
            "expires_at": now + keep,
            **extra,
        }
    )


def get(job_id: str) -> dict[str, Any] | None:
    return jobs_collection.find_one({"_id": job_id})


def owned(job_id: str, user_id: str, kind: str) -> dict[str, Any] | None:
    """The job when ``user_id`` asked for it, else ``None`` (a 404 to the caller)."""
    doc = get(job_id)
    if not doc or doc.get("kind") != kind or str(doc.get("user_id")) != str(user_id):
        return None
    return doc


def finish(job_id: str, status: str, *, reason: str | None = None) -> None:
    """The job is over. ``reason`` is what its owner is shown for a failure."""
    update: dict[str, Any] = {"finished_at": utc_now_naive(), "status": status}
    if reason:
        update["reason"] = reason
    try:
        jobs_collection.update_one({"_id": job_id}, {"$set": update})
    except Exception as exc:  # noqa: BLE001 - the record is bookkeeping, the job stands
        logger.warning(f"notebook export jobs: could not mark {job_id} finished: {exc}")


def acquire_slot(name: str, holder: str, *, capacity: int, hold_s: int) -> bool:
    """Claim one of ``capacity`` deployment-wide slots named ``name``.

    Each slot is a document claimed atomically when free or when its holder's
    claim has lapsed (``hold_s``: a crashed worker releases nothing).
    """
    now = utc_now_naive()
    for i in range(max(1, capacity)):
        slot_id = f"{name}:{i}"
        try:
            slots_collection.update_one(
                {"_id": slot_id}, {"$setOnInsert": {"holder": None}}, upsert=True
            )
        except Exception:  # noqa: BLE001 - a concurrent insert of the same slot
            pass
        claimed = slots_collection.find_one_and_update(
            {
                "_id": slot_id,
                "$or": [{"holder": None}, {"until": {"$lt": now}}, {"holder": holder}],
            },
            {"$set": {"holder": holder, "until": now + timedelta(seconds=hold_s)}},
        )
        if claimed is not None:
            return True
    return False


def release_slot(name: str, holder: str) -> None:
    try:
        slots_collection.update_many(
            {"_id": {"$regex": f"^{name}:"}, "holder": holder}, {"$set": {"holder": None}}
        )
    except Exception as exc:  # noqa: BLE001 - the claim lapses on its own
        logger.warning(f"notebook export jobs: could not release {name} for {holder}: {exc}")


_PRUNE_MARK = "prune:reports"


def prune_reports() -> int:
    """Delete rendered reports older than the retention; at most once an hour.

    Run by the render task once it is done, not on a schedule: the deployment
    has no beat, and a deployment that renders nothing stores nothing new.
    A bucket lifecycle rule on ``render_prefix`` does the same job, at the
    storage's own pace.
    """
    from depictio.api.v1.s3 import s3_client

    now = utc_now_naive()
    mark = slots_collection.find_one_and_update(
        {"_id": _PRUNE_MARK, "$or": [{"until": None}, {"until": {"$lt": now}}]},
        {"$set": {"until": now + timedelta(hours=1)}},
    )
    if mark is None:
        try:
            slots_collection.insert_one({"_id": _PRUNE_MARK, "until": now + timedelta(hours=1)})
        except Exception:  # noqa: BLE001 - somebody pruned within the hour
            return 0
    cutoff = now - _retention()
    prefix = settings.notebook_export.render_prefix.strip("/") + "/"
    removed = 0
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3.bucket, Prefix=prefix):
        stale = [
            {"Key": obj["Key"]}
            for obj in page.get("Contents") or []
            if obj["LastModified"].replace(tzinfo=None) < cutoff
        ]
        for start in range(0, len(stale), 1000):
            batch = stale[start : start + 1000]
            s3_client.delete_objects(Bucket=settings.s3.bucket, Delete={"Objects": batch})
            removed += len(batch)
    if removed:
        logger.info(f"📄 Pruned {removed} rendered report object(s) older than {cutoff:%Y-%m-%d}")
    return removed
