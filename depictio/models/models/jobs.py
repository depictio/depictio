"""User-facing job records for offloaded (Celery) work.

A ``Job`` is the *client contract* for a piece of work the API accepted but did
not finish inline: submit, get a ``job_id``, poll until terminal. It is
deliberately a separate record from ``TaskEvent``
(``depictio/models/models/monitoring.py``), which stays the admin-facing view of
a Celery task. The two are joined on ``celery_task_id``.

Why not reuse ``TaskEvent`` as the job record — five concrete reasons, each of
which would be a bug rather than an inelegance:

1. ``TaskEvent`` rows are created by the ``task_prerun`` signal, i.e. when a
   worker *picks up* the task. A job submitted while the queue is saturated has
   no row at all, so ``GET /jobs/{id}`` would 404 immediately after a
   successful submit — the single worst failure mode for a polling protocol.
2. ``TaskEvent`` has no owner field, and ``GET /monitoring/tasks/{id}`` is
   admin-gated. The users who ingest data are usually not admins.
3. ``result_summary`` is a ``repr()`` truncated to 4000 chars — fine for an
   admin log line, useless as a structured result a client must parse.
4. No idempotency key: a CLI retrying after a dropped connection would enqueue
   the work a second time.
5. ``TaskEvent`` is ``extra="forbid"``, so every field a job needs would be a
   schema change to an admin-facing model.

The division of labour is therefore: ``Job`` owns ownership, idempotency, the
structured result and the polling contract; ``TaskEvent`` keeps logs, traceback,
worker identity and the live admin push. ``JobStatus.task_id`` lets the admin UI
pivot from one to the other.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ``pending`` covers both "queued" and "not yet picked up"; the distinction is
# only visible in TaskEvent and is not part of the client contract.
JobState = Literal["pending", "running", "success", "failed", "cancelled"]

TERMINAL_JOB_STATES: frozenset[str] = frozenset({"success", "failed", "cancelled"})

# Only kinds declared here can be submitted. There is deliberately no generic
# ``POST /jobs`` endpoint — an "enqueue arbitrary task" route is a privilege
# escalation surface. Submission stays domain-specific and each domain route
# names its own kind.
JobKind = Literal["deltatable.upsert", "project.ingest"]


class Job(BaseModel):
    """One unit of offloaded work, as the submitting client sees it.

    Stored in the ``jobs`` collection keyed by ``job_id``, with a TTL index on
    ``expires_at`` (``expireAfterSeconds=0``) so failed jobs can be retained
    longer than successful ones — a fixed window from ``created_at`` could not
    express that.

    Invariant that makes ``acks_late`` safe: **the task writes its own terminal
    state into this document**. ``AsyncResult`` is only ever consulted as a
    hint (e.g. to notice a worker died before it could write). Anything that
    treats the Celery result backend as the source of truth breaks the moment
    ``result_expires`` elapses, because Celery cannot distinguish an expired
    result from an unknown task id — both report ``PENDING``, forever.
    """

    model_config = ConfigDict(extra="ignore")

    job_id: str
    kind: JobKind
    status: JobState = "pending"

    # Bumped when the response shape changes in a way clients must notice.
    # Clients that do not recognise the version should fall back to polling
    # `status` alone, which is stable by construction.
    api_version: int = 1

    # Ownership. ``GET /jobs/{id}`` 404s (never 403s) for a non-owner, so a
    # leaked job_id does not confirm its own existence.
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    data_collection_id: Optional[str] = None
    ingestion_run_id: Optional[str] = None

    # Unique per (user_id, kind, idempotency_key) via a sparse index. A client
    # that resubmits after a network drop re-attaches to the in-flight job
    # instead of enqueuing a duplicate.
    idempotency_key: Optional[str] = None

    celery_task_id: Optional[str] = None

    progress: Optional[dict[str, Any]] = None
    step: Optional[str] = None
    detail: Optional[str] = None

    result: Optional[dict[str, Any]] = None
    # Set when ``result`` exceeded ``jobs.max_result_bytes`` and was dropped
    # rather than stored. The job still counts as successful; the client is
    # expected to re-read the underlying resource.
    result_truncated: bool = False
    error: Optional[str] = None

    submitted_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class JobStatus(BaseModel):
    """Polling response for ``GET /jobs/{job_id}``.

    Narrower than ``Job``: it deliberately omits ``idempotency_key`` and
    ``user_id``. ``task_id`` is exposed so the admin UI can pivot to
    ``GET /monitoring/tasks/{task_id}`` for logs and traceback.
    """

    model_config = ConfigDict(extra="ignore")

    job_id: str
    kind: JobKind
    status: JobState
    api_version: int = 1

    progress: Optional[dict[str, Any]] = None
    step: Optional[str] = None
    detail: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    result_truncated: bool = False
    error: Optional[str] = None

    task_id: Optional[str] = None
    ingestion_run_id: Optional[str] = None

    submitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Server-suggested backpressure, honoured by the CLI poller. Lets a loaded
    # server slow its clients down without them having to guess.
    poll_after_seconds: Optional[float] = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_JOB_STATES
