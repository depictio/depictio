"""Capture a dashboard version on save.

The seam between "a dashboard was written" and "the version ledger". Called
after a successful write, never before: it re-reads the family from Mongo
rather than trusting the request body, so a version always holds exactly what
a subsequent ``GET`` would return.

Three properties this module exists to guarantee:

**A capture can never break a save.** Every call site wraps this in
``try/except`` (same posture as the screenshot dispatch), and internally an
oversized family is skipped with a warning rather than risking the 16 MB BSON
limit.

**Autosaves coalesce.** The editor debounces layout changes at 500 ms and
saves on every drag, so one editing session produces dozens of writes.
Without folding, the timeline would be unreadable. The window is anchored at
the version's creation rather than sliding, so a long session yields a
reviewable series instead of one entry spanning hours.

**A no-op save writes nothing.** Content is hashed and compared first, so the
async screenshot task's ``last_saved_ts`` rewrite — and any idempotent
re-save — leaves no trace, with no special-casing of those callers.

Capture is synchronous on purpose. Queued behind Celery it would race the next
save and could snapshot a state that was never current.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from pymongo import ASCENDING

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, deltatables_collection, projects_collection
from depictio.api.v1.endpoints.dashboards_endpoints import version_store
from depictio.models.models.dashboard_versions import (
    DashboardVersion,
    DataCollectionStamp,
    TabSnapshot,
    VersionKind,
)

#: Fields never carried into a snapshot.
#:
#: The first group is dead weight: Dash-era leftovers still round-tripped
#: through ``/save`` that nothing reads. Including them would make every diff
#: look noisy. (``stored_layout_data`` is the *legacy* layout field — the live
#: ones are ``left_panel_layout_data`` / ``right_panel_layout_data``.)
#:
#: The second group is a security boundary, not tidiness: a snapshot must
#: never be able to restore an access grant that was since revoked, so
#: permissions and ownership always come from the live document.
SNAPSHOT_DEAD_FIELDS: frozenset[str] = frozenset(
    {
        "buttons_data",
        "stored_add_button",
        "stored_children_data",
        "tmp_children_data",
        "stored_edit_dashboard_mode_button",
        "stored_layout_data",
    }
)
SNAPSHOT_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {"permissions", "is_public", "project_id", "_id"}
)

#: Data collection types whose storage supports each versioning mechanism.
#: ``image`` is Delta-backed for its *manifest* of image paths; the image
#: blobs themselves live at a user-supplied prefix with no content
#: addressing, which is recorded as an explicit gap rather than glossed over.
_DELTA_TYPES = frozenset({"table", "image"})
_MANIFEST_TYPES = frozenset({"multiqc", "jbrowse2"})
_ASSET_TYPES = frozenset({"geojson", "phylogeny"})


def resolve_family_id(dashboard_doc: dict[str, Any]) -> Optional[ObjectId]:
    """The main tab's ``dashboard_id`` — the subject of a version.

    A child tab's versions belong to its parent's timeline, because a version
    covers the whole family atomically.
    """
    if not dashboard_doc:
        return None
    if dashboard_doc.get("is_main_tab", True):
        raw = dashboard_doc.get("dashboard_id") or dashboard_doc.get("_id")
    else:
        raw = dashboard_doc.get("parent_dashboard_id")
    if raw is None:
        return None
    try:
        return ObjectId(str(raw))
    except Exception:
        return None


def load_family_docs(family_id: ObjectId) -> list[dict[str, Any]]:
    """Full documents for the main tab and every child, in tab order.

    Deliberately not ``get_child_tabs()``: that helper projects away
    ``stored_metadata``, which is the entire point of a snapshot.
    """
    main = dashboards_collection.find_one({"dashboard_id": family_id})
    if not main:
        main = dashboards_collection.find_one({"_id": family_id})
    if not main:
        return []

    children = list(
        dashboards_collection.find({"parent_dashboard_id": family_id}).sort("tab_order", ASCENDING)
    )
    return [main, *children]


def build_tab_snapshots(family_docs: list[dict[str, Any]]) -> list[TabSnapshot]:
    """Project each tab document down to its renderable content."""
    snapshots: list[TabSnapshot] = []
    for doc in family_docs:
        snapshots.append(
            TabSnapshot(
                dashboard_id=str(doc.get("dashboard_id") or doc.get("_id")),
                is_main_tab=bool(doc.get("is_main_tab", True)),
                tab_order=int(doc.get("tab_order", 0) or 0),
                title=str(doc.get("title", "") or ""),
                subtitle=str(doc.get("subtitle", "") or ""),
                main_tab_name=doc.get("main_tab_name"),
                tab_icon=doc.get("tab_icon"),
                tab_icon_color=doc.get("tab_icon_color"),
                icon=doc.get("icon"),
                icon_color=doc.get("icon_color"),
                icon_variant=doc.get("icon_variant"),
                workflow_system=str(doc.get("workflow_system", "none") or "none"),
                notes_content=str(doc.get("notes_content", "") or ""),
                stored_metadata=_jsonify(doc.get("stored_metadata") or []),
                left_panel_layout_data=_jsonify(doc.get("left_panel_layout_data") or []),
                right_panel_layout_data=_jsonify(doc.get("right_panel_layout_data") or []),
            )
        )
    return snapshots


def _jsonify(value: Any) -> Any:
    """Convert ObjectIds/datetimes to primitives so the snapshot round-trips.

    ``stored_metadata`` embeds ``wf_id`` / ``dc_id`` as ObjectIds and
    ``last_updated`` as a string; normalising here means the stored snapshot
    is plain JSON and hashes deterministically.
    """
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


def collect_dc_ids(tabs: list[TabSnapshot]) -> list[str]:
    """Distinct data collection ids referenced across a family.

    Reads ``dc_id`` — the key components actually carry. (The pre-existing
    export helper reads ``data_collection_id``, which appears on no component
    in any seeded dashboard, so it always found nothing.)
    """
    seen: list[str] = []
    for tab in tabs:
        for component in tab.stored_metadata:
            if not isinstance(component, dict):
                continue
            raw = component.get("dc_id")
            if not raw:
                continue
            dc_id = str(raw.get("$oid") if isinstance(raw, dict) else raw)
            if dc_id and dc_id not in seen:
                seen.append(dc_id)
    return seen


def _classify_dc(dc_type: str) -> str:
    dc_type = (dc_type or "").lower()
    if dc_type in _DELTA_TYPES:
        return "delta"
    if dc_type in _MANIFEST_TYPES:
        return "manifest"
    if dc_type in _ASSET_TYPES:
        return "asset"
    return "none"


def _dc_type_from_components(tabs: list[TabSnapshot], dc_id: str) -> str:
    """Best-effort data collection type, read from the embedded component config.

    Components carry a ``dc_config`` snapshot including ``type``. Using it
    avoids a project-document lookup per collection on the save path.
    """
    return _component_field(tabs, dc_id, lambda c: (c.get("dc_config") or {}).get("type"))


def _component_field(tabs: list[TabSnapshot], dc_id: str, pick) -> str:
    """First non-empty value ``pick`` yields from a component using ``dc_id``.

    Components referencing the same collection agree on these fields, so the
    first hit is the answer; scanning past it only costs time.
    """
    for tab in tabs:
        for component in tab.stored_metadata:
            if not isinstance(component, dict):
                continue
            raw = component.get("dc_id")
            current = str(raw.get("$oid") if isinstance(raw, dict) else raw) if raw else ""
            if current != dc_id:
                continue
            try:
                value = pick(component)
            except Exception:  # pragma: no cover - defensive
                continue
            if value:
                return str(value)
    return ""


def _dc_types_from_project(dc_ids: list[str]) -> dict[str, str]:
    """Data collection types read from the project documents that own them.

    The authority for a collection's type, and the fallback whenever the
    component's embedded ``dc_config`` has none — which is the common case, not
    a rare one: components store a *projected* config whose ``type`` is
    frequently null (confirmed on a freshly imported dashboard, where every
    component carried ``dc_config.type == None`` while the project document
    said ``table``). Without this, `_classify_dc` sees "" for every collection
    and stamps the whole version ``version_kind="none"``, so nothing is
    reproducible and data time travel has no version to travel to.

    One query for the whole set rather than one per collection: this runs on
    the save path, which is hot.
    """
    if not dc_ids:
        return {}

    object_ids = []
    for dc_id in dc_ids:
        try:
            object_ids.append(ObjectId(dc_id))
        except Exception:  # pragma: no cover - defensive
            continue
    if not object_ids:
        return {}

    types: dict[str, str] = {}
    try:
        cursor = projects_collection.find(
            {"workflows.data_collections._id": {"$in": object_ids}},
            {"workflows.data_collections._id": 1, "workflows.data_collections.config.type": 1},
        )
        wanted = {str(oid) for oid in object_ids}
        for project in cursor:
            for workflow in project.get("workflows") or []:
                for dc in workflow.get("data_collections") or []:
                    dc_id = str(dc.get("_id") or "")
                    if dc_id not in wanted:
                        continue
                    dc_type = (dc.get("config") or {}).get("type")
                    if dc_type:
                        types[dc_id] = str(dc_type)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"versioning: project dc_type lookup failed: {exc}")

    return types


def build_dc_stamps(tabs: list[TabSnapshot]) -> list[DataCollectionStamp]:
    """Record what data each referenced collection was at, right now.

    Reads only Mongo — no object-store round trip — because this runs on the
    save path. A collection with no aggregation record yields a ``none``
    stamp carrying the reason, which the UI shows rather than implying the
    version is fully reproducible.
    """
    stamps: list[DataCollectionStamp] = []

    dc_ids = collect_dc_ids(tabs)
    project_types = _dc_types_from_project(dc_ids)

    for dc_id in dc_ids:
        # Component config first (no extra I/O), project document second. The
        # embedded copy is a projection and often has a null type.
        dc_type = _dc_type_from_components(tabs, dc_id) or project_types.get(dc_id, "")
        kind = _classify_dc(dc_type)
        stamp = DataCollectionStamp(
            dc_id=dc_id,
            dc_type=dc_type,
            version_kind="none",
            # Human-readable identity for the picker; components carry both.
            workflow_tag=_component_field(tabs, dc_id, lambda c: c.get("workflow_tag")),
            data_collection_tag=_component_field(
                tabs, dc_id, lambda c: c.get("data_collection_tag")
            ),
        )

        # An image DC's manifest is versioned but its pixels are not: the blobs
        # live under a user-supplied prefix with no content addressing.
        if (dc_type or "").lower() == "image":
            stamp.unversioned_parts = ["image_pixels"]

        try:
            dt_doc = deltatables_collection.find_one({"data_collection_id": ObjectId(dc_id)})
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"versioning: deltatable lookup failed for {dc_id}: {exc}")
            dt_doc = None

        aggregations = (dt_doc or {}).get("aggregation") or []
        latest = aggregations[-1] if aggregations else None

        if kind == "delta" and latest:
            stamp.aggregation_version = latest.get("aggregation_version")
            stamp.delta_version = latest.get("delta_version")
            stamp.delta_commit_timestamp = latest.get("delta_commit_timestamp")
            stamp.row_count = latest.get("rows_total")
            stamp.columns = _columns_from_aggregation(latest)
            stamp.schema_hash = generate_schema_hash(stamp.columns)
            if stamp.delta_version is None:
                # Pre-provenance aggregations, and every UI upload, land here.
                stamp.version_kind = "none"
                stamp.reason = "no_delta_version_recorded"
            else:
                stamp.version_kind = "delta"
        elif kind == "manifest":
            # Populated in the manifest stage; the stamp records the intent and
            # the instant so a later backfill has an anchor.
            stamp.version_kind = "none"
            stamp.reason = "manifest_versioning_not_enabled"
            if latest:
                stamp.columns = _columns_from_aggregation(latest)
                stamp.schema_hash = generate_schema_hash(stamp.columns)
        elif kind == "asset":
            stamp.version_kind = "none"
            stamp.reason = "asset_versioning_not_enabled"
        else:
            stamp.reason = (
                "unknown_data_collection_type" if not dc_type else "no_aggregation_record"
            )

        stamps.append(stamp)

    return stamps


def _columns_from_aggregation(aggregation: dict[str, Any]) -> list[dict[str, str]]:
    """Column specs live on the aggregation, not on the data collection config."""
    raw = aggregation.get("aggregation_columns_specs")
    columns: list[dict[str, str]] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and entry.get("name"):
                columns.append(
                    {"name": str(entry["name"]), "type": str(entry.get("type", "") or "")}
                )
    elif isinstance(raw, dict):  # legacy shape
        for name, spec in raw.items():
            columns.append({"name": str(name), "type": str((spec or {}).get("type", "") or "")})
    return columns


def generate_schema_hash(columns: list[dict[str, str]]) -> str:
    """Stable digest of a column set, order-independent."""
    ordered = sorted(columns, key=lambda c: c.get("name", ""))
    payload = "|".join(f"{c.get('name', '')}:{c.get('type', '')}" for c in ordered)
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def compute_content_hash(tabs: list[TabSnapshot]) -> str:
    """Digest of the family's renderable content.

    Ordered by ``tab_order`` then id so tab reordering is a real change while
    Mongo's return order is not.
    """
    canonical = [
        tab.model_dump(mode="json")
        for tab in sorted(tabs, key=lambda t: (t.tab_order, t.dashboard_id))
    ]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _should_coalesce(latest: dict[str, Any], author_id: str | None, now: datetime) -> bool:
    """Fold this save into the previous version?

    Only ever folds one autosave into another autosave, by the same author,
    inside the previous version's window, when that version is neither pinned
    nor named. Pinning seals a version precisely so the next save opens a
    fresh one rather than mutating what the user chose to keep.
    """
    if latest.get("kind") != "auto":
        return False
    if latest.get("pinned") or latest.get("label"):
        return False
    if (latest.get("author_id") or None) != (author_id or None):
        return False

    until = latest.get("coalesce_until")
    if not isinstance(until, datetime):
        return False
    return now <= until


def capture_dashboard_version(
    dashboard_id: ObjectId | str,
    *,
    kind: VersionKind = "auto",
    author: Any = None,
    label: str | None = None,
    parent_version_id: str | None = None,
    now: datetime | None = None,
) -> Optional[DashboardVersion]:
    """Snapshot a dashboard family. Returns None when nothing was recorded.

    None means: versioning disabled, the dashboard is gone, the family is
    empty, the snapshot is oversized, or — the common case — the content is
    byte-identical to the newest version.
    """
    cfg = settings.dashboard_versions
    if not cfg.enabled:
        return None

    now = now or datetime.now()

    try:
        dashboard_oid = ObjectId(str(dashboard_id))
    except Exception:
        logger.warning(f"versioning: not a valid dashboard id: {dashboard_id!r}")
        return None

    anchor = dashboards_collection.find_one({"dashboard_id": dashboard_oid}) or (
        dashboards_collection.find_one({"_id": dashboard_oid})
    )
    if not anchor:
        logger.debug(f"versioning: dashboard {dashboard_id} not found; nothing to capture")
        return None

    family_id = resolve_family_id(anchor)
    if family_id is None:
        logger.warning(f"versioning: could not resolve family for {dashboard_id}")
        return None

    family_docs = load_family_docs(family_id)
    if not family_docs:
        return None

    tabs = build_tab_snapshots(family_docs)
    content_hash = compute_content_hash(tabs)
    family_key = str(family_id)
    project_id = str(anchor.get("project_id") or "")

    author_id = str(getattr(author, "id", "") or "") or None
    author_email = getattr(author, "email", None)

    latest = version_store.latest_version(family_key)

    # Nothing changed, so there is no new state to preserve.
    #
    # This applies to every kind, not just autosaves. Without it, a restore
    # whose target is already live — or any deliberate snapshot of an
    # unchanged dashboard — writes a second entry that says nothing, which is
    # what made a single restore appear as two versions.
    if latest and latest.get("content_hash") == content_hash:
        version_store.touch_version(latest["version_id"], now)
        return None

    stamps = build_dc_stamps(tabs)

    record = DashboardVersion(
        version_id=uuid.uuid4().hex,
        family_id=family_key,
        project_id=project_id,
        seq=0,  # replaced below unless we coalesce
        kind=kind,
        label=label,
        author_id=author_id,
        author_email=author_email,
        created_at=now,
        updated_at=now,
        coalesce_until=now + timedelta(seconds=cfg.coalesce_window_seconds),
        content_hash=content_hash,
        tabs=tabs,
        data_collections=stamps,
        parent_version_id=parent_version_id,
    )

    # mode="python" so datetimes stay real datetimes: they are stored as BSON
    # dates and read back as datetimes, which the coalescing window and the
    # prune policy both compare against. Serialising them to ISO strings here
    # would silently disable both. Every other field is already a primitive —
    # `_jsonify` flattened the ObjectIds out of stored_metadata.
    payload = record.model_dump(mode="python")
    size = len(json.dumps(payload, default=str))
    if size > cfg.max_snapshot_bytes:
        logger.warning(
            f"versioning: skipping capture for {family_key} — snapshot is {size} bytes, "
            f"over the {cfg.max_snapshot_bytes} limit"
        )
        return None

    if latest and kind == "auto" and _should_coalesce(latest, author_id, now):
        version_store.fold_into_version(
            latest["version_id"],
            {
                "tabs": payload["tabs"],
                "data_collections": payload["data_collections"],
                "content_hash": content_hash,
                "tab_count": payload["tab_count"],
                "component_count": payload["component_count"],
                "updated_at": now,
            },
        )
        record.version_id = latest["version_id"]
        record.seq = int(latest.get("seq", 1))
        record.created_at = latest.get("created_at", now)
        record.save_count = int(latest.get("save_count", 1)) + 1
        return record

    record.seq = version_store.next_seq(family_key)
    payload["seq"] = record.seq
    version_store.insert_version(payload)
    version_store.maybe_prune_family(family_key, now=now)
    return record


def capture_quietly(dashboard_id: ObjectId | str, **kwargs: Any) -> Optional[DashboardVersion]:
    """``capture_dashboard_version`` that can never propagate an exception.

    The save path uses this: a version is a nice-to-have, a saved dashboard is
    not. Mirrors the screenshot-enqueue block's posture in ``routes.py``.
    """
    try:
        return capture_dashboard_version(dashboard_id, **kwargs)
    except Exception as exc:  # noqa: BLE001 — versioning must never break a save
        logger.warning(f"versioning: capture failed for {dashboard_id}: {exc}")
        return None


def ensure_baseline_quietly(
    dashboard_id: ObjectId | str, *, author: Any = None
) -> Optional[DashboardVersion]:
    """Record the state a dashboard is in *before* its first tracked write.

    Capture runs after a save, so every version describes a state the user has
    already moved to. For a dashboard that predates the ledger — which is every
    existing dashboard — that leaves its original state permanently
    unreachable: the first edit is recorded, but the thing being edited is not.
    Users read that as "restore does not go back to the original", and they are
    right.

    So the very first write to a family seeds a baseline from the live document
    first. Called *before* the write, unlike every other capture. It is a
    one-time cost per family: the ledger is non-empty from then on, and the
    check is a single indexed count.

    Labelled rather than left bare, because "v1" for a state the user never
    explicitly saved needs to explain itself in the timeline.
    """
    try:
        if not settings.dashboard_versions.enabled:
            return None

        anchor = dashboards_collection.find_one({"dashboard_id": ObjectId(str(dashboard_id))}) or (
            dashboards_collection.find_one({"_id": ObjectId(str(dashboard_id))})
        )
        if not anchor:
            return None

        family_id = resolve_family_id(anchor)
        if family_id is None:
            return None
        if version_store.count_versions(str(family_id)) > 0:
            return None

        return capture_dashboard_version(
            family_id,
            kind="explicit",
            author=author,
            label="Before first tracked change",
        )
    except Exception as exc:  # noqa: BLE001 — must never break a save
        logger.warning(f"versioning: baseline capture failed for {dashboard_id}: {exc}")
        return None
