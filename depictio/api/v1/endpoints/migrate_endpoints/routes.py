"""
Project Migration Endpoints

Provides non-destructive project-scoped migration between Depictio instances.
Exports a project bundle (MongoDB docs + S3 files) from the source instance
and imports it into the target instance via upsert (never wipes other projects).
"""

import hashlib
import os
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import boto3
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    data_collections_collection,
    deltatables_collection,
    jbrowse_collection,
    multiqc_collection,
    projects_collection,
    users_collection,
)
from depictio.api.v1.endpoints.projects_endpoints.publish_lock import LOCKED_DETAIL
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
)
from depictio.api.v1.permissions import build_access_query, get_user_group_ids
from depictio.api.v1.services import project_bundle
from depictio.api.v1.services.migration_push import BundleListingError, build_project_bundle_file
from depictio.models.models.data_collections_types.genomic_tracks import genomic_tracks_s3_prefix
from depictio.models.models.data_collections_types.phylogeny import phylogeny_s3_key
from depictio.models.models.migration import ImportHop
from depictio.models.models.users import User
from depictio.version import get_version

migrate_endpoint_router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class MigrateExportRequest(BaseModel):
    project_id: str | None = None
    project_name: str | None = None
    mode: Literal["all", "metadata", "dashboard", "files"] = "all"
    target_s3_config: dict | None = None
    dry_run: bool = False


class MigrateImportRequest(BaseModel):
    bundle: dict
    owner_user_id: str | None = None
    dry_run: bool = False
    force_owner_remap: bool = False
    overwrite: bool = False  # must be True to replace an already-existing project


class MigrateImportResponse(BaseModel):
    success: bool
    message: str
    upserted: dict = {}
    dry_run: bool = False
    conflict: bool = False  # True when project exists and overwrite=False was rejected
    warnings: list[str] = []
    report: dict | None = None


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def _normalize_s3_path(location: str, bucket: str) -> str | None:
    """Strip s3://bucket/ prefix and return the path within the bucket.

    Returns None if the path is empty or an S3 URI without a key component.
    Non-S3 paths are assumed to be bare keys and returned as-is.
    """
    if not location:
        return None
    prefix = "s3://"
    if not location.startswith(prefix):
        return location
    # Split "bucket/path/to/object" into at most 2 parts
    parts = location[len(prefix) :].split("/", 1)
    return parts[1] if len(parts) == 2 else None


def _dc_ids_query(dc_ids: list[ObjectId]) -> dict:
    """Build a $in query matching data_collection_id stored as either ObjectId or string.

    Some documents (e.g. deltatables created by the background processor) store
    data_collection_id as a plain string; others store it as an ObjectId.  Querying
    with both forms ensures we find all matching documents regardless of storage format.
    """
    return {"$in": dc_ids + [str(dc_id) for dc_id in dc_ids]}


def _collect_s3_locations_for_project(dc_ids: list[ObjectId], source_bucket: str) -> list[str]:
    """Collect all S3 paths for a project's data collections across all DC types."""
    locations: list[str] = []
    seen: set[str] = set()

    def add(loc: str | None) -> None:
        if loc and loc not in seen:
            seen.add(loc)
            locations.append(loc)

    dc_query = _dc_ids_query(dc_ids)

    # Delta Lake tables
    for dt in deltatables_collection.find({"data_collection_id": dc_query}):
        raw = dt.get("delta_table_location") or dt.get("location")
        add(_normalize_s3_path(raw, source_bucket) if raw else None)

    # GeoJSON and Image (stored in data_collections.config.dc_specific_properties)
    for dc in data_collections_collection.find({"_id": {"$in": dc_ids}}):
        props = dc.get("config", {}).get("dc_specific_properties", {}) or {}
        # GeoJSON
        geojson_loc = props.get("s3_location")
        if geojson_loc:
            add(_normalize_s3_path(geojson_loc, source_bucket))
        # Image base folder (prefix-based)
        image_folder = props.get("s3_base_folder")
        if image_folder:
            add(_normalize_s3_path(image_folder, source_bucket))

    # MultiQC reports
    for report in multiqc_collection.find({"data_collection_id": dc_query}):
        raw = report.get("s3_location")
        if raw:
            add(_normalize_s3_path(raw, source_bucket))

    # JBrowse2 – only include S3 URIs
    for jb in jbrowse_collection.find({"data_collection_id": dc_query}):
        for track in jb.get("tracks", []):
            uri = track.get("uri", "")
            if uri.startswith("s3://"):
                add(_normalize_s3_path(uri, source_bucket))

    # Phylogeny trees and genomic track files: no document records where the
    # CLI uploaded them, the key is derived from the DC id, so tell those DCs
    # apart by their config.
    wanted = set(dc_ids)
    for project in projects_collection.find(
        {"workflows.data_collections._id": {"$in": dc_ids}},
        {"workflows.data_collections._id": 1, "workflows.data_collections.config.type": 1},
    ):
        for wf in project.get("workflows") or []:
            for dc in wf.get("data_collections") or []:
                if dc.get("_id") not in wanted:
                    continue
                dc_type = (dc.get("config") or {}).get("type")
                if dc_type == "phylogeny":
                    add(phylogeny_s3_key(str(dc["_id"])))
                elif dc_type == "genomic_tracks":
                    add(genomic_tracks_s3_prefix(str(dc["_id"])))

    return locations


