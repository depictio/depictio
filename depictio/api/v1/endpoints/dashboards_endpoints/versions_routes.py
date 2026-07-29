"""HTTP surface for dashboard version history.

Mounted under ``/dashboards`` **before** ``routes.py`` so these paths are
matched first: that module declares ``GET /{dashboard_id}/yaml`` and
``GET /{dashboard_id}/json``, and a greedy path parameter there would happily
swallow ``/versions/...``.

Permissions come from the same ``check_project_permission`` helper the rest of
the dashboard routes use, resolved through the family's main tab. One
deliberate deviation: deleting a version requires **owner**, not editor.
Everything else here is recoverable — a bad restore is undone by restoring the
version before it — but erasing history is not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints import version_store, versioning
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import (
    sync_tab_family_permissions,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.users import User

dashboard_versions_endpoint_router = APIRouter()


# ── request bodies ──────────────────────────────────────────────────────────


class PinVersionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)


class RenameVersionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)


class CreateVersionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)


# ── shared resolution + guards ──────────────────────────────────────────────


def _load_dashboard(dashboard_id: PyObjectId | str) -> dict[str, Any]:
    try:
        oid = ObjectId(str(dashboard_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid dashboard id: {exc}") from exc

    doc = dashboards_collection.find_one({"dashboard_id": oid}) or dashboards_collection.find_one(
        {"_id": oid}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    return doc


def _resolve_family(dashboard_id: PyObjectId | str) -> tuple[ObjectId, dict[str, Any]]:
    """Return the family id and the family's main-tab document.

    Permissions live on the project, and a child tab inherits its parent's, so
    every guard resolves through the main tab rather than the tab that was
    addressed.
    """
    doc = _load_dashboard(dashboard_id)
    family_id = versioning.resolve_family_id(doc)
    if family_id is None:
        raise HTTPException(
            status_code=500, detail="Dashboard is not associated with a tab family."
        )

    main = dashboards_collection.find_one({"dashboard_id": family_id})
    if not main:
        raise HTTPException(status_code=404, detail="Dashboard family's main tab not found.")
    return family_id, main


def _require(main_doc: dict[str, Any], user: User, level: str) -> ObjectId:
    """Enforce a permission level against the family's project."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    project_id = main_doc.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if not check_project_permission(project_id, user, level):
        raise HTTPException(
            status_code=403, detail=f"You don't have {level} permission on this dashboard."
        )
    return project_id


def _version_or_404(version_id: str) -> dict[str, Any]:
    record = version_store.get_version(version_id)
    if not record:
        raise HTTPException(status_code=404, detail="Version not found.")
    return record


def _guarded_version(version_id: str, user: User, level: str) -> dict[str, Any]:
    """Fetch a version and check the caller may act on it at ``level``.

    The permission check is anchored on the *family recorded in the version*,
    so a caller cannot reach another project's history by guessing a
    ``version_id``.
    """
    record = _version_or_404(version_id)
    _, main = _resolve_family(record["family_id"])
    _require(main, user, level)
    return record


