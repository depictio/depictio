"""Cross-tab global filters & stories — API logic.

Global filters and stories live on the **parent** dashboard document
(``is_main_tab=True``). Per-user state (last-used filter values, last
active story) lives in ``user_dashboard_state_collection`` so each user
maintains their own view without overwriting collaborators.

Wired into the existing ``dashboards_endpoint_router`` from
``routes.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    user_dashboard_state_collection,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import GlobalFilterDef, Journey
from depictio.models.models.users import User

# ============================================================================
# Request bodies
# ============================================================================


class FilterValuePatch(BaseModel):
    value: Any = None


class FunnelStep(BaseModel):
    """A single step in a funnel chain — one global filter + its current value."""

    filter_id: str
    value: Any = None


class FunnelTargetDC(BaseModel):
    wf_id: str
    dc_id: str


class FunnelRequest(BaseModel):
    steps: list[FunnelStep] = Field(default_factory=list)
    target_dcs: list[FunnelTargetDC] = Field(default_factory=list)


class ActiveJourneyPatch(BaseModel):
    """Sets the user's active journey + which stop within it they're on.

    Both fields are optional. Passing ``journey_id=None`` exits the active
    journey entirely (clears both fields server-side). Passing a non-null
    ``journey_id`` with no ``stop_id`` keeps whichever stop the user was
    last on for that journey (resume); see the ``journey_stops`` field on
    :class:`UserDashboardState`.
    """

    journey_id: str | None = None
    stop_id: str | None = None


# ============================================================================
# Permission helpers (thin wrappers over the routes.py utilities)
# ============================================================================


def _load_parent_or_404(parent_dashboard_id: PyObjectId) -> dict:
    """Fetch the parent dashboard document or raise 404.

    Resolves either a true main tab or, defensively, a child tab whose
    ``parent_dashboard_id`` points to the real main tab — callers should
    pass the parent ID, but the React store sometimes hydrates against
    whichever tab the user landed on first.
    """
    doc = dashboards_collection.find_one({"dashboard_id": parent_dashboard_id})
    if doc and not doc.get("is_main_tab", True) and doc.get("parent_dashboard_id"):
        parent_dashboard_id = doc["parent_dashboard_id"]
        doc = dashboards_collection.find_one({"dashboard_id": parent_dashboard_id})
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Dashboard {parent_dashboard_id} not found.",
        )
    return doc


def _require_editor(parent_doc: dict, user: User) -> None:
    """Block non-editors. Lazy-imports the permission helper to avoid cycles."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        check_project_permission,
    )

    project_id = parent_doc.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard has no project_id.")
    if not check_project_permission(project_id, user, "editor"):
        raise HTTPException(
            status_code=403,
            detail="Editor permission required to modify global filters or stories.",
        )


def _require_viewer(parent_doc: dict, user: User) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        check_project_permission,
    )

    project_id = parent_doc.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard has no project_id.")
    if not check_project_permission(project_id, user, "viewer"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this dashboard.",
        )


def _user_state_key(user_id: PyObjectId, parent_dashboard_id: PyObjectId) -> dict:
    return {
        "user_id": ObjectId(user_id),
        "parent_dashboard_id": ObjectId(parent_dashboard_id),
    }


def _get_user_state(user_id: PyObjectId, parent_dashboard_id: PyObjectId) -> dict:
    return (
        user_dashboard_state_collection.find_one(_user_state_key(user_id, parent_dashboard_id))
        or {}
    )


# ============================================================================
# Handlers (mounted from routes.py)
# ============================================================================


async def get_global_state(parent_dashboard_id: PyObjectId, current_user: User) -> dict:
    """Return definitions, journeys, and the current user's per-user overrides.

    Shape:
        {
            "definitions": [GlobalFilterDef, ...],
            "journeys": [Journey, ...],
            "user_values": {filter_id: value, ...},
            "last_active_journey_id": str | None,
            "last_active_journey_stop_id": str | None,
            "journey_stops": {journey_id: stop_id, ...},
        }
    """
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)

    user_state = _get_user_state(current_user.id, parent["dashboard_id"])

    return convert_objectid_to_str(
        {
            "definitions": parent.get("global_filters", []) or [],
            "journeys": parent.get("journeys", []) or [],
            "user_values": user_state.get("global_filter_values", {}) or {},
            "last_active_journey_id": user_state.get("last_active_journey_id"),
            "last_active_journey_stop_id": user_state.get("last_active_journey_stop_id"),
            "journey_stops": user_state.get("journey_stops", {}) or {},
        }
    )


