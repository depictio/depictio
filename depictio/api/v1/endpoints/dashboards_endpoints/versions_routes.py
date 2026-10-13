"""HTTP surface for dashboard version history.

Mounted under ``/dashboards`` **before** ``routes.py`` so these paths are
matched first: that module declares ``GET /{dashboard_id}/yaml`` and
``GET /{dashboard_id}/json``, and a greedy path parameter there would happily
swallow ``/versions/...``.

Permissions come from the same helpers the rest of the dashboard routes use,
resolved through the family's main tab: reading is project-level, as
``GET /dashboards/get`` is, and writing goes through
``check_dashboard_mutation_permission``, so whoever may save the dashboard may
use its history. One deliberate deviation: deleting a version requires
**owner**, not editor. Everything else here is recoverable (a bad restore is
undone by restoring the version before it), but erasing history is not.
"""

from __future__ import annotations

from typing import Any, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints import (
    schema_integrity,
    version_store,
    versioning,
)
from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import (
    sync_tab_family_permissions,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboard_versions import TAB_IDENTITY_FIELDS, TabSnapshot
from depictio.models.models.users import User
from depictio.models.timestamps import preserved_creation_time, utc_now_naive, utc_now_str

dashboard_versions_endpoint_router = APIRouter()


# ── request bodies ──────────────────────────────────────────────────────────


class PinVersionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)


class RenameVersionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)


class CreateVersionRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)


class RestoreComponentRequest(BaseModel):
    """Put one component back, leaving every other component alone."""

    component_index: str = Field(min_length=1, max_length=200)
    #: The tab the component sits on in that version. An index is only unique
    #: within a tab: two tabs once derived the same id from the same tag, and a
    #: lookup by index alone restored whichever came first into the wrong tab.
    tab_id: str = Field(min_length=1, max_length=64)
    #: Restore the component's place too: its grid position and size, and the
    #: section, group or panel it sat in. Off by default: the usual request is
    #: "give me back what this chart *showed*", and moving the surrounding
    #: layout to satisfy it is a surprise. On, when the place is itself the
    #: thing being restored.
    restore_layout: bool = False


#: Component fields that say *where* it sits in the dashboard, not what it
#: shows. They belong with its grid entry, so they follow ``restore_layout``.
#: Taken from the snapshot otherwise, a component restored from before the
#: dashboard had sections loses its section; its grid entry, kept from the
#: live layout, is relative to that section, so the tile lands on top of the
#: unsectioned tiles and the whole grid recompacts around it.
_PLACEMENT_FIELDS: tuple[str, ...] = (
    "section",
    "group",
    "parent_index",
    "panel",
    "placement",
    "fit",
)


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
    """Enforce a permission level against the family's main tab.

    ``viewer`` is the project-level check ``GET /dashboards/get`` makes, so the
    timeline is never readable by someone who cannot open the dashboard.
    ``editor`` and ``owner`` are the checks the save and delete routes make,
    which also let the dashboard's own owners through (a visitor's copy in a
    public project, whose owner holds no project role): whoever can save a
    dashboard can undo the save, and whoever can delete it can delete a version.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        check_dashboard_mutation_permission,
        check_project_permission,
    )

    project_id = main_doc.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")

    if level == "viewer":
        allowed = check_project_permission(project_id, user, level)
    else:
        allowed = check_dashboard_mutation_permission(main_doc, user, level)
    if not allowed:
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
    """Timeline row. ``tabs`` is already projected away by the store."""
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
        # Read the persisted counts, not a derivation over `tabs` — the list
        # query projects `tabs` away, so deriving here would always yield 0.
        "tab_count": record.get("tab_count", 0),
        "component_count": record.get("component_count", 0),
        "parent_version_id": record.get("parent_version_id"),
        "data_version_kinds": versioning.count_data_version_kinds(
            record.get("data_collections") or []
        ),
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
    match = next(
        (
            record
            for record in version_store.list_versions(str(family_id), limit=200)
            if record.get("content_hash") == live_hash
        ),
        None,
    )

    return {
        "version_id": match["version_id"] if match else None,
        "seq": match.get("seq") if match else None,
        "content_hash": live_hash,
    }


@dashboard_versions_endpoint_router.get("/versions/{version_id}/compatibility")
async def dashboard_version_compatibility(
    version_id: str,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Can this version still render against today's data?

    Answered per data collection, naming the columns that changed and the
    components that reference them — a pair of schema hashes can only say
    "different", which is not something anyone can act on.
    """
    record = _guarded_version(version_id, current_user, "viewer")

    components = [
        component
        for tab in (record.get("tabs") or [])
        for component in (tab.get("stored_metadata") or [])
    ]
    report = schema_integrity.build_compatibility_report(
        components, record.get("data_collections") or []
    )
    report["version_id"] = version_id
    report["seq"] = record.get("seq")
    return convert_objectid_to_str(report)


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

