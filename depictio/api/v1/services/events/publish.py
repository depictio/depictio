"""Synchronous publisher for data-collection update events.

Exists because of a concrete multi-worker bug. ``_dashboard_subscriptions`` in
``connection_manager`` is **process-local**: it maps dashboard ids to WebSocket
clients held by *this* process. The existing broadcast path enumerates that dict
and publishes one Redis message per locally-known dashboard. With
``--workers 4``, an upsert handled by gunicorn worker 2 therefore only ever
reaches dashboards whose sockets happen to live on worker 2 — the other three
workers' clients are never told. A Celery worker is the extreme case of the
same bug: it holds no WebSockets at all, so it has nothing to enumerate.

The fix is to publish to a channel keyed by the thing that actually changed —
the data collection — and let every API worker fan out to whichever of its own
connections care. One publish instead of N, and correct regardless of which
process handled the write.

The existing ``psubscribe("depictio:events:*")`` already matches this channel;
``_handle_pubsub_message`` grew a ``dc`` branch to route it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

DC_CHANNEL_PREFIX = "depictio:events:dc:"
PROJECT_CHANNEL_PREFIX = "depictio:events:project:"

#: Name a client subscribes to (the WebSocket ``dashboard_id`` field carries it,
#: like the admin monitoring channel does): ``project:<project_id>``.
PROJECT_SUBSCRIPTION_PREFIX = "project:"

#: A run that left data behind. A failed or interrupted run brought nothing new,
#: so announcing "new data" for it would be wrong.
INGESTION_ANNOUNCE_STATUSES = frozenset({"success", "partial"})


def publish_dc_update(dc_id: str, payload: dict[str, Any] | None = None) -> None:
    """Announce that a data collection's data changed. Never raises.

    Best-effort like every other live-push path here: a dropped notification
    costs a stale panel until the next poll, which is not worth failing an
    ingestion over.
    """
    if not settings.events.enabled:
        return
    try:
        from depictio.api.v1.monitoring.publish import get_sync_redis

        message = {
            "event_type": "data_collection_updated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_collection_id": dc_id,
            "payload": payload or {},
        }
        get_sync_redis().publish(f"{DC_CHANNEL_PREFIX}{dc_id}", json.dumps(message))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"events: DC update publish failed for {dc_id} (non-fatal): {exc}")


def publish_ingestion_finished(run: dict[str, Any] | None) -> None:
    """Announce that an ingestion run finished, on its project's channel. Never raises.

    ``run`` is the ``ingestion_runs`` document, read after it was closed. Runs
    in whichever process closed the run (an API worker or a Celery worker): the
    message goes to Redis, and every API worker's pub/sub listener relays it to
    the sockets that subscribed to ``project:<id>`` (see
    ``ConnectionManager._handle_pubsub_message``). Off unless the changes-since
    feature is on; a run with no project, or one that failed, is not announced.
    """
    if not run or not settings.events.enabled:
        return
    try:
        if not settings.dashboard_versions.changes_since_enabled:
            return
        project_id = run.get("project_id")
        status = run.get("status")
        if not project_id or status not in INGESTION_ANNOUNCE_STATUSES:
            return
        from depictio.api.v1.monitoring.publish import get_sync_redis
        from depictio.models.timestamps import utc_now_naive

        project_id = str(project_id)
        collections = [
            str(dc.get("tag")) for dc in run.get("data_collections") or [] if dc.get("tag")
        ]
        message = {
            "event_type": "ingestion_finished",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dashboard_id": f"{PROJECT_SUBSCRIPTION_PREFIX}{project_id}",
            "payload": {
                "project_id": project_id,
                "project_name": run.get("project_name"),
                "run_id": run.get("run_id"),
                "status": status,
                "run_tags": list(run.get("run_tags") or []),
                "collections": collections,
                "at": utc_now_naive().isoformat(),
            },
        }
        get_sync_redis().publish(f"{PROJECT_CHANNEL_PREFIX}{project_id}", json.dumps(message))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"events: ingestion_finished publish failed (non-fatal): {exc}")
