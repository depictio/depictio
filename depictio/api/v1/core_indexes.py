"""Indexes for the core collections that predate the monitoring/jobs stores.

``files``, ``runs`` and ``dashboards`` were never given any indexes: every
lookup against them is a collection scan. That was survivable while the only
access pattern was "fetch everything for this data collection", but two newer
patterns make it costly:

* the dashboard-version capture reads a whole tab family on every save, which
  means a ``parent_dashboard_id`` lookup per autosave;
* reconstructing which files backed a data collection at a point in time is a
  ``(data_collection_id, registration_time)`` range query.

``ensure_core_indexes()`` is idempotent and never raises — a failure here
degrades performance, and must not stop the API from booting. It mirrors
``monitoring/store.ensure_monitoring_storage``.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import OperationFailure

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    files_collection,
    runs_collection,
    static_exports_collection,
)

#: The TTL index on ``static_exports.created_at`` (static-bundle export jobs).
STATIC_EXPORTS_TTL_INDEX = "static_exports_ttl"


def ensure_core_indexes() -> None:
    """Create indexes on files/runs/dashboards. Idempotent, never raises."""
    try:
        # Every file read is scoped to a data collection; the registration_time
        # component additionally serves "which files existed at or before T"
        # without a scan.
        files_collection.create_index(
            [("data_collection_id", ASCENDING), ("registration_time", ASCENDING)],
            name="dc_registration_time",
        )
        files_collection.create_index("file_location", name="file_location")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"core_indexes: failed to ensure files indexes: {exc}")

    try:
        runs_collection.create_index("run_tag", name="run_tag")
        runs_collection.create_index(
            [("workflow_id", ASCENDING), ("run_tag", ASCENDING)], name="workflow_run_tag"
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"core_indexes: failed to ensure runs indexes: {exc}")

    try:
        # Child-tab lookup: every family snapshot (`versioning.load_family_docs`)
        # runs one, i.e. once per dashboard save.
        dashboards_collection.create_index("parent_dashboard_id", name="parent_dashboard_id")
        dashboards_collection.create_index("dashboard_id", name="dashboard_id")
        dashboards_collection.create_index(
            [("project_id", ASCENDING), ("last_saved_ts", DESCENDING)], name="project_last_saved"
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"core_indexes: failed to ensure dashboards indexes: {exc}")

    ensure_static_exports_ttl()


def ensure_static_exports_ttl(collection=None, retention_days: int | None = None) -> None:
    """Expire static-export job documents after the configured retention.

    ``performance.static_export_retention_days`` (0 = keep forever, which drops
    the index). A changed retention is applied to the existing index with
    ``collMod``: ``create_index`` refuses to change ``expireAfterSeconds`` on an
    index that already exists. Never raises.
    """
    collection = static_exports_collection if collection is None else collection
    days = settings.performance.static_export_retention_days if retention_days is None else retention_days
    try:
        if days <= 0:
            if STATIC_EXPORTS_TTL_INDEX in collection.index_information():
                collection.drop_index(STATIC_EXPORTS_TTL_INDEX)
            return
        seconds = int(days) * 86_400
        try:
            collection.create_index(
                "created_at", expireAfterSeconds=seconds, name=STATIC_EXPORTS_TTL_INDEX
            )
        except OperationFailure:
            # Same key, other expireAfterSeconds: retune the index in place.
            collection.database.command(
                "collMod",
                collection.name,
                index={"keyPattern": {"created_at": 1}, "expireAfterSeconds": seconds},
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"core_indexes: failed to ensure the static_exports TTL: {exc}")