#: Status for each reason a capture can skip other than unchanged content.
_SKIPPED_STATUS: dict[str, int] = {"disabled": 409, "missing": 404, "oversized": 413}


@dashboard_versions_endpoint_router.post("/{dashboard_id}/versions")
async def create_dashboard_version(
    dashboard_id: PyObjectId,
    payload: CreateVersionRequest,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Name the dashboard's current state.

    ``kind="explicit"``, so it never folds into a neighbouring autosave and is
    kept for the full retention window.

    When the current state is already the newest version (the common case,
    since every save records one), this names *that* version rather than
    writing a duplicate. It never names a version whose content differs from
    the live state: a snapshot that could not be taken at all is an error that
    says why, 409 when versioning is off and 413 when the dashboard is over
    the size cap.
    """
    family_id, main = _resolve_family(dashboard_id)
    _require(main, current_user, "editor")

    try:
        record = versioning.capture_dashboard_version(
            dashboard_id, kind="explicit", author=current_user, label=payload.label, strict=True
        )
    except versioning.CaptureSkipped as skipped:
        raise HTTPException(
            status_code=_SKIPPED_STATUS[skipped.reason], detail=str(skipped)
        ) from skipped
    if record is not None:
        return {"version_id": record.version_id, "seq": record.seq, "label": record.label}

    # Unchanged content: name the version that holds it. Checked again here,
    # because a save landing since the capture may have moved the live state on.
    latest = version_store.latest_version(str(family_id))
    if latest is None or latest.get("content_hash") != _live_content_hash(family_id):
        raise HTTPException(
            status_code=409,
            detail="The dashboard changed while it was being named. Try again.",
        )

    # A null label names nothing, so it leaves an existing name alone.
    updates: dict[str, Any] = {} if payload.label is None else {"label": payload.label}
    if latest.get("kind") == "auto":
        # Sealed, so a later autosave cannot fold into what the user just named.
        updated = version_store.seal_version(latest, updates)
    elif updates:
        # An import, restore or explicit version keeps its kind.
        updated = version_store.set_version_fields(latest["version_id"], updates)
    else:
        updated = latest
    updated = updated or latest
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
        "coalesce_until": record.get("created_at") or utc_now_naive(),
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
#: snapshot model minus its identity fields, so adding a content field to
#: TabSnapshot automatically restores it — while `permissions`, `is_public`
#: and `project_id` remain structurally unreachable, because a TabSnapshot
#: never holds them in the first place.
_RESTORABLE_FIELDS: tuple[str, ...] = tuple(
    name for name in TabSnapshot.model_fields if name not in TAB_IDENTITY_FIELDS
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

    Only the fields a stored tab holds are written, so a version recorded
    before a setting existed leaves that setting as it is live rather than
    resetting it to a default.
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

    # A restore is an edit like a save: the listing's thumbnail cache-buster
    # and "last modified" column must move with it.
    saved_ts = utc_now_str()
    updated, created, deleted = 0, 0, 0

    for tab_id, tab in snapshot_by_id.items():
        live = live_by_id.get(tab_id)
        # Rehydrated, or the restored components carry string `dc_id`s and
        # render no data (see `_rehydrate_ids`).
        content = {f: _rehydrate_ids(tab[f]) for f in _RESTORABLE_FIELDS if f in tab}
        unset: dict[str, str] = {}
        if "brand_theme" in content:
            theme = versioning.restorable_brand_theme(
                content.pop("brand_theme"), (live or {}).get("brand_theme")
            )
            # No override at that version and no logo now: drop the field, as
            # PATCH /appearance does for an empty theme, so the tab inherits
            # again. A live logo is never dropped (see `restorable_brand_theme`).
            if theme is None:
                unset["brand_theme"] = ""
            else:
                content["brand_theme"] = theme
        content["last_saved_ts"] = saved_ts

        if live is not None:
            update: dict[str, Any] = {"$set": content}
            if unset:
                update["$unset"] = unset
            dashboards_collection.update_one({"dashboard_id": ObjectId(tab_id)}, update)
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
            # The id's own timestamp: the tab is the one created back then.
            doc["creation_time"] = preserved_creation_time(None, doc["_id"], saved_ts)
            # Its import origin comes back with it, so the next refresh of its
            # YAML finds this tab instead of adding a second one.
            if tab.get("source_key"):
                doc["source_key"] = tab["source_key"]
            dashboards_collection.insert_one(doc)
            created += 1

    # Tabs added after the snapshot are removed, so the family matches the
    # version exactly. The main tab is never deleted. Their comment threads are
    # left in place on purpose: restoring a later version recreates the tab
    # under the same id, and its threads are then still attached to it.
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

    # The listing thumbnail shows the main tab, which may just have changed
    # completely. Forced, as an explicit Save is: a restore is deliberate.
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dashboard_routes

    dashboard_routes._queue_screenshot(str(family_id), current_user, force=True)

    return {
        "restored_from": version_id,
        "restored_from_seq": record.get("seq"),
        "new_version_id": restored.version_id if restored else None,
        "tabs_updated": updated,
        "tabs_created": created,
        "tabs_deleted": deleted,
    }


@dashboard_versions_endpoint_router.post("/versions/{version_id}/restore_component")
async def restore_component_from_version(
    version_id: str,
    payload: RestoreComponentRequest,
    current_user: User = Depends(get_user_or_anonymous),
):
    """Put **one** component back, leaving the rest of the dashboard alone.

    Restoring a whole version to recover a single chart is a blunt instrument:
    it reverts every other component, and any work done since, to get one thing
    back. This is the narrow edit — the component's stored config replaces the
    live one, and nothing else on the dashboard moves.

    Deliberately not simply "write the snapshot's component over the live one":

    * **Access-control fields are not restorable.** They live on the dashboard
      document rather than the component, so they cannot travel through here,
      and that is checked by construction rather than by hoping.
    * **The layout is opt-in.** ``restore_layout`` is off by default because
      the common request is "give me back what this chart showed", and silently
      shuffling neighbours to reinstate an old grid position is a second,
      unasked-for change. Off, the component keeps its live place: grid entry
      *and* section, group and panel, which a grid entry is relative to.
    * **A component absent from the live dashboard is re-added.** Restoring a
      component someone deleted is the single most valuable case, so it is
      supported rather than 404'd — placed using the snapshot's layout, since
      there is no live position to preserve.

    Like a full restore, the pre-change state is captured first, so this is
    undoable by restoring the version that precedes the new entry.
    """
    record = _guarded_version(version_id, current_user, "editor")
    index = payload.component_index

    family_id = ObjectId(record["family_id"])
    main = dashboards_collection.find_one({"dashboard_id": family_id})
    if not main:
        raise HTTPException(status_code=404, detail="Dashboard family's main tab not found.")

    # Locate the component in the snapshot by tab and index: a component
    # restored into the wrong tab would be as good as lost.
    located = next(
        (
            (tab, component)
            for tab in record.get("tabs") or []
            if str(tab.get("dashboard_id") or "") == payload.tab_id
            for component in tab.get("stored_metadata") or []
            if str(component.get("index") or "") == index
        ),
        None,
    )
    if located is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Component {index} does not exist on tab {payload.tab_id} in version {version_id}."
            ),
        )
    snapshot_tab, snapshot_component = located

    tab_id = ObjectId(str(snapshot_tab["dashboard_id"]))
    live_tab = dashboards_collection.find_one({"dashboard_id": tab_id})
    if not live_tab:
        raise HTTPException(
            status_code=409,
            detail=(
                "The tab this component belonged to no longer exists. "
                "Restore the full version instead."
            ),
        )

    # Capture before writing, so this edit is undoable exactly like a full
    # restore. No-ops when the live state already matches the newest version.
    versioning.capture_quietly(family_id, kind="explicit", author=current_user)

    restored_component = _rehydrate_ids(snapshot_component)

    components = list(live_tab.get("stored_metadata") or [])
    position = next(
        (i for i, component in enumerate(components) if str(component.get("index") or "") == index),
        None,
    )
    replaced = position is not None
    if position is None:
        components.append(restored_component)
    else:
        if not payload.restore_layout:
            restored_component = _with_placement_of(restored_component, components[position])
        components[position] = restored_component

    # An edit like a save, as a full restore is: the listing's thumbnail
    # cache-buster and "last modified" column move with it.
    update: dict[str, Any] = {"stored_metadata": components, "last_saved_ts": utc_now_str()}

    # A re-added component has no live position to keep, so its snapshot
    # layout is the only sane placement — otherwise it lands wherever the
    # grid's fallback puts it, typically on top of something else.
    layout_restored = payload.restore_layout or not replaced
    if layout_restored:
        for field_name in ("left_panel_layout_data", "right_panel_layout_data"):
            entry = _layout_entry_for(snapshot_tab.get(field_name), index)
            if entry is not None:
                update[field_name] = _with_layout_entry(live_tab.get(field_name), index, entry)

    dashboards_collection.update_one({"dashboard_id": tab_id}, {"$set": update})

    captured = versioning.capture_quietly(
        family_id, kind="restore", author=current_user, parent_version_id=version_id
    )

    logger.info(
        f"restored component {index} from version {version_id} "
        f"({'replaced' if replaced else 're-added'}) on tab {tab_id}"
    )

    # Forced, as a full restore's is: the edit is deliberate.
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dashboard_routes

    dashboard_routes._queue_screenshot(str(family_id), current_user, force=True)

    return {
        "restored_from": version_id,
        "restored_from_seq": record.get("seq"),
        "component_index": index,
        "readded": not replaced,
        "layout_restored": layout_restored,
        "new_version_id": captured.version_id if captured else None,
    }


def _layout_entry_for(layout: Any, index: str) -> dict[str, Any] | None:
    """One component's grid entry, or None when it has no explicit position.

    Layouts are a flat list of ``{i, x, y, w, h}`` on both the live model and
    ``TabSnapshot``; a breakpoint-keyed map is not a shape either can hold, so
    it is not accepted here. Handling a shape the models reject would be dead
    code that reads as coverage.
    """
    if not isinstance(layout, list):
        return None
    for entry in layout:
        if isinstance(entry, dict) and _layout_key(entry) == index:
            return entry
    return None


def _layout_key(entry: dict[str, Any]) -> str:
    """The component index a grid entry belongs to.

    An import writes ``box-<index>`` and the editor the bare index; the
    frontend treats both as the same tile (``stripBoxPrefix``), so must this.
    """
    key = str(entry.get("i") or "")
    return key[4:] if key.startswith("box-") else key


def _with_placement_of(restored: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """``restored`` placed where ``live`` sits now (see ``_PLACEMENT_FIELDS``)."""
    placed = {k: v for k, v in restored.items() if k not in _PLACEMENT_FIELDS}
    placed.update({k: live[k] for k in _PLACEMENT_FIELDS if k in live})
    return placed


def _with_layout_entry(layout: Any, index: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Live layout with one component's entry replaced.

    Only that component is touched. Rewriting the whole layout from the
    snapshot would move every neighbour, which is precisely the blast radius
    this endpoint exists to avoid.
    """
    source = layout if isinstance(layout, list) else []
    kept = [e for e in source if not (isinstance(e, dict) and _layout_key(e) == index)]
    return [*kept, entry]
