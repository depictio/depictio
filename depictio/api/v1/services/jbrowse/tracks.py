"""Track manifest access: DC lookup, manifest rows, per-track locations."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import polars as pl
from bson import ObjectId

from depictio.api.v1.configs.config import settings
from depictio.models.models.data_collections_types.genomic_tracks import (
    DCGenomicTracksConfig,
    infer_index_uri,
    infer_track_format,
    is_bgzipped,
)

TRACK_ROLES = ("data", "index")
ASSEMBLY_ROLES = ("fasta", "fai", "gzi", "twobit", "chrom_sizes", "aliases")


def default_s3_base_folder(dc_id: str) -> str:
    return f"s3://{settings.s3.bucket}/genomic_tracks/{dc_id}/"


def s3_base_folder(dc_id: str, props: DCGenomicTracksConfig) -> str:
    return props.s3_base_folder or default_s3_base_folder(dc_id)


def track_key(uri: str) -> str:
    """Stable, URL-safe id of a track, derived from its data location."""
    return hashlib.sha1(uri.encode("utf-8")).hexdigest()[:16]


@dataclass
class TrackRow:
    key: str
    track_id: str
    name: str
    uri: str
    index_uri: str | None
    fmt: str
    sample: str | None = None
    color: str | None = None
    category: str | None = None
    row: dict[str, Any] = field(default_factory=dict)

    @property
    def bgzipped(self) -> bool:
        return is_bgzipped(self.uri)


def _cell(row: dict[str, Any], column: str | None) -> str | None:
    if not column:
        return None
    value = row.get(column)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def manifest_rows(df: pl.DataFrame, props: DCGenomicTracksConfig) -> list[TrackRow]:
    """Turn manifest rows into tracks; rows without a usable location are skipped."""
    if props.uri_column not in df.columns:
        return []
    tracks: list[TrackRow] = []
    seen: set[str] = set()
    for row in df.to_dicts():
        uri = _cell(row, props.uri_column)
        if not uri:
            continue
        fmt = (_cell(row, props.format_column) or "").lower() or infer_track_format(uri)
        fmt = fmt or props.default_format
        if not fmt:
            continue
        index_uri = _cell(row, props.index_column) or infer_index_uri(uri, fmt)
        key = track_key(uri)
        if key in seen:
            continue
        seen.add(key)
        track_id = _cell(row, props.track_id_column) or key
        name = (
            _cell(row, props.name_column)
            or _cell(row, props.track_id_column)
            or uri.rsplit("/", 1)[-1].split("?", 1)[0]
        )
        tracks.append(
            TrackRow(
                key=key,
                track_id=track_id,
                name=name,
                uri=uri,
                index_uri=index_uri,
                fmt=fmt,
                sample=_cell(row, props.sample_column),
                color=_cell(row, props.color_column),
                category=_cell(row, props.category_column),
                row=row,
            )
        )
    return tracks


# --------------------------------------------------------------------------
# DC lookup (the proxy only has a dc_id)
# --------------------------------------------------------------------------


@dataclass
class TracksDC:
    dc_id: str
    wf_id: str
    project_id: str
    props: DCGenomicTracksConfig
    delta_location: str | None


def find_tracks_dc(dc_id: str) -> TracksDC | None:
    from depictio.api.v1.db import deltatables_collection, projects_collection

    try:
        dc_oid = ObjectId(dc_id)
    except Exception:
        return None
    project = projects_collection.find_one(
        {"workflows.data_collections._id": dc_oid},
        {"_id": 1, "workflows._id": 1, "workflows.data_collections": 1},
    )
    if not project:
        return None
    for wf in project.get("workflows", []) or []:
        for dc in wf.get("data_collections", []) or []:
            if dc.get("_id") != dc_oid:
                continue
            config = dc.get("config") or {}
            if str(config.get("type", "")).lower() != "genomic_tracks":
                return None
            props = DCGenomicTracksConfig.model_validate(config.get("dc_specific_properties") or {})
            dt = deltatables_collection.find_one({"data_collection_id": dc_oid})
            return TracksDC(
                dc_id=dc_id,
                wf_id=str(wf.get("_id")),
                project_id=str(project["_id"]),
                props=props,
                delta_location=dt.get("delta_table_location") if dt else None,
            )
    return None


_manifest_cache: dict[str, tuple[float, dict[str, TrackRow]]] = {}
_manifest_lock = threading.Lock()
_MANIFEST_TTL_S = 60.0


def tracks_by_key(tdc: TracksDC) -> dict[str, TrackRow]:
    """All tracks of a DC keyed by ``track_key`` (cached briefly for the proxy)."""
    now = time.monotonic()
    with _manifest_lock:
        cached = _manifest_cache.get(tdc.dc_id)
        if cached and now - cached[0] < _MANIFEST_TTL_S:
            return cached[1]

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    init_data: dict[str, dict] = {}
    if tdc.delta_location:
        init_data[tdc.dc_id] = {
            "delta_location": tdc.delta_location,
            "dc_type": "genomic_tracks",
            "size_bytes": 0,
        }
    df = load_deltatable_lite(
        workflow_id=ObjectId(tdc.wf_id), data_collection_id=tdc.dc_id, init_data=init_data
    )
    mapping = {t.key: t for t in manifest_rows(df, tdc.props)}
    with _manifest_lock:
        _manifest_cache[tdc.dc_id] = (now, mapping)
    return mapping


def user_can_read_project(project_id: str, user_id: str) -> bool:
    """Same rule as the DC access checks elsewhere: owner, viewer, public or admin."""
    from depictio.api.v1.db import projects_collection, users_collection

    try:
        pid = ObjectId(project_id)
    except Exception:
        return False
    user_doc = None
    if ObjectId.is_valid(user_id):
        user_doc = users_collection.find_one({"_id": ObjectId(user_id)}, {"is_admin": 1})
    if user_doc and user_doc.get("is_admin"):
        return projects_collection.find_one({"_id": pid}, {"_id": 1}) is not None
    clauses: list[dict[str, Any]] = [{"permissions.viewers": "*"}, {"is_public": True}]
    if user_doc:
        uid = user_doc["_id"]
        clauses += [
            {"permissions.owners._id": uid},
            {"permissions.editors._id": uid},
            {"permissions.viewers._id": uid},
        ]
    return projects_collection.find_one({"_id": pid, "$or": clauses}, {"_id": 1}) is not None
