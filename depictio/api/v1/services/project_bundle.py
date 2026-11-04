"""Project bundles: build, read, validate and import one project.

A bundle is what ``/migrate/export-project`` produces and every import path
consumes (the CLI ``depictio migrate``, the UI ZIP import and, later, the
instance-to-instance push). It is a ZIP holding:

- ``migrate_metadata.json``: who exported it, with which Depictio, from which
  S3 bucket, in which bundle format;
- ``bundle.json``: the Mongo documents of one project (the project itself with
  its embedded workflows and data collections, files, deltatables, runs,
  dashboards, MultiQC and JBrowse records), ObjectIds flattened to strings;
- ``s3_data/<key>``: the project's S3 objects, when the data travels inline;
- ``s3_metadata.json``: the S3 locations and, for a push that copies server
  side, the manifest of objects (key, size, etag).

Importing is three steps, kept apart so a caller can stop after any of them:
``validate_bundle`` (read-only report), ``prepare_docs_for_import`` (pure
transform) and ``apply_project_import`` (the writes, with version capture).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Any, Literal, cast

from bson import ObjectId
from pydantic import BaseModel
from pymongo.collection import Collection

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.mongo_json import (
    convert_complex_objects_to_strings,
    parse_json_datetime_naive,
    restore_complex_objects,
)
from depictio.models.models.data_collections_types.genomic_tracks import genomic_tracks_s3_prefix
from depictio.models.models.migration import BUNDLE_FORMAT_VERSION, ImportHop

BundleMode = Literal["all", "metadata", "dashboard", "files"]

#: bundle.json sections, in the order an import writes them.
COLLECTION_ORDER: tuple[str, ...] = (
    "projects",
    "files",
    "deltatables",
    "runs",
    "dashboards",
    "multiqc",
    "jbrowse",
)

#: Sections whose documents point at a data collection.
DC_SCOPED_SECTIONS: tuple[str, ...] = ("files", "deltatables", "multiqc", "jbrowse")

S3_DATA_PREFIX = "s3_data/"


def _db():
    """The live collections, imported late so tests can patch this module."""
    from depictio.api.v1 import db

    return db


def _collections() -> dict[str, Collection[dict[str, Any]]]:
    db = _db()
    return {
        "projects": db.projects_collection,
        "files": db.files_collection,
        "deltatables": db.deltatables_collection,
        "runs": db.runs_collection,
        "dashboards": db.dashboards_collection,
        "multiqc": db.multiqc_collection,
        "jbrowse": db.jbrowse_collection,
    }


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


@dataclass
class ProjectScope:
    """The ids a project owns: everything a bundle of it may touch."""

    project_id: ObjectId
    dc_ids: list[ObjectId] = field(default_factory=list)
    workflow_ids: list[ObjectId] = field(default_factory=list)
    # dc id -> config.type, for the S3 keys derived from the id.
    dc_types: dict[str, str | None] = field(default_factory=dict)

    @property
    def dc_id_strs(self) -> set[str]:
        return {str(d) for d in self.dc_ids}

    def s3_prefixes(self) -> list[str]:
        """Bucket-relative prefixes this project's objects live under."""
        prefixes: list[str] = []
        for dc in self.dc_id_strs:
            prefixes.append(f"{dc}/")
            prefixes.append(f"phylogeny/{dc}/")
            prefixes.append(genomic_tracks_s3_prefix(dc))
        return prefixes

    def owns_key(self, key: str) -> bool:
        return any(key.startswith(p) for p in self.s3_prefixes())


def _as_oid(value: Any) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    if isinstance(value, dict):
        return _as_oid(value.get("$oid"))
    return None


def resolve_project_scope(project_doc: dict[str, Any]) -> ProjectScope:
    """Scope of a project document, raw from Mongo or from a bundle.

    Covers DCs embedded in workflows and the top-level ``data_collections`` of
    a basic project.
    """
    pid = _as_oid(project_doc.get("_id") or project_doc.get("id"))
    if pid is None:
        raise ValueError("project document has no valid _id")
    scope = ProjectScope(project_id=pid)

    def add_dc(dc: dict[str, Any]) -> None:
        dc_id = _as_oid(dc.get("_id") or dc.get("id"))
        if dc_id is None or dc_id in scope.dc_ids:
            return
        scope.dc_ids.append(dc_id)
        scope.dc_types[str(dc_id)] = (dc.get("config") or {}).get("type")

    for wf in project_doc.get("workflows") or []:
        if not isinstance(wf, dict):
            continue
        wf_id = _as_oid(wf.get("_id") or wf.get("id"))
        if wf_id is not None and wf_id not in scope.workflow_ids:
            scope.workflow_ids.append(wf_id)
        for dc in wf.get("data_collections") or []:
            if isinstance(dc, dict):
                add_dc(dc)
    for dc in project_doc.get("data_collections") or []:
        if isinstance(dc, dict):
            add_dc(dc)
    return scope


