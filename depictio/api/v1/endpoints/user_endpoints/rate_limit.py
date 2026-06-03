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

from fastapi import HTTPException, Request

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# Optional Redis import — graceful degradation if the package is missing.
try:
    import redis as _redis

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - redis is a stack dependency
    _redis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False


# Fixed-window parameters. Kept conservative — these endpoints are
# human-driven (login / register / temp-user mint), not high-throughput.
_RATE_WINDOW_SECS = 60
_RATE_MAX_CALLS = 10

# Lazily-initialised shared Redis client (one per worker process).
_redis_client: "_redis.Redis | None" = None  # type: ignore[name-defined]
_redis_init_attempted = False


def _get_redis_client() -> "_redis.Redis | None":  # type: ignore[name-defined]
    """Return a shared Redis client, or ``None`` if Redis is unavailable.

    Reuses ``settings.cache`` connection details (same Redis instance used by
    the DataFrame cache). Connection failures are swallowed here; callers must
    treat ``None`` as "fail open".
    """
    global _redis_client, _redis_init_attempted

    if _redis_client is not None:
        return _redis_client

    if _redis_init_attempted:
        # We already tried and failed; don't hammer Redis on every request.
        return None

    _redis_init_attempted = True

    if not _REDIS_AVAILABLE:
        logger.warning("Redis package unavailable — auth rate limiting is disabled (fail-open).")
        return None

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
            "rate limiting disabled (fail-open)."
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
