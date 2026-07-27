"""Telemetry constants with no third-party imports.

Split out from :mod:`depictio.telemetry.posthog` so that
``depictio/api/v1/configs/settings_models.py`` can use the default endpoint as a
field default without pulling ``httpx`` into the config module — that module is
the earliest thing imported in every context and is deliberately free of
dependencies beyond pydantic.
"""

from typing import Final

#: PostHog Cloud EU ingestion endpoint. The EU region keeps event data inside the
#: EEA, which matters for an EMBL-affiliated project even though nothing sent is
#: personal data.
DEFAULT_ENDPOINT: Final[str] = "https://eu.i.posthog.com/i/v0/e/"

#: Total budget for a send, including connect. Short on purpose: a slow collector
#: must never hold a CLI process open or occupy an event-loop task for long.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0

#: Tighter budget for the CLI, which sends on the way out of a user's command.
CLI_TIMEOUT_SECONDS: Final[float] = 2.0