def _normalize_endpoint(url: str) -> str | None:
    """Normalize an S3 endpoint URL to a comparable scheme://host:port form.

    Lower-cases scheme and host, fills in the default port for the scheme when
    absent, and drops any path / query / fragment. Returns None if the URL has
    no usable host (so callers can reject it rather than match loosely).
    """
    try:
        parts = urlsplit(url.strip())
    except (ValueError, AttributeError):
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return None
    port = parts.port
    if port is None:
        port = {"http": 80, "https": 443}.get(scheme)
    return f"{scheme}://{host}:{port}"


def _validate_target_s3_endpoint(target_config: dict) -> None:
    """Guard against SSRF / data-exfiltration via a caller-supplied S3 endpoint.

    A caller-supplied ``endpoint_url`` is handed to boto3, which makes the SERVER
    connect to it. Without a gate an attacker could point migration at internal
    hosts (cloud metadata, internal services) or exfiltrate exported project data
    to an attacker-controlled bucket.

    Policy (safe-by-default / opt-in):
      * Always allow the deployment's own configured S3 endpoint (self-migration).
      * Otherwise require an exact normalized (scheme+host+port) match against the
        operator-vetted allowlist ``settings.backup.migration_allowed_s3_endpoints``.
      * The allowlist is empty by default, so all external endpoints are rejected
        unless an operator has explicitly opted in.

    Allowlist entries are operator-vetted, so we deliberately keep the logic simple
    (own-endpoint OR allowlisted) and do not additionally resolve hostnames / probe
    IP ranges — the empty default already rejects everything caller-supplied.
    """
    raw_endpoint = target_config.get("endpoint_url")
    if not raw_endpoint or not isinstance(raw_endpoint, str):
        raise HTTPException(
            status_code=400,
            detail="target_s3_config.endpoint_url is required and must be a string",
        )

    candidate = _normalize_endpoint(raw_endpoint)
    if candidate is None:
        raise HTTPException(
            status_code=400, detail="target_s3_config.endpoint_url is not a valid URL"
        )

    own_endpoint = _normalize_endpoint(settings.s3.endpoint_url)
    if own_endpoint is not None and candidate == own_endpoint:
        return  # self-migration to this deployment's own S3 store

    allowlist = {
        normalized
        for entry in settings.backup.migration_allowed_s3_endpoints
        if (normalized := _normalize_endpoint(entry)) is not None
    }
    if candidate in allowlist:
        return

    logger.warning(
        "migrate export: rejected target S3 endpoint not in allowlist (host=%s)",
        urlsplit(raw_endpoint.strip()).hostname,
    )
    raise HTTPException(
        status_code=403,
        detail=(
            "Target S3 endpoint is not permitted. Only this deployment's own S3 "
            "endpoint or an operator-allowlisted endpoint "
            "(DEPICTIO_BACKUP_MIGRATION_ALLOWED_S3_ENDPOINTS) may be used for migration."
        ),
    )


