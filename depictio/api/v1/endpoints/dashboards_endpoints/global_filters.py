"""Cross-tab global filters & journeys — API logic.

Global filters and journeys live on the **parent** dashboard document
(``is_main_tab=True``). Per-user state (last-used filter values, last
active journey) lives in ``user_dashboard_state_collection`` so each
user maintains their own view without overwriting collaborators.

Wired into the existing ``dashboards_endpoint_router`` from
``routes.py``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Literal

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    projects_collection,
    user_dashboard_state_collection,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import GlobalFilterDef, Journey
from depictio.models.models.links import DCLink
from depictio.models.models.users import User

# ============================================================================
# Request bodies
# ============================================================================


class FilterValuePatch(BaseModel):
    value: Any = None


class FunnelStepInput(BaseModel):
    """A single step in a funnel chain — global filter OR local filter, with its current value.

    Global step: ``scope='global'`` + ``global_filter_id``. Server resolves
    the column via the matching ``GlobalFilterDef.links`` entry per target
    DC.

    Local step: ``scope='local'`` + ``tab_id`` + ``component_index`` +
    ``column_name`` + ``interactive_component_type``. When ``source_dc_id``
    is set, the step applies to that DC directly (used for tabs that carry
    multiple DCs — the tab→DC index fallback can pick the wrong one).
    Legacy steps without ``source_dc_id`` fall back to the
    ``tab_dc_index[tab_id]`` lookup.
    """

    scope: str = "global"
    value: Any = None
    # Global step refs
    global_filter_id: str | None = None
    # Local step refs
    tab_id: str | None = None
    component_index: str | None = None
    column_name: str | None = None
    interactive_component_type: str | None = None
    source_dc_id: str | None = None


class FunnelTargetDC(BaseModel):
    wf_id: str
    dc_id: str


class FunnelRequest(BaseModel):
    """Request body for :func:`compute_funnel`.

    ``metric`` selects how each step's surviving rows are measured:
    ``"rows"`` returns ``df.height``; ``"nunique"`` returns
    ``df[metric_column].n_unique()``. ``metric_column`` is required when
    ``metric="nunique"``; unknown columns yield ``0``. Derived display modes
    (``% survived``, ``step drop %``, ``abs drop``) are computed client-side
    from the raw values returned here, so they don't need backend support.
    """

    steps: list[FunnelStepInput] = Field(default_factory=list)
    target_dcs: list[FunnelTargetDC] = Field(default_factory=list)
    metric: Literal["rows", "nunique"] = "rows"
    metric_column: str | None = None


class JourneyPreviewRequest(BaseModel):
    """Request body for :func:`compute_journey_preview`.

    Returns the top ``limit`` rows of ``target_dc`` (unfiltered) plus a
    parallel ``removed_at_step`` array marking which step first removed
    each row (``None`` if it survived all). Fires on-demand from the
    "View filtered rows" button — not on every filter keystroke.
    """

    steps: list[FunnelStepInput] = Field(default_factory=list)
    target_dc: FunnelTargetDC
    limit: int = 200


class ActiveJourneyPatch(BaseModel):
    """Sets the user's active journey (which funnel to view).

    ``journey_id=None`` exits the active journey entirely. The pin-based
    funnel model carries no per-step user state — a journey is a
    declarative list of pinned filters, so we only persist the active
    journey id.
    """

    journey_id: str | None = None


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


def _rename_id_key(doc: dict) -> dict:
    """Move a top-level ``_id`` to ``id`` on a shallow dict.

    ``MongoModel.mongo()`` renames every ``id`` recursively to ``_id`` on
    save (see :func:`depictio.models.models.base.MongoModel.mongo`), so
    journeys, journey steps, and global filter definitions land in Mongo
    keyed as ``_id``. The Pydantic models expect ``id`` on the wire, so
    we flip it back on every read path. Idempotent — safe on docs that
    already have ``id``.
    """
    if "_id" in doc and "id" not in doc:
        new_doc = {"id": doc["_id"]}
        for k, v in doc.items():
            if k != "_id":
                new_doc[k] = v
        return new_doc
    return doc


def _normalize_journey(journey: dict) -> dict:
    """Apply ``_id``→``id`` to the journey and each of its steps."""
    journey = _rename_id_key(dict(journey))
    journey["steps"] = [_rename_id_key(dict(s)) for s in (journey.get("steps") or [])]
    return journey


async def get_global_state(parent_dashboard_id: PyObjectId, current_user: User) -> dict:
    """Return definitions, journeys, and the current user's per-user overrides.

    Shape:
        {
            "definitions": [GlobalFilterDef, ...],
            "journeys": [Journey, ...],
            "user_values": {filter_id: value, ...},
            "last_active_journey_id": str | None,
        }
    """
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)

    user_state = _get_user_state(current_user.id, parent["dashboard_id"])

    definitions = [_rename_id_key(dict(f)) for f in (parent.get("global_filters") or [])]
    journeys = [_normalize_journey(dict(j)) for j in (parent.get("journeys") or [])]

    return convert_objectid_to_str(
        {
            "definitions": definitions,
            "journeys": journeys,
            "user_values": user_state.get("global_filter_values", {}) or {},
            "last_active_journey_id": user_state.get("last_active_journey_id"),
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
    # Normalize existing entries to `id` (legacy entries stored as `_id` by
    # the recursive id→_id rename in MongoModel.mongo()).
    existing = [_rename_id_key(dict(f)) for f in (parent.get("global_filters") or [])]
    idx = next((i for i, f in enumerate(existing) if f.get("id") == new_def["id"]), -1)
    if idx >= 0:
        existing[idx] = new_def
    else:
        existing.append(new_def)

    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$set": {"global_filters": existing}},
    )
    return convert_objectid_to_str({"success": True, "global_filters": existing})


async def delete_global_filter(
    parent_dashboard_id: PyObjectId,
    filter_id: str,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_editor(parent, current_user)

    # Normalize legacy `_id`-keyed entries before filtering. A direct
    # ``$pull`` by ``id`` would miss those legacy docs.
    existing = [_rename_id_key(dict(f)) for f in (parent.get("global_filters") or [])]
    filtered = [f for f in existing if f.get("id") != filter_id]
    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$set": {"global_filters": filtered}},
    )

    # Journey steps may reference this global filter id. We don't rewrite
    # them on demote — the funnel evaluator tolerates unknown filter ids
    # (the step simply yields no narrowing), so stale references degrade to
    # a no-op. Keeps demote idempotent and avoids touching every journey.

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

    if not any(
        _rename_id_key(dict(f)).get("id") == filter_id for f in (parent.get("global_filters") or [])
    ):
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


def _build_tab_order_map(parent_dashboard_id: PyObjectId) -> dict[str, int]:
    """Map ``tab_id (str) -> tab_order (int)`` for ordering steps across tabs.

    Includes the parent (main tab, ``tab_order=0`` by convention) plus all
    children, fetched with the existing ascending-by-``tab_order`` sort.
    """
    tab_orders: dict[str, int] = {}
    parent = dashboards_collection.find_one({"dashboard_id": ObjectId(parent_dashboard_id)})
    if parent:
        tab_orders[str(parent["dashboard_id"])] = int(parent.get("tab_order", 0) or 0)
    for child in dashboards_collection.find(
        {"parent_dashboard_id": ObjectId(parent_dashboard_id)}
    ).sort("tab_order", 1):
        tab_orders[str(child["dashboard_id"])] = int(child.get("tab_order", 0) or 0)
    return tab_orders


def _resort_journey_steps(journey_dict: dict, tab_orders: dict[str, int]) -> None:
    """Sort steps in-place by ``(tab_order, order_within_tab)``.

    Steps whose ``tab_id`` is not in ``tab_orders`` (e.g. deleted tab) are
    dropped silently to keep stale data from blocking the upsert.
    """
    steps = list(journey_dict.get("steps") or [])
    steps = [s for s in steps if str(s.get("tab_id")) in tab_orders]
    steps.sort(
        key=lambda s: (
            tab_orders.get(str(s.get("tab_id")), 0),
            int(s.get("order_within_tab", 0) or 0),
        )
    )
    journey_dict["steps"] = steps


async def upsert_journey(
    parent_dashboard_id: PyObjectId,
    journey: Journey,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_editor(parent, current_user)

    new_journey = journey.model_dump(mode="json")
    tab_orders = _build_tab_order_map(parent["dashboard_id"])
    _resort_journey_steps(new_journey, tab_orders)

    # Normalize existing entries: legacy docs were saved through
    # MongoModel.mongo() which renamed `id` → `_id` recursively, so older
    # journeys/steps may still be `_id`-keyed in Mongo. Flip them back so
    # the persisted array is canonical going forward.
    existing = [_normalize_journey(dict(j)) for j in (parent.get("journeys") or [])]
    idx = next((i for i, j in enumerate(existing) if j.get("id") == new_journey["id"]), -1)
    if idx >= 0:
        existing[idx] = new_journey
    else:
        existing.append(new_journey)

    # Enforce single is_default per dashboard: if this journey is being
    # marked default, demote any previously-default journey.
    #
    # KNOWN LIMITATION: concurrent first-pin auto-creation (two sessions
    # both seeing an empty journeys list) is last-writer-wins because we
    # rewrite the whole `journeys` array. Real exposure is narrow (only
    # the very first pin on a dashboard with no journeys); follow-up fix
    # is optimistic-concurrency via expected-count or a `$push` with a
    # guard filter on the array length.
    if new_journey.get("is_default"):
        for j in existing:
            if j.get("id") != new_journey["id"]:
                j["is_default"] = False

    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$set": {"journeys": existing}},
    )
    return convert_objectid_to_str({"success": True, "journeys": existing})


async def delete_journey(
    parent_dashboard_id: PyObjectId,
    journey_id: str,
    current_user: User,
) -> dict:
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_editor(parent, current_user)

    # Normalize legacy `_id`-keyed entries before filtering, same reason
    # as ``delete_global_filter``.
    existing = [_normalize_journey(dict(j)) for j in (parent.get("journeys") or [])]
    filtered = [j for j in existing if j.get("id") != journey_id]
    dashboards_collection.update_one(
        {"dashboard_id": parent["dashboard_id"]},
        {"$set": {"journeys": filtered}},
    )
    # Clear any user who had this as their active journey so they fall back
    # to Free Explore.
    user_dashboard_state_collection.update_many(
        {
            "parent_dashboard_id": ObjectId(parent["dashboard_id"]),
            "last_active_journey_id": journey_id,
        },
        {"$set": {"last_active_journey_id": None}},
    )
    return {"success": True}


async def patch_active_journey(
    parent_dashboard_id: PyObjectId,
    body: ActiveJourneyPatch,
    current_user: User,
) -> dict:
    """Set or clear the user's active journey.

    ``journey_id=None`` exits the active journey entirely. The pin-based
    funnel model carries no per-step state — the journey is declarative,
    so we only persist the active journey id.
    """
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)

    if body.journey_id is not None:
        journey = next(
            (
                j
                for j in (_normalize_journey(dict(j)) for j in (parent.get("journeys") or []))
                if j.get("id") == body.journey_id
            ),
            None,
        )
        if journey is None:
            raise HTTPException(status_code=404, detail=f"Journey {body.journey_id} not found.")

    user_dashboard_state_collection.update_one(
        _user_state_key(current_user.id, parent["dashboard_id"]),
        {
            "$set": {
                "last_active_journey_id": body.journey_id,
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


_EMPTY_STEP_VALUES: tuple[Any, ...] = (None, [], "", False)


def _is_empty_step_value(value: Any) -> bool:
    """A step with an empty value is a no-op — carry the previous count forward."""
    return value in _EMPTY_STEP_VALUES


def _step_applies_to_target(
    step: FunnelStepInput,
    target: FunnelTargetDC,
    definitions_by_id: dict[str, dict],
    tab_dc_index: dict[str, tuple[str, str]],
) -> dict | None:
    """Return the ``(column_name, interactive_component_type)`` for a step on a target DC.

    For global steps: matches via ``GlobalFilterDef.links`` entry whose
    ``dc_id`` equals the target. For local steps: prefer the step's own
    ``source_dc_id`` (set at pin-time) and fall back to the tab→DC index
    when missing — legacy journeys persisted before ``source_dc_id`` existed
    rely on the tab-level lookup, which picks a tab's first DC and can
    misroute on multi-DC tabs.

    Returns ``None`` when the step doesn't apply to this target (carry
    previous count forward).
    """
    if _is_empty_step_value(step.value):
        return None

    target_dc = str(target.dc_id)

    if step.scope == "local":
        if not step.column_name:
            return None
        resolved_dc = _resolve_step_source_dc_id(step, tab_dc_index)
        if resolved_dc is None or resolved_dc != target_dc:
            return None
        return {
            "column_name": step.column_name,
            "interactive_component_type": step.interactive_component_type or "Select",
            "value": step.value,
        }

    # Global step
    definition = definitions_by_id.get(step.global_filter_id or "")
    if not definition:
        return None
    link = next(
        (
            link_
            for link_ in (definition.get("links") or [])
            if str(link_.get("dc_id")) == target_dc
        ),
        None,
    )
    if link is None:
        return None
    return {
        "column_name": link.get("column_name"),
        "interactive_component_type": definition.get("interactive_component_type") or "Select",
        "value": step.value,
    }


# Per-dashboard mongo metadata is read-only during a normal session
# (changes only when someone edits the dashboard or project links).
# Caching the two heavy lookups for 30s removes ~3 mongo round-trips
# from every funnel call — significant when filters fire rapidly.
_META_CACHE_TTL_S = 30.0
_tab_dc_index_cache: dict[str, tuple[float, dict[str, tuple[str, str]]]] = {}
_project_links_cache: dict[str, tuple[float, list[DCLink]]] = {}


def _load_project_links(parent_doc: dict) -> list[DCLink]:
    """Return the project's enabled ``DCLink`` definitions, or ``[]``.

    Used by the funnel to project a local step's filter from its source DC
    onto other target DCs (e.g. Phylum on the taxonomy DC narrows the
    metadata DC via a sample-keyed link). Disabled or malformed links are
    silently dropped — the funnel keeps rendering even when the project
    has stale link definitions.

    Results are cached for ``_META_CACHE_TTL_S`` seconds keyed by
    ``project_id`` — project links rarely change inside a session, so
    re-fetching on every funnel call (every filter keystroke!) burns
    mongo round-trips for no reason.
    """
    project_id = parent_doc.get("project_id")
    if not project_id:
        return []
    key = str(project_id)
    cached = _project_links_cache.get(key)
    if cached and (time.perf_counter() - cached[0]) < _META_CACHE_TTL_S:
        return cached[1]
    try:
        project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"funnel: failed to load project {project_id} for links: {exc}")
        return []
    if not project_doc:
        _project_links_cache[key] = (time.perf_counter(), [])
        return []
    out: list[DCLink] = []
    for raw in project_doc.get("links") or []:
        try:
            link = DCLink(**raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"funnel: skipping malformed project link: {exc}")
            continue
        if link.enabled:
            out.append(link)
    _project_links_cache[key] = (time.perf_counter(), out)
    return out


def _resolve_step_source_dc_id(
    step: FunnelStepInput, tab_dc_index: dict[str, tuple[str, str]]
) -> str | None:
    """Return the DC a local step's filter operates on.

    Prefers the step's own ``source_dc_id`` (set at pin-time post-Phase 1);
    falls back to the tab→DC index for legacy steps. Mirrors the resolution
    that :func:`_step_applies_to_target` does so the Phase 2 link-reach
    branch uses the same source DC the native branch already validated.
    Returns ``None`` when neither path resolves.
    """
    if step.source_dc_id:
        return str(step.source_dc_id)
    if not step.tab_id:
        return None
    tab_target = tab_dc_index.get(str(step.tab_id))
    return str(tab_target[1]) if tab_target else None


def _find_link(links: list[DCLink], source_dc_id: str | None, target_dc_id: str) -> DCLink | None:
    """Return the first link from ``source_dc_id`` to ``target_dc_id``.

    Callers pass the already-filtered enabled-links list from
    :func:`_load_project_links`, so enablement is not re-checked here.
    """
    if not source_dc_id:
        return None
    source = str(source_dc_id)
    target = str(target_dc_id)
    return next(
        (
            link
            for link in links
            if str(link.source_dc_id) == source and str(link.target_dc_id) == target
        ),
        None,
    )


def _resolve_source_values(
    step: FunnelStepInput,
    source_dc_id: str,
    source_column: str,
    source_df_cache: dict[str, Any],
    wf_id_for_dc: dict[str, str],
) -> list[Any] | None:
    """Filter the source DC by the step's filter and return unique source-column values.

    Identical for every target reached via the same source — callers cache
    by ``(step_idx, source_dc_id, source_column)`` so multiple per-target
    link projections don't re-filter the source. Returns ``None`` on load
    or filter failure, or when the column is missing / no rows survive.
    """
    import polars as pl

    from depictio.api.v1.deltatables_utils import (
        apply_runtime_filters,
        load_deltatable_lite,
    )

    if not step.column_name:
        return None

    source_df = source_df_cache.get(source_dc_id)
    if source_df is None:
        source_wf_id = wf_id_for_dc.get(source_dc_id)
        if not source_wf_id:
            return None
        try:
            source_df = load_deltatable_lite(
                workflow_id=ObjectId(source_wf_id),
                data_collection_id=ObjectId(source_dc_id),
                metadata=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"funnel: failed to load source DC {source_dc_id}: {exc}")
            return None
        source_df_cache[source_dc_id] = source_df

    step_filter = {
        "column_name": step.column_name,
        "interactive_component_type": step.interactive_component_type or "Select",
        "value": step.value,
    }
    try:
        filtered_source = apply_runtime_filters(source_df, [step_filter])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"funnel: source-side filter failed on DC {source_dc_id}: {exc}")
        return None

    if source_column not in filtered_source.columns:
        logger.warning(f"funnel: source_column {source_column!r} missing on DC {source_dc_id}")
        return None

    values = (
        filtered_source.select(pl.col(source_column).cast(pl.Utf8, strict=False))
        .drop_nulls()
        .unique()
        .to_series()
        .to_list()
    )
    return values or None


def _resolve_via_link(
    link: DCLink,
    source_values: list[Any],
) -> dict | None:
    """Wrap pre-resolved source values into an applied-dict via the link's resolver.

    The source-side filter+unique work is target-independent and lives in
    :func:`_resolve_source_values`. This step is per-link (per-target):
    the resolver maps source values to target values, and the wrapper
    targets ``link.link_config.target_field`` (falling back to
    ``link.source_column`` when the link doesn't rename).
    """
    from depictio.api.v1.endpoints.links_endpoints.resolvers import get_resolver

    try:
        resolver = get_resolver(link.link_config.resolver)
    except ValueError as exc:
        logger.warning(f"funnel: unknown resolver {link.link_config.resolver!r}: {exc}")
        return None
    resolved, _unmapped = resolver.resolve(source_values, link.link_config)
    if not resolved:
        return None

    target_column = link.link_config.target_field or link.source_column
    return {
        "column_name": target_column,
        "interactive_component_type": "MultiSelect",
        "value": resolved,
    }


def _measure_df(df, metric: str, metric_column: str | None) -> int:
    """Compute the funnel cell value for a DataFrame slice.

    ``metric="rows"`` returns ``df.height``; ``metric="nunique"`` returns
    ``df[metric_column].n_unique()``. Missing/unknown columns yield ``0``
    rather than raising — funnel evaluation is best-effort, and a bad
    column shouldn't tank the response.
    """
    if metric == "nunique":
        if not metric_column or metric_column not in df.columns:
            return 0
        return int(df.select(metric_column).n_unique())
    return int(df.height)


def _build_tab_dc_index(parent_dashboard_id: PyObjectId) -> dict[str, tuple[str, str]]:
    """Map ``tab_id (str) -> (wf_id, dc_id)`` for each tab that has a primary DC.

    Local funnel steps need this to know which target DC their tab maps
    to. The primary DC is derived from the first interactive component's
    metadata on the tab; if a tab has multiple DCs, only the first one is
    indexed (limitation of the MVP; matches the existing assumption that
    a filter component is bound to one DC).

    Cached for ``_META_CACHE_TTL_S`` seconds keyed by parent dashboard id
    — tab structure rarely changes inside a session, so the mongo
    ``find()`` over all child tabs is wasted work on every funnel call.
    """
    key = str(parent_dashboard_id)
    cached = _tab_dc_index_cache.get(key)
    if cached and (time.perf_counter() - cached[0]) < _META_CACHE_TTL_S:
        return cached[1]
    index: dict[str, tuple[str, str]] = {}
    candidates = list(
        dashboards_collection.find(
            {
                "$or": [
                    {"dashboard_id": ObjectId(parent_dashboard_id)},
                    {"parent_dashboard_id": ObjectId(parent_dashboard_id)},
                ]
            }
        )
    )
    for doc in candidates:
        for comp in doc.get("stored_metadata", []) or []:
            wf_id = comp.get("wf_id") or comp.get("workflow_id")
            dc_id = comp.get("dc_id") or comp.get("data_collection_id")
            if wf_id and dc_id:
                index[str(doc["dashboard_id"])] = (str(wf_id), str(dc_id))
                break
    _tab_dc_index_cache[key] = (time.perf_counter(), index)
    return index


async def compute_funnel(
    parent_dashboard_id: PyObjectId,
    body: FunnelRequest,
    current_user: User,
) -> dict:
    """Return cumulative measurements per target DC after each step.

    Steps are global (filter applies via ``GlobalFilterDef.links``) or
    local (filter applies only to its tab's DC). A step that doesn't
    apply to a given target carries the previous value forward, and that
    cell is marked ``False`` in the ``applicable`` matrix so the client
    can render it as a no-op (dimmed cell) without re-deriving the link
    logic.

    The ``body.metric`` toggle picks between ``rows`` (``df.height``) and
    ``nunique`` (``n_unique`` of ``metric_column``). Missing/unknown
    columns yield ``0``.

    Returns ``{counts: { dc_id: [N0, ...] }, applicable: { dc_id: [bool, ...] }}``.
    Each list has ``len() == len(steps) + 1`` (slot 0 = ``All rows``, always
    applicable). On data load failure for a DC, returns ``None`` for both.
    """
    t_start = time.perf_counter()
    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)
    t_parent = time.perf_counter()

    # Normalize legacy `_id`-keyed entries written by MongoModel.mongo()
    # before indexing — same fix as get_global_state / upsert_*.
    definitions_by_id = {
        f["id"]: f for f in (_rename_id_key(dict(f)) for f in (parent.get("global_filters") or []))
    }
    tab_dc_index = _build_tab_dc_index(parent["dashboard_id"])
    project_links = _load_project_links(parent)
    t_meta = time.perf_counter()

    # wf_id lookup for source DCs that aren't in the targets list — required
    # to load their deltatable when resolving a link.
    wf_id_for_dc: dict[str, str] = {td.dc_id: td.wf_id for td in body.target_dcs}
    for wf, dc in tab_dc_index.values():
        wf_id_for_dc.setdefault(str(dc), str(wf))
    for definition in definitions_by_id.values():
        for link in definition.get("links") or []:
            dc = link.get("dc_id")
            wf = link.get("wf_id")
            if dc and wf:
                wf_id_for_dc.setdefault(str(dc), str(wf))

    from depictio.api.v1.deltatables_utils import (
        apply_runtime_filters,
        load_deltatable_lite,
    )

    metric = body.metric
    metric_column = body.metric_column

    counts_by_dc: dict[str, list[int] | None] = {}
    applicable_by_dc: dict[str, list[bool] | None] = {}
    # Shared across targets: a DC loaded once, e.g. when one source DC
    # projects onto multiple target DCs via different links.
    source_df_cache: dict[str, Any] = {}
    # Source-side filter+unique result is target-independent — three targets
    # reached from the same source via different links share the same set.
    # Keyed by (step_idx, source_dc_id, source_column).
    source_values_cache: dict[tuple[int, str, str], list[Any] | None] = {}

    # Parallelize cold-cache target loads. On warm cache (Redis/memory)
    # each call returns nearly instantly, so to_thread overhead is small;
    # on cold cache the S3 fetches run concurrently.
    def _load(target: FunnelTargetDC):
        t0 = time.perf_counter()
        try:
            df = load_deltatable_lite(
                workflow_id=ObjectId(target.wf_id),
                data_collection_id=ObjectId(target.dc_id),
                metadata=None,
            )
            return target, df, None, time.perf_counter() - t0
        except Exception as exc:  # noqa: BLE001
            return target, None, exc, time.perf_counter() - t0

    results = await asyncio.gather(*[asyncio.to_thread(_load, t) for t in body.target_dcs])
    t_loaded = time.perf_counter()
    # Per-DC load timing so the user can see if any single target is
    # blowing past the budget (cache miss vs. hit, S3 vs. local).
    for target, _df, _err, elapsed in results:
        logger.info(f"funnel: load_dc dc={target.dc_id} elapsed={elapsed:.3f}s")
    loaded = [(t, df, err) for (t, df, err, _) in results]

    for target, df, err in loaded:
        if df is None:
            logger.warning(f"funnel: failed to load DC {target.dc_id}: {err}; skipping target.")
            counts_by_dc[target.dc_id] = None
            applicable_by_dc[target.dc_id] = None
            continue
        # Share with the link resolver so a target that's also a source for
        # a later link doesn't reload.
        source_df_cache[str(target.dc_id)] = df

        counts: list[int] = [_measure_df(df, metric, metric_column)]
        applicable: list[bool] = [True]  # "All rows" slot always applies.
        accumulated: list[dict] = []

        for step_idx, step in enumerate(body.steps):
            applied = _step_applies_to_target(step, target, definitions_by_id, tab_dc_index)
            # Cross-DC reach: when a local step doesn't natively apply to this
            # target, try to project its filter via a project DCLink (e.g.
            # Phylum on taxonomy_rel_abundance narrows metadata via the
            # samplesheet→metadata sample link). Resolve the source DC the
            # same way the native branch does so legacy steps without an
            # explicit ``source_dc_id`` still get cross-DC reach via the
            # tab→DC fallback.
            if applied is None and step.scope == "local" and not _is_empty_step_value(step.value):
                source_dc_id = _resolve_step_source_dc_id(step, tab_dc_index)
                link = _find_link(project_links, source_dc_id, str(target.dc_id))
                # _find_link returns None unless source_dc_id is truthy, so a
                # non-None link implies a usable source_dc_id.
                if link is not None and source_dc_id:
                    cache_key = (step_idx, source_dc_id, link.source_column)
                    if cache_key not in source_values_cache:
                        source_values_cache[cache_key] = _resolve_source_values(
                            step,
                            source_dc_id,
                            link.source_column,
                            source_df_cache,
                            wf_id_for_dc,
                        )
                    source_values = source_values_cache[cache_key]
                    if source_values:
                        applied = _resolve_via_link(link, source_values)
            if applied is None:
                counts.append(counts[-1])
                applicable.append(False)
                continue
            accumulated.append(applied)
            try:
                filtered = apply_runtime_filters(df, list(accumulated))
                counts.append(_measure_df(filtered, metric, metric_column))
                applicable.append(True)
            except Exception as exc:
                step_ref = step.global_filter_id or step.component_index or "?"
                logger.warning(
                    f"funnel: filter application failed for DC {target.dc_id} at step "
                    f"{step_ref}: {exc}; carrying previous count."
                )
                counts.append(counts[-1])
                # We did want to apply this step, but evaluation failed — mark
                # it as not applicable so the UI doesn't claim the filter ran.
                applicable.append(False)

        counts_by_dc[target.dc_id] = counts
        applicable_by_dc[target.dc_id] = applicable

    t_done = time.perf_counter()
    # Single punchy line so the user can grep / paste one log entry to
    # diagnose where the seconds are going. Order: cheap → expensive.
    logger.info(
        f"[funnel-timing] total={t_done - t_start:.3f}s "
        f"parent={t_parent - t_start:.3f}s "
        f"meta={t_meta - t_parent:.3f}s "
        f"load={t_loaded - t_meta:.3f}s "
        f"steps={t_done - t_loaded:.3f}s "
        f"targets={len(body.target_dcs)} nsteps={len(body.steps)}"
    )

    return {"counts": counts_by_dc, "applicable": applicable_by_dc}


async def compute_journey_preview(
    parent_dashboard_id: PyObjectId,
    body: JourneyPreviewRequest,
    current_user: User,
) -> dict:
    """Return up to ``limit`` rows of ``body.target_dc`` annotated with their removal step.

    For each row sampled from the unfiltered target DC, we report which
    step first removed it (or ``None`` if it survived the full chain).
    The UI uses this to render a single table where rows are colored by
    when they got filtered out, and a step selector to show subsets.

    Per-step "applies" semantics match :func:`compute_funnel` exactly,
    including cross-DC link resolution — so the per-row annotation maps
    to the same counts the funnel shows.

    Returns ``{"columns": [...], "rows": [dict], "removed_at_step":
    [int | None], "total": int, "survivors": int, "step_drops":
    list[int]}``. ``total`` = unfiltered row count, ``survivors`` =
    rows surviving all steps, ``step_drops[i]`` = rows first removed at
    step ``i``.
    """

    parent = _load_parent_or_404(parent_dashboard_id)
    _require_viewer(parent, current_user)

    definitions_by_id = {
        f["id"]: f for f in (_rename_id_key(dict(f)) for f in (parent.get("global_filters") or []))
    }
    tab_dc_index = _build_tab_dc_index(parent["dashboard_id"])
    project_links = _load_project_links(parent)

    wf_id_for_dc: dict[str, str] = {body.target_dc.dc_id: body.target_dc.wf_id}
    for wf, dc in tab_dc_index.values():
        wf_id_for_dc.setdefault(str(dc), str(wf))

    from depictio.api.v1.deltatables_utils import (
        apply_runtime_filters,
        load_deltatable_lite,
    )

    target = body.target_dc
    try:
        df = await asyncio.to_thread(
            load_deltatable_lite,
            workflow_id=ObjectId(target.wf_id),
            data_collection_id=ObjectId(target.dc_id),
            metadata=None,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load DC {target.dc_id}: {exc}",
        ) from exc

    # Resolve each step's applied-filter against this target. None means
    # the step doesn't narrow this DC — we still track it in the result
    # so the UI's step selector matches the journey's step indices.
    source_df_cache: dict[str, Any] = {str(target.dc_id): df}
    per_step_filter: list[dict | None] = []
    for step in body.steps:
        applied = _step_applies_to_target(step, target, definitions_by_id, tab_dc_index)
        if applied is None and step.scope == "local" and not _is_empty_step_value(step.value):
            source_dc_id = _resolve_step_source_dc_id(step, tab_dc_index)
            link = _find_link(project_links, source_dc_id, str(target.dc_id))
            if link is not None and source_dc_id:
                source_values = _resolve_source_values(
                    step, source_dc_id, link.source_column, source_df_cache, wf_id_for_dc
                )
                if source_values:
                    applied = _resolve_via_link(link, source_values)
        per_step_filter.append(applied)

    # Annotate each row with a 0-indexed `_step` column = step at which
    # it was first removed (-1 means survived all). Build via incremental
    # anti-joins so each row is processed once per step.
    df_id = df.with_row_index("_funnel_rowid")
    # `removed_at` accumulates row_id -> step_idx as steps are applied.
    removed_at: dict[int, int] = {}
    survived = df_id
    accumulated: list[dict] = []
    step_drops: list[int] = []
    for step_idx, applied in enumerate(per_step_filter):
        if applied is None:
            # Step is a no-op for this target — every survivor carries
            # forward, no rows removed.
            step_drops.append(0)
            continue
        accumulated.append(applied)
        try:
            # Apply the FULL accumulated chain to the original (row-id'd)
            # df rather than incrementally to `survived`, so the filter
            # semantics match `compute_funnel` exactly.
            next_survivors = apply_runtime_filters(df_id, list(accumulated))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"funnel/preview: filter eval failed at step {step_idx} on DC {target.dc_id}: {exc}"
            )
            accumulated.pop()
            step_drops.append(0)
            continue
        # Anti-join: rows in `survived` not in `next_survivors`. These
        # rows are first removed at this step (we never touch them again).
        removed_now = (
            survived.join(next_survivors.select("_funnel_rowid"), on="_funnel_rowid", how="anti")
            .select("_funnel_rowid")
            .to_series()
            .to_list()
        )
        for rid in removed_now:
            removed_at[int(rid)] = step_idx
        step_drops.append(len(removed_now))
        survived = next_survivors

    # Sample top N unfiltered rows for display; annotate with their
    # removal step (or None for survivors).
    limit = max(1, min(body.limit, 1000))
    head = df_id.head(limit)
    head_rowids = head.select("_funnel_rowid").to_series().to_list()
    removed_at_step = [removed_at.get(int(r)) for r in head_rowids]
    # Drop the internal id column from the user-visible payload.
    head_rows = head.drop("_funnel_rowid").to_dicts()
    columns = [c for c in df.columns if c != "_funnel_rowid"]

    return {
        "columns": columns,
        "rows": head_rows,
        "removed_at_step": removed_at_step,
        "total": int(df.height),
        "survivors": int(survived.height),
        "step_drops": step_drops,
    }
