"""Per-user dashboard filter state endpoints.

Separate from the main dashboards router: filter state is per-(user, dashboard)
and writable at *viewer* permission level, while ``/dashboards/save`` requires
editor. Anonymous users (public / single-user mode share one anonymous account)
are served no-ops so their state stays browser-local — persisting it server-side
would leak one visitor's view to every other anonymous visitor.
"""

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Response

from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboard_filter_state import (
    DashboardFilterStateBeanie,
    DashboardFilterStatePayload,
)
from depictio.models.models.users import User

filter_state_router = APIRouter()

_EMPTY_STATE = {"filters": [], "enabled": True, "updated_at": None, "persisted": False}


def _is_anonymous(user: User) -> bool:
    return bool(getattr(user, "is_anonymous", False))


async def _authorize(dashboard_id: PyObjectId, user: User) -> None:
    """404 if the dashboard doesn't exist, 403 unless the user can view it."""
    dashboard = dashboards_collection.find_one(
        {"dashboard_id": ObjectId(str(dashboard_id))}, {"project_id": 1}
    )
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    project_id = dashboard.get("project_id")
    if not project_id or not check_project_permission(project_id, user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to view this dashboard."
        )


@filter_state_router.get("/{dashboard_id}")
async def get_filter_state(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """Return the caller's saved filter state. Absence is a normal answer, not a 404."""
    if _is_anonymous(current_user):
        return dict(_EMPTY_STATE)
    await _authorize(dashboard_id, current_user)
    doc = await DashboardFilterStateBeanie.find_one(
        DashboardFilterStateBeanie.user_id == ObjectId(str(current_user.id)),
        DashboardFilterStateBeanie.dashboard_id == ObjectId(str(dashboard_id)),
    )
    if not doc:
        return dict(_EMPTY_STATE)
    return {
        "filters": doc.filters,
        "enabled": doc.enabled,
        "updated_at": doc.updated_at.isoformat(),
        "persisted": True,
    }


@filter_state_router.put("/{dashboard_id}")
async def put_filter_state(
    dashboard_id: PyObjectId,
    payload: DashboardFilterStatePayload,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """Upsert the caller's filter state (last write wins)."""
    if _is_anonymous(current_user):
        return {"persisted": False}
    await _authorize(dashboard_id, current_user)
    updated_at = datetime.now(timezone.utc)
    # Race-safe upsert: two debounced tabs writing concurrently would make a
    # find+save pair violate the unique (user_id, dashboard_id) index.
    await DashboardFilterStateBeanie.get_pymongo_collection().update_one(
        {
            "user_id": ObjectId(str(current_user.id)),
            "dashboard_id": ObjectId(str(dashboard_id)),
        },
        {
            "$set": {
                "filters": payload.filters,
                "enabled": payload.enabled,
                "updated_at": updated_at,
            }
        },
        upsert=True,
    )
    return {"persisted": True, "updated_at": updated_at.isoformat()}


@filter_state_router.delete("/{dashboard_id}", status_code=204)
async def delete_filter_state(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """Drop the caller's saved state entirely (toggle OFF uses PUT so the preference roams)."""
    if not _is_anonymous(current_user):
        await _authorize(dashboard_id, current_user)
        await DashboardFilterStateBeanie.get_pymongo_collection().delete_one(
            {
                "user_id": ObjectId(str(current_user.id)),
                "dashboard_id": ObjectId(str(dashboard_id)),
            }
        )
    return Response(status_code=204)
