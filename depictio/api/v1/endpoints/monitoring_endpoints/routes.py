"""Admin "Log & Task" monitoring API.

Read endpoints (admin-only) back the admin monitoring tab: Celery task history,
CLI ingestion runs, recent application logs, and live worker health. Two write
endpoints (auth-only, not admin-gated) let the CLI open/close an ingestion-run
record — the caller is the ingesting user, identified by token + CLI headers.

Admin gating mirrors ``celery_endpoints/routes.py`` (module-local
``_require_admin``). The whole feature is additionally refused in public/demo
mode, where there is no meaningful per-user admin surface.
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from depictio.api.celery_app import celery_app
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.monitoring import store
from depictio.api.v1.monitoring.rate_limit import allow_step_update
from depictio.models.models.monitoring import (
    CliAgent,
    IngestionDataCollection,
    IngestionRun,
    IngestionStep,
)
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

monitoring_endpoint_router = APIRouter()


def _require_admin(current_user: User) -> None:
    """Reject non-admin callers and public/demo deployments.

    Mirrors the celery introspection gate. The monitoring surface exposes task
    args, tracebacks and host logs — admin-only, and meaningless in public/demo
    mode (no real admin user), so we refuse there outright.
    """
    # Single-user is a trusted personal admin instance — always allowed, even if
    # public_mode is also set. Only pure public/demo deployments are refused.
    if (
        settings.auth.is_public_mode or settings.auth.is_demo_mode
    ) and not settings.auth.is_single_user_mode:
        raise HTTPException(status_code=404, detail="Monitoring is not available in this mode.")
    if not getattr(current_user, "is_admin", False):
        logger.warning(
            f"Denied monitoring access: non-admin user {current_user.id} ({current_user.email})"
        )
        raise HTTPException(status_code=403, detail="User is not an admin.")


# ── Tasks ───────────────────────────────────────────────────────────────────


@monitoring_endpoint_router.get("/tasks")
def list_tasks(
    current_user: User = Depends(get_current_user),
    status: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    since_seconds: Optional[float] = Query(
        default=None, description="Only events updated within N seconds"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
):
    """List Celery task events, newest-first, with optional filters."""
    _require_admin(current_user)
    since = store.task_event_seconds_ago(since_seconds) if since_seconds else None
    return {
        "tasks": store.query_task_events(
            status=status, kind=kind, since=since, limit=limit, skip=skip
        )
    }


@monitoring_endpoint_router.get("/tasks/{task_id}")
def get_task(task_id: str, current_user: User = Depends(get_current_user)):
    """Return a single task event including captured logs and traceback."""
    _require_admin(current_user)
    event = store.get_task_event(task_id)
    if not event:
        raise HTTPException(status_code=404, detail="Task event not found.")
    return event


# ── Ingestion runs ────────────────────────────────────────────────────────────


class IngestionStartRequest(BaseModel):
    run_id: Optional[str] = Field(
        default=None, description="Client-supplied run id (uuid). Generated if omitted."
    )
    command: str = Field(default="run")
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    cli_version: Optional[str] = None
    command_line: Optional[str] = None
    cli_config_path: Optional[str] = None
    project_config_path: Optional[str] = None
    data_root: Optional[str] = None
    #: How the run was initiated. Optional so an older CLI, which sends nothing,
    #: still opens a record — it defaults to "manual", which is what such a CLI
    #: could only have been doing anyway. An unrecognised value is coerced to
    #: "manual" rather than 422'd: a newer CLI inventing a trigger must not be
    #: unable to open a monitoring record against an older server.
    trigger: Optional[Literal["manual", "watch", "schedule", "ui"]] = None
    trigger_reason: Optional[str] = None

    @field_validator("trigger", mode="before")
    @classmethod
    def _coerce_unknown_trigger(cls, value):
        if value is None:
            return None
        return value if value in ("manual", "watch", "schedule", "ui") else "manual"


class IngestionFinishRequest(BaseModel):
    status: str = Field(default="success", description="running|success|partial|failed")
    steps: list[IngestionStep] = Field(default_factory=list)
    error: Optional[str] = None
    # Resolved mid-run (the CLI often only learns the server-side project id after
    # sync), so it can be patched onto the record at close time.
    project_id: Optional[str] = None
    # Per-DC breakdown (tag / type / format + local scan paths), derived from the
    # validated project config once the run has scanned.
    data_collections: list[IngestionDataCollection] = Field(default_factory=list)


class IngestionStepRequest(BaseModel):
    """Live per-step update, pushed while the run is still ``running``."""

    step: IngestionStep
    current_step: Optional[str] = None
    #: Run-level rollups, refreshed alongside the step rather than only at
    #: finish, so a run in flight shows real numbers instead of zeros.
    counters: Optional[dict[str, int]] = None
    progress: Optional[dict] = None


@monitoring_endpoint_router.post("/ingestion/start")
def start_ingestion(
    body: IngestionStartRequest,
    current_user: User = Depends(get_current_user),
    x_depictio_cli_instance: Optional[str] = Header(default=None),
    x_depictio_cli_host: Optional[str] = Header(default=None),
):
    """Open an ingestion-run record. Auth-only (the ingesting user), not admin-gated.

    Best-effort from the CLI's perspective — failures here must never abort a
    real ingestion, so the CLI calls this in a try/except.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")
    run_id = body.run_id or str(uuid.uuid4())
    run = IngestionRun(
        run_id=run_id,
        source="cli",
        cli_instance_label=x_depictio_cli_instance,
        cli_hostname=x_depictio_cli_host,
        cli_version=body.cli_version,
        user_id=str(current_user.id),
        email=current_user.email,
        project_id=body.project_id,
        project_name=body.project_name,
        command=body.command,
        command_line=body.command_line,
        cli_config_path=body.cli_config_path,
        project_config_path=body.project_config_path,
        data_root=body.data_root,
        trigger=body.trigger or "manual",
        trigger_reason=body.trigger_reason,
        status="running",
    )
    store.create_ingestion_run(run)
    from depictio.api.v1.monitoring.publish import publish_ingestion_event

    publish_ingestion_event(run_id, "running", x_depictio_cli_instance or x_depictio_cli_host)
    return {"run_id": run_id}


