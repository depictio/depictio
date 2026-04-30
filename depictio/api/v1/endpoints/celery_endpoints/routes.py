"""Lightweight Celery introspection endpoints — health, active tasks, stats.

Backed by `celery_app.control.inspect()` for live worker state. For a full UI
(task history, retry queues, time series), use Flower (docker-compose
`monitoring` profile, port 5555).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.dash.celery_app import celery_app
from depictio.models.models.users import User

logger = logging.getLogger(__name__)

celery_endpoint_router = APIRouter()


def _inspect():
    """Wrap `celery_app.control.inspect()` with a tiny timeout.

    `inspect()` returns `None` for some methods if no workers respond inside
    the broker poll window — callers must handle that.
    """
    return celery_app.control.inspect(timeout=1.0)


@celery_endpoint_router.get("/health")
def celery_health(
    current_user: User = Depends(get_user_or_anonymous),
):
    """Return broker connectivity + worker count + queue list.

    Useful for liveness/readiness probes and to confirm the offload flag is
    actually pointing at a live worker pool.
    """
    try:
        inspect = _inspect()
        ping = inspect.ping() or {}
        active_queues = inspect.active_queues() or {}
    except Exception as e:
        logger.warning(f"celery/health: inspect failed: {e}")
        raise HTTPException(status_code=503, detail=f"Celery broker unreachable: {e}")

    workers = sorted(ping.keys())
    queues = sorted(
        {q.get("name") for qs in active_queues.values() for q in (qs or []) if q.get("name")}
    )
    return {
        "status": "ok" if workers else "no_workers",
        "broker": settings.celery.broker_url.rsplit("@", 1)[-1],
        "workers": workers,
        "worker_count": len(workers),
        "queues": queues,
        "offload_preview": settings.celery.offload_preview,
        "offload_rendering": settings.celery.offload_rendering,
        "offload_timeout_seconds": settings.celery.offload_timeout_seconds,
    }


@celery_endpoint_router.get("/active")
def celery_active(
    current_user: User = Depends(get_user_or_anonymous),
):
    """Return tasks currently executing on each worker."""
    try:
        active = _inspect().active() or {}
    except Exception as e:
        logger.warning(f"celery/active: inspect failed: {e}")
        raise HTTPException(status_code=503, detail=f"Celery broker unreachable: {e}")

    summary = {
        worker: [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "args_repr": str(t.get("args"))[:200],
                "time_start": t.get("time_start"),
            }
            for t in (tasks or [])
        ]
        for worker, tasks in active.items()
    }
    return {
        "active_count": sum(len(v) for v in summary.values()),
        "tasks": summary,
    }


@celery_endpoint_router.get("/stats")
def celery_stats(
    current_user: User = Depends(get_user_or_anonymous),
):
    """Aggregate per-worker stats (pool size, totals, prefetch count)."""
    try:
        stats = _inspect().stats() or {}
    except Exception as e:
        logger.warning(f"celery/stats: inspect failed: {e}")
        raise HTTPException(status_code=503, detail=f"Celery broker unreachable: {e}")

    out = {}
    for worker, s in stats.items():
        pool = (s or {}).get("pool", {})
        total = (s or {}).get("total", {})
        out[worker] = {
            "pool_max_concurrency": pool.get("max-concurrency"),
            "pool_processes": pool.get("processes"),
            "total_tasks": total,
            "uptime_s": (s or {}).get("uptime"),
        }
    return {"workers": out, "worker_count": len(out)}
