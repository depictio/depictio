"""Minimal PostHog capture client.

Deliberately not the ``posthog`` SDK. Everything Depictio sends is a single flat
JSON POST, ``httpx`` is already a dependency of both the API and the CLI wheel,
and the SDK's background queue/threading would be a liability in a
``gunicorn --preload`` worker and pointless in a CLI process that exits
immediately. One function and one POST is the whole requirement.

**This module is the single patch seam for tests.** The repo has no ``respx`` or
``pytest-httpx``, so tests patch :func:`capture` / :func:`acapture` rather than
the HTTP layer underneath. Keep the network call confined to this file so that
stays true.

Both entry points swallow every exception. A telemetry failure is not an
application failure, and an unreachable collector must be indistinguishable from
a healthy one from the caller's point of view.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from depictio.telemetry.constants import DEFAULT_ENDPOINT, DEFAULT_TIMEOUT_SECONDS

logger = logging.getLogger("depictio-telemetry")

__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_TIMEOUT_SECONDS",
    "acapture",
    "build_body",
    "capture",
    "render_for_debug",
]


def build_body(
    event: str,
    distinct_id: str,
    properties: dict[str, Any],
    *,
    api_key: str,
) -> dict[str, Any]:
    """Assemble a PostHog capture body.

    Separated from the send so the admin preview endpoint can render exactly what
    would go over the wire without sending it — the payload an operator inspects
    is then the payload by construction, not a second implementation that could
    drift from it.

    Every event is marked anonymous. Applied here, in the one place all three
    senders (server, CLI, browser) pass through, so it cannot be forgotten at a
    call site.
    """
    return {
        "api_key": api_key,
        "event": event,
        "distinct_id": distinct_id,
        "properties": {
            **properties,
            # Suppresses person-profile creation at the collector. Two reasons:
            # a profile per installation ID would make PostHog hold a person
            # record for every Depictio deployment, which sits badly against
            # what docs/telemetry.md promises operators; and identified events
            # cost up to 4x more than anonymous ones.
            "$process_person_profile": False,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _log_outcome(event: str, response_status: int | None, error: Exception | None) -> bool:
    """Log the result of a send at debug level and report success."""
    if error is not None:
        logger.debug("Telemetry send failed for event %r: %s", event, error)
        return False
    if response_status is not None and response_status >= 400:
        logger.debug("Telemetry send rejected for event %r: HTTP %s", event, response_status)
        return False
    logger.debug("Telemetry event %r accepted", event)
    return True


def capture(
    event: str,
    distinct_id: str,
    properties: dict[str, Any],
    *,
    api_key: str,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Send one event synchronously. Never raises.

    Used by the CLI, which has no event loop and exits straight after.

    Returns:
        True if the collector accepted the event. Callers are not expected to
        care — the return value exists for tests and for the debug log.
    """
    body = build_body(event, distinct_id, properties, api_key=api_key)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(endpoint, json=body)
        return _log_outcome(event, response.status_code, None)
    except Exception as exc:
        return _log_outcome(event, None, exc)


async def acapture(
    event: str,
    distinct_id: str,
    properties: dict[str, Any],
    *,
    api_key: str,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = 1,
) -> bool:
    """Send one event from within an event loop. Never raises.

    Used by the API's heartbeat task. Unlike the CLI path this retries once,
    because the heartbeat's next chance is 24 hours away — a single dropped
    connection would otherwise cost a day of data for that install.

    Args:
        retries: Additional attempts after the first. ``0`` disables retrying.
    """
    body = build_body(event, distinct_id, properties, api_key=api_key)
    last_error: Exception | None = None
    last_status: int | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(retries + 1):
            try:
                response = await client.post(endpoint, json=body)
                last_status = response.status_code
                if response.status_code < 400:
                    return _log_outcome(event, response.status_code, None)
                last_error = None
            except Exception as exc:
                last_error = exc
                last_status = None
            if attempt < retries:
                logger.debug("Retrying telemetry event %r after attempt %d", event, attempt + 1)

    return _log_outcome(event, last_status, last_error)


def render_for_debug(body: dict[str, Any]) -> str:
    """Pretty-print a capture body for the ``debug`` mode log line.

    ``debug`` mode logs what would be sent instead of sending it, so an operator
    can audit the payload on their own deployment before deciding whether to
    leave telemetry enabled.
    """
    redacted = {**body, "api_key": "<redacted>"}
    return json.dumps(redacted, indent=2, sort_keys=True, default=str)