@monitoring_endpoint_router.post("/ingestion/{run_id}/finish")
def finish_ingestion(
    run_id: str,
    body: IngestionFinishRequest,
    current_user: User = Depends(get_current_user),
):
    """Close an ingestion-run record with the final status + per-step tally."""
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")
    extra: dict = {}
    if body.project_id:
        extra["project_id"] = body.project_id
    if body.data_collections:
        extra["data_collections"] = [dc.model_dump() for dc in body.data_collections]
    matched = store.finish_ingestion_run(
        run_id,
        status=body.status,
        steps=[s.model_dump() for s in body.steps],
        error=body.error,
        finished_at=datetime.now(),
        # A finished run is no longer "running" any step.
        current_step=None,
        **extra,
    )
    if not matched:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    from depictio.api.v1.monitoring.publish import publish_ingestion_event

    publish_ingestion_event(run_id, body.status, None)
    return {"run_id": run_id, "status": body.status}


@monitoring_endpoint_router.post("/ingestion/{run_id}/step")
def update_ingestion_step(
    run_id: str,
    body: IngestionStepRequest,
    current_user: User = Depends(get_current_user),
):
    """Upsert a single step of an in-flight ingestion and mark it as current.

    The CLI calls this as each step starts and finishes, so the admin UI shows
    live state rather than only the final tally.

    Throttled per run: over the configured rate the update is dropped and the
    response says so, rather than returning 429. A dropped progress ping is not
    an error and must not make the client retry — but a *terminal* step always
    goes through, so a run's final tally is never lost to throttling.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")

    terminal = body.step.status in ("success", "failed", "skipped")
    if not terminal and not allow_step_update(run_id):
        return {"run_id": run_id, "step": body.step.name, "throttled": True}

    matched = store.upsert_ingestion_step(
        run_id,
        step=body.step.model_dump(),
        current_step=body.current_step,
        counters=body.counters,
        progress=body.progress,
    )
    if not matched:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    from depictio.api.v1.monitoring.publish import publish_ingestion_event

    # Carry the step itself, not just a "something changed" ping: the client
    # patches its copy of the run in place instead of refetching the whole list
    # on every one of a run's ~50 step updates.
    publish_ingestion_event(
        run_id,
        "running",
        None,
        current_step=body.current_step,
        step=body.step.model_dump(mode="json"),
        progress=body.progress,
        counters=body.counters,
    )
    return {"run_id": run_id, "step": body.step.name}


@monitoring_endpoint_router.post("/agents/heartbeat")
def agent_heartbeat(body: CliAgent, current_user: User = Depends(get_current_user)):
    """Record that a long-running CLI agent (a watcher) is alive.

    Auth-only rather than admin-gated, like the ingestion start/finish calls:
    the agent reports about itself, using its own credentials.

    ``expires_at`` is set several heartbeat intervals ahead so one missed beat
    does not evict a healthy agent, while a dead one clears within minutes.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")

    ttl = max(60, settings.monitoring.agent_ttl_seconds)
    agent = body.model_copy(
        update={
            "user_id": str(current_user.id),
            "email": current_user.email,
            "heartbeat_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(seconds=ttl),
        }
    )
    # Namespace the id by owner. agent_id is derived client-side from
    # hostname:pid:project_id, which is guessable, and upsert keys on it — so
    # without this any authenticated user could overwrite another user's agent
    # record, including the status and error strings the admin UI renders.
    agent = agent.model_copy(update={"agent_id": _scoped_agent_id(agent.agent_id, current_user)})
    store.upsert_cli_agent(agent)
    return {"agent_id": agent.agent_id, "expires_in": ttl}


