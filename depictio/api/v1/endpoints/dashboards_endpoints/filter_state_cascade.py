"""Delete remembered filter states along with the dashboards they belong to.

Kept apart from ``routes.py`` (and free of any import of the dashboard or
project routers) so those routers can import it without a cycle.

A state is keyed on ``(user_id, dashboard_id)``; once its dashboard is gone no
read can reach it. A failure here never fails the delete that triggered it: it
is logged and the orphaned states stay behind.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboard_filter_states_collection, dashboards_collection


def delete_filter_states_for_dashboards(dashboard_ids: Iterable[Any]) -> int:
    """Delete every user's saved filters for these tabs. Returns the count deleted."""
    ids = sorted(
        {ObjectId(str(i)) for i in dashboard_ids if i is not None and ObjectId.is_valid(str(i))}
    )
    if not ids:
        return 0
    try:
        result = dashboard_filter_states_collection.delete_many({"dashboard_id": {"$in": ids}})
        if result.deleted_count:
            logger.info(f"filter_state: deleted {result.deleted_count} state(s) for tabs {ids}")
        return result.deleted_count
    except Exception as exc:  # noqa: BLE001 — cascade is best-effort
        logger.warning(f"filter_state: failed to delete states for tabs {ids}: {exc}")
        return 0


def delete_filter_states_for_project(project_id: Any) -> int:
    """Delete the saved filters of every dashboard of a project.

    Must run before the project's dashboards are deleted: the state rows only
    carry the dashboard id, so the project's tabs are looked up first.
    """
    if project_id is None or not ObjectId.is_valid(str(project_id)):
        return 0
    try:
        tab_ids = [
            d["dashboard_id"]
            for d in dashboards_collection.find(
                {"project_id": ObjectId(str(project_id))}, {"dashboard_id": 1}
            )
        ]
    except Exception as exc:  # noqa: BLE001 — cascade is best-effort
        logger.warning(f"filter_state: failed to list tabs of project {project_id}: {exc}")
        return 0
    return delete_filter_states_for_dashboards(tab_ids)
