"""The anonymous installation identity.

One random UUID per Depictio installation, created on first use and stored in the
dedicated ``telemetry`` collection. It is the only thing that makes an install
*countable*: without a stable ID, a restart is indistinguishable from a new
deployment and every metric becomes a process count.

It lives in its own collection, which ``wipe_database()`` (``DEPICTIO_MONGODB_WIPE``)
keeps along with the init lock: an identity dropped by a wipe would be regenerated
on the next boot, quietly inflating the project's installation count with phantom
installs. ``clean_test_database()`` still drops this collection along with all the
others, which is correct: test runs should not be counted, and they are suppressed
before ever reaching this code.

Keeping it is still a negative fact, true only as long as no deletion path touches
the collection. So the identity also records whether it was created on a database
an earlier boot had initialised (``preexisting_data``), and the payload sends it:
a regenerated identity is visible in the data rather than counted as a new install.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Final

# Imported from the submodule rather than as ``pymongo.errors.DuplicateKeyError``:
# the attribute form does not resolve for the type checker, which is why the
# existing call sites in services/lifespan.py carry a type-ignore comment.
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.logging_init import logger

#: Document ID of the singleton identity record.
IDENTITY_DOC_ID: Final[str] = "instance_identity"

#: How much earlier than this process the database must have been initialised to
#: count as another boot's: absorbs the replicas of one fresh install starting
#: minutes apart, and clock skew between their nodes.
SAME_BOOT_GRACE: Final[timedelta] = timedelta(minutes=10)


def _process_started_at() -> datetime:
    """When this process started. The worker's own, not a module import time:
    telemetry is imported after initialization has already run."""
    import psutil

    return datetime.fromtimestamp(psutil.Process().create_time(), tz=timezone.utc)


def database_predates_this_boot() -> bool:
    """Whether an earlier boot initialised this database.

    The identity is created on the first heartbeat, a minute after the boot that
    initialised a fresh install, so there the init lock completes after this
    process started. A lock completed well before it means the identity is
    younger than the data: telemetry turned on after the first boot, an upgrade
    from a release without it, or a regenerated identity. False when there is no
    lock to judge by, or when it cannot be read: never the reason an identity is
    not created.
    """
    from depictio.api.v1.db import initialization_collection

    try:
        lock = initialization_collection.find_one({"_id": "init_lock"}) or {}
        initialised_at = lock.get("completed_at") or lock.get("started_at")
        if not isinstance(initialised_at, datetime):
            return False
        if initialised_at.tzinfo is None:
            initialised_at = initialised_at.replace(tzinfo=timezone.utc)
        return initialised_at < _process_started_at() - SAME_BOOT_GRACE
    except Exception as exc:
        logger.debug("Telemetry: could not tell whether the database predates this boot: %s", exc)
        return False


def get_or_create_instance_id() -> tuple[str, datetime, bool]:
    """Return this installation's anonymous ID and the moment it was first seen.

    Safe to call concurrently from every gunicorn worker and every Kubernetes
    replica. The insert is attempted unconditionally and a
    :class:`pymongo.errors.DuplicateKeyError` is treated as "someone else got
    there first", which is the same atomic-insert idiom the YAML watcher lock uses
    in ``services/lifespan.py`` — no read-then-write race window, and no
    distributed lock to manage.

    Returns:
        ``(instance_id, created_at, preexisting_data)``. ``created_at`` backs the
        ``install_age_days`` retention metric, which is the only time-derived value
        ever sent. ``preexisting_data`` is decided once, when the identity is
        created (see :func:`database_predates_this_boot`), and False for an
        identity recorded before the field existed.
    """
    from depictio.api.v1.db import telemetry_collection

    now = datetime.now(timezone.utc)

    try:
        telemetry_collection.insert_one(
            {
                "_id": IDENTITY_DOC_ID,
                "instance_id": uuid.uuid4().hex,
                "created_at": now,
                "preexisting_data": database_predates_this_boot(),
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
        return uuid.uuid4().hex, now, False

    created_at = doc.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = now

    return str(doc["instance_id"]), created_at, doc.get("preexisting_data") is True


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