def _copy_s3_locations(
    s3_paths: list[str],
    source_config: dict,
    target_config: dict,
    dry_run: bool = False,
) -> dict:
    """Copy S3 objects from source to target S3 store, preserving paths."""
    source_client = boto3.client(
        "s3",
        endpoint_url=source_config["endpoint_url"],
        aws_access_key_id=source_config["aws_access_key_id"],
        aws_secret_access_key=source_config["aws_secret_access_key"],
        region_name=source_config.get("region_name", "us-east-1"),
        verify=source_config.get("verify", settings.s3.verify_tls),
    )
    target_client = boto3.client(
        "s3",
        endpoint_url=target_config["endpoint_url"],
        aws_access_key_id=target_config["aws_access_key_id"],
        aws_secret_access_key=target_config["aws_secret_access_key"],
        region_name=target_config.get("region_name", "us-east-1"),
        verify=target_config.get("verify", settings.s3.verify_tls),
    )

    source_bucket = source_config["bucket"]
    target_bucket = target_config["bucket"]

    total_files = 0
    total_bytes = 0
    errors: list[str] = []

    for path in s3_paths:
        path_key = path.strip("/")
        try:
            paginator = source_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=source_bucket, Prefix=path_key):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not dry_run:
                        try:
                            get_resp = source_client.get_object(Bucket=source_bucket, Key=key)
                            target_client.upload_fileobj(
                                get_resp["Body"],
                                target_bucket,
                                key,
                                ExtraArgs={
                                    "ContentType": get_resp.get(
                                        "ContentType", "application/octet-stream"
                                    )
                                },
                            )
                        except ClientError as e:
                            # Log full error internally; return a generic message to the
                            # caller — boto3 ClientError text can include endpoint
                            # hostnames/URLs we don't want to leak in the response.
                            logger.error("Failed to copy %s: %s", key, e)
                            errors.append(f"Failed to copy {key}")
                            continue
                    total_files += 1
                    total_bytes += obj["Size"]
                    logger.debug(
                        "%s %s -> s3://%s/%s",
                        "DRY RUN:" if dry_run else "Copied:",
                        key,
                        target_bucket,
                        key,
                    )
        except ClientError as e:
            # See above: keep the detailed boto3 error in logs only.
            logger.error("Error listing %s: %s", path_key, e)
            errors.append(f"Error listing {path_key}")

    return {
        "locations_copied": len(s3_paths),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "errors": errors,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------

#: Default cap on the S3 data an export may carry inline (overridden by
#: ``DEPICTIO_MIGRATION_MAX_BUNDLE_BYTES`` once the migration settings exist).
DEFAULT_MAX_BUNDLE_BYTES = 10 * 1024**3


def _migration_setting(name: str, default: Any) -> Any:
    migration = getattr(settings, "migration", None)
    value = getattr(migration, name, None) if migration is not None else None
    return default if value is None else value


def _instance_s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3.endpoint_url,
        aws_access_key_id=settings.s3.aws_access_key_id,
        aws_secret_access_key=settings.s3.aws_secret_access_key,
        region_name="us-east-1",
        verify=settings.s3.verify_tls,
    )


def _content_disposition(project_name: str) -> str:
    """Latin-1 safe ``filename`` plus an RFC 5987 ``filename*`` with the real name."""
    filename = f"depictio_export_{project_name}.zip"
    ascii_name = "".join(
        c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in project_name
    )
    return (
        f'attachment; filename="depictio_export_{ascii_name}.zip"; '
        f"filename*=UTF-8''{quote(filename)}"
    )


@migrate_endpoint_router.post("/export-project")
async def export_project(
    request: MigrateExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
) -> FileResponse:
    """
    Export a project bundle from this instance.

    Scoped to one project: cascades through workflows → data_collections →
    files / deltatables / runs → dashboards.  Optionally copies S3 data to
    a target S3 store (modes all / files).

    Access rules:
    - Admins can export any project, in every mode.
    - In public/demo mode the anonymous and temporary visitors are non-admin,
      so they're allowed to export too — but only projects they can actually
      read (public projects or ones shared with them), never arbitrary private
      projects. Uses ``get_user_or_anonymous`` so tokenless public-mode
      visitors resolve to the anonymous user instead of 401-ing.
    - On standard (non-public) instances export stays admin-only.

    Non-admin callers may not supply ``target_s3_config``: that triggers the
    server-to-server S3 copy path (an exfiltration vector gated by
    ``_validate_target_s3_endpoint``), which has no place in the UI export flow
    that bundles S3 objects straight into the ZIP.

    The ZIP is written to a temporary file and streamed from there, so memory
    use does not grow with the project's data. Data above
    ``DEPICTIO_MIGRATION_MAX_BUNDLE_BYTES`` is refused with a 413.
    """
    if not current_user.is_admin:
        if not settings.auth.is_public_mode:
            raise HTTPException(status_code=403, detail="Only administrators can export projects")
        if request.target_s3_config:
            raise HTTPException(
                status_code=403,
                detail="Non-admin users cannot specify a target S3 config for export",
            )

    # Resolve project (permission-scoped for non-admin callers)
    query: dict[str, Any]
    if request.project_id:
        query = {"_id": ObjectId(request.project_id)}
    elif request.project_name:
        query = {"name": request.project_name}
    else:
        raise HTTPException(status_code=400, detail="Provide project_id or project_name")

    if not current_user.is_admin:
        # Mirror _async_get_project_from_id: a non-admin may only reach projects
        # they own/edit/view or that are explicitly public.
        query.update(
            build_access_query(current_user, "viewer", get_user_group_ids(current_user.id))
        )

    project = projects_collection.find_one(query)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        built = build_project_bundle_file(
            project,
            mode=request.mode,
            dry_run=request.dry_run,
            target_s3_config=request.target_s3_config,
        )
    except project_bundle.BundleTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except BundleListingError:
        raise HTTPException(status_code=502, detail="Could not list the project's data")
    path = built.path

    return FileResponse(
        path,
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(project.get("name") or "export")},
        background=BackgroundTask(os.unlink, path),
    )


