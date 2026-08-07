"""Shared lazy Redis client for auth-adjacent features.

Extracted from the rate limiter so other modules (OAuth/SAML state store) can
reuse the same connection instead of each keeping a private one. Reuses
``settings.cache`` connection details (same Redis instance as the DataFrame
cache, celery broker and events pub/sub).

Callers must treat ``None`` as "Redis unavailable" and degrade gracefully —
this module never raises on connection failure.
"""

from __future__ import annotations

import time
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# Optional Redis import — graceful degradation if the package is missing.
# Typed ``Any`` so the module alias can be None without a type-ignore.
_redis: Any = None
try:
    import redis as _redis_module

    _redis = _redis_module
    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - redis is a stack dependency
    _REDIS_AVAILABLE = False
    logger.warning("Redis package unavailable — Redis-backed auth features are degraded.")


# How long to wait before re-trying a failed Redis connection. Without this a
# worker that starts during a brief Redis bounce would lose Redis-backed
# features for its entire process lifetime.
_REDIS_RETRY_SECS = 60

# Lazily-initialised shared Redis client (one per worker process).
_redis_client: Any = None
_redis_next_retry_at = 0.0


def get_shared_redis_client() -> Any:
    """Return a shared Redis client, or ``None`` if Redis is unavailable.

    Connection failures are swallowed here; callers must treat ``None`` as
    "degrade gracefully". Failed connections are retried at most once every
    ``_REDIS_RETRY_SECS`` so a Redis bounce doesn't permanently disable
    dependent features, while a hard outage isn't hammered on every request.
    """
    global _redis_client, _redis_next_retry_at

    if _redis_client is not None:
        return _redis_client

    if not _REDIS_AVAILABLE:
        return None

    now = time.monotonic()
    if now < _redis_next_retry_at:
        # Recent attempt failed; wait out the backoff window.
        return None
    _redis_next_retry_at = now + _REDIS_RETRY_SECS

    try:
        cache_cfg = settings.cache
        client = _redis.Redis(
            host=cache_cfg.redis_host,
            port=cache_cfg.redis_port,
            password=cache_cfg.redis_password,
            db=cache_cfg.redis_db,
            ssl=cache_cfg.redis_ssl,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        _redis_client = client
        logger.debug("Shared auth Redis client connected.")
        return _redis_client
    except Exception as e:
        logger.warning(
            f"Could not connect to Redis ({e}); Redis-backed auth features degraded, "
            f"retrying in {_REDIS_RETRY_SECS}s."
        )
        return None


def reset_shared_redis_client() -> None:
    """Drop the cached client and retry backoff (for tests)."""
    global _redis_client, _redis_next_retry_at
    _redis_client = None
    _redis_next_retry_at = 0.0
