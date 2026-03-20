"""
Project Migration Endpoints

Provides non-destructive project-scoped migration between Depictio instances.
Exports a project bundle (MongoDB docs + S3 files) from the source instance
and imports it into the target instance via upsert (never wipes other projects).
"""

import io
import json
import zipfile
from datetime import datetime
from typing import Any, Literal, cast

import boto3
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pymongo.collection import Collection
from pymongo.operations import ReplaceOne

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    jbrowse_collection,
    multiqc_collection,
    projects_collection,
    runs_collection,
    users_collection,
    workflows_collection,
)
from depictio.api.v1.endpoints.backup_endpoints.routes import _convert_complex_objects_to_strings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.users import User

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


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def _normalize_s3_path(location: str, bucket: str) -> str | None:
    """Strip s3://bucket/ prefix and return the path within the bucket.

    Returns None if the path is not S3 or belongs to a different bucket.
    """
    if not location:
        return None
    if location.startswith("s3://"):
        rest = location[len("s3://") :]
        parts = rest.split("/", 1)
        if len(parts) == 2:
            return parts[1]
        return None
    # Assume it is already a bare path
    return location


def _collect_s3_locations_for_project(dc_ids: list[ObjectId], source_bucket: str) -> list[str]:
    """Collect all S3 paths for a project's data collections across all DC types."""
    locations: list[str] = []
    seen: set[str] = set()

    def add(loc: str | None) -> None:
        if loc and loc not in seen:
            seen.add(loc)
            locations.append(loc)

    # Delta Lake tables
    for dt in deltatables_collection.find({"data_collection_id": {"$in": dc_ids}}):
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
    for report in multiqc_collection.find({"data_collection_id": {"$in": dc_ids}}):
        raw = report.get("s3_location")
        if raw:
            add(_normalize_s3_path(raw, source_bucket))

    # JBrowse2 – only include S3 URIs
    for jb in jbrowse_collection.find({"data_collection_id": {"$in": dc_ids}}):
        for track in jb.get("tracks", []):
            uri = track.get("uri", "")
            if uri.startswith("s3://"):
                add(_normalize_s3_path(uri, source_bucket))

    return locations


