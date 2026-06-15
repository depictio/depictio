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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from depictio.api.celery_app import celery_app
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.monitoring import store
from depictio.models.models.monitoring import IngestionRun, IngestionStep
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

monitoring_endpoint_router = APIRouter()


def _require_admin(current_user: User) -> None:
    """Reject non-admin callers and public/demo deployments.

    Mirrors the celery introspection gate. The monitoring surface exposes task
    args, tracebacks and host logs — admin-only, and meaningless in public/demo
    mode (no real admin user), so we refuse there outright.
    """
    if settings.auth.is_public_mode or settings.auth.is_demo_mode:
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


class IngestionFinishRequest(BaseModel):
    status: str = Field(default="success", description="running|success|partial|failed")
    steps: list[IngestionStep] = Field(default_factory=list)
    error: Optional[str] = None


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
        cli_instance_label=x_depictio_cli_instance,
        cli_hostname=x_depictio_cli_host,
        user_id=str(current_user.id),
        email=current_user.email,
        project_id=body.project_id,
        project_name=body.project_name,
        command=body.command,
        status="running",
    )
    store.create_ingestion_run(run)
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
    matched = store.finish_ingestion_run(
        run_id,
        status=body.status,
        steps=[s.model_dump() for s in body.steps],
        error=body.error,
        finished_at=datetime.now(),
    )
    if not matched:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    return {"run_id": run_id, "status": body.status}


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
        inspect = celery_app.control.inspect(timeout=1.0)
        ping = inspect.ping() or {}
        active = inspect.active() or {}
        out["workers"] = sorted(ping.keys())
        out["worker_count"] = len(ping)
        out["active_count"] = sum(len(v or []) for v in active.values())
        out["status"] = "ok" if ping else "no_workers"
    except Exception as exc:
        logger.warning(f"monitoring/health: inspect failed: {exc}")
        out["status"] = "broker_unreachable"
        out["workers"] = []
        out["worker_count"] = 0
        out["active_count"] = 0
    return out