# ---------------------------------------------------------------------------
# Import endpoints
# ---------------------------------------------------------------------------


def _run_import(
    *,
    metadata: dict[str, Any],
    data: dict[str, list[dict]],
    s3_keys: list[str],
    current_user: User,
    dry_run: bool,
    overwrite: bool,
    owner_user_id: str | None,
    force_owner_remap: bool,
    via: Literal["cli", "zip"],
    bundle_sha256: str | None = None,
    write_s3: Callable[[], None] | None = None,
) -> MigrateImportResponse:
    """Validate, prepare and apply one bundle (the admin import paths).

    ``write_s3`` restores the bundle's inline data; it runs after every check
    and before any Mongo write, and raises to abort the import.
    """
    report = project_bundle.validate_bundle(metadata, data, s3_keys, strict=False)
    if report.errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Bundle refused", "errors": report.errors[:20]},
        )

    if report.existing_locked:
        # Only an approved migration request may write to a published project.
        raise HTTPException(status_code=409, detail=LOCKED_DETAIL)

    if report.conflict != "none" and not overwrite and not dry_run:
        name = report.existing_project_name or report.project_id
        return MigrateImportResponse(
            success=False,
            message=f"Project '{name}' already exists on this instance. "
            "Set overwrite=true to replace it.",
            conflict=True,
            warnings=report.warnings,
        )

    owner_id: Any = current_user.id
    if owner_user_id:
        try:
            owner_id = ObjectId(owner_user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid owner_user_id")

    existing = (
        projects_collection.find_one({"_id": ObjectId(report.project_id)})
        if report.project_id
        else None
    )
    hop = ImportHop(
        source_instance=str(metadata.get("source_instance") or "unknown"),
        source_depictio_version=metadata.get("depictio_version"),
        bundle_format_version=report.bundle_format_version,
        exported_at=metadata.get("exported_at") or metadata.get("timestamp"),
        target_depictio_version=get_version(),
        bundle_sha256=bundle_sha256,
        via=via,
    )
    prepared = project_bundle.prepare_docs_for_import(
        data,
        owner_id=ObjectId(str(owner_id)),
        owner_email=getattr(current_user, "email", None) if not owner_user_id else None,
        existing_user_ids={str(u["_id"]) for u in users_collection.find({}, {"_id": 1})},
        force_remap=force_owner_remap,
        source_bucket=project_bundle._source_bucket(metadata, data),
        target_bucket=settings.s3.bucket,
        hop=hop if data.get("projects") else None,
        existing_project=existing,
    )
    counts = {k: len(v) for k, v in prepared.docs.items()}

    if dry_run:
        total = sum(counts.values())
        return MigrateImportResponse(
            success=True,
            message=f"DRY RUN: would upsert {total} documents",
            upserted=counts,
            dry_run=True,
            warnings=report.warnings,
            report=report.model_dump(),
        )

    if write_s3 is not None:
        write_s3()

    label = f"Imported from {hop.source_instance}"
    if hop.source_depictio_version:
        label += f" (Depictio {hop.source_depictio_version})"
    try:
        written = project_bundle.apply_project_import(
            prepared,
            actor=current_user,
            label=label,
            existing_project=existing,
            invalidate=project_bundle.default_invalidate,
        )
    except project_bundle.ImportWriteError as e:
        logger.error("migrate import error: %s", e)
        raise HTTPException(status_code=500, detail=f"Import failed for {e.collection}")

    upserted = {k: v for k, v in written.items() if k in project_bundle.COLLECTION_ORDER}
    total = sum(upserted.values())
    logger.info("migrate import: upserted %d documents (%s)", total, upserted)
    return MigrateImportResponse(
        success=True,
        message=f"Upserted {total} documents",
        upserted=upserted,
        warnings=report.warnings,
        report=report.model_dump(),
    )


@migrate_endpoint_router.post("/import-project", response_model=MigrateImportResponse)
async def import_project(
    request: MigrateImportRequest,
    current_user: User = Depends(get_user_or_anonymous),
) -> MigrateImportResponse:
    """
    Import a project bundle into this instance (upsert by id).

    The bundle is validated first: every document must belong to the bundled
    project, and none may collide with another project's ids here. Owner ids
    that do not exist on this instance are remapped to the calling admin (or
    the specified owner_user_id). ``s3://`` locations are rewritten to this
    instance's bucket. Each dashboard family records the state the import
    replaces, then an ``import`` version.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can import projects")

    bundle = request.bundle
    if "data" not in bundle or not isinstance(bundle["data"], dict):
        raise HTTPException(status_code=400, detail="Bundle missing 'data' section")
    metadata = bundle.get("migrate_metadata") or {}
    s3_keys: list[str] = []  # the CLI copies S3 server side; the JSON bundle holds no data
    return _run_import(
        metadata=metadata if isinstance(metadata, dict) else {},
        data=bundle["data"],
        s3_keys=s3_keys,
        current_user=current_user,
        dry_run=request.dry_run,
        overwrite=request.overwrite,
        owner_user_id=request.owner_user_id,
        force_owner_remap=request.force_owner_remap,
        via="cli",
    )


def _hash_upload(fileobj: Any) -> str:
    digest = hashlib.sha256()
    fileobj.seek(0)
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        digest.update(chunk)
    fileobj.seek(0)
    return digest.hexdigest()


@migrate_endpoint_router.post("/import-project-zip", response_model=MigrateImportResponse)
async def import_project_zip(
    file: UploadFile = File(...),
    dry_run: bool = False,
    overwrite: bool = False,
    current_user: User = Depends(get_user_or_anonymous),
) -> MigrateImportResponse:
    """
    Import a project bundle from a ZIP file (for UI use).

    Accepts a .zip file containing bundle.json and migrate_metadata.json.
    Always remaps all owners to the calling user (force_owner_remap=True).

    Requires an authenticated admin caller — previously this used
    ``get_user_or_anonymous`` which let an anonymous (admin-flagged)
    public-mode user import arbitrary project ZIPs.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can import projects")

    # Parsing the archive and restoring its payload to object storage are two
    # different failures and are kept apart deliberately: they used to share one
    # try block, so an unreachable S3 endpoint surfaced as "Invalid ZIP bundle"
    # and sent the operator hunting a corrupt export that was in fact fine.
    sha256 = _hash_upload(file.file)
    try:
        opened = project_bundle.open_bundle_zip(file.file)
    except project_bundle.BundleError as e:
        logger.error("migrate import-zip: failed to parse ZIP bundle: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid ZIP bundle: {e}")

    def write_s3() -> None:
        if not opened.s3_entries:
            return
        uploaded, failures = project_bundle.restore_s3_entries(
            opened, _instance_s3_client(), settings.s3.bucket
        )
        logger.info("Migrate import: restored %d S3 objects to the S3 store", uploaded)
        # Abort before touching Mongo. Importing the metadata of a project
        # whose data files never landed would leave a project that lists
        # collections it cannot read, which is worse than not importing it.
        if failures:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"ZIP bundle is valid, but only {uploaded} of {len(opened.s3_entries)} data "
                    f"files could be written to object storage at "
                    f"{settings.s3.endpoint_url}. Nothing was imported. "
                    f"First error: {failures[0]}"
                ),
            )

    try:
        return _run_import(
            metadata=opened.metadata,
            data=opened.data,
            s3_keys=[key for _, key in opened.s3_entries],
            current_user=current_user,
            dry_run=dry_run,
            overwrite=overwrite,
            owner_user_id=None,
            force_owner_remap=True,
            via="zip",
            bundle_sha256=sha256,
            write_s3=write_s3,
        )
    finally:
        opened.close()
