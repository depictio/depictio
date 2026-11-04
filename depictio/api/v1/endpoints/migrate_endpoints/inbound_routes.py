"""Target side: requests pushed by a paired source instance (X-Depictio-Pairing-Key). (#1303).

The source authenticates with its pairing key and uploads a bundle; nothing is
imported here. A valid bundle is parked in S3 and recorded as a ``pending``
request for an administrator to approve (``requests_routes``).
"""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.configs.settings_models import MigrationInboundSource
from depictio.api.v1.endpoints.migrate_endpoints.inbound_auth import (
    require_inbound_source,
    source_max_bundle_bytes,
)
from depictio.api.v1.endpoints.migrate_endpoints.routes import (
    _instance_s3_client,
    _normalize_endpoint,
)
from depictio.api.v1.endpoints.projects_endpoints.provenance import instance_label
from depictio.api.v1.services import migration_import, project_bundle
from depictio.models.models.migration import (
    BUNDLE_FORMAT_VERSION,
    MigrationRequest,
    MigrationRequester,
)
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now, utc_now_str
from depictio.version import get_version

inbound_router = APIRouter()

_CHUNK = 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TRANSFER_MODES = ("inline", "server_side_copy")


def _db():
    return migration_import._db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def server_side_copy_possible(
    source: MigrationInboundSource, source_s3_endpoint: str | None, source_bucket: str | None
) -> bool:
    """Whether the data can be copied inside one S3 endpoint instead of travelling.

    Both instances must talk to the same endpoint, the source's bucket must be
    one this source is allowed to read from, and it must not be this
    instance's own bucket (that would copy a bucket onto itself).
    """
    if not source_s3_endpoint or not source_bucket:
        return False
    mine = _normalize_endpoint(settings.s3.endpoint_url or "")
    theirs = _normalize_endpoint(source_s3_endpoint)
    return bool(
        mine
        and theirs == mine
        and source_bucket in source.allowed_source_buckets
        and source_bucket != settings.s3.bucket
    )


def _since(hours: int) -> str:
    return (utc_now() - timedelta(hours=hours)).strftime(TIMESTAMP_FORMAT)


def _created_last_day(source: MigrationInboundSource) -> int:
    return _db().migration_requests_collection.count_documents(
        {"source_name": source.name, "created_at": {"$gte": _since(24)}}
    )


def _pending_count(source: MigrationInboundSource, *, except_project: str | None = None) -> int:
    query: dict[str, Any] = {"source_name": source.name, "status": "pending"}
    if except_project:
        query["project_id"] = {"$ne": except_project}
    return _db().migration_requests_collection.count_documents(query)


def _clip(value: str | None, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] or None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@inbound_router.get("/info")
async def inbound_info(source: MigrationInboundSource = Depends(require_inbound_source)):
    """What a source needs to know about this instance before it builds a bundle."""
    return {
        "instance_label": instance_label(),
        "depictio_version": get_version(),
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "s3_endpoint": _normalize_endpoint(settings.s3.endpoint_url or ""),
        "s3_bucket": settings.s3.bucket,
        "max_bundle_bytes": source_max_bundle_bytes(source),
        "server_side_copy_buckets": list(source.allowed_source_buckets),
        "lock_imported_default": settings.migration.lock_imported_default,
    }


class PreflightBody(BaseModel):
    project_id: str
    project_name: str | None = None
    requester_email: str | None = None
    source_depictio_version: str | None = None
    bundle_format_version: int | None = None
    total_bytes: int = 0
    source_s3_endpoint: str | None = None
    source_bucket: str | None = None


