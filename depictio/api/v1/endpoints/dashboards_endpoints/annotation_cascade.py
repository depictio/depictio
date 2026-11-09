"""Delete session annotations along with the dashboards, projects and users they belong to.

Kept apart from ``routes.py`` (and free of any import of the dashboard, project
or user routers) so all of them can import it without a cycle.

A document is keyed on ``(user_id, dashboard_id)``, where ``dashboard_id`` is a
family's main tab. A failure here never fails the delete that triggered it: it
is logged and the orphaned documents stay behind.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboard_annotations_collection, dashboards_collection


def _ids(values: Iterable[Any]) -> list[ObjectId]:
    return sorted({ObjectId(str(v)) for v in values if v is not None and ObjectId.is_valid(str(v))})


def delete_annotations_for_dashboards(dashboard_ids: Iterable[Any]) -> int:
    """Delete every user's annotations on these tabs. Returns the count deleted.

    Passing a child tab is harmless: annotations are stored on the main tab, so
    nothing matches it.
    """
    ids = _ids(dashboard_ids)
    if not ids:
        return 0
    try:
        result = dashboard_annotations_collection.delete_many({"dashboard_id": {"$in": ids}})
        if result.deleted_count:
            logger.info(f"annotations: deleted {result.deleted_count} for tabs {ids}")
        return result.deleted_count
    except Exception as exc:  # noqa: BLE001 — cascade is best-effort
        logger.warning(f"annotations: failed to delete for tabs {ids}: {exc}")
        return 0


def delete_annotations_for_project(project_id: Any) -> int:
    """Delete the annotations on every dashboard of a project.

    Must run before the project's dashboards are deleted: the documents only
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
        logger.warning(f"annotations: failed to list tabs of project {project_id}: {exc}")
        return 0
    return delete_annotations_for_dashboards(tab_ids)


def delete_annotations_for_user(user_id: Any) -> int:
    """Delete everything a user annotated, on every dashboard."""
    ids = _ids([user_id])
    if not ids:
        return 0
    try:
        result = dashboard_annotations_collection.delete_many({"user_id": ids[0]})
        if result.deleted_count:
            logger.info(f"annotations: deleted {result.deleted_count} of user {ids[0]}")
        return result.deleted_count
    except Exception as exc:  # noqa: BLE001 — cascade is best-effort
        logger.warning(f"annotations: failed to delete for user {ids[0]}: {exc}")
        return 0
