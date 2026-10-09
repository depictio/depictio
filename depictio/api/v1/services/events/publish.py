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
