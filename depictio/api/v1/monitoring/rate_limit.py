"""Rate limiting for live ingestion-step updates.

A CLI reporting every step transition is fine. A CLI reporting per-file progress
during a large parallel scan is not — that is a write to Mongo and a Redis
publish per ping, multiplied by however many CLIs are running.

The bucket **fails open**: if Redis is unreachable the update is allowed
through. Losing progress telemetry because a cache is down would be a strictly
worse outcome than the load it was meant to shed, and the monitoring path is
best-effort by design everywhere else too.
"""

from __future__ import annotations

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

_KEY_PREFIX = "depictio:ingest:step:"


def allow_step_update(run_id: str) -> bool:
    """Whether another non-terminal step update may be recorded for this run.

    Callers must bypass this for terminal steps: throttling a run's final tally
    would lose it permanently, whereas a dropped intermediate ping costs
    nothing.
    """
    limit = max(1, settings.ingestion.step_updates_per_minute)

    try:
        from depictio.api.v1.monitoring.publish import get_sync_redis

        client = get_sync_redis()
        if client is None:
            return True

        key = f"{_KEY_PREFIX}{run_id}"
        count = client.incr(key)
        if count == 1:
            # First hit in this window — start the clock.
            client.expire(key, 60)
        return count <= limit
    except Exception as exc:  # noqa: BLE001 - fail open, never block the write
        logger.debug(f"Step rate limiting unavailable ({exc}); allowing the update.")
        return True
