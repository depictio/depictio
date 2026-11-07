"""Add plain tables from a folder to an existing project (no pipeline).

``POST /projects/{project_id}/add_tables_from_folder`` points at a folder (a
folder on the server's own disk when ``depictio local`` allows it, or an
``s3://`` prefix, including a private bucket with typed credentials) that holds
plain table files. A dry run lists the files found and says which are tables;
a real run creates one table data collection per requested file.

Confinement and storage rules are those of the run-folder flow and are reused
as they are, not reimplemented:

* a local folder goes through ``from_run._build_local_data_root`` (local
  folders on, request from this machine, administrator, inside the allowed
  roots), and every entry listed or read is checked against the same policy;
* an ``s3://`` folder goes through ``run_folders._s3_folder`` (bucket lists,
  the instance's own bucket refused, or typed ``storage`` read alone).

Storage settings of a private bucket: ingestion here is synchronous and
in-process, so the typed settings are handed straight to
``_push_workflow_and_ingest`` (``remote_storage_options``) and the scan and
process stages read with them. Nothing but that read uses them. So that a later
refresh of the project can read the bucket too, they are also stored on the
project (``storage_config._store_project_storage``), but only when the caller
owns the project and the project has no storage settings yet: an existing
configuration is never overwritten by a request that merely names a bucket.

Synchronous helpers throughout; the route dispatches via ``asyncio.to_thread``
because the CLI helpers call back into this same FastAPI process.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Literal

from bson import ObjectId
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import projects_collection
from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _build_table_workflow,
    _editable_project_and_token,
    _push_workflow_and_ingest,
    _user_can_edit_project,
    origin_now,
)
from depictio.api.v1.endpoints.projects_endpoints.from_run import (
    _build_local_data_root,
    _is_local_path,
)
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import (
    NOISE_DIRS,
    CodedHTTPException,
)
from depictio.api.v1.endpoints.projects_endpoints.publish_lock import assert_project_unlocked
from depictio.api.v1.endpoints.projects_endpoints.run_folders import (
    LOCATION_RULE,
    LOCATION_RULE_LOCAL,
    _s3_folder,
)
from depictio.api.v1.endpoints.projects_endpoints.storage_config import RunStorageIn
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.logging import logger
from depictio.models.s3_access import S3AccessError, is_s3_url, iter_object_pages

#: Files returned by one listing. More are dropped and ``truncated`` is set.
MAX_LISTED_FILES = 500
#: Entries looked at (local walk) or keys read (S3 listing) before stopping.
MAX_EXAMINED = 10_000
#: Folder levels below the location a recursive listing goes down.
MAX_DEPTH = 4
#: Files created by one real run.
MAX_CREATED = 100

PRIVATE_BUCKET_ACTION = "Reading a private bucket"

# extension (lower case, no dot) -> DCTableConfig format
TABLE_FORMATS: dict[str, str] = {
    "csv": "csv",
    "tsv": "tsv",
    "tab": "tsv",
    "parquet": "parquet",
    "pq": "parquet",
    "feather": "feather",
    "arrow": "feather",
    "xls": "xls",
    "xlsx": "xlsx",
}
# Formats polars reads from a gzip stream; the others are binary containers.
GZIP_FORMATS = frozenset({"csv", "tsv"})


class FolderTablesRequest(BaseModel):
    location: str
    # Paths relative to ``location``; required when the request is not a dry run.
    files: list[str] | None = None
    dry_run: bool = True
    storage: RunStorageIn | None = None
    # Look into sub-folders too (bounded by MAX_DEPTH and MAX_LISTED_FILES).
    recursive: bool = False


class FolderTableFile(BaseModel):
    path: str
    name: str
    format: str | None = None
    size: int | None = None
    table: bool
    reason: str | None = None
    compression: Literal["none", "gzip"] = "none"


class FolderTableCreated(BaseModel):
    path: str
    data_collection_id: str | None = None
    data_collection_tag: str | None = None
    status: Literal["ingested", "failed"]
    error: str | None = None


class FolderTablesReport(BaseModel):
    location: str
    source: Literal["local", "s3"]
    files: list[FolderTableFile] = Field(default_factory=list)
    truncated: bool = False
    created: list[FolderTableCreated] = Field(default_factory=list)
    dry_run: bool = True
    # True when typed storage settings were stored on the project by this call.
    storage_saved: bool = False


# ── classification ───────────────────────────────────────────────────────────


def _split_name(filename: str) -> tuple[str, str | None, str]:
    """``(stem, format or None, compression)`` of a file name.

    ``.gz`` is a compression suffix, not a format: ``counts.csv.gz`` is a gzip
    csv named ``counts``. The stem is the name without its last extension, as
    the create-data-collection form fills it.
    """
    compression = "none"
    base = filename
    if base.lower().endswith(".gz"):
        compression = "gzip"
        base = base[: -len(".gz")]
    stem, dot, ext = base.rpartition(".")
    if not dot or not stem:
        return base, None, compression
    return stem, TABLE_FORMATS.get(ext.lower()), compression


def _classify(rel_path: str, size: int | None) -> FolderTableFile:
    filename = rel_path.rsplit("/", 1)[-1]
    stem, fmt, compression = _split_name(filename)
    reason: str | None = None
    if fmt is None:
        reason = "Not a table file (csv, tsv, parquet, feather, xls, xlsx)."
    elif compression == "gzip" and fmt not in GZIP_FORMATS:
        reason = f"A gzip-compressed {fmt} file cannot be read as a table."
        fmt = None
    elif size == 0:
        reason = "The file is empty."
    return FolderTableFile(
        path=rel_path,
        name=stem,
        format=fmt,
        size=size,
        table=reason is None,
        reason=reason,
        compression=compression if fmt else "none",  # type: ignore[arg-type]
    )


def _hidden(name: str) -> bool:
    return name.startswith(".") or name in NOISE_DIRS


# ── listing ──────────────────────────────────────────────────────────────────


def _list_local(root: str, policy, recursive: bool) -> tuple[list[FolderTableFile], bool]:
    found: list[FolderTableFile] = []
    examined = 0
    truncated = False
    max_depth = MAX_DEPTH if recursive else 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        depth = 0 if dirpath == root else os.path.relpath(dirpath, root).count(os.sep) + 1
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not _hidden(d) and depth < max_depth and policy.allows(os.path.join(dirpath, d))
        )
        for filename in sorted(filenames):
            examined += 1
            if examined > MAX_EXAMINED or len(found) >= MAX_LISTED_FILES:
                return found, True
            full = os.path.join(dirpath, filename)
            if _hidden(filename) or not policy.allows(full) or not os.path.isfile(full):
                continue
            try:
                size: int | None = os.path.getsize(full)
            except OSError:
                size = None
            found.append(_classify(os.path.relpath(full, root).replace(os.sep, "/"), size))
    return found, truncated


def _list_s3(folder, recursive: bool) -> tuple[list[FolderTableFile], bool]:
    found: list[FolderTableFile] = []
    examined = 0
    for page in iter_object_pages(
        folder.target, folder.prefix, delimiter=None if recursive else "/"
    ):
        for obj in page.get("Contents") or []:
            examined += 1
            if examined > MAX_EXAMINED or len(found) >= MAX_LISTED_FILES:
                return found, True
            rel = str(obj.get("Key") or "")[len(folder.prefix) :]
            parts = rel.split("/")
            if not rel or rel.endswith("/") or any(_hidden(p) for p in parts):
                continue
            if len(parts) - 1 > (MAX_DEPTH if recursive else 0):
                continue
            size = obj.get("Size")
            found.append(_classify(rel, int(size) if size is not None else None))
    found.sort(key=lambda f: f.path)
    return found, False


# ── naming ───────────────────────────────────────────────────────────────────


def _project_tags(project_dict: dict[str, Any]) -> set[str]:
    return {
        str(dc.get("data_collection_tag"))
        for wf in project_dict.get("workflows") or []
        for dc in wf.get("data_collections") or []
        if dc.get("data_collection_tag")
    }


def _assign_unique_names(files: list[FolderTableFile], taken: set[str]) -> None:
    """Make every suggested name unique within the project, in listing order.

    A clash gets ``_2``, ``_3``, ... appended. ``taken`` is updated, so a name
    suggested here is not suggested twice.
    """
    for file in files:
        candidate, n = file.name, 1
        while candidate in taken:
            n += 1
            candidate = f"{file.name}_{n}"
        file.name = candidate
        taken.add(candidate)


# ── guards ───────────────────────────────────────────────────────────────────


def _reject_non_admin_in_public_mode(current_user, action: str) -> None:
    if settings.auth.is_public_mode and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"{action} is disabled in public/demo mode for non-admin users",
        )


def _editable_project(project_id: str, current_user) -> dict[str, Any]:
    """The project document, once the caller may edit it and it is not locked.

    400 malformed id, 404 unknown, 403 without edit permission, 409 when the
    project is published (``assert_project_unlocked``).
    """
    try:
        project_oid = ObjectId(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid project_id: {exc}")
    project_dict = projects_collection.find_one({"_id": project_oid})
    if not project_dict:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not _user_can_edit_project(
        project_dict, current_user.id, getattr(current_user, "is_admin", False)
    ):
        raise HTTPException(
            status_code=403, detail="You don't have edit permission on this project."
        )
    assert_project_unlocked(project_dict)
    return project_dict


# ── the work ─────────────────────────────────────────────────────────────────


class _Source:
    """A folder resolved and confined: where it is, how to read and list it."""

    def __init__(self, location: str, kind: Literal["local", "s3"], policy=None, folder=None):
        self.location = location
        self.kind = kind
        self.policy = policy
        self.folder = folder

    def list(self, recursive: bool) -> tuple[list[FolderTableFile], bool]:
        if self.kind == "local":
            return _list_local(self.location, self.policy, recursive)
        return _list_s3(self.folder, recursive)

    def file_location(self, rel: str) -> str:
        if self.kind == "local":
            return os.path.join(self.location, *rel.split("/"))
        return f"{self.folder.url}{rel}"


def _open_source(payload: FolderTablesRequest, request, current_user) -> _Source:
    location = payload.location.strip()
    if _is_local_path(location):
        root = _build_local_data_root(
            location, request=request, current_user=current_user, count_files=False
        )
        from depictio.api.v1.configs.settings_models import local_data_policy

        policy = local_data_policy()
        return _Source(root.location, "local", policy=policy)
    if is_s3_url(location):
        folder = _s3_folder(location, payload.storage)
        return _Source(folder.url, "s3", folder=folder)
    from depictio.api.v1.configs.settings_models import local_data_policy

    rule = LOCATION_RULE_LOCAL if local_data_policy() is not None else LOCATION_RULE
    raise CodedHTTPException(422, rule, "location_unsupported")


def _ingest_one(
    *,
    source: _Source,
    file: FolderTableFile,
    project_oid: ObjectId,
    current_user,
    full_token: dict,
    remote_storage_options,
) -> dict:
    from depictio.models.models.data_collections import Scan, ScanSingle, ScanURL

    location = source.file_location(file.path)
    if source.kind == "local":
        real = os.path.realpath(location)
        # The listing was confined; a swap since (a symlink) must not escape it.
        if not source.policy.allows(real) or not os.path.isfile(real):
            raise HTTPException(status_code=422, detail=f"'{file.path}' is no longer readable.")
        scan = Scan(mode="single", scan_parameters=ScanSingle(filename=real))
        wf_location = os.path.dirname(real)
    else:
        from depictio.api.v1.remote_fetch import RemoteURLRejected, validate_remote_url

        try:
            validate_remote_url(location)
        except RemoteURLRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        scan = Scan(mode="url", scan_parameters=ScanURL(url=location))
        wf_location = location

    # Read compression is detected by polars from the bytes, so no
    # ``compression`` kwarg is passed (read_csv does not accept one).
    polars_kwargs: dict[str, Any] = {}
    assert file.format is not None
    if file.format in ("csv", "tsv"):
        polars_kwargs = {
            "separator": "," if file.format == "csv" else "\t",
            "has_header": True,
            "null_values": ["NA", "NaN", ""],
        }
    workflow, data_collection = _build_table_workflow(
        name=file.name,
        description=f"Added from folder {source.location}",
        data_type="table",
        file_format=file.format,
        polars_kwargs=polars_kwargs,
        lat_column=None,
        lon_column=None,
        scan=scan,
        location=wf_location,
        origin=origin_now("folder", source.location),
    )
    return _push_workflow_and_ingest(
        project_oid=project_oid,
        workflow=workflow,
        data_collection=data_collection,
        name=file.name,
        current_user=current_user,
        full_token=full_token,
        remote_storage_options=remote_storage_options,
    )


def _remote_options(source: _Source, payload: FolderTablesRequest, project_oid: ObjectId):
    """``(settings to read an s3 folder with, typed settings to store)``."""
    if source.kind != "s3":
        return None, None
    from depictio.api.v1.endpoints.projects_endpoints.from_run import _request_read_config
    from depictio.api.v1.endpoints.projects_endpoints.storage_config import (
        ProjectStorageUnusable,
        project_storage_for,
        read_settings,
    )

    if payload.storage is not None:
        settings_in, _reads = _request_read_config(payload.location, payload.storage)
        assert settings_in is not None
        return read_settings(settings_in), settings_in
    try:
        return project_storage_for(project_oid), None
    except ProjectStorageUnusable as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _maybe_store_storage(project_dict: dict, settings_in, current_user) -> bool:
    """Store typed settings on the project when it owns none and the caller owns it."""
    from depictio.api.v1.endpoints.projects_endpoints import storage_config

    project_oid = project_dict["_id"]
    if settings_in is None or not storage_config._user_owns_project(project_dict, current_user):
        return False
    if storage_config.project_storage_collection.find_one({"project_id": project_oid}):
        return False
    try:
        storage_config._store_project_storage(project_oid, settings_in)
    except Exception as exc:
        # Type only: the exception may hold the secret.
        logger.warning(
            f"Could not store typed storage on project {project_oid}: {type(exc).__name__}"
        )
        return False
    return True


def _add_tables(
    project_id: str,
    payload: FolderTablesRequest,
    request,
    current_user,
) -> FolderTablesReport:
    project_dict = _editable_project(project_id, current_user)
    source = _open_source(payload, request, current_user)
    files, truncated = source.list(payload.recursive)
    _assign_unique_names(files, _project_tags(project_dict))
    report = FolderTablesReport(
        location=source.location,
        source=source.kind,
        files=files,
        truncated=truncated,
        dry_run=payload.dry_run,
    )
    if payload.dry_run:
        return report

    requested = payload.files or []
    if not requested:
        raise HTTPException(status_code=422, detail="Name the files to add in 'files'.")
    if len(requested) > MAX_CREATED:
        raise HTTPException(status_code=422, detail=f"At most {MAX_CREATED} files per request.")
    by_path = {f.path: f for f in files}
    unknown = [p for p in requested if p not in by_path]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Not found in '{source.location}': {', '.join(unknown[:5])}",
        )
    not_tables = [p for p in requested if not by_path[p].table]
    if not_tables:
        raise HTTPException(
            status_code=422, detail=f"Not a table file: {', '.join(not_tables[:5])}"
        )

    project_oid, full_token = _editable_project_and_token(project_id, current_user)
    remote_options, typed = _remote_options(source, payload, project_oid)
    for path in dict.fromkeys(requested):
        file = by_path[path]
        try:
            result = _ingest_one(
                source=source,
                file=file,
                project_oid=project_oid,
                current_user=current_user,
                full_token=full_token,
                remote_storage_options=remote_options,
            )
            report.created.append(
                FolderTableCreated(
                    path=path,
                    data_collection_id=result["data_collection_id"],
                    data_collection_tag=file.name,
                    status="ingested",
                )
            )
        except S3AccessError as exc:
            report.created.append(FolderTableCreated(path=path, status="failed", error=exc.detail))
        except HTTPException as exc:
            report.created.append(
                FolderTableCreated(path=path, status="failed", error=str(exc.detail))
            )
        except Exception as exc:
            logger.error(f"add_tables_from_folder: {path} failed: {type(exc).__name__}")
            report.created.append(
                FolderTableCreated(path=path, status="failed", error=f"{type(exc).__name__}: {exc}")
            )
    if typed is not None and any(c.status == "ingested" for c in report.created):
        report.storage_saved = _maybe_store_storage(
            projects_collection.find_one({"_id": project_oid}) or project_dict, typed, current_user
        )
    return report


async def add_tables_from_folder(
    project_id: str,
    payload: FolderTablesRequest,
    request: Request,
    current_user=Depends(get_user_or_anonymous),
):
    """List the table files of a folder, or add one table data collection per file.

    ``POST /projects/{project_id}/add_tables_from_folder``. Dry run (the
    default) lists; a real run needs ``files``, each a path from that listing.
    Refusals of a local folder or an s3 location answer ``{detail, code}``.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    _reject_non_admin_in_public_mode(current_user, "Adding data collections")
    if payload.storage is not None:
        _reject_non_admin_in_public_mode(current_user, PRIVATE_BUCKET_ACTION)
    if not payload.dry_run:
        from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
            _ensure_user_cli_token,
        )

        await _ensure_user_cli_token(current_user)
    try:
        return await asyncio.to_thread(_add_tables, project_id, payload, request, current_user)
    except CodedHTTPException as exc:
        return exc.response()
