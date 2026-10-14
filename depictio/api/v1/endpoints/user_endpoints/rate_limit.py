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

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.redis_client import get_shared_redis_client

# Fixed-window parameters. Kept conservative — these endpoints are
# human-driven (login / register / temp-user mint), not high-throughput.
_RATE_WINDOW_SECS = 60
_RATE_MAX_CALLS = 10


def _get_redis_client() -> Any:
    """Return the shared Redis client, or ``None`` (fail open) if unavailable."""
    return get_shared_redis_client()


def enforce_rate_limit(request: Request, endpoint: str) -> None:
    """Rate-limit ``endpoint`` per client IP using a Redis fixed window.

    Allows up to ``_RATE_MAX_CALLS`` calls per ``_RATE_WINDOW_SECS`` window per
    ``(client_ip, endpoint)``. Raises HTTP 429 when exceeded.

    FAIL-OPEN: any Redis error (unreachable, timeout) allows the request through
    so an outage cannot lock everyone out of auth.
    """
    # Prefer X-Real-IP forwarded by the nginx reverse-proxy over the raw TCP
    # connection source, which would be the nginx pod IP in k8s (causing all
    # visitors to share one rate-limit bucket).
    client_ip = (
        request.headers.get("x-real-ip")
        or (request.client.host if request.client else None)
        or "unknown"
    )
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
