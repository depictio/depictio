"""Send-once coordination across workers and replicas.

A Depictio API runs ``gunicorn --workers 4 --preload`` by default, and Kubernetes
may run several replicas on top of that — a dozen or more processes, each with its
own event loop and its own copy of the heartbeat task. Without coordination a
single installation would report a dozen heartbeats a day and the "installations"
metric would really be measuring worker counts.

The obvious fix — only run the task on the worker that won the initialization
election — does not work, and would fail silently. ``check_and_set_initialization``
returns ``False`` for *every* worker once an ``initialization_complete`` document
exists, so after the very first boot of a deployment there is no elected worker at
all. Gating on it would send telemetry exactly once in an installation's lifetime.

So every worker runs the loop, and correctness lives here instead: before sending,
a process tries to insert a guard document whose ``_id`` encodes the event and the
UTC date. Exactly one insert can succeed; everyone else gets a
:class:`~pymongo.errors.DuplicateKeyError` and skips. Whichever process happens to
wake first that day does the send, so a replica dying mid-day costs nothing.

Daily guard documents expire via a TTL index so the collection cannot grow without
bound. The one-off install guard is undated and never expires: it is the only
thing standing between a long-lived deployment and re-reporting itself as a new
installation on every TTL period.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Final

from pymongo.errors import DuplicateKeyError, OperationFailure

from depictio.api.v1.configs.logging_init import logger

#: How long *daily* guard documents are kept. Only needs to outlive one send
#: interval; a week leaves plenty of slack for a clock skew or a long outage.
GUARD_TTL_SECONDS: Final[int] = 7 * 24 * 3600

_TTL_INDEX_NAME: Final[str] = "telemetry_guard_ttl"


def ensure_guard_index() -> None:
    """Create the TTL index on guard documents. Never raises.

    ``expireAfterSeconds=0`` does not mean "expire immediately". It selects
    MongoDB's expire-at-a-timestamp mode, where a document is removed once the
    indexed date field is in the past — so the lifetime lives in the value written
    by :func:`claim_send`, not here. Getting that backwards silently un-guards
    every send, which is the failure this subsystem can least afford.

    Only *daily* guard documents carry ``guard_expires_at``. The identity document
    and the undated install guard do not, and MongoDB's TTL monitor ignores
    documents where the indexed field is missing — so neither is ever expired by
    this index, which is what keeps them permanent.
    """
    from depictio.api.v1.db import telemetry_collection

    try:
        telemetry_collection.create_index(
            "guard_expires_at",
            name=_TTL_INDEX_NAME,
            expireAfterSeconds=0,
        )
    except OperationFailure as exc:
        # An index with the same name but different options already exists, or the
        # user lacks index privileges. Neither is worth failing a boot over — the
        # guard documents simply accumulate, a few dozen bytes a day.
        logger.debug("Telemetry: could not ensure guard TTL index: %s", exc)
    except Exception as exc:
        logger.debug("Telemetry: unexpected error ensuring guard TTL index: %s", exc)


def _guard_id(event: str, *, daily: bool) -> str:
    """Build the guard document ID for an event.

    Daily events include the UTC date, so a new guard becomes available each day.
    Non-daily events (the one-time install event) omit it, so the guard can only
    ever be claimed once per installation.
    """
    if not daily:
        return f"send:{event}"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"send:{event}:{today}"


def claim_send(event: str, *, daily: bool = True) -> str | None:
    """Try to claim the right to send ``event``.

    Returns:
        The guard ID claimed, for :func:`release_send` to give back if the send
        fails. ``None`` if another process already holds it, or if MongoDB is
        unreachable — declining to send is the safe failure, as a missed heartbeat
        costs one data point whereas a duplicate corrupts the installation count.

        The ID is returned rather than recomputed later because a daily ID embeds
        today's date: a send that starts at 23:59 and fails at 00:00 would
        otherwise release *tomorrow's* guard, freeing a day that has already been
        reported.
    """
    from depictio.api.v1.db import telemetry_collection

    now = datetime.now(timezone.utc)
    guard_id = _guard_id(event, daily=daily)
    document: dict[str, Any] = {
        "_id": guard_id,
        "sent_at": now,
    }

    if daily:
        # The TTL index above uses expireAfterSeconds=0, which is MongoDB's
        # "expire *at* the indexed timestamp" idiom — so this field must be the
        # expiry moment, not the write moment. Writing `now` here made every guard
        # eligible for deletion the instant it was created, and the TTL monitor
        # removed it within a minute: heartbeats could then repeat within a day,
        # inflating the very installation count this guard exists to keep honest.
        #
        # Its presence is also what marks a document as a disposable guard rather
        # than a durable one, which carries no such field.
        document["guard_expires_at"] = now + timedelta(seconds=GUARD_TTL_SECONDS)

    try:
        telemetry_collection.insert_one(document)
        return guard_id
    except DuplicateKeyError:
        logger.debug("Telemetry: %r already sent for this period, skipping", event)
        return None
    except Exception as exc:
        logger.debug("Telemetry: could not claim send for %r: %s", event, exc)
        return None


def release_send(guard_id: str) -> None:
    """Give back a claim whose send did not go through. Never raises.

    Takes the ID :func:`claim_send` returned, never a recomputed one: see the note
    there about a send that straddles UTC midnight.

    A claim is taken *before* the network call, so that concurrent workers settle
    the "who sends" question without waiting on a collector. The cost is that a
    failed send would otherwise burn the claim: one lost data point for the daily
    heartbeat, but for the undated install event — which no longer expires — the
    installation would never be counted at all. An air-gapped or firewalled
    deployment is exactly the case where the first send fails, so releasing lets
    the next iteration try again.
    """
    from depictio.api.v1.db import telemetry_collection

    try:
        telemetry_collection.delete_one({"_id": guard_id})
    except Exception as exc:
        # Nothing to do about it: the send already failed, and the next period's
        # guard is a different key anyway.
        logger.debug("Telemetry: could not release the claim %r: %s", guard_id, exc)


def has_sent(event: str, *, daily: bool = True) -> bool:
    """Whether ``event`` has already been sent for the current period.

    A read-only check for the admin preview endpoint, so inspecting the payload
    never consumes the day's guard and suppresses the real send.
    """
    from depictio.api.v1.db import telemetry_collection

    try:
        return telemetry_collection.find_one({"_id": _guard_id(event, daily=daily)}) is not None
    except Exception:
        return False
