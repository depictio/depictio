"""Shared timestamp helpers.

Depictio stores wall-clock timestamps as naive strings formatted
``"%Y-%m-%d %H:%M:%S"``. Historically these were produced with
``datetime.now()``, i.e. in the *server's* local timezone, which made the
stored value ambiguous (UTC in Docker, CEST on a developer laptop) and left
the frontend no way to render them in the viewer's timezone.

Everything now goes through :func:`utc_now_str`, so stored timestamps are
always UTC. Clients (see ``viewer/src/dashboards/lib/format.ts``) parse naive
strings as UTC and render them in the user's local timezone.
"""

from datetime import datetime, timezone

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def utc_now_str() -> str:
    """Current UTC time as a naive ``"%Y-%m-%d %H:%M:%S"`` string."""
    return utc_now().strftime(TIMESTAMP_FORMAT)


def objectid_creation_str(oid) -> str:
    """Best-effort creation timestamp (UTC) derived from a MongoDB ObjectId.

    Used as a fallback for documents created before ``creation_time`` was
    stored explicitly: every ObjectId embeds its generation time.

    Returns ``""`` when the embedded time is in the future, which means the id
    was hand-written rather than generated (Depictio's seed data uses literal
    ids like ``746b0f3c...``, whose 4-byte prefix decodes to 2031). Callers
    then fall back rather than showing a nonsensical creation date.
    """
    try:
        from bson import ObjectId

        if not isinstance(oid, ObjectId):
            oid = ObjectId(str(oid))
        generated = oid.generation_time.astimezone(timezone.utc)
        if generated > utc_now():
            return ""
        return generated.strftime(TIMESTAMP_FORMAT)
    except Exception:
        return ""


def preserved_creation_time(existing: dict | None, oid, fallback: str = "") -> str:
    """Resolve the creation timestamp to persist for a document being written.

    ``creation_time`` / ``registration_time`` are **write-once**: clients
    round-trip the whole document, so trusting the incoming payload would let a
    save clobber (or invent) the creation date and make the "created" and
    "modified" columns show the same value (issue #932).

    Resolution order:
      1. the value already stored on the existing document,
      2. the ObjectId's embedded generation time (covers documents written
         before the field existed),
      3. ``fallback`` (normally the current save's timestamp, for brand-new
         documents that have no history to preserve).
    """
    stored = (existing or {}).get("creation_time") or (existing or {}).get("registration_time")
    if stored:
        return str(stored)
    return objectid_creation_str(oid) or fallback
