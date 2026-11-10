"""Label columns shared on a dashboard.

A reader's own labels (``annotation_routes``) are personal. Shared labels live
on the dashboard family's main tab (``shared_labels``) and every reader of the
dashboard sees them, read-only: they can compare by them, or copy one into
their own labels and change the copy.

Who may share: whoever may change the dashboard, i.e. an editor of the
project, or the owner of the dashboard document (a reader who duplicated a
public dashboard owns the copy without any role on the project). Never an
anonymous visitor outside single-user mode. A published (locked) dashboard is
refused with 409, like every content change; its copies are not locked.

Shared labels are dashboard content: the write seeds a baseline and captures a
version, so the timeline holds them, a restore brings them back and a
``?version=`` preview shows them as they were.
"""

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.annotation_routes import (
    _check_tables,
    _project,
    _readable_family,
)
from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _capture_version_quietly,
    _ensure_baseline_quietly,
    check_dashboard_mutation_permission,
)
from depictio.api.v1.endpoints.projects_endpoints.publish_lock import (
    assert_dashboard_unlocked,
    dashboard_lock,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboard_annotations import AnnotationColumn, SharedLabelsPayload
from depictio.models.models.users import User

shared_labels_router = APIRouter()


def _plain(value: Any) -> Any:
    """ObjectIds back to strings: a restore turns every id-looking string into
    one (``versions_routes._rehydrate_ids``), and the columns are validated as
    the client's plain-string shape."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    return value


def shared_columns(raw: list[Any] | None) -> list[dict[str, Any]]:
    """The stored shared labels in the client's shape. A column that no longer
    validates is left out rather than failing the whole read."""
    columns: list[dict[str, Any]] = []
    for item in raw or []:
        try:
            columns.append(AnnotationColumn.model_validate(_plain(item)).model_dump(by_alias=True))
        except ValidationError as exc:
            logger.warning(f"Shared labels: skipping an invalid column: {exc}")
    return columns


def can_share(main_tab: dict[str, Any], user: User) -> bool:
    """Whether ``user`` may change the shared labels of this dashboard family."""
    if getattr(user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        return False
    if not check_dashboard_mutation_permission(main_tab, user, "editor"):
        return False
    return dashboard_lock(main_tab) is None


def main_tab_doc(family_id: ObjectId) -> dict[str, Any]:
    doc = dashboards_collection.find_one({"dashboard_id": family_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    return doc


@shared_labels_router.put("/{dashboard_id}/shared")
async def put_shared_labels(
    dashboard_id: PyObjectId,
    payload: SharedLabelsPayload,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """Replace the label columns shared on this dashboard (last write wins)."""
    family_id, project_id = await _readable_family(dashboard_id, current_user)
    main_tab = main_tab_doc(family_id)
    if getattr(current_user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        raise HTTPException(status_code=403, detail="Sign in to share labels.")
    if not check_dashboard_mutation_permission(main_tab, current_user, "editor"):
        raise HTTPException(
            status_code=403,
            detail="Only an editor of the project or an owner of this dashboard can share labels.",
        )
    assert_dashboard_unlocked(main_tab)
    _check_tables(payload, _project(project_id))

    columns = [column.model_dump() for column in payload.columns]
    # Before the write, as for every route that bypasses `/save`.
    _ensure_baseline_quietly(family_id, current_user)
    dashboards_collection.update_one(
        {"dashboard_id": family_id}, {"$set": {"shared_labels": columns}}
    )
    # Sharing, unsharing or deleting a column is a step of its own in the
    # timeline, so the state before it stays restorable; an edit of a shared
    # column's labels folds into the autosave window like any other edit.
    before = {str(c.get("id")) for c in main_tab.get("shared_labels") or [] if isinstance(c, dict)}
    after = {c["id"] for c in columns}
    _capture_version_quietly(
        family_id, current_user, kind="explicit" if before != after else "auto"
    )
    logger.info(f"Dashboard {family_id}: {len(columns)} shared label column(s)")
    return {"shared": shared_columns(columns)}