@inbound_router.post("/preflight")
async def inbound_preflight(
    body: PreflightBody, source: MigrationInboundSource = Depends(require_inbound_source)
):
    """Would a push of this project be accepted? Nothing is stored."""
    errors: list[str] = []
    warnings: list[str] = []
    max_bytes = source_max_bundle_bytes(source)
    if body.total_bytes > max_bytes:
        errors.append(f"the bundle ({body.total_bytes} bytes) is over the {max_bytes} byte limit")
    if (body.bundle_format_version or 1) > BUNDLE_FORMAT_VERSION:
        errors.append(
            f"bundle format {body.bundle_format_version} is newer than this instance supports "
            f"({BUNDLE_FORMAT_VERSION}); upgrade Depictio here first"
        )

    conflict = "none"
    existing_name: str | None = None
    existing_locked = False
    try:
        pid = ObjectId(body.project_id)
    except Exception:  # noqa: BLE001
        pid = None
        errors.append("project_id is not a valid id")
    if pid is not None:
        existing = _db().projects_collection.find_one({"_id": pid})
        if existing:
            existing_name = existing.get("name")
            existing_locked = bool(existing.get("published_lock"))
            # Same lineage rule as validate_bundle: the last import came from this source.
            same = project_bundle._last_hop_source(existing) == source.name
            conflict = "re_push" if same else "foreign"
            if not same:
                errors.append(
                    "a project with this id already exists here and was not imported from "
                    f"{source.name!r}"
                )
        if body.project_name:
            clash = _db().projects_collection.find_one(
                {"name": body.project_name, "_id": {"$ne": pid}}, {"_id": 1}
            )
            if clash:
                errors.append(f"another project here is already named {body.project_name!r}")

    pending = _pending_count(source)
    remaining = max(0, source.max_per_day - _created_last_day(source))
    if remaining == 0:
        errors.append("daily push quota reached for this source")
    if pending >= source.max_pending and conflict != "re_push":
        errors.append("too many requests are waiting for approval; wait for a decision")

    mode = (
        "server_side_copy"
        if server_side_copy_possible(source, body.source_s3_endpoint, body.source_bucket)
        else "inline"
    )
    has_account = migration_import.find_user_by_email(body.requester_email) is not None
    if body.requester_email and not has_account:
        warnings.append(
            "the requester has no account here; an admin owns the project until they sign in"
        )
    return {
        "ok": not errors,
        "conflict": conflict,
        "existing_project_name": existing_name,
        "existing_locked": existing_locked,
        "requester_has_account": has_account,
        "pending_requests": pending,
        "remaining_today": remaining,
        "max_bundle_bytes": max_bytes,
        "transfer_mode": mode,
        "errors": errors,
        "warnings": warnings,
    }


class ProbeBody(BaseModel):
    bucket: str
    key: str


@inbound_router.post("/probe")
async def inbound_probe(
    body: ProbeBody, source: MigrationInboundSource = Depends(require_inbound_source)
):
    """Can THIS instance's credentials read ``bucket/key``? (decides server-side copy)

    Limited to the buckets the source is allowed to copy from, so the probe
    cannot be used to explore the rest of the object store.
    """
    if body.bucket not in source.allowed_source_buckets or body.bucket == settings.s3.bucket:
        raise HTTPException(status_code=400, detail="bucket is not allowed for this source")
    if not project_bundle.is_safe_s3_key(body.key):
        raise HTTPException(status_code=400, detail="invalid key")
    client = _instance_s3_client()
    try:
        await run_in_threadpool(client.head_object, Bucket=body.bucket, Key=body.key)
    except Exception as exc:  # noqa: BLE001 — any failure just means "not readable"
        return {"readable": False, "error": str(exc)[:300]}
    return {"readable": True, "error": None}


