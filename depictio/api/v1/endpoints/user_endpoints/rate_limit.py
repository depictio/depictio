"""Redis-backed per-IP rate limiter for public/auth endpoints.

The previous implementation used an in-process ``dict`` of timestamps. That is
useless across gunicorn workers (each worker has its own dict) and resets on
restart. This module reimplements the limiter on Redis using a fixed-window
``INCR`` + ``EXPIRE`` counter keyed by ``(client_ip, endpoint)``.

Design notes:
- Redis is already a stack dependency (DataFrame cache, celery broker, events
  pub/sub). We reuse the same ``CacheConfig`` connection settings rather than
  introducing a new accessor or setting.
- FAIL-OPEN: if Redis is unreachable we log a warning and ALLOW the request, so
  a Redis outage degrades to "no rate limiting" instead of locking every user
  out of login/registration. This is a deliberate availability-over-strictness
  trade-off for an auth path.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException, Request

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
    logger.warning("Redis package unavailable — auth rate limiting is disabled (fail-open).")


# Fixed-window parameters. Kept conservative — these endpoints are
# human-driven (login / register / temp-user mint), not high-throughput.
_RATE_WINDOW_SECS = 60
_RATE_MAX_CALLS = 10

# How long to wait before re-trying a failed Redis connection. Without this a
# worker that starts during a brief Redis bounce would lose rate limiting for
# its entire process lifetime.
_REDIS_RETRY_SECS = 60

# Lazily-initialised shared Redis client (one per worker process).
_redis_client: Any = None
_redis_next_retry_at = 0.0


def _get_redis_client() -> Any:
    """Return a shared Redis client, or ``None`` if Redis is unavailable.

    Reuses ``settings.cache`` connection details (same Redis instance used by
    the DataFrame cache). Connection failures are swallowed here; callers must
    treat ``None`` as "fail open". Failed connections are retried at most once
    every ``_REDIS_RETRY_SECS`` so a Redis bounce doesn't permanently disable
    rate limiting, while a hard outage isn't hammered on every request.
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
        logger.debug("Auth rate limiter connected to Redis.")
        return _redis_client
    except Exception as e:
        logger.warning(
            f"Auth rate limiter could not connect to Redis ({e}); "
            f"rate limiting disabled (fail-open), retrying in {_REDIS_RETRY_SECS}s."
        )
        return None


def enforce_rate_limit(request: Request, endpoint: str) -> None:
    """Rate-limit ``endpoint`` per client IP using a Redis fixed window.

    Allows up to ``_RATE_MAX_CALLS`` calls per ``_RATE_WINDOW_SECS`` window per
    ``(client_ip, endpoint)``. Raises HTTP 429 when exceeded.

    FAIL-OPEN: any Redis error (unreachable, timeout) allows the request through
    so an outage cannot lock everyone out of auth.
    """
    client_ip = request.client.host if request.client else "unknown"
    client = _get_redis_client()
    if client is None:
        # Fail open — Redis unavailable.
        return

    # Bucket the window so the key naturally rolls over; INCR then EXPIRE makes
    # the first hit in a window set the TTL.
    window_id = int(time.time()) // _RATE_WINDOW_SECS
    key = f"depictio:ratelimit:{endpoint}:{client_ip}:{window_id}"

    try:
        count = client.incr(key)
        if count == 1:
            # First hit in this window — set expiry so the counter self-cleans.
            client.expire(key, _RATE_WINDOW_SECS)
    except Exception as e:
        # FAIL-OPEN on any Redis error during the check itself.
        logger.warning(f"Auth rate limiter Redis error ({e}); allowing request (fail-open).")
        return

    if int(count) > _RATE_MAX_CALLS:
        logger.warning(
            f"Rate limit exceeded for {endpoint} from {client_ip} "
            f"({count} calls in {_RATE_WINDOW_SECS}s window)."
        )
        raise HTTPException(
            status_code=429,
            detail="Too many authentication requests; please wait before retrying.",
        )
