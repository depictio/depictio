"""Per-user session annotation endpoints.

A viewer labels a table's rows on a dashboard to compare groups without
changing the data. Labels are stored per (user, dashboard family main tab), and
writable at *viewer* level, like filter state.

Who gets account storage: any real account, and single-user mode's shared
anonymous user (there is only one person). A temporary or an anonymous account
outside single-user mode is refused with 403: anonymous visitors share one
account, so storing would show one visitor's labels to every other, and a
temporary account keeps its annotations in the browser.

Read access is re-checked on every call, so a viewer who loses access to the
dashboard can no longer read what they stored on it.
"""

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Response

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboard_annotations import (
    DashboardAnnotationsBeanie,
    DashboardAnnotationsPayload,
)
from depictio.models.models.users import User
from depictio.models.timestamps import utc_now_naive

annotation_router = APIRouter()

_EMPTY = {"annotations": None, "updated_at": None, "persisted": False}


def _refuse_unstorable(user: User) -> None:
    if getattr(user, "is_temporary", False):
        raise HTTPException(
            status_code=403,
            detail="A temporary account keeps its annotations in the browser.",
        )
    if getattr(user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        raise HTTPException(
            status_code=403,
            detail="Sign in to keep annotations on your account.",
        )


async def _family_id(dashboard_id: PyObjectId, user: User) -> ObjectId:
    """The family main tab id. 404 if the dashboard is missing, 403 without read access."""
    _refuse_unstorable(user)
    dashboard = dashboards_collection.find_one(
        {"dashboard_id": ObjectId(str(dashboard_id))},
        {"project_id": 1, "parent_dashboard_id": 1},
    )
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    project_id = dashboard.get("project_id")
    if not project_id or not check_project_permission(project_id, user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to view this dashboard."
        )
    parent = dashboard.get("parent_dashboard_id")
    return ObjectId(str(parent)) if parent else ObjectId(str(dashboard_id))


def _key(user: User, family_id: ObjectId) -> dict:
    return {"user_id": ObjectId(str(user.id)), "dashboard_id": family_id}


@annotation_router.get("/{dashboard_id}")
async def get_annotations(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """The caller's annotations on this dashboard. Absence is a normal answer."""
    family_id = await _family_id(dashboard_id, current_user)
    doc = await DashboardAnnotationsBeanie.find_one(
        DashboardAnnotationsBeanie.user_id == ObjectId(str(current_user.id)),
        DashboardAnnotationsBeanie.dashboard_id == family_id,
    )
    if not doc:
        return dict(_EMPTY)
    return {
        "annotations": doc.annotations.model_dump(by_alias=True),
        "updated_at": doc.updated_at.isoformat(),
        "persisted": True,
    }


@annotation_router.put("/{dashboard_id}")
async def put_annotations(
    dashboard_id: PyObjectId,
    payload: DashboardAnnotationsPayload,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """Replace the caller's annotations (last write wins)."""
    family_id = await _family_id(dashboard_id, current_user)
    updated_at = utc_now_naive()
    # Race-safe upsert against the unique (user_id, dashboard_id) index: two
    # debounced tabs writing at once would break a find + save pair.
    await DashboardAnnotationsBeanie.get_pymongo_collection().update_one(
        _key(current_user, family_id),
        {"$set": {"annotations": payload.model_dump(), "updated_at": updated_at}},
        upsert=True,
    )
    return {"persisted": True, "updated_at": updated_at.isoformat()}


@annotation_router.delete("/{dashboard_id}", status_code=204)
async def delete_annotations(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """Drop the caller's annotations on this dashboard."""
    family_id = await _family_id(dashboard_id, current_user)
    await DashboardAnnotationsBeanie.get_pymongo_collection().delete_one(
        _key(current_user, family_id)
    )
    return Response(status_code=204)
