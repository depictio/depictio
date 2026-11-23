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

import hashlib
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


def _client_ip(request: Request) -> str:
    """The visitor's address.

    Behind the bundled nginx / an ingress the TCP peer is the proxy (a private
    address), so its ``X-Real-IP`` names the visitor. A client reaching the API
    directly has a public peer address and could forge that header to dodge
    per-IP limits, so the header is only honoured from a private or loopback peer.
    """
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-real-ip")
    if forwarded and (peer is None or _is_proxy_peer(peer)):
        return forwarded.strip()
    return peer or "unknown"


def _is_proxy_peer(host: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def _window_key(endpoint: str, scope: str) -> str:
    window_id = int(time.time()) // _RATE_WINDOW_SECS
    return f"depictio:ratelimit:{endpoint}:{scope}:{window_id}"


_LIMITER_UNAVAILABLE = "Sign-in is temporarily unavailable; please retry in a moment."


def _limiter_down(error: Exception | None, *, fail_closed: bool) -> None:
    """Redis is unreachable: let the request through, or refuse it (503)."""
    if fail_closed:
        logger.error(f"Auth rate limiter unavailable ({error}); refusing request (fail-closed).")
        raise HTTPException(status_code=503, detail=_LIMITER_UNAVAILABLE)
    logger.warning(f"Auth rate limiter Redis error ({error}); allowing request (fail-open).")


def enforce_rate_limit(
    request: Request,
    endpoint: str,
    *,
    max_calls: int = _RATE_MAX_CALLS,
    fail_closed: bool = False,
) -> None:
    """Rate-limit ``endpoint`` per client IP using a Redis fixed window.

    Allows up to ``max_calls`` calls per ``_RATE_WINDOW_SECS`` window per
    ``(client_ip, endpoint)``. Raises HTTP 429 when exceeded.

    FAIL-OPEN by default: any Redis error (unreachable, timeout) allows the
    request through so an outage cannot lock everyone out of auth. With
    ``fail_closed`` it is a 503 instead: for a door the whole internet can
    reach (password sign-in on a public instance), unlimited guessing during an
    outage is worse than a sign-in that waits for Redis.
    """
    client_ip = _client_ip(request)
    client = _get_redis_client()
    if client is None:
        _limiter_down(None, fail_closed=fail_closed)
        return

    # Bucket the window so the key naturally rolls over; INCR then EXPIRE makes
    # the first hit in a window set the TTL.
    key = _window_key(endpoint, client_ip)

    try:
        count = client.incr(key)
        if count == 1:
            # First hit in this window — set expiry so the counter self-cleans.
            client.expire(key, _RATE_WINDOW_SECS)
    except Exception as e:
        # Redis error during the check itself: open, unless asked to close.
        _limiter_down(e, fail_closed=fail_closed)
        return

    if int(count) > max_calls:
        logger.warning(
            f"Rate limit exceeded for {endpoint} from {client_ip} "
            f"({count} calls in {_RATE_WINDOW_SECS}s window)."
        )
        raise HTTPException(
            status_code=429,
            detail="Too many authentication requests; please wait before retrying.",
        )


# ---------------------------------------------------------------------------
# Failure-only limits, for a shared secret such as the public access code.
#
# Counting every call would lock out a room of people behind one NAT who all
# type the right code at once; counting only wrong answers slows a guesser
# down without that. The instance-wide bucket also slows a guesser spread over
# many addresses. Same fixed windows and the same fail-open rule as above.
# ---------------------------------------------------------------------------


def _failure_counts(client: Any, endpoint: str, client_ip: str) -> tuple[int, int]:
    per_ip = client.get(_window_key(endpoint, client_ip))
    overall = client.get(_window_key(endpoint, "*"))
    return int(per_ip or 0), int(overall or 0)


def enforce_failure_limit(
    request: Request, endpoint: str, *, max_per_ip: int, max_overall: int
) -> None:
    """Refuse with 429 while this IP, or the whole instance, has failed too often."""
    client = _get_redis_client()
    if client is None:
        return
    client_ip = _client_ip(request)
    try:
        per_ip, overall = _failure_counts(client, endpoint, client_ip)
    except Exception as e:
        logger.warning(f"Auth rate limiter Redis error ({e}); allowing request (fail-open).")
        return
    if per_ip >= max_per_ip or overall >= max_overall:
        logger.warning(
            f"Failure limit reached for {endpoint} from {client_ip} "
            f"({per_ip} from this address, {overall} in all, in {_RATE_WINDOW_SECS}s)."
        )
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts; please wait a minute before retrying.",
        )


def record_failure(request: Request, endpoint: str) -> None:
    """Count one failed attempt for this IP and for the whole instance."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        for scope in (_client_ip(request), "*"):
            key = _window_key(endpoint, scope)
            if client.incr(key) == 1:
                client.expire(key, _RATE_WINDOW_SECS)
    except Exception as e:
        logger.warning(f"Auth rate limiter Redis error ({e}); failure not counted.")


# ---------------------------------------------------------------------------
# Per-account lockout, for password sign-in on a public instance.
#
# The per-IP limit above does not stop a guesser spread over many addresses
# from working on one known email (the admin's). This counts wrong passwords
# per account, whatever the address: after ``_LOCKOUT_MAX_FAILURES`` within
# ``_LOCKOUT_WINDOW_SECS`` that account's password sign-in is refused until the
# window ends. Someone can therefore lock an admin out for a window by failing
# on purpose; single sign-on is not affected. The email is hashed so keys never
# hold an address.
# ---------------------------------------------------------------------------

_LOCKOUT_WINDOW_SECS = 15 * 60
_LOCKOUT_MAX_FAILURES = 5


def _lockout_key(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"depictio:lockout:login:{digest}"


def enforce_account_lockout(email: str, *, fail_closed: bool = False) -> None:
    """Refuse (401, as a wrong password would) while this account is locked."""
    client = _get_redis_client()
    if client is None:
        _limiter_down(None, fail_closed=fail_closed)
        return
    try:
        failures = int(client.get(_lockout_key(email)) or 0)
    except Exception as e:
        _limiter_down(e, fail_closed=fail_closed)
        return
    if failures >= _LOCKOUT_MAX_FAILURES:
        logger.warning("Password sign-in refused: account locked after repeated failures.")
        # Same answer as a wrong password: a distinct one would confirm that the
        # email has an account.
        raise HTTPException(status_code=401, detail="Invalid credentials")


def record_account_failure(email: str) -> None:
    """Count one wrong password for this account."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        key = _lockout_key(email)
        if client.incr(key) == 1:
            client.expire(key, _LOCKOUT_WINDOW_SECS)
    except Exception as e:
        logger.warning(f"Auth rate limiter Redis error ({e}); failure not counted.")


def clear_account_failures(email: str) -> None:
    """A successful sign-in starts the count again."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.delete(_lockout_key(email))
    except Exception as e:
        logger.warning(f"Auth rate limiter Redis error ({e}); failures not cleared.")
