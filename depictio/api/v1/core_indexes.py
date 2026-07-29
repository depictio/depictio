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

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    files_collection,
    runs_collection,
)


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
        # Every "the files in this collection" read now also filters
        # ``deleted_at: None``. Without this the tombstone predicate turns each
        # of those into a scan of the collection's whole history rather than
        # its live set.
        files_collection.create_index(
            [("data_collection_id", ASCENDING), ("deleted_at", ASCENDING)],
            name="dc_deleted_at",
        )
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
        # Child-tab lookup: get_child_tabs() runs on every family snapshot, i.e.
        # once per dashboard save.
        dashboards_collection.create_index("parent_dashboard_id", name="parent_dashboard_id")
        dashboards_collection.create_index("dashboard_id", name="dashboard_id")
        dashboards_collection.create_index(
            [("project_id", ASCENDING), ("last_saved_ts", DESCENDING)], name="project_last_saved"
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"core_indexes: failed to ensure dashboards indexes: {exc}")
