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

Only a metadata table linked to the data can carry labels
(``annotation_tables``): ``GET /{dashboard_id}/tables`` lists the project's
tables with that verdict, and a save naming any other table, or a key column
that is not one of its links' source columns, is refused with 422.
"""

import asyncio

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.endpoints.dashboards_endpoints.annotation_tables import (
    annotatable_tables,
    classify_tables,
)
from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboard_annotations import (
    DashboardAnnotationsBeanie,
    DashboardAnnotationsPayload,
    SharedLabelsPayload,
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


async def _family(dashboard_id: PyObjectId, user: User) -> tuple[ObjectId, ObjectId]:
    """``(family main tab id, project id)``. 404 if the dashboard is missing, 403
    without read access."""
    _refuse_unstorable(user)
    return await _readable_family(dashboard_id, user)


async def _readable_family(dashboard_id: PyObjectId, user: User) -> tuple[ObjectId, ObjectId]:
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
    family_id = ObjectId(str(parent)) if parent else ObjectId(str(dashboard_id))
    return family_id, ObjectId(str(project_id))


async def _family_id(dashboard_id: PyObjectId, user: User) -> ObjectId:
    return (await _family(dashboard_id, user))[0]


def _project(project_id: ObjectId) -> dict:
    project = projects_collection.find_one(
        {"_id": project_id}, {"workflows": 1, "links": 1, "joins": 1}
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _check_tables(
    payload: DashboardAnnotationsPayload | SharedLabelsPayload, project: dict
) -> None:
    """422 when a column names a table that cannot carry labels, or a key column
    none of its links uses. Row counts are left to ``/tables``: a save only
    checks the structure, so it reads no table."""
    tables = {t["dc_id"]: t for t in classify_tables(project, lambda _dc_id: 0)}
    for column in payload.columns:
        table = tables.get(column.dc_id)
        if table is None or not table["eligible"]:
            reason = table["reason"] if table else "This table is not in the project."
            raise HTTPException(status_code=422, detail=f"{column.name}: {reason}")
        if column.key_column not in table["key_columns"]:
            raise HTTPException(
                status_code=422,
                detail=f"{column.name}: {column.key_column} is not a key column of this table.",
            )


def _key(user: User, family_id: ObjectId) -> dict:
    return {"user_id": ObjectId(str(user.id)), "dashboard_id": family_id}


@annotation_router.get("/{dashboard_id}/tables")
async def get_annotation_tables(
    dashboard_id: PyObjectId,
    version_id: str | None = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """The project's tables, each with whether labels can be put on it and why
    not, plus the labels shared on this dashboard and whether the caller may
    change them.

    Open to every reader of the dashboard, a temporary or anonymous one
    included: they label in the browser, on the same tables.

    ``version_id`` reads the shared labels as that version of the family held
    them (404 for another family's version), for a ``?version=`` view, which
    is read-only.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store
    from depictio.api.v1.endpoints.dashboards_endpoints.shared_labels_routes import (
        can_share,
        main_tab_doc,
        shared_columns,
    )

    family_id, project_id = await _readable_family(dashboard_id, current_user)
    main_tab = main_tab_doc(family_id)
    if version_id:
        record = version_store.get_version(version_id)
        if not record or record.get("family_id") != str(family_id):
            raise HTTPException(
                status_code=404, detail="That version does not belong to this dashboard."
            )
        stored_main = next((t for t in record.get("tabs") or [] if t.get("is_main_tab")), {})
        shared, sharing = shared_columns(stored_main.get("shared_labels")), False
    else:
        shared = shared_columns(main_tab.get("shared_labels"))
        sharing = can_share(main_tab, current_user)
    return {
        # Blocking Delta reads: off the event loop, or every request waits on them.
        "tables": await asyncio.to_thread(annotatable_tables, _project(project_id)),
        "shared": shared,
        "can_share": sharing,
    }


@annotation_router.get("/{dashboard_id}")
async def get_annotations(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """The caller's annotations on this dashboard. Absence is a normal answer."""
    family_id = await _family_id(dashboard_id, current_user)
    raw = await DashboardAnnotationsBeanie.get_pymongo_collection().find_one(
        _key(current_user, family_id)
    )
    if not raw:
        return dict(_EMPTY)
    try:
        annotations = DashboardAnnotationsPayload.model_validate(raw.get("annotations"))
    except ValidationError:
        # A document of an older shape (one table per dashboard, version 1)
        # reads as absent; the next save replaces it.
        return dict(_EMPTY)
    return {
        "annotations": annotations.model_dump(by_alias=True),
        "updated_at": raw["updated_at"].isoformat(),
        "persisted": True,
    }


@annotation_router.put("/{dashboard_id}")
async def put_annotations(
    dashboard_id: PyObjectId,
    payload: DashboardAnnotationsPayload,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """Replace the caller's annotations (last write wins)."""
    family_id, project_id = await _family(dashboard_id, current_user)
    _check_tables(payload, _project(project_id))
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
