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

#: Depictio's own PostHog project token (EU cloud, project 232364).
#:
#: Committed deliberately. A PostHog *project* token is a public, write-only
#: ingestion key — it is embedded in the page source of every website using
#: PostHog, grants no read access, and cannot query anything. It is not a secret,
#: and it has to ship inside the artifacts for telemetry to work at all: no
#: operator is going to set the Depictio project's key by hand.
#:
#: Not to be confused with a PostHog *personal* API key, which does grant read
#: access and must never appear in this repository.
DEFAULT_API_KEY: Final[str] = "phc_Auxev6EYhAUhApdp9QXRfGUWFhti3mgVjyowXjpmcgQw"

#: Total budget for a send, including connect. Short on purpose: a slow collector
#: must never hold a CLI process open or occupy an event-loop task for long.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0

#: Tighter budget for the CLI, which sends on the way out of a user's command.
CLI_TIMEOUT_SECONDS: Final[float] = 2.0
