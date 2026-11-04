"""The published lock: a project frozen read-only on this instance (#1303).

A locked project (``Project.published_lock`` set) refuses every change to what
was published, with a 409: its dashboards' content, its data collections and
their data, its links and its own document. An administrator lifts it with
``POST /projects/{id}/unlock``; the only other writer is an approved migration
request, which writes the collections directly and records a new version.

What is published is the project plus ``published_lock.dashboard_ids``. A
visitor's copy of a public dashboard lives in the same project (the duplicate
keeps ``project_id``) but is not part of the release, so it stays editable by
its owner, and a visitor may still create one.

Every mutating route calls one of the ``assert_*`` helpers explicitly, after
authentication and before writing. ``test_publish_lock_routes.py`` lists every
mutating route as guarded or exempt and fails on one that is neither.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import HTTPException

LOCKED_DETAIL = "Project is published (read-only). An administrator must unlock it first."


def _db():
    from depictio.api.v1 import db

    return db


def _oid(value: Any) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def project_lock(project: dict[str, Any] | None) -> dict[str, Any] | None:
    """The lock of a project document, or None."""
    if not project:
        return None
    lock = project.get("published_lock")
    return lock if isinstance(lock, dict) else None


def _raise_locked() -> None:
    raise HTTPException(status_code=409, detail=LOCKED_DETAIL)


def _project_doc(project_or_id: Any) -> dict[str, Any] | None:
    if isinstance(project_or_id, dict):
        if "published_lock" in project_or_id:
            return project_or_id
        project_or_id = project_or_id.get("_id") or project_or_id.get("id")
    pid = _oid(project_or_id)
    if pid is None:
        return None
    return _db().projects_collection.find_one({"_id": pid}, {"published_lock": 1})


def is_project_locked(project_or_id: Any) -> bool:
    return project_lock(_project_doc(project_or_id)) is not None


def assert_project_unlocked(project_or_id: Any) -> None:
    """409 when the project (a document or an id) is published."""
    if is_project_locked(project_or_id):
        _raise_locked()


def _project_of_dc(dc_id: Any) -> dict[str, Any] | None:
    oid = _oid(dc_id)
    if oid is None:
        return None
    return _db().projects_collection.find_one(
        {
            "$or": [
                {"workflows.data_collections._id": oid},
                {"data_collections._id": oid},
                {"workflows.data_collections._id": str(oid)},
            ]
        },
        {"published_lock": 1},
    )


def assert_dc_project_unlocked(dc_id: Any) -> None:
    """409 when the data collection belongs to a published project."""
    if project_lock(_project_of_dc(dc_id)) is not None:
        _raise_locked()


def assert_workflow_project_unlocked(workflow_id: Any) -> None:
    """409 when the workflow belongs to a published project."""
    oid = _oid(workflow_id)
    if oid is None:
        return
    project = _db().projects_collection.find_one(
        {"$or": [{"workflows._id": oid}, {"workflows._id": str(oid)}]}, {"published_lock": 1}
    )
    if project_lock(project) is not None:
        _raise_locked()


def _dashboard_doc(dashboard_or_id: Any) -> dict[str, Any] | None:
    if isinstance(dashboard_or_id, dict):
        return dashboard_or_id
    oid = _oid(dashboard_or_id)
    if oid is None:
        return None
    return _db().dashboards_collection.find_one(
        {"$or": [{"dashboard_id": oid}, {"_id": oid}]},
        {"project_id": 1, "dashboard_id": 1, "parent_dashboard_id": 1, "is_main_tab": 1},
    )


def dashboard_is_published(dashboard: dict[str, Any] | None, lock: dict[str, Any] | None) -> bool:
    """Whether ``dashboard`` (a tab) is part of what ``lock`` froze."""
    if not dashboard or not lock:
        return False
    published = {str(d) for d in lock.get("dashboard_ids") or []}
    own = str(dashboard.get("dashboard_id") or dashboard.get("_id") or "")
    parent = dashboard.get("parent_dashboard_id")
    return own in published or (parent is not None and str(parent) in published)


def dashboard_lock(dashboard_or_id: Any) -> dict[str, Any] | None:
    """The lock that freezes this dashboard, or None (also for a visitor's copy)."""
    dashboard = _dashboard_doc(dashboard_or_id)
    if not dashboard or dashboard.get("project_id") is None:
        return None
    lock = project_lock(_project_doc(dashboard["project_id"]))
    return lock if dashboard_is_published(dashboard, lock) else None


def assert_dashboard_unlocked(dashboard_or_id: Any) -> None:
    """409 when the dashboard (a document or an id) is part of a published release."""
    if dashboard_lock(dashboard_or_id) is not None:
        _raise_locked()


def assert_dashboard_creation_allowed(
    project_id: Any, user: Any, parent_dashboard_id: Any = None
) -> None:
    """Whether ``user`` may add a dashboard (or a tab) to ``project_id``.

    In a published project only a visitor's copy may be created: a caller with
    no editor role on the project, adding a dashboard that is not a tab of a
    published one. Owners, editors and admins change a release by publishing a
    new one, not by adding to it.
    """
    project = _db().projects_collection.find_one(
        {"_id": _oid(project_id)}, {"published_lock": 1, "permissions": 1, "is_public": 1}
    )
    lock = project_lock(project)
    if lock is None:
        return
    from depictio.api.v1.permissions import get_user_group_ids, has_permission

    try:
        group_ids = get_user_group_ids(user.id)
    except Exception:
        group_ids = []
    if has_permission(project, user, "editor", group_ids):
        _raise_locked()
    if parent_dashboard_id is not None and str(parent_dashboard_id) in {
        str(d) for d in lock.get("dashboard_ids") or []
    }:
        _raise_locked()
