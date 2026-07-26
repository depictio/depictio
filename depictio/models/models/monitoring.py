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

# Pseudo "dashboard id" used as the admin monitoring pub/sub channel. Reuses the
# existing dashboard-scoped events plumbing (Redis channel
# ``depictio:events:dashboard:__admin_monitoring__``) without a real dashboard;
# the WebSocket route gates subscription to this channel on ``is_admin``.
ADMIN_MONITORING_CHANNEL = "__admin_monitoring__"

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
    #: Same correlation as AppLogRecord.run_id: lets a run's offloaded work be
    #: listed alongside its steps instead of hunting through every task.
    run_id: Optional[str] = Field(default=None, description="Ingestion run this task belongs to")
    project_id: Optional[str] = Field(default=None, description="Project id if applicable")
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

    # Live progress. All optional, because a step reported only at completion
    # (the historical behaviour) has none of it.
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    duration_ms: Optional[float] = Field(default=None)
    index: Optional[int] = Field(default=None, description="Position in the run, for 'step 3 of 7'")
    total: Optional[int] = Field(default=None, description="Total steps in the run")
    progress: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction complete, only when a denominator exists",
    )
    #: Free-form counters rather than named fields, so the CLI can add one
    #: without a coordinated server schema change. Well-known keys:
    #: files_scanned, files_new, files_changed, files_updated, files_deleted,
    #: files_skipped, bytes_written, rows_written.
    counters: dict[str, int] = Field(default_factory=dict)
    data_collection_tag: Optional[str] = Field(default=None)
    job_id: Optional[str] = Field(default=None, description="Server-side job, for offloaded work")
    error: Optional[str] = Field(default=None)

    model_config = ConfigDict(extra="forbid")


class IngestionError(BaseModel):
    """One failure encountered during a run, with enough context to act on it."""

    stage: str = Field(..., description="Where it happened: scan, process, join, ...")
    kind: str = Field(..., description="Short machine-readable classification")
    message: str
    dc_tag: Optional[str] = Field(default=None)
    file_path: Optional[str] = Field(default=None)

    model_config = ConfigDict(extra="forbid")


class IngestionProgress(BaseModel):
    """Run-level progress. Every field optional — a percentage is only reported
    when a real denominator exists, never synthesised from the step index."""

    percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    steps_done: Optional[int] = Field(default=None)
    steps_total: Optional[int] = Field(default=None)
    dcs_done: Optional[int] = Field(default=None)
    dcs_total: Optional[int] = Field(default=None)
    files_done: Optional[int] = Field(default=None)
    files_total: Optional[int] = Field(default=None)

    model_config = ConfigDict(extra="forbid")


class IngestionDataCollection(BaseModel):
    """Per-data-collection summary captured for an ingestion run.

    Mirrors what the DC manager surfaces (tag / type / format) *plus* the local
    scan paths the CLI resolved — base directories and the file-matching pattern
    (regex for recursive scans, or the single filename) — which the DC manager
    itself does not display.
    """

    tag: str = Field(..., description="Data collection tag")
    type: Optional[str] = Field(default=None, description="DC type, e.g. 'table', 'jbrowse2'")
    format: Optional[str] = Field(default=None, description="Table format, e.g. 'csv', 'parquet'")
    scan_mode: Optional[str] = Field(default=None, description="'recursive' or 'single'")
    scan_pattern: Optional[str] = Field(
        default=None, description="Regex (recursive) or filename (single) the scan matched on"
    )
    locations: list[str] = Field(
        default_factory=list, description="Local base directories scanned (workflow data location)"
    )
    file_count: Optional[int] = Field(default=None, description="Files matched, when known")

    # Outcome counters for this DC in this run.
    status: Optional[str] = Field(default=None)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    duration_ms: Optional[float] = Field(default=None)
    files_matched: Optional[int] = Field(default=None)
    files_new: Optional[int] = Field(default=None)
    files_changed: Optional[int] = Field(default=None)
    files_updated: Optional[int] = Field(default=None)
    files_skipped: Optional[int] = Field(default=None)
    files_deleted: Optional[int] = Field(default=None)
    files_failed: Optional[int] = Field(default=None)
    rows_written: Optional[int] = Field(default=None)
    delta_version: Optional[int] = Field(default=None)
    write_mode: Optional[str] = Field(default=None)

    # Scan diagnostics. These turn "No files found" from a dead end into a
    # diagnosis: how much of the tree was walked, how many candidates the regex
    # rejected, why files were skipped, and a few concrete paths that were seen
    # but did not match.
    dirs_walked: Optional[int] = Field(default=None)
    files_seen: Optional[int] = Field(default=None)
    regex_rejected: Optional[int] = Field(default=None)
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    sample_rejected: list[str] = Field(
        default_factory=list, description="Up to a handful of paths seen but not matched"
    )
    errors: list[IngestionError] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class IngestionRun(BaseModel):
    """Lifecycle record for one ingestion invocation (CLI ``run`` or UI upload).

    Stored in the ``ingestion_runs`` collection, keyed by ``run_id``. CLI runs are
    opened by ``POST /monitoring/ingestion/start`` and closed by
    ``POST /monitoring/ingestion/{run_id}/finish``; UI table uploads open/close the
    record in-process via the monitoring store.
    """

    run_id: str = Field(..., description="Client-generated UUID for the ingestion run")
    source: Literal["cli", "ui"] = Field(
        default="cli", description="Origin of the ingestion: CLI run or web UI upload"
    )
    cli_instance_label: Optional[str] = Field(
        default=None, description="CLI instance label (CLI runs) or 'Web UI' for UI uploads"
    )
    cli_hostname: Optional[str] = Field(default=None, description="Hostname the CLI ran on")
    cli_version: Optional[str] = Field(default=None, description="Depictio CLI version that ran")
    user_id: Optional[str] = Field(default=None, description="Id of the ingesting user")
    email: Optional[str] = Field(default=None, description="Email of the ingesting user")
    project_id: Optional[str] = Field(default=None, description="Target project id")
    project_name: Optional[str] = Field(default=None, description="Target project name")
    command: str = Field(default="run", description="CLI command that triggered the run")
    command_line: Optional[str] = Field(
        default=None, description="Exact CLI invocation used (sensitive flags redacted)"
    )
    cli_config_path: Optional[str] = Field(
        default=None, description="Local CLI config file the run used"
    )
    project_config_path: Optional[str] = Field(
        default=None, description="Local project config YAML path (standard mode)"
    )
    data_root: Optional[str] = Field(
        default=None, description="Local data root directory (template mode)"
    )
    data_collections: list[IngestionDataCollection] = Field(
        default_factory=list, description="Per-DC summary + local scan paths for this run"
    )
    status: IngestionStatus = Field(default="running", description="Overall run status")
    steps: list[IngestionStep] = Field(default_factory=list, description="Per-step tally")
    # Written while status='running', via POST /monitoring/ingestion/{run_id}/step:
    # by the CLI's StepReporter for `depictio run` / `data watch`, and by the
    # server-side ingestion task for browser-triggered runs. Cleared when a step
    # reaches a terminal status, so the UI does not keep a spinner on a phase
    # that already ended. Runs recorded before live reporting existed leave it
    # None and report their whole step list at finish.
    current_step: Optional[str] = Field(
        default=None, description="Step currently running, for live progress"
    )
    error: Optional[str] = Field(default=None, description="Failure message if the run failed")
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = Field(default=None, description="When the run completed")

    #: What started this run. A watcher cycle and a hand-typed command produce
    #: very different expectations, and the ledger could not tell them apart.
    trigger: Literal["manual", "watch", "schedule", "ui"] = Field(default="manual")
    trigger_reason: Optional[str] = Field(
        default=None, description="What changed, for automatic triggers"
    )
    progress: Optional[IngestionProgress] = Field(default=None)
    counters: dict[str, int] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict, description="Per-phase milliseconds")
    concurrency: Optional[int] = Field(default=None)
    warnings: list[str] = Field(default_factory=list)
    errors: list[IngestionError] = Field(default_factory=list)
    errors_truncated: bool = Field(default=False)
    logs_truncated: bool = Field(default=False)

    model_config = ConfigDict(extra="forbid")


