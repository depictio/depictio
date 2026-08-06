"""Records which ``depictio-cli`` versions talk to this instance.

This is the cheap half of CLI telemetry. The CLI already tags every API request
with identity headers — ``generate_api_headers`` in ``cli/cli/utils/common.py``
sends them and ``monitoring_endpoints/routes.py`` already reads two of them for
ingestion records — so adding a version header costs the user no extra network
call, works even when the CLI's own outbound telemetry is disabled, and tells us
what actually matters: which CLI versions are in live use against which server
versions.

Only the version string is kept. The CLI also sends ``X-Depictio-CLI-Host``, which
is a real hostname; it stays in the operator's own database where it is already
used for admin monitoring, and is deliberately never read here.

Versions are stored as a bounded set on a single document, with a timestamp per
version so stale entries age out. That keeps this to one cheap upsert per request
rather than a growing per-request log.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Final

from depictio.api.v1.configs.logging_init import logger

#: Document holding the observed-version map.
CLI_VERSIONS_DOC_ID: Final[str] = "cli_versions"

#: Versions unseen for longer than this drop out of the heartbeat.
RETENTION_DAYS: Final[int] = 30

#: Versions must look like a version. An unvalidated header is attacker-controlled
#: free text, and this value ends up in an outbound payload — so it is matched
#: against a strict pattern rather than sanitised, and dropped if it does not fit.
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z.]{1,20})?$"
)

#: Guards against a malformed client filling the document with junk keys.
MAX_TRACKED_VERSIONS: Final[int] = 50


def _is_plausible_version(value: str) -> bool:
    """Whether a header value is safe to store and later transmit."""
    return bool(_VERSION_RE.match(value))


def record_cli_version(version: str | None) -> None:
    """Note that ``version`` of the CLI contacted this instance. Never raises.

    Called from the request path, so it must stay cheap and must never surface an
    error to the caller: a telemetry bookkeeping failure is not a reason to fail a
    user's CLI command.
    """
    if not version:
        return

    candidate = version.strip()
    if not _is_plausible_version(candidate):
        logger.debug("Telemetry: ignoring implausible CLI version header %r", candidate[:32])
        return

    from depictio.api.v1.db import telemetry_collection

    try:
        # MongoDB keys cannot contain dots, so the version is stored with dots
        # replaced. Reversed on read.
        key = candidate.replace(".", "_")
        telemetry_collection.update_one(
            {"_id": CLI_VERSIONS_DOC_ID},
            {"$set": {f"versions.{key}": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception as exc:
        logger.debug("Telemetry: could not record CLI version: %s", exc)


def read_cli_versions(*, limit: int = 10) -> list[str]:
    """Recently seen CLI versions, most recent first. Never raises."""
    from depictio.api.v1.db import telemetry_collection

    try:
        doc = telemetry_collection.find_one({"_id": CLI_VERSIONS_DOC_ID})
    except Exception as exc:
        logger.debug("Telemetry: could not read CLI versions: %s", exc)
        return []

    if not doc:
        return []

    versions = doc.get("versions")
    if not isinstance(versions, dict):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    fresh: list[tuple[datetime, str]] = []
    for key, last_seen in list(versions.items())[:MAX_TRACKED_VERSIONS]:
        # Both come straight out of MongoDB, so neither type is guaranteed —
        # a hand-edited document could hold anything.
        if not isinstance(key, str) or not isinstance(last_seen, datetime):
            continue
        seen_at = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=timezone.utc)
        if seen_at < cutoff:
            continue
        restored = key.replace("_", ".")
        # Re-validate on the way out: the document could have been written by an
        # older, laxer version of this code, and this value is about to be sent.
        if _is_plausible_version(restored):
            fresh.append((seen_at, restored))

    fresh.sort(reverse=True)
    return [version for _, version in fresh[:limit]]
