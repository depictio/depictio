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
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from pymongo import ASCENDING

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, deltatables_collection
from depictio.api.v1.endpoints.dashboards_endpoints import schema_integrity, version_store
from depictio.models.models.dashboard_versions import (
    RECORD_SCHEMA_VERSION,
    TAB_SCHEMA_1_FIELDS,
    DashboardVersion,
    DataCollectionStamp,
    TabSnapshot,
    VersionKind,
)
from depictio.models.models.dashboards import DashboardData
from depictio.models.timestamps import utc_now_naive

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

#: Fields that move without the dashboard changing. Hashing them would turn a
#: screenshot, a re-save or an import counter bump into a version.
SNAPSHOT_VOLATILE_FIELDS: frozenset[str] = frozenset(
    {"creation_time", "last_saved_ts", "screenshot_ts", "version"}
)

#: Recomputed rather than recorded. The ``inherited_*`` pair, the parent title
#: and the realtime config are filled in by each GET and never stored;
#: ``parent_dashboard_id`` is implied by the version's family, and restore sets
#: it from there.
SNAPSHOT_DERIVED_FIELDS: frozenset[str] = frozenset(
    {
        "inherited_brand_theme",
        "inherited_category_colors",
        "parent_dashboard_title",
        "project_realtime",
        "parent_dashboard_id",
    }
)

#: ``MongoModel`` bookkeeping every model inherits (``id`` is ``_id``). No
#: dashboard route writes the other three.
SNAPSHOT_BASE_MODEL_FIELDS: frozenset[str] = frozenset(
    {"id", "description", "flexible_metadata", "hash"}
)

#: Every dashboard field a snapshot leaves out on purpose. A ``DashboardData``
#: field in neither this set nor ``TabSnapshot`` is one somebody forgot, and the
#: field-coverage test fails on it rather than letting restore drop it silently.
SNAPSHOT_EXCLUDED_FIELDS: frozenset[str] = (
    SNAPSHOT_DEAD_FIELDS
    | SNAPSHOT_FORBIDDEN_FIELDS
    | SNAPSHOT_VOLATILE_FIELDS
    | SNAPSHOT_DERIVED_FIELDS
    | SNAPSHOT_BASE_MODEL_FIELDS
)

#: The brand-theme keys that point at logo bytes. The bytes live in
#: ``branding_assets`` and are not versioned, so these always come from the
#: live document on restore and preview.
_LOGO_URL_KEYS: tuple[str, ...] = ("logo_url", "logo_url_dark")

#: The cache-buster ``logo_asset_url`` appends, and that boot-time
#: ``_migrate_dashboard_logos`` rewrites. It names an upload, not a look.
_LOGO_CACHE_BUSTER = re.compile(r"\?v=\d+$")

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


def _find_dashboard(oid: ObjectId) -> Optional[dict[str, Any]]:
    """A dashboard document by its ``dashboard_id``, falling back to ``_id``."""
    return dashboards_collection.find_one({"dashboard_id": oid}) or (
        dashboards_collection.find_one({"_id": oid})
    )


def load_family_docs(family_id: ObjectId) -> list[dict[str, Any]]:
    """Full documents for the main tab and every child, in tab order.

    Deliberately not ``get_child_tabs()``: that helper projects away
    ``stored_metadata``, which is the entire point of a snapshot.
    """
    main = _find_dashboard(family_id)
    if not main:
        return []

    children = list(
        dashboards_collection.find({"parent_dashboard_id": family_id}).sort("tab_order", ASCENDING)
    )
    return [main, *children]