def dc_ids_query(dc_ids: Iterable[ObjectId]) -> dict[str, Any]:
    """Match ``data_collection_id`` stored as either ObjectId or string."""
    ids = list(dc_ids)
    return {"$in": ids + [str(i) for i in ids]}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def collect_bundle_docs(
    project_doc: dict[str, Any], scope: ProjectScope, mode: BundleMode
) -> dict[str, list[dict]]:
    """The Mongo documents of one project, as raw dicts, per bundle section."""
    cols = _collections()
    data: dict[str, list[dict]] = {}
    if mode in ("all", "metadata"):
        data["projects"] = [project_doc]
        dcq = dc_ids_query(scope.dc_ids)
        for section in DC_SCOPED_SECTIONS:
            data[section] = (
                list(cols[section].find({"data_collection_id": dcq})) if scope.dc_ids else []
            )
        data["runs"] = (
            list(cols["runs"].find({"workflow_id": {"$in": scope.workflow_ids}}))
            if scope.workflow_ids
            else []
        )
    if mode in ("all", "metadata", "dashboard"):
        pid = scope.project_id
        data["dashboards"] = list(
            cols["dashboards"].find({"$or": [{"project_id": pid}, {"project_id": str(pid)}]})
        )
    return data


def normalize_s3_path(location: str | None, bucket: str) -> str | None:
    """``s3://bucket/key`` -> ``key``; a bare key is returned as-is."""
    if not location:
        return None
    prefix = "s3://"
    if not location.startswith(prefix):
        return location
    parts = location[len(prefix) :].split("/", 1)
    return parts[1] if len(parts) == 2 else None


@dataclass(frozen=True)
class S3ObjectRef:
    key: str
    size: int
    etag: str | None = None


def list_s3_objects(paths: Iterable[str], bucket: str, client: Any) -> list[S3ObjectRef]:
    """Every object under ``paths``, de-duplicated, ``_delta_log`` entries last.

    Copying in this order means a Delta table never becomes readable on the
    target before the data files its log names are there.
    """
    seen: set[str] = set()
    objects: list[S3ObjectRef] = []
    paginator = client.get_paginator("list_objects_v2")
    for path in paths:
        prefix = path.strip("/")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if key in seen:
                    continue
                seen.add(key)
                etag = obj.get("ETag")
                objects.append(
                    S3ObjectRef(
                        key=key,
                        size=int(obj.get("Size", 0)),
                        etag=etag.strip('"') if etag else None,
                    )
                )
    return sorted(objects, key=lambda o: ("/_delta_log/" in f"/{o.key}", o.key))