def _summarise(record: dict[str, Any]) -> dict[str, Any]:
    """Timeline row. ``tabs`` is already projected away by the store.

    The counts are read from the stored fields, falling back to counting
    ``tabs`` for records written before those fields existed — the list
    endpoint projects ``tabs`` away, so that fallback only fires on the
    single-record reads that keep it.
    """
    kinds: dict[str, int] = {}
    for stamp in record.get("data_collections") or []:
        kind = stamp.get("version_kind", "none")
        kinds[kind] = kinds.get(kind, 0) + 1

    tabs = record.get("tabs") or []
    tab_count = record.get("tab_count")
    component_count = record.get("component_count")
    if tab_count is None:
        tab_count = len(tabs)
    if component_count is None:
        component_count = sum(len(t.get("stored_metadata") or []) for t in tabs)

    return {
        "version_id": record.get("version_id"),
        "family_id": record.get("family_id"),
        "seq": record.get("seq"),
        "kind": record.get("kind", "auto"),
        "label": record.get("label"),
        "pinned": bool(record.get("pinned", False)),
        "author_id": record.get("author_id"),
        "author_email": record.get("author_email"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "save_count": record.get("save_count", 1),
        "content_hash": record.get("content_hash", ""),
        "tab_count": tab_count,
        "component_count": component_count,
        "parent_version_id": record.get("parent_version_id"),
        "data_version_kinds": kinds,
    }


# ── read ────────────────────────────────────────────────────────────────────


@dashboard_versions_endpoint_router.get("/{dashboard_id}/versions")
async def list_dashboard_versions(
    dashboard_id: PyObjectId,
    limit: int = Query(default=50, ge=1, le=200),
    before_seq: int | None = Query(default=None),
    pinned_only: bool = Query(default=False),
    current_user: User = Depends(get_user_or_anonymous),
):
    """Version timeline for a dashboard family, newest first."""
    family_id, main = _resolve_family(dashboard_id)
    _require(main, current_user, "viewer")

    records = version_store.list_versions(
        str(family_id), limit=limit, before_seq=before_seq, pinned_only=pinned_only
    )
    summaries = [_summarise(r) for r in records]

    # Which entry, if any, matches what is live right now. Computed from the
    # content hash rather than "the newest version", because the newest version
    # can be stale relative to a save that was skipped as a no-op.
    live_hash = _live_content_hash(family_id)
    current_version_id = next(
        (s["version_id"] for s in summaries if s["content_hash"] == live_hash), None
    )

    return convert_objectid_to_str(
        {
            "family_id": str(family_id),
            "total": version_store.count_versions(str(family_id)),
            "current_version_id": current_version_id,
            "versions": summaries,
        }
    )


def _live_content_hash(family_id: ObjectId) -> str:
    docs = versioning.load_family_docs(family_id)
    if not docs:
        return ""
    return versioning.compute_content_hash(versioning.build_tab_snapshots(docs))


@dashboard_versions_endpoint_router.get("/{dashboard_id}/versions/current")
async def current_dashboard_version(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
):
    """The version whose content matches the live dashboard, if any."""
    family_id, main = _resolve_family(dashboard_id)
    _require(main, current_user, "viewer")

    live_hash = _live_content_hash(family_id)
    match = None
    for record in version_store.list_versions(str(family_id), limit=200):
        if record.get("content_hash") == live_hash:
            match = record
            break

    return {
        "version_id": match["version_id"] if match else None,
        "seq": match.get("seq") if match else None,
        "content_hash": live_hash,
    }


@dashboard_versions_endpoint_router.get("/versions/{version_id}")
async def get_dashboard_version(
    version_id: str,
    current_user: User = Depends(get_user_or_anonymous),
):
    """One version in full, including the snapshot."""
    record = _guarded_version(version_id, current_user, "viewer")
    record.pop("_id", None)
    return convert_objectid_to_str(record)


# ── write ───────────────────────────────────────────────────────────────────


@dashboard_versions_endpoint_router.post("/{dashboard_id}/versions")
async def create_dashboard_version(
    dashboard_id: PyObjectId,
    payload: CreateVersionRequest,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Name the dashboard's current state.

    ``kind="explicit"``, so it never folds into a neighbouring autosave and is
    kept for the full retention window.

    When the current state is already the newest version — the common case,
    since every save records one — this names *that* version rather than
    writing a duplicate. Naming is idempotent from the user's side: they asked
    for "this state, under this name", and they get exactly one entry either
    way.
    """
    family_id, main = _resolve_family(dashboard_id)
    _require(main, current_user, "editor")

    record = versioning.capture_dashboard_version(
        dashboard_id, kind="explicit", author=current_user, label=payload.label
    )
    if record is not None:
        return {"version_id": record.version_id, "seq": record.seq, "label": record.label}

    # Nothing was written because the content is unchanged. Label the version
    # that already holds this exact state, and seal it so a later autosave
    # cannot fold into and rewrite what the user just named.
    latest = version_store.latest_version(str(family_id))
    if latest is None:
        raise HTTPException(
            status_code=409,
            detail="No version could be created for this dashboard.",
        )

    updates: dict[str, Any] = {
        "label": payload.label,
        "kind": "explicit",
        "coalesce_until": latest.get("created_at") or datetime.now(),
    }
    updated = version_store.set_version_fields(latest["version_id"], updates) or latest
    return {
        "version_id": updated["version_id"],
        "seq": updated.get("seq"),
        "label": updated.get("label"),
    }


@dashboard_versions_endpoint_router.post("/versions/{version_id}/pin")
async def pin_dashboard_version(
    version_id: str,
    payload: PinVersionRequest,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Pin a version so retention can never remove it.

    Pinning also *seals* the version: ``coalesce_until`` is pulled back to the
    creation instant so the next autosave opens a fresh version instead of
    folding into — and rewriting — the state the user just chose to keep.
    """
    record = _guarded_version(version_id, current_user, "editor")

    updates: dict[str, Any] = {
        "pinned": True,
        "coalesce_until": record.get("created_at") or datetime.now(),
    }
    if payload.label is not None:
        updates["label"] = payload.label

    updated = version_store.set_version_fields(version_id, updates)
    return _summarise(updated or record)


@dashboard_versions_endpoint_router.delete("/versions/{version_id}/pin")
async def unpin_dashboard_version(
    version_id: str,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Unpin a version, making it eligible for retention again."""
    record = _guarded_version(version_id, current_user, "editor")
    updated = version_store.set_version_fields(version_id, {"pinned": False})
    return _summarise(updated or record)


@dashboard_versions_endpoint_router.patch("/versions/{version_id}")
async def rename_dashboard_version(
    version_id: str,
    payload: RenameVersionRequest,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Set or clear a version's label."""
    record = _guarded_version(version_id, current_user, "editor")
    updated = version_store.set_version_fields(version_id, {"label": payload.label})
    return _summarise(updated or record)


@dashboard_versions_endpoint_router.delete("/versions/{version_id}")
async def delete_dashboard_version(
    version_id: str,
    force: bool = Query(default=False),
    current_user: User = Depends(get_user_or_anonymous),
):
    """Erase one version.

    Requires **owner**: unlike a restore, this is not recoverable. A pinned
    version additionally needs ``force=true``, so the pin has to be overridden
    deliberately rather than by a mis-click.
    """
    record = _guarded_version(version_id, current_user, "owner")

    if record.get("pinned") and not force:
        raise HTTPException(
            status_code=409,
            detail="This version is pinned. Unpin it first, or pass force=true.",
        )

    family_id = record["family_id"]
    if version_store.count_versions(family_id) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a dashboard's only version.",
        )

    version_store.delete_version(version_id)
    return {"deleted": True, "version_id": version_id}


# ── restore ─────────────────────────────────────────────────────────────────

#: Snapshot fields written back onto a live tab document. Derived from the
#: snapshot model minus its identity field, so adding a content field to
#: TabSnapshot automatically restores it — while `permissions`, `is_public`
#: and `project_id` remain structurally unreachable, because a TabSnapshot
#: never holds them in the first place.
_RESTORABLE_FIELDS: tuple[str, ...] = tuple(
    name
    for name in (
        "title",
        "subtitle",
        "main_tab_name",
        "tab_icon",
        "tab_icon_color",
        "icon",
        "icon_color",
        "icon_variant",
        "workflow_system",
        "notes_content",
        "stored_metadata",
        "left_panel_layout_data",
        "right_panel_layout_data",
        "tab_order",
        "is_main_tab",
    )
)


def _rehydrate_ids(value: Any) -> Any:
    """Undo the snapshot's ObjectId→str flattening before writing back.

    ``versioning._jsonify`` stringifies ObjectIds so a snapshot is plain JSON
    and hashes deterministically. Writing that back verbatim would leave a
    restored dashboard's components carrying string ``dc_id`` / ``wf_id``,
    which no ``find_one({"data_collection_id": ObjectId(...)})`` on the read
    path can match: the dashboard returns structurally intact but renders no
    data, which reads as "restore did nothing".

    Deliberately the same rule ``MongoModel.mongo`` applies on the normal save
    path — any string that is a valid ObjectId becomes one — so a restored
    document is byte-identical to one the save endpoint would have written.
    Sharing that quirk is the point: a divergence here would mean restore and
    save produce different documents from the same content.
    """
    if isinstance(value, dict):
        return {k: _rehydrate_ids(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rehydrate_ids(v) for v in value]
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    return value


@dashboard_versions_endpoint_router.post("/versions/{version_id}/restore")
async def restore_dashboard_version(
    version_id: str,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Put a past version back, without destroying the present.

    The current state is captured as a version *before* anything is written,
    so a restore is always undoable by restoring the entry that precedes the
    new restore point. That pre-capture is a no-op when the live state already
    matches the newest version — the usual case — so a restore normally adds
    exactly one entry to the timeline.

    Only content is written. ``permissions``, ``is_public`` and ``project_id``
    are never taken from the snapshot — a months-old version must not be able
    to re-grant access that has since been revoked.
    """
    record = _guarded_version(version_id, current_user, "editor")

    family_id = ObjectId(record["family_id"])
    main = dashboards_collection.find_one({"dashboard_id": family_id})
    if not main:
        raise HTTPException(status_code=404, detail="Dashboard family's main tab not found.")

    snapshot_tabs = record.get("tabs") or []
    if not snapshot_tabs:
        raise HTTPException(
            status_code=422,
            detail="This version holds no tab snapshot and cannot be restored.",
        )

    # Capture the pre-restore state first, so the state being replaced is never
    # unrecoverable — precisely the situation restore exists to prevent. Writes
    # nothing when the live content already matches the newest version.
    versioning.capture_quietly(family_id, kind="explicit", author=current_user)

    live_docs = versioning.load_family_docs(family_id)
    live_by_id = {str(d.get("dashboard_id") or d.get("_id")): d for d in live_docs}
    snapshot_by_id = {str(t["dashboard_id"]): t for t in snapshot_tabs}

    updated, created, deleted = 0, 0, 0

    for tab_id, tab in snapshot_by_id.items():
        # `_rehydrate_ids` undoes the snapshot's ObjectId→str flattening.
        # Without it a restored dashboard's components carry string `dc_id`s,
        # which every `find_one({"data_collection_id": ObjectId(...)})` lookup
        # on the read path then fails to match — the dashboard comes back
        # structurally correct but renders no data.
        content = {f: _rehydrate_ids(tab[f]) for f in _RESTORABLE_FIELDS if f in tab}
        if tab_id in live_by_id:
            dashboards_collection.update_one({"dashboard_id": ObjectId(tab_id)}, {"$set": content})
            updated += 1
        else:
            # A tab that existed in the snapshot but has since been deleted.
            # Recreate it, taking access control from the *live* parent.
            doc = dict(content)
            doc["_id"] = ObjectId(tab_id)
            doc["dashboard_id"] = ObjectId(tab_id)
            doc["project_id"] = main.get("project_id")
            doc["permissions"] = main.get("permissions")
            doc["is_public"] = main.get("is_public", False)
            doc["parent_dashboard_id"] = None if tab.get("is_main_tab") else family_id
            dashboards_collection.insert_one(doc)
            created += 1

    # Tabs added after the snapshot are removed, so the family matches the
    # version exactly. The main tab is never deleted.
    for tab_id, doc in live_by_id.items():
        if tab_id in snapshot_by_id:
            continue
        if doc.get("is_main_tab", False) or str(family_id) == tab_id:
            continue
        dashboards_collection.delete_one({"dashboard_id": ObjectId(tab_id)})
        deleted += 1

    # Keep child-tab access in step with the parent, as the tab CRUD routes do.
    try:
        sync_tab_family_permissions(
            PyObjectId(str(family_id)),
            new_permissions=main.get("permissions"),
            new_is_public=main.get("is_public", False),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"restore: permission sync failed for {family_id}: {exc}")

    restored = versioning.capture_quietly(
        family_id, kind="restore", author=current_user, parent_version_id=version_id
    )

    return {
        "restored_from": version_id,
        "restored_from_seq": record.get("seq"),
        "new_version_id": restored.version_id if restored else None,
        "tabs_updated": updated,
        "tabs_created": created,
        "tabs_deleted": deleted,
    }