def build_tab_snapshots(family_docs: list[dict[str, Any]]) -> list[TabSnapshot]:
    """Project each tab document down to its renderable content.

    Explicit keyword arguments rather than ``DashboardData.from_mongo``: the raw
    document carries fields the model forbids, and a capture must not fail on
    them. A boolean setting reads ``is not False`` so a document written before
    the setting existed (no key, or an explicit null) records its default.
    """
    snapshots: list[TabSnapshot] = []
    for raw in family_docs:
        # The same fold `DashboardData` applies on load: a document still
        # carrying the pre-brand-theme `logo_url` / `plot_theme` keys renders
        # with them, so its snapshot must hold them too.
        doc = DashboardData._fold_legacy_appearance(raw)
        is_main_tab = bool(doc.get("is_main_tab", True))
        snapshots.append(
            TabSnapshot(
                dashboard_id=str(doc.get("dashboard_id") or doc.get("_id")),
                is_main_tab=is_main_tab,
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
                tab_group=doc.get("tab_group"),
                filter_sections=_jsonify(doc.get("filter_sections") or []),
                grid_sections=_jsonify(doc.get("grid_sections") or []),
                category_colors=_jsonify(doc.get("category_colors")) or None,
                funnel_filtering=doc.get("funnel_filtering") is not False,
                filter_panel_default=doc.get("filter_panel_default") or "open",
                content_width_default=doc.get("content_width_default") or "full",
                show_tab_header=doc.get("show_tab_header") is not False,
                # The viewer reads the Guide from the main tab for the whole
                # family. A child's copy is never shown, so recording it would
                # only let an invisible field move the hash.
                show_guide=(doc.get("show_guide") is not False) if is_main_tab else True,
                guide_intro=str(doc.get("guide_intro") or "") if is_main_tab else "",
                advanced_viz_controls=doc.get("advanced_viz_controls") or "popover",
                autofit=doc.get("autofit") is not False,
                brand_theme=_jsonify(doc.get("brand_theme")) or None,
                source_key=doc.get("source_key"),
            )
        )
    return snapshots


