"""Shared one-shot state store for browser SSO flows (OAuth state, SAML request IDs).

The previous OAuth implementation kept the anti-CSRF ``state`` in a per-process
dict, which breaks as soon as the login and the callback land on different
gunicorn workers or replicas. This store is Redis-backed (shared across
workers/pods) with an in-process fallback so single-worker dev setups and unit
tests keep working without Redis.

FALLBACK, NOT FAIL-CLOSED: if Redis is unreachable we log a warning and use the
in-process dict — login then only succeeds when both legs of the flow hit the
same worker, which mirrors the rate limiter's availability-over-strictness
posture on auth paths.
"""

from __future__ import annotations

import time

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.redis_client import get_shared_redis_client

_STATE_TTL_SECONDS = 600  # 10 minutes, matches the historical OAuth state expiry
_KEY_PREFIX = "depictio:authstate"

# In-process fallback: {(kind, key): (value, expiry_monotonic)}
_local_states: dict[tuple[str, str], tuple[str, float]] = {}


def _redis_key(kind: str, key: str) -> str:
    return f"{_KEY_PREFIX}:{kind}:{key}"


def _prune_local() -> None:
    now = time.monotonic()
    for k in [k for k, (_, expiry) in _local_states.items() if expiry < now]:
        del _local_states[k]


def store_auth_state(
    kind: str, key: str, value: str = "1", ttl_seconds: int = _STATE_TTL_SECONDS
) -> None:
    """Store a one-shot auth state (OAuth ``state``, SAML AuthnRequest ID)."""
    client = get_shared_redis_client()
    if client is not None:
        try:
            client.set(_redis_key(kind, key), value, ex=ttl_seconds, nx=True)
            return
        except Exception as e:
            logger.warning(f"Auth state store Redis error ({e}); using in-process fallback.")
    else:
        logger.warning(
            "Auth state store: Redis unavailable, using in-process fallback "
            "(SSO logins only succeed when both flow legs hit the same worker)."
        )
    _prune_local()
    _local_states[(kind, key)] = (value, time.monotonic() + ttl_seconds)


def consume_auth_state(kind: str, key: str) -> str | None:
    """Atomically fetch-and-delete a state; ``None`` if unknown, used, or expired.

    Checks the in-process fallback too, so a state stored during a Redis outage
    (or in tests) still redeems.
    """
    if not key:
        return None

    value: str | None = None
    client = get_shared_redis_client()
    if client is not None:
        try:
            value = client.getdel(_redis_key(kind, key))
        except Exception as e:
            logger.warning(f"Auth state store Redis error on consume ({e}).")

    if value is None:
        _prune_local()
        local = _local_states.pop((kind, key), None)
        if local is not None:
            value = local[0]

    return value