def _scoped_agent_id(agent_id: str, current_user: User) -> str:
    """Bind a client-supplied agent id to its owner.

    Two users on the same host can legitimately watch the same project, so the
    id itself is not unique across users — and it is guessable, so it must not
    be a bare primary key.
    """
    return f"{current_user.id}:{agent_id}"


@monitoring_endpoint_router.delete("/agents/{agent_id}")
def deregister_agent(agent_id: str, current_user: User = Depends(get_current_user)):
    """Remove an agent immediately, on clean shutdown.

    Without this the agent would linger until its TTL expires, which reads as
    "still running" for several minutes after a deliberate stop.

    Scoped to the caller's own agents. The bare id is derived from
    hostname:pid:project_id and is therefore enumerable, so deleting by it
    alone would let anyone unregister anyone else's watcher — the process would
    keep running while disappearing from the admin's view.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")
    scoped = _scoped_agent_id(agent_id, current_user)
    removed = store.delete_cli_agent(scoped)
    if not removed and getattr(current_user, "is_admin", False):
        # Admins may clean up a stale row left by an older CLI that registered
        # before ids were owner-scoped.
        removed = store.delete_cli_agent(agent_id)
    return {"agent_id": agent_id, "removed": removed}


@monitoring_endpoint_router.post("/agents/{agent_id}/trigger")
def request_agent_run(agent_id: str, current_user: User = Depends(get_current_user)):
    """Ask a running watcher to start an ingestion cycle now.

    The registry is one-way — agents heartbeat in, and the server has no route
    back out to a process on a login node behind a firewall — so this records a
    request that the agent claims on its next command poll. The response says
    the request was *recorded*, not that a cycle ran; the agent card shows it
    turning into a run a few seconds later.

    ``agent_id`` is the stored (owner-scoped) id, as returned by ``GET /agents``.
    Authorised against the agent's recorded ``user_id`` rather than by parsing
    that id, so a caller cannot drive someone else's watcher by constructing a
    plausible-looking one.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")

    agent = store.get_cli_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found, or no longer running.")
    if agent.get("user_id") != str(current_user.id) and not getattr(
        current_user, "is_admin", False
    ):
        raise HTTPException(status_code=403, detail="Not your agent.")

    store.request_cli_agent_run(agent_id, requested_by=current_user.email)
    logger.info(f"Run requested for agent {agent_id} by {current_user.email}")
    return {"agent_id": agent_id, "requested": True}