def restorable_brand_theme(
    snapshot_theme: Optional[dict[str, Any]], live_theme: Optional[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """A snapshot's brand theme as restore writes it (and preview shows it).

    The logo URLs are the live ones. The bytes behind them are not versioned,
    so an old URL could only serve today's image, under a cache-buster a browser
    may still hold an older image for. None means the tab had no brand override
    at that version, which restore turns into an ``$unset``.
    """
    if not snapshot_theme:
        return None
    live = live_theme or {}
    theme = {k: v for k, v in snapshot_theme.items() if k not in _LOGO_URL_KEYS}
    for key in _LOGO_URL_KEYS:
        if live.get(key):
            theme[key] = live[key]
    return theme or None


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
    for tab in tabs:
        for component in tab.stored_metadata:
            if not isinstance(component, dict):
                continue
            raw = component.get("dc_id")
            current = str(raw.get("$oid") if isinstance(raw, dict) else raw) if raw else ""
            if current != dc_id:
                continue
            config = component.get("dc_config") or {}
            if isinstance(config, dict) and config.get("type"):
                return str(config["type"])
    return ""


def build_dc_stamps(tabs: list[TabSnapshot]) -> list[DataCollectionStamp]:
    """Record what data each referenced collection was at, right now.

    Reads only Mongo — no object-store round trip — because this runs on the
    save path. A collection with no aggregation record yields a ``none``
    stamp carrying the reason, which the UI shows rather than implying the
    version is fully reproducible.
    """
    stamps: list[DataCollectionStamp] = []

    for dc_id in collect_dc_ids(tabs):
        dc_type = _dc_type_from_components(tabs, dc_id)
        kind = _classify_dc(dc_type)
        stamp = DataCollectionStamp(dc_id=dc_id, dc_type=dc_type, version_kind="none")

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

        # Every stamp starts at ``version_kind="none"``; only a Delta
        # aggregation with a recorded commit moves it.
        if kind == "delta" and latest:
            stamp.aggregation_version = latest.get("aggregation_version")
            stamp.delta_version = latest.get("delta_version")
            stamp.delta_commit_timestamp = latest.get("delta_commit_timestamp")
            stamp.row_count = latest.get("rows_total")
            stamp.columns = schema_integrity.columns_from_aggregation(latest)
            stamp.schema_hash = schema_integrity.generate_schema_hash(stamp.columns)
            if stamp.delta_version is None:
                # Pre-provenance aggregations, and every UI upload, land here.
                stamp.reason = "no_delta_version_recorded"
            else:
                stamp.version_kind = "delta"
        elif kind == "manifest":
            # Populated in the manifest stage; the stamp records the intent and
            # the instant so a later backfill has an anchor.
            stamp.reason = "manifest_versioning_not_enabled"
            if latest:
                stamp.columns = schema_integrity.columns_from_aggregation(latest)
                stamp.schema_hash = schema_integrity.generate_schema_hash(stamp.columns)
        elif kind == "asset":
            stamp.reason = "asset_versioning_not_enabled"
        else:
            stamp.reason = (
                "unknown_data_collection_type" if not dc_type else "no_aggregation_record"
            )

        stamps.append(stamp)

    return stamps


#: JSON defaults of every ``TabSnapshot`` field added after record schema 1.
_LATER_FIELD_DEFAULTS: dict[str, Any] = {
    name: field.get_default(call_default_factory=True)
    for name, field in TabSnapshot.model_fields.items()
    if name not in TAB_SCHEMA_1_FIELDS
}


def _canonical_tab(tab: TabSnapshot) -> dict[str, Any]:
    """The part of a tab the content hash covers.

    ``source_key`` is identity, not content. A field added after schema 1 is
    left out while it holds its default (see ``TAB_SCHEMA_1_FIELDS``); leaving
    a default out is lossless, since the default is known, so two different
    states still never share a hash.
    """
    dumped = tab.model_dump(mode="json", exclude={"source_key"})
    for name, default in _LATER_FIELD_DEFAULTS.items():
        if name in dumped and dumped[name] == default:
            del dumped[name]

    theme = dumped.get("brand_theme")
    if isinstance(theme, dict):
        theme = dict(theme)
        for key in _LOGO_URL_KEYS:
            if isinstance(theme.get(key), str):
                theme[key] = _LOGO_CACHE_BUSTER.sub("", theme[key])
        dumped["brand_theme"] = theme
    return dumped


def compute_content_hash(tabs: list[TabSnapshot]) -> str:
    """Digest of the family's renderable content.

    Ordered by ``tab_order`` then id so tab reordering is a real change while
    Mongo's return order is not. A logo URL is hashed without its ``?v=``
    cache-buster: the boot-time logo migration rewrites it, and a rewrite that
    shows the same image is not an edit.
    """
    canonical = [
        _canonical_tab(tab) for tab in sorted(tabs, key=lambda t: (t.tab_order, t.dashboard_id))
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
    seal: bool = False,
    now: datetime | None = None,
    only_if_changed: bool = False,
) -> Optional[DashboardVersion]:
    """Snapshot a dashboard family. Returns None when nothing was recorded.

    None means: versioning disabled, the dashboard is gone, the family is
    empty, the snapshot is oversized, or — the common case — the content is
    byte-identical to the newest version.

    ``only_if_changed`` writes nothing when the content matches the newest
    version, whatever ``kind`` is. For recording "the state before" ahead of a
    restore or an import: that state is usually the newest version already,
    and an explicit capture would otherwise write a duplicate of it every time.

    ``seal`` is for a user's explicit Save: when the content is unchanged and
    the newest version is an autosave, that autosave becomes ``explicit``
    instead, so the Save is visible and nothing folds into it afterwards.
    """
    cfg = settings.dashboard_versions
    if not cfg.enabled:
        return None

    now = now or utc_now_naive()

    try:
        dashboard_oid = ObjectId(str(dashboard_id))
    except Exception:
        logger.warning(f"versioning: not a valid dashboard id: {dashboard_id!r}")
        return None

    anchor = _find_dashboard(dashboard_oid)
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

    # Nothing changed. An explicit save still deserves a marker, so it falls
    # through to the normal path; an autosave leaves no trace at all, and
    # neither does a "state before" capture.
    #
    # A Save click (`seal`) marks the autosave that already holds this content
    # instead: the debounced autosave has nearly always written it, and a
    # second entry with the same content would say nothing.
    if latest and latest.get("content_hash") == content_hash:
        if only_if_changed:
            return None
        if kind == "auto":
            version_store.touch_version(latest["version_id"], now)
            return None
        if seal and latest.get("kind") == "auto":
            version_store.seal_version(latest, {"updated_at": now})
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
    ).recount()

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
                "updated_at": now,
                # The folded content can add or remove components and tabs, so
                # the denormalised counts have to move with it.
                "tab_count": record.tab_count,
                "component_count": record.component_count,
                # The tabs now have this capture's shape, whatever the
                # version they fold into was first written as.
                "record_schema_version": RECORD_SCHEMA_VERSION,
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
