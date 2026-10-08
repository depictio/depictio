"""Lightweight, synchronous publisher for live monitoring events.

Celery signal handlers (worker process, no event loop) and the API need to push
small status-change notifications to admin browsers. Rather than reach into the
async ``connection_manager`` from sync code, we publish directly to the same
Redis channel the events pub/sub listener already consumes
(``depictio:events:dashboard:__admin_monitoring__``). The FastAPI events
listener then fans the message out to locally-connected admin WebSocket clients.

Best-effort: gated by ``monitoring.live_updates`` AND ``events.enabled``, and any
failure (Redis down, serialization) is swallowed — live push is an enhancement
over the always-on polling baseline.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.monitoring import ADMIN_MONITORING_CHANNEL

_CHANNEL = f"depictio:events:dashboard:{ADMIN_MONITORING_CHANNEL}"

# Cached sync Redis client (created lazily; the worker is long-lived).
_redis_client: Any = None


def get_sync_redis() -> Any:
    """Shared lazily-created sync Redis client.

    Public because the rate limiter and the DC event publisher need the same
    connection from the same sync contexts (Celery workers, request handlers
    outside the loop); a second client per caller would multiply connections
    for no benefit.
    """
    global _redis_client
    if _redis_client is None:
        import redis  # sync client (redis-py); already a transitive dep of celery

        _redis_client = redis.Redis.from_url(settings.events.redis_url, decode_responses=True)
    return _redis_client


def _live_enabled() -> bool:
    return bool(settings.monitoring.live_updates and settings.events.enabled)


def publish_monitoring_event(event_type: str, payload: dict[str, Any]) -> None:
    """Publish one small monitoring event to the admin channel. Never raises."""
    if not _live_enabled():
        return
    try:
        message = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "dashboard_id": ADMIN_MONITORING_CHANNEL,
            "payload": payload,
        }
        get_sync_redis().publish(_CHANNEL, json.dumps(message))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"monitoring: live publish failed (non-fatal): {exc}")


def publish_task_event(task_id: str, task_name: str, kind: str, status: str) -> None:
    publish_monitoring_event(
        "task_event",
        {"task_id": task_id, "task_name": task_name, "kind": kind, "status": status},
    )


def publish_ingestion_event(
    run_id: str,
    status: str,
    instance: str | None,
    *,
    current_step: str | None = None,
    step: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    counters: dict[str, int] | None = None,
) -> None:
    """Announce an ingestion-run change, carrying the delta rather than a ping.

    The payload includes the changed step so the client can patch its copy in
    place. A bare notification would force a refetch of the whole run list on
    every push — tolerable at two pushes per run (start, finish), but live step
    reporting emits one per step and a watcher produces them continuously.

    Kept small (< 1 KB): only the step that changed, never the whole run.
    """
    payload: dict[str, Any] = {"run_id": run_id, "status": status, "instance": instance}
    if current_step is not None:
        payload["current_step"] = current_step
    if step is not None:
        payload["step"] = step
    if progress is not None:
        payload["progress"] = progress
    if counters is not None:
        payload["counters"] = counters
    publish_monitoring_event("ingestion_event", payload)