@inbound_router.post("/requests", status_code=202)
async def inbound_create_request(
    file: UploadFile = File(...),
    sha256: str = Form(...),
    transfer_mode: str = Form(...),
    requester_email: str | None = Form(default=None),
    requester_name: str | None = Form(default=None),
    source_user_id: str | None = Form(default=None),
    message: str | None = Form(default=None),
    source: MigrationInboundSource = Depends(require_inbound_source),
):
    """Receive a bundle, validate it and park it for an admin's decision."""
    if transfer_mode not in _TRANSFER_MODES:
        raise HTTPException(
            status_code=400, detail="transfer_mode must be inline or server_side_copy"
        )
    sha256 = sha256.strip().lower()
    if not _SHA256.match(sha256):
        raise HTTPException(status_code=400, detail="sha256 must be 64 hex characters")
    if _created_last_day(source) >= source.max_per_day:
        raise HTTPException(status_code=429, detail="daily push quota reached for this source")

    max_bytes = source_max_bundle_bytes(source)
    with project_bundle.spool_file(settings.migration.spool_dir) as spool:
        digest = hashlib.sha256()
        size = 0
        while chunk := await file.read(_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=413, detail=f"bundle is over the {max_bytes} byte limit"
                )
            digest.update(chunk)
            spool.write(chunk)
        spool.flush()
        if digest.hexdigest() != sha256:
            raise HTTPException(status_code=400, detail="sha256 does not match the uploaded bundle")
        spool.seek(0)

        try:
            opened = project_bundle.open_bundle_zip(spool)
        except project_bundle.BundleError as exc:
            return _refused([f"invalid bundle: {exc}"])
        try:
            report = migration_import.validate_opened_bundle(
                opened, source_name=source.name, transfer_mode=transfer_mode
            )
            dc_ids = migration_import.bundle_dc_ids(opened)
            metadata = opened.metadata
        finally:
            opened.close()
        if report.errors:
            return _refused(report.errors[:50])
        if report.s3_bytes > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"bundle data is over the {max_bytes} byte limit"
            )
        if _pending_count(source, except_project=report.project_id) >= source.max_pending:
            raise HTTPException(
                status_code=429, detail="too many requests are waiting for approval"
            )

        request_id = ObjectId()
        bucket = settings.s3.bucket
        key = migration_import.staging_object_key(str(request_id))
        spool.seek(0)
        try:
            await run_in_threadpool(_instance_s3_client().upload_fileobj, spool, bucket, key)
        except Exception as exc:  # noqa: BLE001
            logger.error("inbound request: staging upload failed: %s", exc)
            raise HTTPException(status_code=502, detail="could not stage the bundle")

    request = MigrationRequest(
        source_name=source.name,
        source_instance=source.name,
        source_depictio_version=report.source_depictio_version,
        bundle_format_version=report.bundle_format_version,
        requester=MigrationRequester(
            email=_clip(requester_email, 320),
            name=_clip(requester_name, 200),
            source_user_id=_clip(source_user_id, 100),
        ),
        message=_clip(message, 2000),
        project_id=report.project_id,
        project_name=report.project_name,
        transfer_mode=transfer_mode,  # type: ignore[arg-type]
        staging_key=migration_import.staging_uri(bucket, key),
        bundle_sha256=sha256,
        bundle_bytes=size,
        report=report.model_dump(),
    )
    doc = request.model_dump(exclude={"id"})
    doc["_id"] = request_id
    # Kept beside the model so the orphan sweep can spare the data an import is writing.
    doc["dc_ids"] = dc_ids
    doc["source_exported_at"] = metadata.get("exported_at")
    col = _db().migration_requests_collection
    col.insert_one(doc)
    _supersede_older(source, report.project_id, request_id)
    logger.info(
        "inbound request %s from %s: project %s", request_id, source.name, report.project_id
    )
    return {"request_id": str(request_id), "status": "pending"}


def _refused(errors: list[str]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Bundle refused", "errors": errors})


def _supersede_older(
    source: MigrationInboundSource, project_id: str | None, new_id: ObjectId
) -> None:
    """A newer push of the same project replaces the older pending one."""
    if not project_id:
        return
    col = _db().migration_requests_collection
    for old in list(
        col.find(
            {
                "source_name": source.name,
                "project_id": project_id,
                "status": "pending",
                "_id": {"$ne": new_id},
            }
        )
    ):
        claimed = col.find_one_and_update(
            {"_id": old["_id"], "status": "pending"},
            {
                "$set": {
                    "status": "superseded",
                    "superseded_by": str(new_id),
                    "updated_at": utc_now_str(),
                }
            },
        )
        if claimed is not None:
            migration_import.delete_staged_bundle(claimed)


@inbound_router.get("/requests/{request_id}")
async def inbound_request_status(
    request_id: str, source: MigrationInboundSource = Depends(require_inbound_source)
):
    """The state of a request, readable only by the source that made it."""
    try:
        oid = ObjectId(request_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Not Found")
    doc = _db().migration_requests_collection.find_one({"_id": oid})
    if not doc or doc.get("source_name") != source.name:
        raise HTTPException(status_code=404, detail="Not Found")
    decision = doc.get("decision") or None
    result = doc.get("result") or None
    return {
        "request_id": str(doc["_id"]),
        "status": doc.get("status"),
        "project_id": doc.get("project_id"),
        "project_name": doc.get("project_name"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "decision": (
            {
                "action": decision.get("action"),
                "at": decision.get("at"),
                "reason": decision.get("reason"),
            }
            if decision
            else None
        ),
        "result": (
            {
                "project_id": result.get("project_id"),
                "locked": bool(result.get("locked")),
                "made_public": bool(result.get("made_public")),
            }
            if result and result.get("project_id")
            else None
        ),
    }
