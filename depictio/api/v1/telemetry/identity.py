"""The anonymous installation identity.

One random UUID per Depictio installation, created on first use and stored in the
dedicated ``telemetry`` collection. It is the only thing that makes an install
*countable*: without a stable ID, a restart is indistinguishable from a new
deployment and every metric becomes a process count.

It lives in its own collection rather than in ``initialization`` on purpose. The
wipe path in ``services/lifespan.py`` deletes everything except the init lock out
of ``initialization``, so an identity kept there would be regenerated on every
developer wipe — quietly inflating the project's installation count with phantom
installs. ``clean_test_database()`` still drops this collection along with all the
others, which is correct: test runs should not be counted, and they are suppressed
before ever reaching this code.
"""

import uuid
from datetime import datetime, timezone
from typing import Final

# Imported from the submodule rather than as ``pymongo.errors.DuplicateKeyError``:
# the attribute form does not resolve for the type checker, which is why the
# existing call sites in services/lifespan.py carry a type-ignore comment.
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.logging_init import logger

#: Document ID of the singleton identity record.
IDENTITY_DOC_ID: Final[str] = "instance_identity"


def get_or_create_instance_id() -> tuple[str, datetime]:
    """Return this installation's anonymous ID and the moment it was first seen.

    Safe to call concurrently from every gunicorn worker and every Kubernetes
    replica. The insert is attempted unconditionally and a
    :class:`pymongo.errors.DuplicateKeyError` is treated as "someone else got
    there first", which is the same atomic-insert idiom the YAML watcher lock uses
    in ``services/lifespan.py`` — no read-then-write race window, and no
    distributed lock to manage.

    Returns:
        ``(instance_id, created_at)``. ``created_at`` backs the ``install_age_days``
        retention metric, which is the only time-derived value ever sent.
    """
    from depictio.api.v1.db import telemetry_collection

    now = datetime.now(timezone.utc)

    try:
        telemetry_collection.insert_one(
            {
                "_id": IDENTITY_DOC_ID,
                "instance_id": uuid.uuid4().hex,
                "created_at": now,
            }
        )
        logger.debug("Telemetry: registered a new anonymous installation identity")
    except DuplicateKeyError:
        pass

    doc = telemetry_collection.find_one({"_id": IDENTITY_DOC_ID})
    if not doc or not doc.get("instance_id"):
        # Should be unreachable: either our insert succeeded or another process's
        # did. Fall back to an ephemeral ID rather than raising, so a heartbeat is
        # never the reason a request or a boot fails.
        logger.warning("Telemetry: identity document missing after upsert; using ephemeral ID")
        return uuid.uuid4().hex, now

    created_at = doc.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = now

    return str(doc["instance_id"]), created_at


def install_age_days(created_at: datetime) -> int:
    """Whole days since this installation first reported.

    Tolerates a naive ``created_at``: MongoDB round-trips datetimes as naive UTC
    unless the client is configured otherwise, and subtracting a naive from an
    aware datetime raises.
    """
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(0, (now - created_at).days)