# ── CLI agent registry ──────────────────────────────────────────────────────

AgentStatus = Literal["idle", "settling", "scanning", "ingesting", "error"]


class CliAgent(BaseModel):
    """A long-running CLI process — today, a watcher — reporting that it is alive.

    Stored in ``cli_agents`` with a TTL on ``expires_at``, so an agent that dies
    disappears on its own rather than lingering as a phantom. A watcher that
    nobody can see is a watcher nobody can debug: this is what makes "is it
    actually running, and against what?" answerable.
    """

    agent_id: str = Field(..., description="Stable id for this agent process")
    kind: Literal["watcher"] = Field(default="watcher")
    instance_label: Optional[str] = Field(default=None)
    hostname: Optional[str] = Field(default=None)
    pid: Optional[int] = Field(default=None)
    cli_version: Optional[str] = Field(default=None)
    user_id: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    project_id: Optional[str] = Field(default=None)
    project_name: Optional[str] = Field(default=None)
    mode: Optional[str] = Field(default=None, description="incremental or full")
    backend: Optional[str] = Field(default=None, description="native, polling or both")
    watching: list[str] = Field(default_factory=list, description="Roots being watched")
    status: AgentStatus = Field(default="idle")
    last_error: Optional[str] = Field(default=None)
    last_run_id: Optional[str] = Field(default=None)
    last_trigger_at: Optional[datetime] = Field(default=None)
    runs_total: int = Field(default=0)
    #: Set server-side when someone presses "Run now", cleared when the watcher
    #: claims it on its next command poll. Server-owned: the agent never sends
    #: these, and the heartbeat deliberately does not overwrite them, or a beat
    #: landing between the request and the claim would drop the request.
    run_requested_at: Optional[datetime] = Field(default=None)
    run_requested_by: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=datetime.now)
    heartbeat_at: datetime = Field(default_factory=datetime.now)
    #: TTL anchor. Set to a few heartbeat intervals ahead so a missed beat does
    #: not evict a healthy agent, but a dead one clears quickly.
    expires_at: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict(extra="forbid")


# ── Application log ledger ──────────────────────────────────────────────────

#: "cli" covers log lines shipped from a CLI run. A run that fails on an HPC
#: login node otherwise leaves nothing server-side but a one-line error, and the
#: operator has to ask the user for their terminal scrollback.
LogSource = Literal["api", "celery", "cli"]


class AppLogRecord(BaseModel):
    """A single application log line persisted to the capped ``app_logs`` collection."""

    ts: datetime = Field(default_factory=datetime.now, description="Log record timestamp")
    level: str = Field(default="INFO", description="Log level name")
    logger: str = Field(default="", description="Logger name")
    source: LogSource = Field(default="api", description="Process that emitted the record")
    message: str = Field(default="", description="Formatted log message")
    pathname: Optional[str] = Field(default=None, description="Source file path")
    lineno: Optional[int] = Field(default=None, description="Source line number")
    #: Correlates a log line with the ingestion run that produced it, so the
    #: admin UI can show a run's logs rather than making the operator grep a
    #: shared stream by timestamp.
    run_id: Optional[str] = Field(default=None, description="Ingestion run this line belongs to")

    model_config = ConfigDict(extra="forbid")