def build_bundle_metadata(
    project_doc: dict[str, Any],
    scope: ProjectScope,
    mode: BundleMode,
    data: dict[str, list[dict]],
    *,
    dry_run: bool,
    source_instance: str,
    depictio_version: str,
    s3_bucket: str,
    s3_endpoint: str | None,
    exported_at: str,
) -> dict[str, Any]:
    counts: dict[str, int] = {k: len(v) for k, v in data.items()}
    if mode in ("all", "metadata"):
        counts["workflows_embedded"] = len(scope.workflow_ids)
        counts["data_collections_embedded"] = len(scope.dc_ids)
    return {
        "timestamp": datetime.now().isoformat(),
        "exported_at": exported_at,
        "project_id": str(scope.project_id),
        "project_name": project_doc.get("name"),
        "mode": mode,
        "depictio_version": depictio_version,
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "source_instance": source_instance,
        "s3_bucket": s3_bucket,
        "s3_endpoint": s3_endpoint,
        "document_counts": counts,
        "dry_run": dry_run,
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def bundle_json_bytes(data: dict[str, list[dict]]) -> bytes:
    serialisable = convert_complex_objects_to_strings(data)
    return json.dumps(serialisable, indent=2, default=_json_default).encode()


class BundleTooLarge(Exception):
    """The data a bundle would carry exceeds the configured cap."""


def write_bundle_zip(
    fp: IO[bytes],
    metadata: dict[str, Any],
    data: dict[str, list[dict]],
    *,
    s3_metadata: dict[str, Any] | None = None,
    s3_objects: list[S3ObjectRef] | None = None,
    s3_client: Any = None,
    bucket: str | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Write a bundle ZIP to ``fp``, streaming S3 objects into ``s3_data/``.

    Objects are stored, not deflated (parquet is already compressed), and read
    in chunks: memory use does not grow with the project's size. Returns the
    S3 metadata written (with ``bundled_files`` / ``bundled_bytes`` when data
    was included).
    """
    s3_meta = dict(s3_metadata or {})
    objects = s3_objects or []
    total = sum(o.size for o in objects)
    if max_bytes is not None and total > max_bytes:
        raise BundleTooLarge(f"project data is {total} bytes, over the {max_bytes} byte limit")
    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr("migrate_metadata.json", json.dumps(metadata, indent=2, default=_json_default))
        zf.writestr("bundle.json", bundle_json_bytes(data))
        if objects:
            if s3_client is None or bucket is None:
                raise ValueError("s3_client and bucket are required to bundle S3 objects")
            bundled = 0
            bundled_bytes = 0
            errors: list[str] = []
            for obj in objects:
                try:
                    body = s3_client.get_object(Bucket=bucket, Key=obj.key)["Body"]
                except Exception as exc:  # noqa: BLE001 — one missing object must not kill the rest
                    logger.error("bundle: failed to read %s: %s", obj.key, exc)
                    errors.append(obj.key)
                    continue
                info = zipfile.ZipInfo(f"{S3_DATA_PREFIX}{obj.key}")
                info.compress_type = zipfile.ZIP_STORED
                with zf.open(info, "w", force_zip64=True) as dest:
                    chunks = body.iter_chunks(1024 * 1024) if hasattr(body, "iter_chunks") else None
                    if chunks is None:
                        shutil.copyfileobj(body, dest, 1024 * 1024)
                    else:
                        for chunk in chunks:
                            dest.write(chunk)
                bundled += 1
                bundled_bytes += obj.size
            s3_meta["bundled_files"] = bundled
            s3_meta["bundled_bytes"] = bundled_bytes
            if errors:
                s3_meta["bundle_errors"] = errors
        if s3_meta:
            zf.writestr("s3_metadata.json", json.dumps(s3_meta, indent=2, default=_json_default))
    return s3_meta


def spool_file(spool_dir: str | None = None) -> IO[bytes]:
    """A named temp file that is removed when closed."""
    if spool_dir:
        os.makedirs(spool_dir, exist_ok=True)
    return tempfile.NamedTemporaryFile(prefix="depictio-bundle-", suffix=".zip", dir=spool_dir)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class BundleError(Exception):
    """A bundle that cannot be read at all (not a ZIP, missing members, too big)."""


@dataclass(frozen=True)
class BundleLimits:
    max_uncompressed_bytes: int = 50 * 1024**3
    max_entries: int = 200_000
    max_json_bytes: int = 512 * 1024**2


@dataclass
class OpenedBundle:
    metadata: dict[str, Any]
    data: dict[str, list[dict]]
    s3_metadata: dict[str, Any]
    #: (member name in the ZIP, bucket-relative key)
    s3_entries: list[tuple[str, str]]
    zf: zipfile.ZipFile

    def close(self) -> None:
        self.zf.close()

    @property
    def total_s3_bytes(self) -> int:
        return sum(self.zf.getinfo(name).file_size for name, _ in self.s3_entries)


def is_safe_s3_key(key: str) -> bool:
    """A clean relative key: no absolute path, no ``..``, nothing normalised away."""
    if not key or key.startswith("/") or "\\" in key:
        return False
    if ".." in key.split("/"):
        return False
    return key == os.path.normpath(key).replace(os.sep, "/") or key.endswith("/")


def open_bundle_zip(fileobj: IO[bytes] | str, limits: BundleLimits | None = None) -> OpenedBundle:
    """Open and sanity-check a bundle ZIP. The caller closes the result.

    Refuses archives whose declared uncompressed size or entry count exceeds
    ``limits`` (zip bombs), and ``s3_data/`` members whose key is not a clean
    relative path (zip-slip). Neither reads the data itself.
    """
    limits = limits or BundleLimits()
    try:
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BundleError("not a ZIP bundle") from exc
    try:
        infos = zf.infolist()
        if len(infos) > limits.max_entries:
            raise BundleError(f"bundle has {len(infos)} entries, over {limits.max_entries}")
        total = sum(i.file_size for i in infos)
        if total > limits.max_uncompressed_bytes:
            raise BundleError(
                f"bundle expands to {total} bytes, over {limits.max_uncompressed_bytes}"
            )

        def read_json(name: str, required: bool) -> Any:
            try:
                info = zf.getinfo(name)
            except KeyError:
                if required:
                    raise BundleError(f"bundle has no {name}") from None
                return {}
            if info.file_size > limits.max_json_bytes:
                raise BundleError(f"{name} is {info.file_size} bytes, over {limits.max_json_bytes}")
            try:
                return json.loads(zf.read(name))
            except ValueError as exc:
                raise BundleError(f"{name} is not valid JSON") from exc

        data = read_json("bundle.json", required=True)
        metadata = read_json("migrate_metadata.json", required=True)
        s3_metadata = read_json("s3_metadata.json", required=False)
        if not isinstance(data, dict) or not isinstance(metadata, dict):
            raise BundleError("bundle.json and migrate_metadata.json must be JSON objects")
        entries: list[tuple[str, str]] = []
        for info in infos:
            if not info.filename.startswith(S3_DATA_PREFIX) or info.is_dir():
                continue
            key = info.filename[len(S3_DATA_PREFIX) :]
            if not is_safe_s3_key(key):
                raise BundleError(f"refusing unsafe S3 key in bundle: {key!r}")
            entries.append((info.filename, key))
        entries.sort(key=lambda e: ("/_delta_log/" in f"/{e[1]}", e[1]))
        return OpenedBundle(
            metadata=metadata,
            data=cast(dict[str, list[dict]], data),
            s3_metadata=s3_metadata if isinstance(s3_metadata, dict) else {},
            s3_entries=entries,
            zf=zf,
        )
    except BaseException:
        zf.close()
        raise


def manifest_from_s3_metadata(s3_metadata: dict[str, Any]) -> list[S3ObjectRef]:
    """The object manifest a server-side-copy bundle carries instead of data."""
    out: list[S3ObjectRef] = []
    for item in s3_metadata.get("manifest") or []:
        if isinstance(item, dict) and isinstance(item.get("key"), str):
            out.append(
                S3ObjectRef(key=item["key"], size=int(item.get("size") or 0), etag=item.get("etag"))
            )
    return out


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


class BundleReport(BaseModel):
    """What importing a bundle here would do, and whether it may."""

    project_id: str | None = None
    project_name: str | None = None
    source_instance: str | None = None
    source_depictio_version: str | None = None
    bundle_format_version: int = 1
    document_counts: dict[str, int] = {}
    s3_object_count: int = 0
    s3_bytes: int = 0
    #: none: new here. re_push: same lineage, becomes a new version.
    #: foreign: a project with this id exists here and did not come from that source.
    conflict: Literal["none", "re_push", "foreign"] = "none"
    existing_project_name: str | None = None
    #: The existing project here is published read-only.
    existing_locked: bool = False
    dashboards_added: list[str] = []
    dashboards_replaced: list[str] = []
    dashboards_removed: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.errors


def _source_bucket(metadata: dict[str, Any], data: dict[str, list[dict]]) -> str | None:
    """The bucket the bundle's ``s3://`` locations name.

    Bundles of format 1 do not record it; take it from the first stored delta
    table location, which is what every reader resolved against.
    """
    bucket = metadata.get("s3_bucket")
    if isinstance(bucket, str) and bucket:
        return bucket
    for doc in data.get("deltatables") or []:
        loc = doc.get("delta_table_location") or ""
        if isinstance(loc, str) and loc.startswith("s3://"):
            return loc[len("s3://") :].split("/", 1)[0] or None
    return None


def _iter_s3_uris(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        if obj.startswith("s3://"):
            yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_s3_uris(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_s3_uris(v)


def _doc_id(doc: dict[str, Any]) -> ObjectId | None:
    return _as_oid(doc.get("_id") or doc.get("id"))


def _last_hop_source(project_doc: dict[str, Any] | None) -> str | None:
    hops = ((project_doc or {}).get("provenance") or {}).get("imported_from") or []
    if hops and isinstance(hops[-1], dict):
        return hops[-1].get("source_instance")
    return None


def validate_bundle(
    metadata: dict[str, Any],
    data: dict[str, list[dict]],
    s3_keys: Iterable[str],
    *,
    strict: bool,
    source_instance: str | None = None,
) -> BundleReport:
    """Check a bundle against itself and against this instance. Read-only.

    ``strict`` (the push path) turns into errors what an admin running the CLI
    has always been allowed to do: S3 keys outside the project's own prefixes,
    ``s3://`` locations in another bucket, and replacing a project that did not
    come from this source. Cross-project id collisions are errors either way:
    an upsert by ``_id`` would rewrite another project's documents.

    ``source_instance`` is the authenticated sender (the inbound source a
    pairing key matched); without it the bundle's own claim is used.
    """
    cols = _collections()
    report = BundleReport(
        source_instance=source_instance or metadata.get("source_instance"),
        source_depictio_version=metadata.get("depictio_version"),
        bundle_format_version=int(metadata.get("bundle_format_version") or 1),
        document_counts={k: len(v) for k, v in data.items() if isinstance(v, list)},
    )
    if report.bundle_format_version > BUNDLE_FORMAT_VERSION:
        report.errors.append(
            f"bundle format {report.bundle_format_version} is newer than this instance supports "
            f"({BUNDLE_FORMAT_VERSION}); upgrade Depictio here first"
        )

    projects = data.get("projects") or []
    keys = list(s3_keys)
    report.s3_object_count = len(keys)
    if not projects:
        if data.get("dashboards"):
            report.warnings.append("dashboard-only bundle: no project document to check")
        return report
    if len(projects) != 1:
        report.errors.append(f"a bundle holds exactly one project, this one holds {len(projects)}")
        return report

    project = projects[0]
    try:
        scope = resolve_project_scope(project)
    except ValueError as exc:
        report.errors.append(str(exc))
        return report
    pid = scope.project_id
    report.project_id = str(pid)
    report.project_name = project.get("name")
    if metadata.get("project_id") and str(metadata["project_id"]) != str(pid):
        report.errors.append("migrate_metadata.project_id does not match the bundled project")

    # Every document must belong to the bundled project.
    for dash in data.get("dashboards") or []:
        if str(dash.get("project_id")) != str(pid):
            report.errors.append(f"dashboard {dash.get('_id')} belongs to another project")
    dc_strs = scope.dc_id_strs
    for section in DC_SCOPED_SECTIONS:
        for doc in data.get(section) or []:
            if str(doc.get("data_collection_id")) not in dc_strs:
                report.errors.append(
                    f"{section} document {doc.get('_id')} names a data collection outside the project"
                )
    wf_strs = {str(w) for w in scope.workflow_ids}
    for run in data.get("runs") or []:
        if str(run.get("workflow_id")) not in wf_strs:
            report.errors.append(f"run {run.get('_id')} names a workflow outside the project")

    # S3 keys confined to the project's own prefixes.
    stray = [k for k in keys if not scope.owns_key(k)]
    if stray:
        msg = f"{len(stray)} S3 object(s) outside the project's prefixes (first: {stray[0]})"
        (report.errors if strict else report.warnings).append(msg)

    bucket = _source_bucket(metadata, data)
    if bucket:
        foreign_uris = sorted(
            {u for u in _iter_s3_uris(data) if not u.startswith(f"s3://{bucket}/")}
        )
        if foreign_uris:
            msg = (
                f"{len(foreign_uris)} location(s) outside the source bucket {bucket!r} "
                f"(first: {foreign_uris[0]}); they are not migrated"
            )
            (report.errors if strict else report.warnings).append(msg)

    # Against this instance --------------------------------------------------
    existing = cols["projects"].find_one({"_id": pid})
    if existing:
        report.existing_project_name = existing.get("name")
        report.existing_locked = bool(existing.get("published_lock"))
        same_lineage = (
            report.source_instance is not None
            and _last_hop_source(existing) == report.source_instance
        )
        report.conflict = "re_push" if same_lineage else "foreign"
        if report.conflict == "foreign" and strict:
            report.errors.append(
                f"project {pid} already exists here and was not imported from "
                f"{report.source_instance!r}"
            )
    name_clash = cols["projects"].find_one({"name": project.get("name"), "_id": {"$ne": pid}})
    if name_clash:
        report.errors.append(f"another project here is already named {project.get('name')!r}")

    other_with_dcs = (
        cols["projects"].find_one(
            {
                "_id": {"$ne": pid},
                "$or": [
                    {"workflows.data_collections._id": {"$in": scope.dc_ids}},
                    {"data_collections._id": {"$in": scope.dc_ids}},
                ],
            }
        )
        if scope.dc_ids
        else None
    )
    if other_with_dcs:
        report.errors.append("a data collection id of this bundle belongs to another project here")

    for section in DC_SCOPED_SECTIONS + ("runs",):
        ids = [i for i in (_doc_id(d) for d in data.get(section) or []) if i is not None]
        if not ids:
            continue
        for doc in cols[section].find({"_id": {"$in": ids}}):
            ref = "workflow_id" if section == "runs" else "data_collection_id"
            allowed = wf_strs if section == "runs" else dc_strs
            if str(doc.get(ref)) not in allowed:
                report.errors.append(f"{section} id {doc['_id']} belongs to another project here")

    bundle_dash_ids = {
        str(i) for i in (_doc_id(d) for d in data.get("dashboards") or []) if i is not None
    }
    if bundle_dash_ids:
        for doc in cols["dashboards"].find(
            {"_id": {"$in": [ObjectId(i) for i in bundle_dash_ids]}}
        ):
            if str(doc.get("project_id")) != str(pid):
                report.errors.append(f"dashboard id {doc['_id']} belongs to another project here")
    existing_dash_ids = {
        str(d["_id"])
        for d in cols["dashboards"].find(
            {"$or": [{"project_id": pid}, {"project_id": str(pid)}]}, {"_id": 1}
        )
    }
    report.dashboards_added = sorted(bundle_dash_ids - existing_dash_ids)
    report.dashboards_replaced = sorted(bundle_dash_ids & existing_dash_ids)
    report.dashboards_removed = sorted(_stale_dashboard_ids(existing, bundle_dash_ids))

    try:
        from depictio.models.models.projects import ProjectResponse

        ProjectResponse.model_validate(restore_complex_objects(_normalise_id(project)))
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        lines = str(exc).splitlines()
        msg = "project document does not validate: " + "; ".join(lines[1:3] or lines[:1])
        (report.errors if strict else report.warnings).append(msg)
    return report


def _stale_dashboard_ids(existing_project: dict[str, Any] | None, incoming: set[str]) -> set[str]:
    """Dashboards the previous import of this lineage wrote that this one drops."""
    hops = ((existing_project or {}).get("provenance") or {}).get("imported_from") or []
    if not hops or not isinstance(hops[-1], dict):
        return set()
    return {str(d) for d in hops[-1].get("dashboard_ids") or []} - incoming


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------


def _normalise_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    if "id" in doc and "_id" not in doc:
        doc["_id"] = doc.pop("id")
    return doc


def _rewrite_bucket(obj: Any, source_prefix: str, target_prefix: str) -> Any:
    if isinstance(obj, str):
        return target_prefix + obj[len(source_prefix) :] if obj.startswith(source_prefix) else obj
    if isinstance(obj, dict):
        return {k: _rewrite_bucket(v, source_prefix, target_prefix) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_bucket(v, source_prefix, target_prefix) for v in obj]
    return obj


def _restore_doc(section: str, doc: dict[str, Any]) -> dict[str, Any]:
    """ObjectIds and datetimes back, with the per-collection exceptions."""
    doc = _normalise_id(doc)
    if section == "multiqc":
        # data_collection_id is a string by model and is queried as one.
        restored = dict(doc)
        if isinstance(restored.get("_id"), str) and ObjectId.is_valid(restored["_id"]):
            restored["_id"] = ObjectId(restored["_id"])
        return restored
    restored = cast(dict[str, Any], restore_complex_objects(doc))
    if section == "deltatables":
        for key in ("delta_commit_timestamp",):
            if key in restored:
                restored[key] = parse_json_datetime_naive(restored[key])
        aggs = restored.get("aggregation")
        if isinstance(aggs, list):
            restored["aggregation"] = [
                {
                    **a,
                    **{
                        k: parse_json_datetime_naive(a[k])
                        for k in ("aggregation_time", "delta_commit_timestamp")
                        if k in a
                    },
                }
                if isinstance(a, dict)
                else a
                for a in aggs
            ]
    return restored


def _owner_entry(
    owner_id: ObjectId, owner_email: str | None, previous: dict[str, Any] | None
) -> dict:
    entry = dict(previous or {})
    entry["_id"] = owner_id
    if owner_email:
        entry["email"] = owner_email
    entry.pop("id", None)
    return entry


def _remap_permissions(
    permissions: Any,
    *,
    owner_id: ObjectId,
    owner_email: str | None,
    existing_user_ids: set[str] | None,
    force_remap: bool,
    strip_shares: bool,
) -> tuple[Any, int]:
    """Owners remapped to this instance; returns (permissions, shares dropped)."""
    if not isinstance(permissions, dict):
        return permissions, 0
    perms = dict(permissions)
    owners = perms.get("owners") if isinstance(perms.get("owners"), list) else []
    new_owners: list[Any] = []
    for owner in owners:
        if not isinstance(owner, dict):
            continue
        oid = str(owner.get("_id") or owner.get("id") or "")
        known = existing_user_ids is not None and oid in existing_user_ids
        if force_remap or not known:
            entry = _owner_entry(owner_id, owner_email, owner)
            if all(str(o.get("_id")) != str(owner_id) for o in new_owners):
                new_owners.append(entry)
        else:
            new_owners.append(owner)
    if not new_owners:
        new_owners = [_owner_entry(owner_id, owner_email, None)]
    perms["owners"] = new_owners
    dropped = 0
    if strip_shares:
        for key in ("editors", "viewers", "group_owners", "group_editors", "group_viewers"):
            value = perms.get(key)
            if isinstance(value, list):
                dropped += len([v for v in value if v != "*"])
                perms[key] = [v for v in value if v == "*"] if key == "viewers" else []
    return perms, dropped


@dataclass
class PreparedImport:
    project_id: ObjectId | None
    docs: dict[str, list[dict]]
    main_family_ids: list[ObjectId]
    dashboard_ids: list[str]
    dc_ids: list[str]
    shares_dropped: int = 0


def prepare_docs_for_import(
    data: dict[str, list[dict]],
    *,
    owner_id: ObjectId,
    owner_email: str | None = None,
    existing_user_ids: set[str] | None = None,
    force_remap: bool = False,
    strip_shares: bool = False,
    source_bucket: str | None,
    target_bucket: str,
    hop: ImportHop | None = None,
    existing_project: dict[str, Any] | None = None,
    keep_bundle_visibility: bool = True,
) -> PreparedImport:
    """Turn bundle sections into documents ready to write here. Pure.

    - ObjectIds and datetimes are restored (``multiqc.data_collection_id``
      stays a string);
    - every ``s3://<source bucket>/`` location becomes ``s3://<target bucket>/``:
      readers use the stored location, so without this an import into another
      bucket reads (or fails to read) the source's;
    - owners unknown here, or all of them with ``force_remap``, become
      ``owner_id``; ``strip_shares`` also drops editors, viewers and group
      shares, whose ids mean nothing on this instance;
    - the server-owned project fields are never taken from the bundle:
      provenance is the incoming chain plus ``hop``, the lock and a parked
      owner are left to the caller.
    """
    source_prefix = f"s3://{source_bucket}/" if source_bucket else None
    target_prefix = f"s3://{target_bucket}/"
    out: dict[str, list[dict]] = {}
    shares_dropped = 0
    project_id: ObjectId | None = None
    project_public: bool | None = None

    for section in COLLECTION_ORDER:
        docs = []
        for raw in data.get(section) or []:
            if not isinstance(raw, dict):
                continue
            doc = raw
            if source_prefix and source_prefix != target_prefix:
                doc = cast(dict[str, Any], _rewrite_bucket(doc, source_prefix, target_prefix))
            doc = _restore_doc(section, doc)
            if "permissions" in doc:
                doc["permissions"], dropped = _remap_permissions(
                    doc["permissions"],
                    owner_id=owner_id,
                    owner_email=owner_email,
                    existing_user_ids=existing_user_ids,
                    force_remap=force_remap,
                    strip_shares=strip_shares,
                )
                shares_dropped += dropped
            if section == "projects":
                project_id = doc.get("_id")
                incoming = doc.get("provenance") or {}
                chain = (
                    list(incoming.get("imported_from") or []) if isinstance(incoming, dict) else []
                )
                created = (
                    incoming.get("created_with_version") if isinstance(incoming, dict) else None
                )
                if hop is not None:
                    chain.append(hop.model_dump())
                doc["provenance"] = {"created_with_version": created, "imported_from": chain}
                doc.pop("published_lock", None)
                doc.pop("pending_owner_email", None)
                if not keep_bundle_visibility:
                    doc["is_public"] = bool((existing_project or {}).get("is_public", False))
                project_public = bool(doc.get("is_public", False))
                if existing_project and existing_project.get("registration_time"):
                    doc["registration_time"] = existing_project["registration_time"]
            docs.append(doc)
        out[section] = docs

    if not keep_bundle_visibility and project_public is not None:
        for dash in out.get("dashboards", []):
            dash["is_public"] = project_public

    dashboard_ids = [str(d["_id"]) for d in out.get("dashboards", []) if d.get("_id") is not None]
    if hop is not None:
        hop.dashboard_ids = dashboard_ids
        for doc in out.get("projects", []):
            doc["provenance"]["imported_from"][-1]["dashboard_ids"] = dashboard_ids
    families: list[ObjectId] = []
    for dash in out.get("dashboards", []):
        if dash.get("is_main_tab", True):
            fid = _as_oid(dash.get("dashboard_id") or dash.get("_id"))
            if fid is not None and fid not in families:
                families.append(fid)
    dc_ids: list[str] = []
    if out.get("projects"):
        dc_ids = sorted(resolve_project_scope(out["projects"][0]).dc_id_strs)
    return PreparedImport(
        project_id=project_id,
        docs=out,
        main_family_ids=families,
        dashboard_ids=dashboard_ids,
        dc_ids=dc_ids,
        shares_dropped=shares_dropped,
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


class ImportWriteError(Exception):
    def __init__(self, collection: str, cause: Exception):
        super().__init__(f"import failed for {collection}: {cause}")
        self.collection = collection


def _capture(family_id: ObjectId, actor: Any, kind: str, label: str | None = None) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning

    try:
        versioning.capture_quietly(family_id, kind=kind, author=actor, label=label)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 — a missing version must never fail an import
        logger.warning("import: version capture failed for %s: %s", family_id, exc)


def _existing_families(project_id: ObjectId) -> list[ObjectId]:
    cols = _collections()
    families: list[ObjectId] = []
    for dash in cols["dashboards"].find(
        {"$or": [{"project_id": project_id}, {"project_id": str(project_id)}]},
        {"_id": 1, "dashboard_id": 1, "is_main_tab": 1, "parent_dashboard_id": 1},
    ):
        raw = (
            dash.get("dashboard_id") or dash.get("_id")
            if dash.get("is_main_tab", True)
            else dash.get("parent_dashboard_id")
        )
        fid = _as_oid(raw)
        if fid is not None and fid not in families:
            families.append(fid)
    return families


def apply_project_import(
    prepared: PreparedImport,
    *,
    actor: Any,
    label: str | None = None,
    existing_project: dict[str, Any] | None = None,
    delete_stale: bool = True,
    invalidate: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Write a prepared import. Returns documents written per collection.

    Before anything is written, every dashboard family of the project already
    here records its current state (unchanged state writes nothing), so the
    import is undoable from History. After, each imported main family records
    an ``import`` version labelled ``label``.

    ``delete_stale`` removes what the previous import of this lineage wrote and
    this one no longer carries: its dashboards, and the file / delta table /
    MultiQC / JBrowse records of data collections the project dropped. A
    dashboard the previous import did not write (a visitor's copy) is kept.
    """
    cols = _collections()
    pid = prepared.project_id
    if pid is not None:
        for family in _existing_families(pid):
            _capture(family, actor, "explicit")

    written: dict[str, int] = {}
    for section in COLLECTION_ORDER:
        docs = prepared.docs.get(section) or []
        if not docs:
            written[section] = 0
            continue
        try:
            for doc in docs:
                cols[section].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        except Exception as exc:  # noqa: BLE001 — re-raised with the collection named
            raise ImportWriteError(section, exc) from exc
        written[section] = len(docs)

    if delete_stale and pid is not None and existing_project is not None:
        stale = _stale_dashboard_ids(existing_project, set(prepared.dashboard_ids))
        if stale:
            res = cols["dashboards"].delete_many(
                {
                    "_id": {"$in": [ObjectId(s) for s in stale]},
                    "$or": [{"project_id": pid}, {"project_id": str(pid)}],
                }
            )
            written["dashboards_deleted"] = res.deleted_count
        old_dcs = resolve_project_scope(existing_project).dc_id_strs
        gone = sorted(old_dcs - set(prepared.dc_ids))
        if gone:
            gone_q = {"$in": gone + [ObjectId(g) for g in gone]}
            for section in DC_SCOPED_SECTIONS:
                cols[section].delete_many({"data_collection_id": gone_q})

    for family in prepared.main_family_ids:
        _capture(family, actor, "import", label)

    if invalidate is not None:
        for dc_id in prepared.dc_ids:
            try:
                invalidate(dc_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("import: cache invalidation failed for %s: %s", dc_id, exc)
    return written


def default_invalidate(dc_id: str) -> None:
    from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
        _invalidate_table_caches_for_dc,
    )

    _invalidate_table_caches_for_dc(dc_id)


def restore_s3_entries(
    bundle: OpenedBundle, client: Any, bucket: str, *, allowed: Callable[[str], bool] | None = None
) -> tuple[int, list[str]]:
    """Upload a bundle's ``s3_data/`` members to ``bucket``. Returns (uploaded, failures).

    Stops at the first connection-level failure: no later object recovers from
    a dead endpoint.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    uploaded = 0
    failures: list[str] = []
    for member, key in bundle.s3_entries:
        if allowed is not None and not allowed(key):
            failures.append(f"{key}: outside the project's prefixes")
            continue
        try:
            with bundle.zf.open(member) as src:
                client.upload_fileobj(src, bucket, key)
            uploaded += 1
        except ClientError as exc:
            logger.error("import: failed to restore %s: %s", key, exc)
            failures.append(f"{key}: {exc}")
        except BotoCoreError as exc:
            logger.error("import: aborting S3 restore, endpoint unusable: %s", exc)
            failures.append(f"{key}: {exc}")
            break
    return uploaded, failures


__all__ = [
    "BUNDLE_FORMAT_VERSION",
    "BundleError",
    "BundleLimits",
    "BundleReport",
    "BundleTooLarge",
    "ImportWriteError",
    "OpenedBundle",
    "PreparedImport",
    "ProjectScope",
    "S3ObjectRef",
    "apply_project_import",
    "build_bundle_metadata",
    "bundle_json_bytes",
    "collect_bundle_docs",
    "default_invalidate",
    "list_s3_objects",
    "manifest_from_s3_metadata",
    "normalize_s3_path",
    "open_bundle_zip",
    "prepare_docs_for_import",
    "resolve_project_scope",
    "restore_s3_entries",
    "spool_file",
    "validate_bundle",
    "write_bundle_zip",
]
