"""Per-token rate limit on agent tool calls.

A fixed one-minute window in Redis when it is reachable (shared by all API
workers), otherwise a sliding window kept in this process. Unlike the auth
limiter this one never fails fully open: losing Redis falls back to a
per-process limit rather than none.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

_WINDOW_SECS = 60
_local_hits: dict[str, deque[float]] = {}


def _redis_client() -> Any:
    try:
        from depictio.api.v1.endpoints.user_endpoints.rate_limit import _get_redis_client

        return _get_redis_client()
    except Exception:
        return None


def _redis_hit(client: Any, key: str) -> int:
    window_id = int(time.time()) // _WINDOW_SECS
    redis_key = f"depictio:agents:ratelimit:{key}:{window_id}"
    count = client.incr(redis_key)
    if count == 1:
        client.expire(redis_key, _WINDOW_SECS)
    return int(count)


def _local_hit(key: str, now: float) -> int:
    hits = _local_hits.setdefault(key, deque())
    while hits and hits[0] <= now - _WINDOW_SECS:
        hits.popleft()
    hits.append(now)
    return len(hits)


async def allow(key: str, limit: int | None = None) -> bool:
    """Count one call for ``key``; False once it exceeds the per-minute limit."""
    limit = limit if limit is not None else settings.mcp.rate_per_min
    # The first connection attempt pings Redis synchronously; keep it off the loop.
    client = await asyncio.to_thread(_redis_client)
    if client is not None:
        try:
            count = await asyncio.to_thread(_redis_hit, client, key)
            return count <= limit
        except Exception as exc:
            logger.warning(f"agents: rate limiter Redis error ({exc}); using the local window")
    return _local_hit(key, time.monotonic()) <= limit


def reset_local() -> None:
    """Forget the in-process window (tests)."""
    _local_hits.clear()