def _copy_s3_locations(
    s3_paths: list[str],
    source_config: dict,
    target_config: dict,
    dry_run: bool = False,
) -> dict:
    """Copy S3 objects from source to target MinIO, preserving paths."""
    source_client = boto3.client(
        "s3",
        endpoint_url=source_config["endpoint_url"],
        aws_access_key_id=source_config["aws_access_key_id"],
        aws_secret_access_key=source_config["aws_secret_access_key"],
        region_name=source_config.get("region_name", "us-east-1"),
        verify=False,
    )
    target_client = boto3.client(
        "s3",
        endpoint_url=target_config["endpoint_url"],
        aws_access_key_id=target_config["aws_access_key_id"],
        aws_secret_access_key=target_config["aws_secret_access_key"],
        region_name=target_config.get("region_name", "us-east-1"),
        verify=False,
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
                    source_key = obj["Key"]
                    target_key = source_key  # Preserve path
                    if not dry_run:
                        try:
                            get_resp = source_client.get_object(
                                Bucket=source_bucket, Key=source_key
                            )
                            target_client.upload_fileobj(
                                get_resp["Body"],
                                target_bucket,
                                target_key,
                                ExtraArgs={
                                    "ContentType": get_resp.get(
                                        "ContentType", "application/octet-stream"
                                    )
                                },
                            )
                        except ClientError as e:
                            error_msg = f"Failed to copy {source_key}: {e}"
                            logger.error(error_msg)
                            errors.append(error_msg)
                            continue
                    total_files += 1
                    total_bytes += obj["Size"]
                    logger.debug(
                        "%s %s -> s3://%s/%s",
                        "DRY RUN:" if dry_run else "Copied:",
                        source_key,
                        target_bucket,
                        target_key,
                    )
        except ClientError as e:
            error_msg = f"Error listing {path_key}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

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


@migrate_endpoint_router.post("/export-project")
async def export_project(
    request: MigrateExportRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Export a project bundle from this instance.

    Scoped to one project: cascades through workflows → data_collections →
    files / deltatables / runs → dashboards.  Optionally copies S3 data to
    a target MinIO (modes all / files).
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can export projects")

    # Resolve project
    if request.project_id:
        project = projects_collection.find_one({"_id": ObjectId(request.project_id)})
    elif request.project_name:
        project = projects_collection.find_one({"name": request.project_name})
    else:
        raise HTTPException(status_code=400, detail="Provide project_id or project_name")

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_id = project["_id"]
    mode = request.mode

    # Cascade queries ---------------------------------------------------
    # Workflows are embedded in the project document (may be ID-only refs after processing).
    # Fetch full workflow documents from workflows_collection for authoritative DC IDs.
    embedded_workflows: list[dict] = project.get("workflows", [])
    workflow_ids: list[ObjectId] = [
        w["_id"] for w in embedded_workflows if isinstance(w.get("_id"), ObjectId)
    ]

    # Prefer workflows_collection (authoritative) over embedded refs (may be ID-only)
    if workflow_ids:
        full_workflows = list(workflows_collection.find({"_id": {"$in": workflow_ids}}))
    else:
        full_workflows = []

    dc_ids: list[ObjectId] = [
        dc["_id"]
        for wf in full_workflows
        for dc in wf.get("data_collections", [])
        if isinstance(dc.get("_id"), ObjectId)
    ]
    # Fallback: extract from embedded workflows if workflows_collection returned nothing
    if not dc_ids:
        dc_ids = [
            dc["_id"]
            for wf in embedded_workflows
            for dc in wf.get("data_collections", [])
            if isinstance(dc.get("_id"), ObjectId)
        ]
    logger.info(
        "migrate export: project=%s workflow_ids=%d dc_ids=%d",
        str(project_id),
        len(workflow_ids),
        len(dc_ids),
    )

    files_docs: list[dict] = []
    deltatables_docs: list[dict] = []
    runs_docs: list[dict] = []
    dashboards_docs: list[dict] = []

    if mode in ("all", "metadata"):
        if dc_ids:
            files_docs = list(files_collection.find({"data_collection_id": {"$in": dc_ids}}))
            deltatables_docs = list(
                deltatables_collection.find({"data_collection_id": {"$in": dc_ids}})
            )
        if workflow_ids:
            runs_docs = list(runs_collection.find({"workflow_id": {"$in": workflow_ids}}))

    if mode in ("all", "metadata", "dashboard"):
        # project_id may be stored as ObjectId or string depending on how the dashboard was created
        dashboards_docs = list(
            dashboards_collection.find(
                {"$or": [{"project_id": project_id}, {"project_id": str(project_id)}]}
            )
        )

    # Build data dict based on mode
    data: dict[str, list[dict]] = {}
    if mode in ("all", "metadata"):
        # The project document already embeds workflows and data_collections — no separate entries needed.
        data["projects"] = [project]
        data["files"] = files_docs
        data["deltatables"] = deltatables_docs
        data["runs"] = runs_docs
        data["dashboards"] = dashboards_docs
    elif mode == "dashboard":
        data["dashboards"] = dashboards_docs
    # files mode: only S3, no MongoDB docs

    # Serialize all ObjectIds / DBRefs
    data = cast(dict[str, list[dict]], _convert_complex_objects_to_strings(data))

    # Document counts (include embedded workflows/DCs for informational purposes)
    doc_counts = {k: len(v) for k, v in data.items()}
    if mode in ("all", "metadata"):
        doc_counts["workflows_embedded"] = len(embedded_workflows)
        doc_counts["data_collections_embedded"] = len(dc_ids)

    # S3 handling -------------------------------------------------------
    s3_metadata: dict[str, Any] = {}
    s3_paths: list[str] = []
    if mode in ("all", "files"):
        s3_paths = _collect_s3_locations_for_project(dc_ids, settings.minio.bucket)
        logger.info("Migrate: found %d S3 locations for project", len(s3_paths))

        if request.target_s3_config:
            # CLI path: copy between two S3 instances
            source_config = {
                "bucket": settings.minio.bucket,
                "endpoint_url": settings.minio.endpoint_url,
                "aws_access_key_id": settings.minio.aws_access_key_id,
                "aws_secret_access_key": settings.minio.aws_secret_access_key,
                "region_name": "us-east-1",
            }
            logger.info("Migrate: copying %d S3 locations to target", len(s3_paths))
            s3_metadata = _copy_s3_locations(
                s3_paths,
                source_config,
                request.target_s3_config,
                dry_run=request.dry_run,
            )
            s3_metadata["paths"] = s3_paths
        else:
            # UI path: S3 objects will be bundled directly into the ZIP below
            s3_metadata = {"paths": s3_paths, "bundled_in_zip": True, "dry_run": request.dry_run}

    bundle: dict[str, Any] = {
        "migrate_metadata": {
            "timestamp": datetime.now().isoformat(),
            "project_id": str(project_id),
            "project_name": project.get("name"),
            "mode": mode,
            "depictio_version": settings.version if hasattr(settings, "version") else "unknown",
            "document_counts": doc_counts,
            "dry_run": request.dry_run,
        },
        "data": data,
    }
    if s3_metadata:
        bundle["s3_migrate_metadata"] = s3_metadata

    def _json_default(obj: Any) -> Any:
        """Fallback serializer for types _convert_complex_objects_to_strings doesn't cover."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "migrate_metadata.json",
            json.dumps(bundle["migrate_metadata"], indent=2, default=_json_default),
        )
        zf.writestr(
            "bundle.json",
            json.dumps(bundle["data"], indent=2, default=_json_default),
        )

        # UI path: bundle S3 objects directly into the ZIP under s3_data/
        if (
            mode in ("all", "files")
            and not request.target_s3_config
            and s3_paths
            and not request.dry_run
        ):
            s3_client = boto3.client(
                "s3",
                endpoint_url=settings.minio.endpoint_url,
                aws_access_key_id=settings.minio.aws_access_key_id,
                aws_secret_access_key=settings.minio.aws_secret_access_key,
                region_name="us-east-1",
                verify=False,
            )
            bundled_files = 0
            for path in s3_paths:
                path_key = path.strip("/")
                try:
                    paginator = s3_client.get_paginator("list_objects_v2")
                    for page in paginator.paginate(Bucket=settings.minio.bucket, Prefix=path_key):
                        for obj in page.get("Contents", []):
                            key = obj["Key"]
                            try:
                                resp = s3_client.get_object(Bucket=settings.minio.bucket, Key=key)
                                zf.writestr(f"s3_data/{key}", resp["Body"].read())
                                bundled_files += 1
                                logger.debug("Bundled S3 object into ZIP: %s", key)
                            except ClientError as e:
                                logger.error("Failed to bundle S3 object %s: %s", key, e)
                except ClientError as e:
                    logger.error("Error listing S3 path %s: %s", path_key, e)
            logger.info("Migrate: bundled %d S3 files into ZIP", bundled_files)
            bundle["s3_migrate_metadata"]["bundled_files"] = bundled_files

        # Write s3_metadata.json last so bundled_files count is included
        if "s3_migrate_metadata" in bundle:
            zf.writestr(
                "s3_metadata.json",
                json.dumps(bundle["s3_migrate_metadata"], indent=2, default=_json_default),
            )
    buf.seek(0)

    project_name = (project.get("name") or "export").replace(" ", "_")
    filename = f"depictio_export_{project_name}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Import endpoint
# ---------------------------------------------------------------------------


@migrate_endpoint_router.post("/import-project", response_model=MigrateImportResponse)
async def import_project(
    request: MigrateImportRequest,
    current_user: User = Depends(get_current_user),
) -> MigrateImportResponse:
    """
    Import a project bundle into this instance (non-destructive upsert).

    Documents are upserted in dependency order.  Owner IDs that do not exist
    on this instance are remapped to the calling admin (or the specified
    owner_user_id).
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can import projects")

    bundle = request.bundle
    if "data" not in bundle:
        raise HTTPException(status_code=400, detail="Bundle missing 'data' section")

    # Conflict check — refuse to overwrite an existing project unless overwrite=True
    project_docs = bundle.get("data", {}).get("projects", [])
    if project_docs:
        raw_pid = project_docs[0].get("_id") or project_docs[0].get("id")
        try:
            existing = projects_collection.find_one({"_id": ObjectId(str(raw_pid))})
        except Exception:
            existing = None
        if existing and not request.overwrite:
            project_name = existing.get("name", str(raw_pid))
            return MigrateImportResponse(
                success=False,
                message=f"Project '{project_name}' already exists on this instance. "
                "Set overwrite=true to replace it.",
                conflict=True,
            )

    # Determine fallback owner ID
    admin_id = current_user.id
    if request.owner_user_id:
        try:
            admin_id = ObjectId(request.owner_user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid owner_user_id")

    # Collect existing user IDs on this instance (for owner remapping)
    existing_user_ids = {str(u["_id"]) for u in users_collection.find({}, {"_id": 1})}

    # workflows and data_collections are embedded in the project document,
    # so they are not stored in separate collections and don't appear in the bundle.
    collection_map: dict[str, Collection[dict[str, Any]]] = {
        "projects": projects_collection,
        "files": files_collection,
        "deltatables": deltatables_collection,
        "runs": runs_collection,
        "dashboards": dashboards_collection,
    }

    # Import order respects dependencies (project first, then its dependents)
    import_order = [
        "projects",
        "files",
        "deltatables",
        "runs",
        "dashboards",
    ]

    data_section = bundle["data"]
    upserted: dict[str, int] = {}
    total_upserted = 0

    for collection_name in import_order:
        if collection_name not in data_section:
            continue

        raw_docs: list[dict] = data_section[collection_name]
        if not raw_docs:
            upserted[collection_name] = 0
            continue

        collection = collection_map[collection_name]
        ops: list[ReplaceOne] = []

        for doc in raw_docs:
            doc = _prepare_doc_for_import(
                doc, existing_user_ids, admin_id, force_remap=request.force_owner_remap
            )
            ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))

        count = len(ops)
        if not request.dry_run and ops:
            try:
                collection.bulk_write(ops, ordered=False)
            except Exception as e:
                logger.error("migrate import error for %s: %s", collection_name, e)
                raise HTTPException(
                    status_code=500,
                    detail=f"Import failed for {collection_name}: {e}",
                )

        upserted[collection_name] = count
        total_upserted += count
        logger.info(
            "migrate import: %s %d docs into %s",
            "DRY RUN would upsert" if request.dry_run else "upserted",
            count,
            collection_name,
        )

    return MigrateImportResponse(
        success=True,
        message=f"{'DRY RUN: would upsert' if request.dry_run else 'Upserted'} {total_upserted} documents",
        upserted=upserted,
        dry_run=request.dry_run,
    )


@migrate_endpoint_router.post("/import-project-zip", response_model=MigrateImportResponse)
async def import_project_zip(
    file: UploadFile = File(...),
    dry_run: bool = False,
    overwrite: bool = False,
    current_user: User = Depends(get_current_user),
) -> MigrateImportResponse:
    """
    Import a project bundle from a ZIP file (for UI use).

    Accepts a .zip file containing bundle.json and migrate_metadata.json.
    Always remaps all owners to the calling user (force_owner_remap=True).
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can import projects")

    contents = await file.read()
    buf = io.BytesIO(contents)
    try:
        with zipfile.ZipFile(buf) as zf:
            bundle_data = json.loads(zf.read("bundle.json"))
            migrate_metadata = json.loads(zf.read("migrate_metadata.json"))

            # Restore S3 data files bundled in the ZIP back to MinIO at original paths
            s3_keys = [n for n in zf.namelist() if n.startswith("s3_data/")]
            if s3_keys and not dry_run:
                s3_client = boto3.client(
                    "s3",
                    endpoint_url=settings.minio.endpoint_url,
                    aws_access_key_id=settings.minio.aws_access_key_id,
                    aws_secret_access_key=settings.minio.aws_secret_access_key,
                    region_name="us-east-1",
                    verify=False,
                )
                uploaded = 0
                for zip_path in s3_keys:
                    s3_key = zip_path[len("s3_data/") :]  # strip prefix to get original path
                    if not s3_key:
                        continue
                    try:
                        s3_client.put_object(
                            Bucket=settings.minio.bucket,
                            Key=s3_key,
                            Body=zf.read(zip_path),
                        )
                        uploaded += 1
                        logger.debug("Restored S3 object: %s", s3_key)
                    except ClientError as e:
                        logger.error("Failed to restore S3 object %s: %s", s3_key, e)
                logger.info("Migrate import: restored %d S3 objects to MinIO", uploaded)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ZIP bundle: {e}")

    bundle = {"data": bundle_data, "migrate_metadata": migrate_metadata}
    import_request = MigrateImportRequest(
        bundle=bundle,
        dry_run=dry_run,
        force_owner_remap=True,
        overwrite=overwrite,
    )
    return await import_project(import_request, current_user)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _prepare_doc_for_import(
    doc: dict,
    existing_user_ids: set[str],
    fallback_owner_id: Any,
    force_remap: bool = False,
) -> dict:
    """Convert string IDs back to ObjectId and remap unknown owners."""
    doc = dict(doc)
    # Convert _id
    if "id" in doc and "_id" not in doc:
        doc["_id"] = doc.pop("id")
    if "_id" in doc and isinstance(doc["_id"], str):
        try:
            doc["_id"] = ObjectId(doc["_id"])
        except Exception:
            pass

    # Remap owner IDs in permissions
    permissions = doc.get("permissions")
    if isinstance(permissions, dict):
        owners = permissions.get("owners")
        if isinstance(owners, list):
            new_owners = []
            for owner in owners:
                if isinstance(owner, dict):
                    owner_id = str(owner.get("_id", ""))
                    if force_remap or owner_id not in existing_user_ids:
                        owner = dict(owner)
                        owner["_id"] = str(fallback_owner_id)
                    new_owners.append(owner)
                else:
                    new_owners.append(owner)
            permissions = dict(permissions)
            permissions["owners"] = new_owners
            doc["permissions"] = permissions

    # Recursively convert any remaining string ObjectIds for known ID fields
    _convert_id_fields(doc)

    return doc


_ID_FIELD_NAMES = {
    "_id",
    "project_id",
    "workflow_id",
    "data_collection_id",
    "run_id",
    "dashboard_id",
}


def _convert_id_fields(obj: Any) -> None:
    """Convert known ID fields from string to ObjectId in-place."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in _ID_FIELD_NAMES and isinstance(val, str):
                try:
                    obj[key] = ObjectId(val)
                except Exception:
                    pass
            else:
                _convert_id_fields(val)
    elif isinstance(obj, list):
        for item in obj:
            _convert_id_fields(item)
