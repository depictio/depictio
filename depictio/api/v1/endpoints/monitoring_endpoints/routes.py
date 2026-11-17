"""Admin "Log & Task" monitoring API.

Read endpoints back the admin monitoring tab: Celery task history, CLI
ingestion runs, CLI agents, recent application logs, and live worker health.
Tasks, ingestion runs and agents are also readable by non-admin users, scoped to
the projects they can access (see ``_reader_scope``); logs and health stay
admin-only. Two write
endpoints (auth-only, not admin-gated) let the CLI open/close an ingestion-run
record — the caller is the ingesting user, identified by token + CLI headers.

Admin gating mirrors ``celery_endpoints/routes.py`` (module-local
``_require_admin``). The whole feature is additionally refused in demo mode,
where there is no meaningful per-user admin surface. A public instance does
have real admins (they sign in), so there it is open to a signed-in admin and
refused to the temporary guests the instance mints.
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import datetime, timedelta
from typing import Optional, get_args

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from depictio.api.celery_app import celery_app
from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import groups_collection, projects_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.monitoring import store
from depictio.api.v1.monitoring.rate_limit import allow_step_update
from depictio.api.v1.permissions import build_access_query, get_user_group_ids
from depictio.models.models.monitoring import (
    CliAgent,
    IngestionDataCollection,
    IngestionRun,
    IngestionStep,
    IngestionTrigger,
)
from depictio.models.models.users import User
from depictio.models.timestamps import utc_now_naive

logger = logging.getLogger(__name__)

monitoring_endpoint_router = APIRouter()


def _require_admin(current_user: User) -> None:
    """Reject non-admin callers, guests of a public instance and demo deployments.

    Mirrors the celery introspection gate. The monitoring surface exposes task
    args, tracebacks and host logs: admin-only, and refused outright in demo
    mode (no real admin user). A public instance can have a real admin signed
    in, so it is allowed there, but never to a temporary guest.
    """
    # Single-user is a trusted personal admin instance — always allowed, even if
    # public_mode or demo_mode is also set.
    single_user = settings.auth.is_single_user_mode
    if settings.auth.is_demo_mode and not single_user:
        raise HTTPException(status_code=404, detail="Monitoring is not available in this mode.")
    if not getattr(current_user, "is_admin", False) or (
        settings.auth.is_public_mode
        and not single_user
        and getattr(current_user, "is_temporary", False)
    ):
        logger.warning(
            f"Denied monitoring access: non-admin user {current_user.id} ({current_user.email})"
        )
        raise HTTPException(status_code=403, detail="User is not an admin.")


class _Scope:
    """What one caller may read of the tasks / runs / agents ledgers.

    ``admin`` sees everything. Anyone else sees the rows filed under a project
    they can read, plus the rows they created themselves; of those, the ones
    under a project they can edit (or that they created) come back in full and
    the rest redacted.
    """

    def __init__(
        self,
        user_id: str,
        admin: bool,
        viewer_project_ids: Optional[list[str]] = None,
        editor_project_ids: Optional[list[str]] = None,
    ):
        self.user_id = user_id
        self.admin = admin
        self.viewer_project_ids = viewer_project_ids or []
        self._editor_project_ids = set(editor_project_ids or [])

    @property
    def query_scope(self) -> Optional[dict]:
        """The ``scope`` argument of the store queries; None for an admin."""
        if self.admin:
            return None
        return {"project_ids": self.viewer_project_ids, "user_id": self.user_id}

    def can_see(self, row: dict) -> bool:
        if self.admin or row.get("user_id") == self.user_id:
            return True
        return row.get("project_id") in self.viewer_project_ids

    def sees_in_full(self, row: dict) -> bool:
        if self.admin or row.get("user_id") == self.user_id:
            return True
        return row.get("project_id") in self._editor_project_ids


def _reader_scope(current_user: User) -> _Scope:
    """Who may read the task / ingestion / agent views, and how much of them.

    Admins read everything (a public instance's temporary guests excepted).
    Other real users read the rows of the projects they can access, but never
    in public or demo mode, where the user base is anonymous or throwaway and
    there is no per-user surface to scope to. Single-user mode is always
    allowed.
    """
    single_user = settings.auth.is_single_user_mode
    if settings.auth.is_demo_mode and not single_user:
        raise HTTPException(status_code=404, detail="Monitoring is not available in this mode.")
    is_admin = bool(getattr(current_user, "is_admin", False))
    temporary = bool(getattr(current_user, "is_temporary", False))
    public = settings.auth.is_public_mode and not single_user
    if is_admin:
        if public and temporary:
            raise HTTPException(status_code=403, detail="User is not an admin.")
        return _Scope(str(current_user.id), admin=True)
    if (public or temporary or getattr(current_user, "is_anonymous", False)) and not single_user:
        logger.warning(
            f"Denied monitoring access: user {current_user.id} ({current_user.email}) "
            "may not read it in this mode"
        )
        raise HTTPException(status_code=403, detail="User is not an admin.")
    group_ids = get_user_group_ids(current_user.id, groups_collection)

    def _ids(level: str) -> list[str]:
        query = build_access_query(current_user, level, group_ids)
        return [str(doc["_id"]) for doc in projects_collection.find(query, {"_id": 1})]

    return _Scope(
        str(current_user.id),
        admin=False,
        viewer_project_ids=_ids("viewer"),
        editor_project_ids=_ids("editor"),
    )


# What a plain viewer of a project does not see of a task: the call's arguments,
# its captured logs, traceback and result, and the machine it ran on.
_TASK_DETAIL_FIELDS = ("args_repr", "traceback", "logs", "result_summary", "worker", "user_id")

# The same for an agent: where the watcher runs and who runs it.
_AGENT_OPERATOR_FIELDS = (
    "hostname",
    "pid",
    "email",
    "user_id",
    "watching",
    "last_error",
    "run_requested_by",
)


def _redact_task(task: dict, scope: _Scope) -> dict:
    if scope.sees_in_full(task):
        return task
    return {**{k: v for k, v in task.items() if k not in _TASK_DETAIL_FIELDS}, "redacted": True}


def _redact_agent(agent: dict, scope: _Scope) -> dict:
    if scope.sees_in_full(agent):
        return agent
    return {
        **{k: v for k, v in agent.items() if k not in _AGENT_OPERATOR_FIELDS},
        "redacted": True,
    }


def _redact_ingestion_run(run: dict, scope: _Scope) -> dict:
    if scope.sees_in_full(run):
        return run
    from depictio.api.v1.endpoints.projects_endpoints.routes import _redact_run

    return {**_redact_run(run, full=False), "redacted": True}


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
    """List Celery task events, newest-first, with optional filters.

    Admins see every task; other users the tasks of their projects, redacted
    unless they can edit the project.
    """
    scope = _reader_scope(current_user)
    since = store.task_event_seconds_ago(since_seconds) if since_seconds else None
    tasks = store.query_task_events(
        status=status, kind=kind, since=since, limit=limit, skip=skip, scope=scope.query_scope
    )
    return {"tasks": [_redact_task(task, scope) for task in tasks]}


@monitoring_endpoint_router.get("/tasks/{task_id}")
def get_task(task_id: str, current_user: User = Depends(get_current_user)):
    """Return a single task event including captured logs and traceback.

    A task outside the caller's scope is a 404, not a 403: it should not be
    possible to tell it exists.
    """
    scope = _reader_scope(current_user)
    event = store.get_task_event(task_id)
    if not event or not scope.can_see(event):
        raise HTTPException(status_code=404, detail="Task event not found.")
    return _redact_task(event, scope)


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
    trigger: Optional[IngestionTrigger] = None
    trigger_reason: Optional[str] = None
    #: The runs a ``--attach-run`` brings, which tie this record to them in the
    #: project's Runs tab and the ingestion event (epic #1399).
    run_tags: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("trigger", mode="before")
    @classmethod
    def _coerce_unknown_trigger(cls, value):
        if value is None or value in get_args(IngestionTrigger):
            return value
        return "manual"


class IngestionFinishRequest(BaseModel):
    status: str = Field(default="success", description="running|success|partial|failed|interrupted")
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


def _may_write_project(project_id: str, current_user: User) -> bool:
    """Owners, editors and admins may record runs against a project.

    A run shows up in the project's ingestion history, so writing one is
    writing to the project; reading it is not enough.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    try:
        ObjectId(project_id)
    except (InvalidId, TypeError):
        return False
    return check_project_permission(project_id, current_user, "editor")


def _owned_run_or_raise(run_id: str, current_user: User) -> dict:
    """The run, if the caller opened it or is an admin; 404 or 403 otherwise.

    Run ids are not secret: the project's ingestion history lists them to every
    viewer, anonymous ones included on a public project. Without this, any
    signed-in user could rewrite another user's run.
    """
    run = store.get_ingestion_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    if run.get("user_id") != str(current_user.id) and not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=403, detail="This ingestion run belongs to another user.")
    return run


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

    The record is upserted by ``run_id``, which the client may supply, so an
    existing run of another user is refused rather than overwritten, and a
    ``project_id`` needs write access to that project.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")
    if body.run_id:
        existing = store.get_ingestion_run(body.run_id)
        if existing and existing.get("user_id") != str(current_user.id):
            raise HTTPException(
                status_code=403, detail="This ingestion run belongs to another user."
            )
    if body.project_id and not _may_write_project(body.project_id, current_user):
        raise HTTPException(
            status_code=403, detail="Editor access to the project is required to record a run."
        )
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
        run_tags=body.run_tags,
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
    """Close an ingestion-run record with the final status + per-step tally.

    Only the user who opened the run, or an admin, may close it. A
    ``project_id`` the caller may not write is dropped rather than refused:
    the run still closes, but it cannot be filed under someone else's project.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")
    _owned_run_or_raise(run_id, current_user)
    extra: dict = {}
    if body.project_id:
        if _may_write_project(body.project_id, current_user):
            extra["project_id"] = body.project_id
        else:
            logger.warning(
                f"Ingestion run {run_id}: not filing it under project {body.project_id}, "
                f"which {current_user.id} may not write"
            )
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

    Only the user who opened the run, or an admin, may update it. Checked before
    the throttle, or anyone could spend the owner's update budget.
    """
    if not settings.monitoring.enabled:
        raise HTTPException(status_code=404, detail="Monitoring is disabled.")
    _owned_run_or_raise(run_id, current_user)

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
    # Naive UTC: Mongo evaluates the TTL index in UTC, so a local clock would
    # evict agents early or late by the server's UTC offset.
    now = utc_now_naive()
    agent = body.model_copy(
        update={
            # Namespace the id by owner. agent_id is derived client-side from
            # hostname:pid:project_id, which is guessable, and upsert keys on
            # it, so without this any authenticated user could overwrite another
            # user's agent record, including the status and error strings the
            # admin UI renders.
            "agent_id": _scoped_agent_id(body.agent_id, current_user),
            "user_id": str(current_user.id),
            "email": current_user.email,
            "heartbeat_at": now,
            "expires_at": now + timedelta(seconds=ttl),
        }
    )
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
    """List live CLI agents: all for an admin, else those of the caller's projects."""
    scope = _reader_scope(current_user)
    agents = store.query_cli_agents(project_id=project_id, limit=limit, scope=scope.query_scope)
    return {"agents": [_redact_agent(agent, scope) for agent in agents]}


@monitoring_endpoint_router.get("/ingestion")
def list_ingestion(
    current_user: User = Depends(get_current_user),
    instance: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
):
    """List ingestion runs, newest-first, with optional filters.

    Admins see every run; other users the runs of their projects and their own,
    redacted unless they can edit the project.
    """
    scope = _reader_scope(current_user)
    store.mark_stale_ingestion_runs()
    runs = store.query_ingestion_runs(
        instance=instance,
        status=status,
        project_id=project_id,
        limit=limit,
        skip=skip,
        scope=scope.query_scope,
    )
    return {"runs": [_redact_ingestion_run(run, scope) for run in runs]}


@monitoring_endpoint_router.get("/ingestion/{run_id}")
def get_ingestion(run_id: str, current_user: User = Depends(get_current_user)):
    """One run. Outside the caller's scope it is a 404, not a 403."""
    scope = _reader_scope(current_user)
    store.mark_stale_ingestion_runs()
    run = store.get_ingestion_run(run_id)
    if not run or not scope.can_see(run):
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    return _redact_ingestion_run(run, scope)


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
