"""Monitoring ledger models for the admin "Log & Task" view.

Three durable records back the admin monitoring UI:

- ``TaskEvent`` — one row per Celery task, upserted by the worker-side signal
  handlers (``depictio/api/v1/monitoring/task_signals.py``) as the task moves
  through its lifecycle. Stored in the ``task_events`` collection, keyed by
  ``task_id``, with a TTL index on ``created_at`` for retention.
- ``IngestionRun`` — one row per CLI ``run`` invocation, opened/closed by the
  CLI via the ``/monitoring/ingestion`` endpoints. Tags each run with the
  originating CLI instance (hostname + user-defined label) so multiple CLIs
  talking to one server stay distinguishable.
- ``AppLogRecord`` — recent application log lines, written by a logging handler
  into the capped ``app_logs`` collection (bounded, cross-process, queryable).

These intentionally use plain ``BaseModel`` + dict upserts via pymongo
collections (mirroring ``MultiQCPrerender``), not Beanie documents.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ── Celery task ledger ──────────────────────────────────────────────────────

TaskStatus = Literal["pending", "started", "success", "failure", "retry", "revoked"]

# Coarse grouping shown as a badge in the UI, derived from the Celery task name.
TaskKind = Literal["figure", "screenshot", "multiqc", "advanced_viz", "deltatable", "other"]


def derive_task_kind(task_name: str | None) -> TaskKind:
    """Map a Celery task name to a coarse UI ``kind`` for badge grouping."""
    name = (task_name or "").lower()
    if "screenshot" in name:
        return "screenshot"
    if "multiqc" in name:
        return "multiqc"
    if "advanced_viz" in name or any(
        k in name for k in ("embedding", "heatmap", "upset", "coverage", "sankey")
    ):
        return "advanced_viz"
    if "deltatable" in name:
        return "deltatable"
    if "figure" in name:
        return "figure"
    return "other"


class TaskEvent(BaseModel):
    """Lifecycle record for a single Celery task.

    Stored in the ``task_events`` collection, keyed by ``task_id``. The
    signal handlers upsert this on prerun/postrun/success/failure/retry/revoked.
    """

    task_id: str = Field(..., description="Celery task id (primary key)")
    task_name: str = Field(default="", description="Fully-qualified Celery task name")
    kind: TaskKind = Field(default="other", description="Coarse grouping derived from task_name")
    status: TaskStatus = Field(default="pending", description="Current lifecycle state")
    args_repr: str = Field(default="", description="Truncated repr of task args/kwargs")
    dashboard_id: Optional[str] = Field(default=None, description="Dashboard id if applicable")
    dc_id: Optional[str] = Field(default=None, description="Data collection id if applicable")
    queue: Optional[str] = Field(default=None, description="Queue the task ran on")
    worker: Optional[str] = Field(default=None, description="Worker hostname that ran the task")
    started_at: Optional[datetime] = Field(default=None, description="When the task began running")
    finished_at: Optional[datetime] = Field(default=None, description="When the task finished")
    duration_ms: Optional[float] = Field(default=None, description="Run duration in milliseconds")
    error: Optional[str] = Field(default=None, description="Short error message on failure")
    traceback: Optional[str] = Field(default=None, description="Full traceback on failure")
    result_summary: Optional[str] = Field(default=None, description="Truncated repr of the result")
    logs: list[str] = Field(default_factory=list, description="Captured log lines for this task")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict(extra="forbid")


# ── CLI ingestion ledger ────────────────────────────────────────────────────

IngestionStatus = Literal["running", "success", "partial", "failed"]


class IngestionStep(BaseModel):
    """One step of a CLI ingestion run (sync / scan / process / ...)."""

    name: str = Field(..., description="Step name, e.g. 'sync', 'scan', 'process'")
    status: str = Field(default="running", description="Step status")
    detail: Optional[str] = Field(default=None, description="Optional human-readable detail")

    model_config = ConfigDict(extra="forbid")


class IngestionRun(BaseModel):
    """Lifecycle record for one CLI ``run`` invocation.

    Stored in the ``ingestion_runs`` collection, keyed by ``run_id``. Opened by
    ``POST /monitoring/ingestion/start`` and closed by
    ``POST /monitoring/ingestion/{run_id}/finish``.
    """

    run_id: str = Field(..., description="Client-generated UUID for the ingestion run")
    cli_instance_label: Optional[str] = Field(
        default=None, description="User-defined CLI instance label from the CLI YAML config"
    )
    cli_hostname: Optional[str] = Field(default=None, description="Hostname the CLI ran on")
    user_id: Optional[str] = Field(default=None, description="Id of the ingesting user")
    email: Optional[str] = Field(default=None, description="Email of the ingesting user")
    project_id: Optional[str] = Field(default=None, description="Target project id")
    project_name: Optional[str] = Field(default=None, description="Target project name")
    command: str = Field(default="run", description="CLI command that triggered the run")
    status: IngestionStatus = Field(default="running", description="Overall run status")
    steps: list[IngestionStep] = Field(default_factory=list, description="Per-step tally")
    error: Optional[str] = Field(default=None, description="Failure message if the run failed")
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = Field(default=None, description="When the run completed")

    model_config = ConfigDict(extra="forbid")


# ── Application log ledger ──────────────────────────────────────────────────

LogSource = Literal["api", "celery"]


class AppLogRecord(BaseModel):
    """A single application log line persisted to the capped ``app_logs`` collection."""

    ts: datetime = Field(default_factory=datetime.now, description="Log record timestamp")
    level: str = Field(default="INFO", description="Log level name")
    logger: str = Field(default="", description="Logger name")
    source: LogSource = Field(default="api", description="Process that emitted the record")
    message: str = Field(default="", description="Formatted log message")
    pathname: Optional[str] = Field(default=None, description="Source file path")
    lineno: Optional[int] = Field(default=None, description="Source line number")

    model_config = ConfigDict(extra="forbid")