async def upsert_global_filter(
    parent_dashboard_id: PyObjectId,
    filter_def: GlobalFilterDef,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_editor(parent, current_user)

    new_def = filter_def.model_dump(mode="json")
    existing = list(parent.get("global_filters") or [])
    idx = next((i for i, f in enumerate(existing) if f.get("id") == new_def["id"]), -1)
    if idx >= 0:
        existing[idx] = new_def
    else:
        existing.append(new_def)

    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$set": {"global_filters": existing}},
    )
    return {"success": True, "global_filters": existing}


async def delete_global_filter(
    parent_dashboard_id: PyObjectId,
    filter_id: str,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_editor(parent, current_user)

    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$pull": {"global_filters": {"id": filter_id}}},
    )

    # Journey stops carry a full filter_state snapshot keyed by global filter
    # id. We don't rewrite stops on demote — `mergeWithGlobal` already
    # tolerates unknown filter ids when applying a stop, so a stale key just
    # becomes a no-op. Keeps demote idempotent and avoids touching every stop.

    # Drop the per-user values for this filter
    user_dashboard_state_collection.update_many(
        {"parent_dashboard_id": ObjectId(parent["dashboard_id"])},
        {"$unset": {f"global_filter_values.{filter_id}": ""}},
    )

    return {"success": True}


async def patch_filter_value(
    parent_dashboard_id: PyObjectId,
    filter_id: str,
    body: FilterValuePatch,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)

    if not any(f.get("id") == filter_id for f in (parent.get("global_filters") or [])):
        raise HTTPException(status_code=404, detail=f"Global filter {filter_id} not found.")

    user_dashboard_state_collection.update_one(
        _user_state_key(current_user.id, parent["dashboard_id"]),
        {
            "$set": {
                f"global_filter_values.{filter_id}": body.value,
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {
                "user_id": ObjectId(current_user.id),
                "parent_dashboard_id": ObjectId(parent["dashboard_id"]),
            },
        },
        upsert=True,
    )
    return {"success": True}


async def upsert_journey(
    parent_dashboard_id: PyObjectId,
    journey: Journey,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_editor(parent, current_user)

    new_journey = journey.model_dump(mode="json")
    existing = list(parent.get("journeys") or [])
    idx = next((i for i, j in enumerate(existing) if j.get("id") == new_journey["id"]), -1)
    if idx >= 0:
        existing[idx] = new_journey
    else:
        existing.append(new_journey)

    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$set": {"journeys": existing}},
    )
    return {"success": True, "journeys": existing}


async def delete_journey(
    parent_dashboard_id: PyObjectId,
    journey_id: str,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_editor(parent, current_user)

    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$pull": {"journeys": {"id": journey_id}}},
    )
    # Clear any user who had this as their active journey so they fall back
    # to Free Explore. Also drop the per-journey resume bookkeeping.
    user_dashboard_state_collection.update_many(
        {
            "parent_dashboard_id": ObjectId(parent["dashboard_id"]),
            "last_active_journey_id": journey_id,
        },
        {"$set": {"last_active_journey_id": None, "last_active_journey_stop_id": None}},
    )
    user_dashboard_state_collection.update_many(
        {"parent_dashboard_id": ObjectId(parent["dashboard_id"])},
        {"$unset": {f"journey_stops.{journey_id}": ""}},
    )
    return {"success": True}


async def patch_active_journey(
    parent_dashboard_id: PyObjectId,
    body: ActiveJourneyPatch,
    current_user: User,
) -> dict:
    """Set the active journey + which stop is active, atomically.

    ``journey_id=None`` exits the active journey entirely. ``stop_id`` is
    persisted both as the top-level ``last_active_journey_stop_id`` and in
    the per-journey ``journey_stops`` dict so picking the same journey
    later resumes at its last stop.
    """
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)

    if body.journey_id is not None:
        journey = next(
            (j for j in (parent.get("journeys") or []) if j.get("id") == body.journey_id),
            None,
        )
        if journey is None:
            raise HTTPException(status_code=404, detail=f"Journey {body.journey_id} not found.")
        if body.stop_id is not None and not any(
            s.get("id") == body.stop_id for s in (journey.get("stops") or [])
        ):
            raise HTTPException(
                status_code=404,
                detail=f"Stop {body.stop_id} not found in journey {body.journey_id}.",
            )

    set_fields: dict[str, Any] = {
        "last_active_journey_id": body.journey_id,
        "last_active_journey_stop_id": body.stop_id,
        "updated_at": datetime.utcnow(),
    }
    # Record the active stop into the per-journey resume map so next time
    # the user picks this journey they land back on the same stop.
    if body.journey_id is not None and body.stop_id is not None:
        set_fields[f"journey_stops.{body.journey_id}"] = body.stop_id

    user_dashboard_state_collection.update_one(
        _user_state_key(current_user.id, parent["dashboard_id"]),
        {
            "$set": set_fields,
            "$setOnInsert": {
                "user_id": ObjectId(current_user.id),
                "parent_dashboard_id": ObjectId(parent["dashboard_id"]),
            },
        },
        upsert=True,
    )
    return {"success": True}


