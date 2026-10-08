"""Client for the server-side job protocol (``/depictio/api/v1/jobs``).

Submit-and-poll, so a long aggregation is no longer bounded by an HTTP timeout.
The design constraint that shapes everything here: **the absence of a
``job_id`` in a response means the work is already done**. That is what makes a
new CLI safe against an old server — the server ignores ``async_mode``, does
the work inline, and the client simply never enters the polling loop.

Deliberately no overall timeout by default. Escaping the timeout is the entire
point of the protocol; re-imposing one here would reintroduce the failure we
set out to remove. ``overall_timeout`` exists for CI, where a hung job should
fail the pipeline rather than block it forever.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from depictio.cli.cli.utils.common import get_http_client
from depictio.cli.cli.utils.http_retry import request_with_retry
from depictio.cli.cli_logging import logger

# Terminal states, mirrored from depictio.models.models.jobs. Not imported:
# the CLI wheel does not depend on the API package, and a three-element
# frozenset is not worth coupling the two.
TERMINAL_STATES = frozenset({"success", "failed", "cancelled"})

DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_MAX_INTERVAL = 15.0


@dataclass(slots=True)
class JobOutcome:
    """Result of waiting on a job."""

    status: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    job_id: Optional[str] = None
    result_truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "success"


class JobPollError(RuntimeError):
    """Polling could not be completed (transport, auth, or timeout)."""


def poll_job(
    job_id: str,
    *,
    api_base_url: str,
    token: str,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_interval: float = DEFAULT_MAX_INTERVAL,
    overall_timeout: Optional[float] = None,
    on_update: Optional[Callable[[dict[str, Any]], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> JobOutcome:
    """Poll until the job reaches a terminal state.

    The interval is server-driven when the server offers one
    (``poll_after_seconds``) and backs off geometrically otherwise, capped at
    ``max_interval``. Honouring the server's hint is what lets a loaded
    deployment slow a fleet of watchers down without each of them guessing.

    ``on_update`` is called with each non-terminal status payload; it is the
    bridge to the CLI's live step reporting. An exception raised inside it is
    swallowed — telemetry must never abort an ingestion.
    """
    client = get_http_client()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{api_base_url}/depictio/api/v1/jobs/{job_id}"

    interval = poll_interval
    deadline = None if overall_timeout is None else time.monotonic() + overall_timeout
    last_status: Optional[str] = None

    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise JobPollError(
                f"Job {job_id} did not finish within {overall_timeout:.0f}s "
                f"(last status: {last_status or 'unknown'})"
            )

        try:
            response = request_with_retry(
                "GET",
                url,
                headers=headers,
                timeout=30.0,
                idempotent=True,
                client=client,
            )
        except httpx.HTTPError as exc:
            raise JobPollError(f"Failed to poll job {job_id}: {exc}") from exc

        if response.status_code == 404:
            # Either the job expired out from under us (TTL) or this server
            # has no /jobs at all. Both are unrecoverable for the caller, and
            # both mean the same thing operationally: stop waiting.
            raise JobPollError(
                f"Job {job_id} is unknown to the server (expired, or jobs are disabled)"
            )
        if response.status_code != 200:
            raise JobPollError(f"Polling job {job_id} returned HTTP {response.status_code}")

        payload = response.json()
        status = payload.get("status", "pending")

        if status in TERMINAL_STATES:
            return JobOutcome(
                status=status,
                result=payload.get("result"),
                error=payload.get("error"),
                job_id=job_id,
                result_truncated=bool(payload.get("result_truncated")),
            )

        if status != last_status or payload.get("step"):
            if on_update is not None:
                try:
                    on_update(payload)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug(f"job poll on_update hook raised: {exc}")
        last_status = status

        server_hint = payload.get("poll_after_seconds")
        if isinstance(server_hint, (int, float)) and server_hint > 0:
            interval = min(float(server_hint), max_interval)
        else:
            interval = min(interval * 1.5, max_interval)
        sleep(interval)


def maybe_wait_for_job(
    response_payload: dict[str, Any],
    *,
    api_base_url: str,
    token: str,
    on_update: Optional[Callable[[dict[str, Any]], None]] = None,
    overall_timeout: Optional[float] = None,
) -> Optional[JobOutcome]:
    """Wait on a job if the response opened one, else return ``None``.

    This is the whole forward/backward-compatibility contract in one function:
    a response without ``job_id`` came from a server that did the work inline
    (either an older build, or a newer one with offloading switched off), so
    there is nothing to wait for and the caller uses the payload as-is.
    """
    job_id = response_payload.get("job_id")
    if not job_id:
        return None
    logger.debug(f"Server accepted work as job {job_id}; polling until complete")
    return poll_job(
        job_id,
        api_base_url=api_base_url,
        token=token,
        on_update=on_update,
        overall_timeout=overall_timeout,
    )


def cancel_job(job_id: str, *, api_base_url: str, token: str) -> bool:
    """Best-effort cancel, used on Ctrl-C so a killed CLI does not orphan work."""
    try:
        response = request_with_retry(
            "POST",
            f"{api_base_url}/depictio/api/v1/jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
            # Cancelling twice is harmless (the second call sees a terminal
            # job and returns it unchanged), so a retry is safe here.
            idempotent=True,
            retries=1,
            client=get_http_client(),
        )
        return response.status_code == 200
    except Exception as exc:
        logger.debug(f"Best-effort cancel of job {job_id} failed: {exc}")
        return False
