"""Polling API for offloaded work.

Read-and-cancel only. There is deliberately **no generic ``POST /jobs``**:
an "enqueue an arbitrary Celery task" route is a privilege-escalation surface,
so submission stays with the domain endpoint that owns the work
(``POST /deltatables/upsert`` with ``async_mode=true`` is the first one).

Ownership is enforced by returning **404, never 403**, for a job belonging to
someone else. A 403 would confirm the job_id exists, which is exactly the
information an attacker probing ids is after. Same posture as
``_assert_job_owner`` in ``advanced_viz_endpoints/routes.py``.

Idempotency-key recipe for clients, so a retry after a dropped connection
re-attaches instead of enqueuing duplicate work::

    sha256(f"{run_id}|{dc_id}|{delta_table_location}|deltatable.upsert")[:32]
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.jobs import store
from depictio.models.models.jobs import TERMINAL_JOB_STATES, JobStatus
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

jobs_endpoint_router = APIRouter()

# Suggested client poll interval. Short while the job is young (the common case
# is a job that finishes in seconds), longer once it is clearly long-running,
# so a fleet of watchers does not hammer the API for the whole of a 20-minute
# aggregation.
_POLL_FAST_SECONDS = 1.0
_POLL_SLOW_SECONDS = 5.0
_POLL_SLOW_AFTER_SECONDS = 30.0


def _poll_hint(doc: dict[str, Any]) -> Optional[float]:
    if doc.get("status") in TERMINAL_JOB_STATES:
        return None
    started = doc.get("started_at") or doc.get("submitted_at")
    if started is None:
        return _POLL_FAST_SECONDS
    from datetime import datetime

    elapsed = (datetime.now() - started).total_seconds()
    return _POLL_SLOW_SECONDS if elapsed > _POLL_SLOW_AFTER_SECONDS else _POLL_FAST_SECONDS


def _owned_or_404(doc: Optional[dict[str, Any]], current_user: User) -> dict[str, Any]:
    """Return the job, or 404 if it is missing *or* owned by someone else."""
    if doc is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if getattr(current_user, "is_admin", False):
        return doc
    if doc.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Job not found")
    return doc


@jobs_endpoint_router.get("/{job_id}", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> JobStatus:
    """Poll one job.

    The stored document is authoritative — the Celery result backend is not
    consulted. Celery reports ``PENDING`` both for an unknown task id and for a
    result that has expired, so a poller that trusted it would hang forever on
    any job older than ``result_expires``.
    """
    doc = _owned_or_404(await asyncio.to_thread(store.get_job, job_id), current_user)
    return store.to_status(doc, poll_after_seconds=_poll_hint(doc))


@jobs_endpoint_router.get("", response_model=list[JobStatus])
async def list_jobs(
    kind: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
) -> list[JobStatus]:
    """List the caller's jobs, newest first. Admins see everyone's."""
    user_filter = None if getattr(current_user, "is_admin", False) else str(current_user.id)
    docs = await asyncio.to_thread(
        store.query_jobs,
        user_id=user_filter,
        kind=kind,
        status=status,
        project_id=project_id,
        limit=limit,
        skip=skip,
    )
    return [store.to_status(doc) for doc in docs]


@jobs_endpoint_router.post("/{job_id}/cancel", response_model=JobStatus)
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> JobStatus:
    """Request cancellation.

    Flips the document first, then revokes the Celery task. That order matters:
    the document is what every reader trusts, and a revoke that succeeds while
    the document still says ``running`` would leave a job that never resolves.

    ``terminate=True`` only works on a prefork pool — the ingestion worker runs
    prefork for exactly this reason. On a threads/solo pool the revoke is a
    no-op for an already-started task and the job will finish anyway; the
    document still reads ``cancelled``, and the task's own terminal write is
    suppressed because ``finish_job`` is not reached on a revoked task.
    """
    doc = _owned_or_404(await asyncio.to_thread(store.get_job, job_id), current_user)
    if doc.get("status") in TERMINAL_JOB_STATES:
        return store.to_status(doc)

    await asyncio.to_thread(store.cancel_job, job_id)

    task_id = doc.get("celery_task_id")
    if task_id:
        try:
            from depictio.api.celery_app import celery_app

            await asyncio.to_thread(
                celery_app.control.revoke, task_id, terminate=True, signal="SIGUSR1"
            )
        except Exception as exc:
            # The document already says cancelled, which is the contract the
            # client sees. A broker hiccup here means the worker may still burn
            # cycles on orphaned work — worth a warning, not an error response.
            logger.warning(f"jobs: revoke failed for task {task_id} (job {job_id}): {exc}")

    refreshed = await asyncio.to_thread(store.get_job, job_id)
    return store.to_status(refreshed or doc)
