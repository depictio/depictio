"""Retry policy for CLI → API requests.

The CLI has had no retries at all: a single dropped connection during a scan
aborts the run. That was survivable while every invocation was a human typing
``depictio run``; it is not survivable for a watcher that stays up for weeks and
will certainly outlive several API restarts.

**Why hand-rolled rather than ``tenacity``.** The CLI ships as a standalone
wheel with its own lockfile into HPC and conda environments where every
transitive dependency is an install-surface and a support burden. The policy
below is fifty lines, and the part that actually matters — deciding which
endpoints may be retried — is depictio-specific and would have to be written
either way.

**Idempotency is the load-bearing decision here.** Retrying is only safe when a
duplicate request is indistinguishable from a single one:

===========================================  ===========  ==========================
Endpoint                                     Retryable?   Why
===========================================  ===========  ==========================
``GET`` anything                             yes          no side effects
``POST /files/upsert_batch``                 yes          upsert keyed on location
``POST /runs/upsert_batch``                  yes          upsert keyed on run tag
``DELETE /files|runs/delete/{id}``           yes          delete by id is idempotent
``POST /deltatables/upsert``                 **no**       appends an Aggregation
===========================================  ===========  ==========================

That last row is the trap. ``upsert_deltatable`` *appends* to
``DeltaTableAggregated.aggregation`` and derives the next version from
``aggregation[-1].aggregation_version + 1``, so a blind retry after a read
timeout creates a duplicate aggregation entry and a phantom version bump — and
``aggregation_version`` salts the API's dataframe cache keys, so the damage
shows up later as silently invalidated caches rather than as an error.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from depictio.cli.cli_logging import logger

#: Statuses worth another attempt: transient overload, upstream hiccups, and the
#: rate-limit signal. Deliberately excludes 4xx that describe the request itself
#: (400, 401, 403, 404, 409, 413, 422) — retrying those just burns time.
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Exceptions where the request provably never reached the server, so replaying
#: it cannot duplicate a side effect regardless of the endpoint's semantics.
_NEVER_DELIVERED = (httpx.ConnectError, httpx.ConnectTimeout)

#: Exceptions where the request may or may not have been processed. Only safe to
#: replay against an idempotent endpoint.
_MAYBE_DELIVERED = (
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Seconds requested by the server, if it asked for a specific delay."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        # Only the delta-seconds form is honoured; the HTTP-date form is rare in
        # practice and not worth the parsing surface.
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


def _backoff_delay(attempt: int, base: float, maximum: float, jitter: float) -> float:
    """Exponential backoff with proportional jitter, so a fleet of watchers
    retrying after the same outage does not resynchronise into a thundering herd.
    """
    delay = min(maximum, base * (2**attempt))
    return delay * (1.0 + random.uniform(-jitter, jitter))


def request_with_retry(
    method: str,
    url: str,
    *,
    timeout: float,
    retries: int = 3,
    backoff_base: float = 0.5,
    backoff_max: float = 8.0,
    jitter: float = 0.2,
    idempotent: bool = True,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Issue a request, retrying transient failures.

    Args:
        idempotent: Whether replaying this request is safe. When ``False``, only
            failures that provably never reached the server are retried; a read
            timeout or a 5xx is returned/raised as-is, because the server may
            already have applied the change.
        retries: Additional attempts after the first. ``0`` disables retrying.
        client: Defaults to the process-wide pooled client.
        sleep: Injectable for tests.

    Returns the final response, including a non-2xx one once attempts are
    exhausted — callers keep their existing status-code handling. Transport
    errors are re-raised after the last attempt.
    """
    # Imported lazily: common.py imports rich_utils, which imports polars.
    from depictio.cli.cli.utils.common import get_http_client

    http_client = client or get_http_client()
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        is_last = attempt == retries
        try:
            response = http_client.request(method, url, timeout=timeout, **kwargs)
        except _NEVER_DELIVERED as exc:
            last_exc = exc
            if is_last:
                raise
            delay = _backoff_delay(attempt, backoff_base, backoff_max, jitter)
            logger.warning(
                f"{method} {url} could not connect ({exc.__class__.__name__}); "
                f"retrying in {delay:.1f}s ({attempt + 1}/{retries})"
            )
            sleep(delay)
            continue
        except _MAYBE_DELIVERED as exc:
            last_exc = exc
            if is_last or not idempotent:
                raise
            delay = _backoff_delay(attempt, backoff_base, backoff_max, jitter)
            logger.warning(
                f"{method} {url} failed mid-flight ({exc.__class__.__name__}); "
                f"retrying in {delay:.1f}s ({attempt + 1}/{retries})"
            )
            sleep(delay)
            continue

        if response.status_code not in RETRYABLE_STATUS or is_last or not idempotent:
            return response

        delay = _parse_retry_after(response)
        if delay is None:
            delay = _backoff_delay(attempt, backoff_base, backoff_max, jitter)
        logger.warning(
            f"{method} {url} returned {response.status_code}; "
            f"retrying in {delay:.1f}s ({attempt + 1}/{retries})"
        )
        sleep(delay)

    # Unreachable: the loop either returns a response or raises on the last
    # attempt. Kept so the function has no implicit None return.
    raise last_exc if last_exc else RuntimeError(f"{method} {url} exhausted retries")
