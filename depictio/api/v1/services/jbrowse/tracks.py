"""Track manifest access: DC lookup, manifest rows, per-track locations."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import polars as pl
from bson import ObjectId

from depictio.api.v1.configs.config import settings
from depictio.models.models.data_collections_types.genomic_tracks import (
    DCGenomicTracksConfig,
    genomic_tracks_s3_prefix,
    infer_index_uri,
    infer_track_format,
    is_bgzipped,
)

TRACK_ROLES = ("data", "index")
ASSEMBLY_ROLES = ("fasta", "fai", "gzi", "twobit", "chrom_sizes", "aliases")


def default_s3_base_folder(dc_id: str) -> str:
    return f"s3://{settings.s3.bucket}/{genomic_tracks_s3_prefix(dc_id)}"


def s3_base_folder(dc_id: str, props: DCGenomicTracksConfig) -> str:
    """Folder relative track locations of the DC resolve under.

    A custom folder in Depictio's own bucket must stay inside the DC's default
    folder: the DC config is owner-controlled, and a folder like the bucket root
    or another DC's prefix would expose data the viewer has no access to.
    """
    from depictio.api.v1.services.remote_read import RemoteReadError

    if props.remote_base_uri:
        # Read-in-place folders are someone else's storage: never Depictio's own
        # bucket, which would let a DC owner read any key with the server's keys.
        if props.remote_base_uri.startswith(f"s3://{settings.s3.bucket}/"):
            raise RemoteReadError(403, "remote_base_uri cannot point into Depictio's bucket")
        return props.remote_base_uri
    default = default_s3_base_folder(dc_id)
    custom = props.s3_base_folder
    if not custom:
        return default
    bucket = custom[len("s3://") :].split("/", 1)[0]
    if bucket == settings.s3.bucket and not custom.startswith(default):
        raise RemoteReadError(403, f"s3_base_folder in Depictio's bucket must be inside {default}")
    return custom


LOCAL_ABSOLUTE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|\\\\)")


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def display_uri(uri: str | None, storage: str = "remote", anonymous: bool = False) -> str | None:
    """``uri`` as the client may be shown it: the one sanitizer for display fields.

    Never carries userinfo, query or fragment (a presigned URL's signature, a
    ``user:pw@`` host). An ingested file (``storage="depictio"``) shows its file
    name, never an internal bucket key, and so does an absolute local path. A
    remote URI keeps its host and path, except for an anonymous viewer, who sees
    the file name only. A relative path is shown as is. Display fields only: the
    locations JBrowse fetches are built elsewhere and are not touched.
    """
    text = (uri or "").strip()
    if not text:
        return None
    if "://" in text:
        try:
            parts = urlsplit(text)
        except ValueError:  # e.g. an unclosed IPv6 bracket
            return _basename(text.split("?", 1)[0].split("#", 1)[0]) or None
        netloc = parts.netloc.rsplit("@", 1)[-1]
        if storage == "depictio" or anonymous:
            return _basename(parts.path) or netloc or None
        return f"{parts.scheme}://{netloc}{parts.path}"
    bare = text.split("#", 1)[0].split("?", 1)[0]
    if LOCAL_ABSOLUTE.match(bare):
        return _basename(bare) or None
    return bare or None


def display_base_uri(uri: str | None, anonymous: bool = False) -> str | None:
    """A ``remote_base_uri`` as host + prefix; nothing for an anonymous viewer."""
    if anonymous or not uri or "://" not in uri:
        return None
    return display_uri(uri, "remote")


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
    if props.order_column and props.order_column in df.columns:
        df = df.sort(props.order_column, nulls_last=True, maintain_order=True)
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

    def init_data(self) -> dict[str, dict]:
        """The ``init_data`` argument of ``load_deltatable_lite`` for this DC."""
        if not self.delta_location:
            return {}
        return {
            self.dc_id: {
                "delta_location": self.delta_location,
                "dc_type": "genomic_tracks",
                "size_bytes": 0,
            }
        }


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


_manifest_cache: dict[tuple[str, int | None], tuple[float, dict[str, TrackRow]]] = {}
_manifest_lock = threading.Lock()
_MANIFEST_TTL_S = 60.0


def tracks_by_key(tdc: TracksDC, delta_version: int | None = None) -> dict[str, TrackRow]:
    """All tracks of a DC keyed by ``track_key`` (cached briefly for the proxy).

    ``delta_version`` reads the manifest as of that Delta commit (a pinned data
    version), else the current one.
    """
    now = time.monotonic()
    cache_key = (tdc.dc_id, delta_version)
    with _manifest_lock:
        cached = _manifest_cache.get(cache_key)
        if cached and now - cached[0] < _MANIFEST_TTL_S:
            return cached[1]

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    df = load_deltatable_lite(
        workflow_id=ObjectId(tdc.wf_id),
        data_collection_id=tdc.dc_id,
        init_data=tdc.init_data(),
        delta_version=delta_version,
    )
    mapping = {t.key: t for t in manifest_rows(df, tdc.props)}
    with _manifest_lock:
        _manifest_cache[cache_key] = (now, mapping)
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