@monitoring_endpoint_router.post("/agents/{agent_id}/claim")
def claim_agent_run(agent_id: str, current_user: User = Depends(get_current_user)):
    """Claim a pending run request. Polled by the watcher itself.

    Takes the bare id and scopes it to the caller, exactly as the heartbeat
    does, so an agent can only ever claim its own requests.

    Deliberately does not 404 on an unknown agent — it answers "nothing
    pending". That keeps 404 meaning one thing to the CLI: this server predates
    UI triggers, so stop polling.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")

    claimed = store.claim_cli_agent_run(_scoped_agent_id(agent_id, current_user))
    return {"agent_id": agent_id, "run_requested": bool(claimed)}


@monitoring_endpoint_router.get("/agents")
def list_agents(
    current_user: User = Depends(get_current_user),
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """List live CLI agents. Admin-gated, like the rest of the monitoring views."""
    _require_admin(current_user)
    return {"agents": store.query_cli_agents(project_id=project_id, limit=limit)}


@monitoring_endpoint_router.get("/ingestion")
def list_ingestion(
    current_user: User = Depends(get_current_user),
    instance: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
):
    """List CLI ingestion runs, newest-first, with optional filters."""
    _require_admin(current_user)
    return {
        "runs": store.query_ingestion_runs(
            instance=instance, status=status, project_id=project_id, limit=limit, skip=skip
        )
    }


@monitoring_endpoint_router.get("/ingestion/{run_id}")
def get_ingestion(run_id: str, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    run = store.get_ingestion_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    return run


# ── Logs ──────────────────────────────────────────────────────────────────────


@monitoring_endpoint_router.get("/logs")
def list_logs(
    current_user: User = Depends(get_current_user),
    level: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Return recent application log records from the capped collection."""
    _require_admin(current_user)
    return {"logs": store.query_app_logs(level=level, source=source, limit=limit)}


class LogLevelRequest(BaseModel):
    level: str = Field(..., description="DEBUG | INFO | WARNING | ERROR | CRITICAL")


@monitoring_endpoint_router.get("/logs/level")
def get_log_capture_level(current_user: User = Depends(get_current_user)):
    """Current floor of what the app-log handler persists (this API process)."""
    _require_admin(current_user)
    from depictio.api.v1.monitoring.log_handler import get_app_log_capture_level

    return {"level": get_app_log_capture_level()}


@monitoring_endpoint_router.post("/logs/level")
def set_log_capture_level(body: LogLevelRequest, current_user: User = Depends(get_current_user)):
    """Change the app-log capture floor at runtime (admin-only).

    Applies immediately in the API process and is broadcast best-effort to Celery
    workers so their logs follow the same floor. Not persisted — a restart reverts
    to ``settings.monitoring.app_log_min_level``.
    """
    _require_admin(current_user)
    from depictio.api.v1.monitoring.log_handler import set_app_log_capture_level

    try:
        applied = set_app_log_capture_level(body.level)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        celery_app.control.broadcast("set_app_log_capture_level", arguments={"level": applied})
    except Exception as exc:
        logger.debug(f"Could not broadcast log level to workers: {exc}")
    return {"level": applied}


# ── Health ──────────────────────────────────────────────────────────────────


@monitoring_endpoint_router.get("/health")
def monitoring_health(current_user: User = Depends(get_current_user)):
    """Live worker/broker health + active task count (Celery inspect)."""
    _require_admin(current_user)
    out: dict = {
        "hostname": socket.gethostname(),
        "events_enabled": settings.events.enabled,
        "live_updates": settings.monitoring.live_updates and settings.events.enabled,
    }
    try:
        inspect = celery_app.control.inspect(timeout=0.75)
        # Single broadcast: active() replies are keyed by every live worker
        # (empty list when idle), so it yields both the worker roster and the
        # active-task count without a second ping() round-trip. inspect waits
        # the full timeout per call, so dropping ping() roughly halves latency.
        active = inspect.active() or {}
        workers = sorted(active.keys())
        out["workers"] = workers
        out["worker_count"] = len(workers)
        out["active_count"] = sum(len(v or []) for v in active.values())
        out["status"] = "ok" if workers else "no_workers"
    except Exception as exc:
        logger.warning(f"monitoring/health: inspect failed: {exc}")
        out["status"] = "broker_unreachable"
        out["workers"] = []
        out["worker_count"] = 0
        out["active_count"] = 0
    return out
