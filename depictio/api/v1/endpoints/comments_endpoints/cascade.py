"""Delete comment threads along with the dashboards and projects they hang off.

Kept apart from ``routes.py`` (and free of any import of the dashboard or
project routers) so those routers can import it without a cycle.

Threads store ``anchor.dashboard_id``, ``parent_dashboard_id`` and
``project_id`` as strings, so every id is stringified before matching.

A failure here never fails the delete that triggered it: it is logged and the
orphaned threads stay behind (they are invisible, since every read goes
through the dashboard they point at).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import comment_threads_collection


def delete_threads_for_dashboards(dashboard_ids: Iterable[Any]) -> int:
    """Delete every thread anchored on one of these tabs. Returns the count deleted."""
    ids = sorted({str(i) for i in dashboard_ids if i is not None})
    if not ids:
        return 0
    try:
        result = comment_threads_collection.delete_many({"anchor.dashboard_id": {"$in": ids}})
        if result.deleted_count:
            logger.info(f"comments: deleted {result.deleted_count} thread(s) for tabs {ids}")
        return result.deleted_count
    except Exception as exc:  # noqa: BLE001 — cascade is best-effort
        logger.warning(f"comments: failed to delete threads for tabs {ids}: {exc}")
        return 0


def delete_threads_for_project(project_id: Any) -> int:
    """Delete every thread of a project. Returns the count deleted."""
    if project_id is None:
        return 0
    pid = str(project_id)
    try:
        result = comment_threads_collection.delete_many({"project_id": pid})
        if result.deleted_count:
            logger.info(f"comments: deleted {result.deleted_count} thread(s) for project {pid}")
        return result.deleted_count
    except Exception as exc:  # noqa: BLE001 — cascade is best-effort
        logger.warning(f"comments: failed to delete threads for project {pid}: {exc}")
        return 0