async def compute_funnel(
    parent_dashboard_id: PyObjectId,
    body: FunnelRequest,
    current_user: User,
) -> dict:
    """Return cumulative row counts per target DC after each step.

    For each target DC, loads the DataFrame once and applies the cumulative
    filter chain in memory via ``apply_runtime_filters``. A step that has
    no link matching a given target DC leaves the count unchanged for that
    DC. Returns ``{ dc_id: [N0, N1, ...] }`` with ``len() == len(steps) + 1``.

    On data load failure for a DC, returns ``None`` in place of its list so
    the UI can degrade gracefully without dragging down the whole widget.
    """
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)

    # Build per-step lookup of which (column, value) applies to each target DC.
    definitions_by_id = {f["id"]: f for f in (parent.get("global_filters") or [])}

    # Lazy import: data loading machinery is heavy and the funnel route is the
    # only place in this module that needs it.
    from depictio.api.v1.deltatables_utils import (
        apply_runtime_filters,
        load_deltatable_lite,
    )

    result: dict[str, list[int] | None] = {}

    for target in body.target_dcs:
        try:
            df = load_deltatable_lite(
                workflow_id=ObjectId(target.wf_id),
                data_collection_id=ObjectId(target.dc_id),
                metadata=None,
            )
        except Exception as exc:
            logger.warning(f"funnel: failed to load DC {target.dc_id}: {exc}; skipping target.")
            result[target.dc_id] = None
            continue

        counts: list[int] = [int(df.height)]
        accumulated: list[dict] = []

        for step in body.steps:
            definition = definitions_by_id.get(step.filter_id)
            link = None
            if definition:
                link = next(
                    (
                        link_
                        for link_ in (definition.get("links") or [])
                        if str(link_.get("dc_id")) == str(target.dc_id)
                    ),
                    None,
                )

            if link is None or step.value in (None, [], "", False):
                counts.append(counts[-1])
                continue

            accumulated.append(
                {
                    "column_name": link.get("column_name"),
                    "interactive_component_type": (
                        definition.get("interactive_component_type") if definition else "Select"
                    ),
                    "value": step.value,
                }
            )
            try:
                filtered = apply_runtime_filters(df, list(accumulated))
                counts.append(int(filtered.height))
            except Exception as exc:
                logger.warning(
                    f"funnel: filter application failed for DC {target.dc_id} at step "
                    f"{step.filter_id}: {exc}; carrying previous count."
                )
                counts.append(counts[-1])

        result[target.dc_id] = counts

    return {"counts": result}
