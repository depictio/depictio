"""The heartbeat loop and its lifespan entry point.

Deliberately *not* gated on the ``should_initialize`` flag that every other
``start_*`` service in ``services/lifespan.py`` uses. That flag is true only on the
very first boot of a deployment — ``check_and_set_initialization`` returns False for
every worker once an ``initialization_complete`` document exists — so gating on it
would send telemetry once in an installation's lifetime and then go quiet forever,
with nothing to indicate anything was wrong. Instead every worker runs this loop
and :mod:`depictio.api.v1.telemetry.guard` collapses them to one send per day.
"""

import asyncio
from typing import Final

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.telemetry.guard import claim_send, ensure_guard_index
from depictio.api.v1.telemetry.payload import build_heartbeat_properties
from depictio.telemetry.gates import telemetry_allowed
from depictio.telemetry.posthog import acapture, build_body, render_for_debug
from depictio.telemetry.schema import EVENT_HEARTBEAT, EVENT_INSTALL

#: Delay before the first iteration. Startup work on the boot path has previously
#: blocked worker readiness and got workers killed by gunicorn — see the
#: equivalent pre-sleep in ``tasks/cleanup_tasks.py``. Telemetry is the last thing
#: that should ever cost a worker its health check.
FIRST_RUN_DELAY_SECONDS: Final[int] = 60


def suppression_reason() -> str | None:
    """Why telemetry is off right now, or ``None`` if it is on."""
    reason = telemetry_allowed(
        enabled=settings.telemetry.enabled,
        wipe=settings.mongodb.wipe,
    )
    if reason is not None:
        return reason.value
    if not settings.telemetry.api_key and not settings.telemetry.debug:
        # No collector configured. Not a suppression the operator chose, but the
        # outcome is the same and saying so beats silence.
        return "no_api_key_configured"
    return None


def log_telemetry_status() -> None:
    """State plainly, once per worker at boot, whether telemetry is on.

    Telemetry that defaults to enabled has to be visible. An operator who never
    reads the docs should still learn from their own logs that it is happening and
    how to stop it.
    """
    reason = suppression_reason()
    if reason is None:
        logger.info(
            "Anonymous installation telemetry is ENABLED "
            "(no personal data; see docs/telemetry.md). "
            "Disable with DEPICTIO_TELEMETRY_ENABLED=false or DO_NOT_TRACK=1."
        )
    else:
        logger.info("Anonymous installation telemetry is disabled (%s).", reason)


async def _send(event: str, *, daily: bool) -> None:
    """Claim, build and send one event. Never raises."""
    if not claim_send(event, daily=daily):
        return

    instance_id, properties = build_heartbeat_properties()
    props = properties.model_dump(mode="json", exclude_none=True)

    if settings.telemetry.debug:
        # Rendered through the same builder the real send uses, so what an operator
        # audits here is byte-for-byte what would have gone out.
        body = build_body(event, instance_id, props, api_key=settings.telemetry.api_key)
        logger.info("Telemetry (debug mode, not sent) %s:\n%s", event, render_for_debug(body))
        return

    await acapture(
        event,
        instance_id,
        props,
        api_key=settings.telemetry.api_key,
        endpoint=settings.telemetry.endpoint,
    )


async def periodic_telemetry_heartbeat() -> None:
    """Send the install event once, then a heartbeat at most once per UTC day.

    Runs in every worker; the guard decides which one actually sends. Wrapped so
    that no failure — MongoDB down, collector unreachable, a bug in the payload
    builder — can take the task down and silently end telemetry for the process's
    lifetime.
    """
    interval_seconds = settings.telemetry.interval_hours * 3600

    await asyncio.sleep(FIRST_RUN_DELAY_SECONDS)

    ensure_guard_index()

    while True:
        try:
            if suppression_reason() is None:
                # Undated guard: fires exactly once per installation, ever.
                await _send(EVENT_INSTALL, daily=False)
                await _send(EVENT_HEARTBEAT, daily=True)
        except Exception as exc:
            logger.debug("Telemetry: heartbeat iteration failed: %s", exc)

        await asyncio.sleep(interval_seconds)


def start_telemetry() -> None:
    """Start the heartbeat task. Never fails boot.

    Mirrors ``start_monitoring_storage`` in ``services/lifespan.py`` — settings
    gated, fully try/excepted — except that it runs in every worker rather than
    only the initializing one, for the reason in this module's docstring.
    """
    log_telemetry_status()

    if suppression_reason() is not None:
        return

    try:
        asyncio.create_task(periodic_telemetry_heartbeat())
    except Exception as exc:
        logger.warning("Telemetry: could not start heartbeat task: %s", exc)
