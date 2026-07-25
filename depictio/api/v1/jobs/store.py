"""MongoDB persistence for the ``jobs`` collection.

Plain pymongo + dict documents, mirroring ``depictio/api/v1/monitoring/store.py``
— no Beanie. ``ensure_jobs_storage()`` is idempotent, called once at API
startup, and never raises: index creation failing must not stop the API from
booting.

Every state transition here is a single atomic Mongo update. The task running
on the worker and the API serving a poll touch the same document concurrently
by design, so read-modify-write is not available to us.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import jobs_collection
from depictio.models.models.jobs import TERMINAL_JOB_STATES, Job, JobStatus


def ensure_jobs_storage() -> None:
    """Create the job indexes. Idempotent; never raises."""
    try:
        jobs_collection.create_index("job_id", unique=True)
        # TTL keyed on expires_at rather than a fixed window from creation:
        # failed jobs are kept longer than successful ones (a user debugging a
        # failure needs it to still be there tomorrow), which a
        # created_at + N index cannot express.
        jobs_collection.create_index("expires_at", expireAfterSeconds=0, name="jobs_ttl")
        # Sparse: the overwhelming majority of jobs carry no idempotency key,
        # and a non-sparse unique index would collide all of them on null.
        jobs_collection.create_index(
            [("user_id", 1), ("kind", 1), ("idempotency_key", 1)],
            unique=True,
            sparse=True,
            name="jobs_idempotency",
        )
        jobs_collection.create_index([("submitted_at", DESCENDING)])
        jobs_collection.create_index("celery_task_id")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"jobs: failed to ensure indexes: {exc}")


def build_idempotency_key(*parts: Any) -> str:
    """Stable key from the identifying parts of a submission.

    Callers pass the tuple that makes a submission *the same submission* —
    for a deltatable upsert that is ``(run_id, dc_id, delta_location, kind)``.
    Truncated to 32 hex chars: collision risk is negligible at this scale and
    the key ends up in an index and in CLI logs.
    """
    blob = "|".join(str(p) for p in parts)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def _expiry(status: str) -> datetime:
    hours = (
        settings.jobs.failed_retention_hours
        if status in {"failed", "cancelled"}
        else settings.jobs.retention_hours
    )
    return datetime.now() + timedelta(hours=max(1, hours))


def create_job(job: Job) -> tuple[Job, bool]:
    """Insert a job, or return the existing one with the same idempotency key.

    Returns ``(job, created)``. When ``created`` is False the caller must *not*
    dispatch a Celery task — an equivalent one is already in flight or done.

    The duplicate-key path is the interesting one: two CLI processes (or one
    CLI retrying through a dropped connection) submitting the same work race
    here, and exactly one wins the insert. The loser re-reads and attaches to
    the winner's job. Same shape as the ``DuplicateKeyError`` handling in
    ``dispatch_compute_embedding``.
    """
    if job.expires_at is None:
        job.expires_at = _expiry(job.status)
    doc = job.model_dump()
    try:
        jobs_collection.insert_one(doc)
        return job, True
    except DuplicateKeyError:
        existing = None
        if job.idempotency_key:
            existing = jobs_collection.find_one(
                {
                    "user_id": job.user_id,
                    "kind": job.kind,
                    "idempotency_key": job.idempotency_key,
                },
                {"_id": 0},
            )
        if existing is None:
            existing = jobs_collection.find_one({"job_id": job.job_id}, {"_id": 0})
        if existing is None:
            # Lost the race against a TTL eviction of the very document that
            # caused the conflict. Vanishingly rare; retrying the insert once
            # is both correct and cheaper than failing the submission.
            jobs_collection.insert_one(doc)
            return job, True
        return Job.model_validate(existing), False


def attach_task(job_id: str, celery_task_id: str) -> None:
    jobs_collection.update_one({"job_id": job_id}, {"$set": {"celery_task_id": celery_task_id}})


def mark_job_running(
    job_id: str, *, step: Optional[str] = None, detail: Optional[str] = None
) -> None:
    """Move a job to ``running``. Called by the task itself, first thing.

    ``started_at`` uses ``$setOnInsert``-like semantics via a filter on the
    current status so a retried task (``acks_late`` redelivery) does not reset
    the clock.
    """
    fields: dict[str, Any] = {"status": "running"}
    if step is not None:
        fields["step"] = step
    if detail is not None:
        fields["detail"] = detail
    jobs_collection.update_one({"job_id": job_id}, {"$set": fields})
    jobs_collection.update_one(
        {"job_id": job_id, "started_at": None}, {"$set": {"started_at": datetime.now()}}
    )


def update_job_progress(
    job_id: str,
    *,
    step: Optional[str] = None,
    detail: Optional[str] = None,
    progress: Optional[dict[str, Any]] = None,
) -> None:
    """Best-effort progress ping from inside a running task.

    Guarded on a non-terminal status: a late progress write must never
    resurrect a job that already finished (or was cancelled).
    """
    fields: dict[str, Any] = {}
    if step is not None:
        fields["step"] = step
    if detail is not None:
        fields["detail"] = detail
    if progress is not None:
        fields["progress"] = progress
    if not fields:
        return
    jobs_collection.update_one(
        {"job_id": job_id, "status": {"$nin": list(TERMINAL_JOB_STATES)}}, {"$set": fields}
    )


def finish_job(
    job_id: str,
    *,
    status: str,
    result: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Write a job's terminal state. The task owns this call.

    Oversized results are dropped rather than stored: a 16 MB Mongo document
    limit is a hard wall, and a result that big is a symptom that the client
    should be re-reading the resource instead of receiving it inline.
    """
    fields: dict[str, Any] = {
        "status": status,
        "finished_at": datetime.now(),
        "expires_at": _expiry(status),
    }
    if error is not None:
        fields["error"] = error[:4000]
    if result is not None:
        encoded = json.dumps(result, default=str).encode()
        if len(encoded) > settings.jobs.max_result_bytes:
            fields["result"] = None
            fields["result_truncated"] = True
            logger.warning(
                f"jobs: result for {job_id} is {len(encoded)} bytes "
                f"(> {settings.jobs.max_result_bytes}), storing truncation marker only"
            )
        else:
            fields["result"] = result
    jobs_collection.update_one({"job_id": job_id}, {"$set": fields})


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    return jobs_collection.find_one({"job_id": job_id}, {"_id": 0})


def query_jobs(
    *,
    user_id: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if user_id:
        query["user_id"] = user_id
    if kind:
        query["kind"] = kind
    if status:
        query["status"] = status
    if project_id:
        query["project_id"] = project_id
    cursor = (
        jobs_collection.find(query, {"_id": 0})
        .sort("submitted_at", DESCENDING)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 200)))
    )
    return list(cursor)


def cancel_job(job_id: str) -> bool:
    """Mark a job cancelled. Returns False if it was already terminal.

    Only flips the document; revoking the Celery task is the caller's job
    (it needs the broker connection, which the store deliberately does not).
    """
    result = jobs_collection.update_one(
        {"job_id": job_id, "status": {"$nin": list(TERMINAL_JOB_STATES)}},
        {
            "$set": {
                "status": "cancelled",
                "finished_at": datetime.now(),
                "expires_at": _expiry("cancelled"),
            }
        },
    )
    return result.modified_count > 0


def to_status(doc: dict[str, Any], *, poll_after_seconds: Optional[float] = None) -> JobStatus:
    """Project a stored job document into the client-facing polling response."""
    return JobStatus(
        job_id=doc["job_id"],
        kind=doc["kind"],
        status=doc.get("status", "pending"),
        api_version=doc.get("api_version", 1),
        progress=doc.get("progress"),
        step=doc.get("step"),
        detail=doc.get("detail"),
        result=doc.get("result"),
        result_truncated=doc.get("result_truncated", False),
        error=doc.get("error"),
        task_id=doc.get("celery_task_id"),
        ingestion_run_id=doc.get("ingestion_run_id"),
        submitted_at=doc.get("submitted_at"),
        started_at=doc.get("started_at"),
        finished_at=doc.get("finished_at"),
        poll_after_seconds=poll_after_seconds,
    )
