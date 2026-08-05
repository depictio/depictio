"""HTTP surface for the serverless static-bundle exporter (producer A).

Four thin endpoints around ``depictio.serverless.producer_a.export_static``:

* ``GET  /export-static/{dashboard_id}/preflight`` — the ``--check`` tier table
  (viewer permission, reads no data, writes nothing).
* ``POST /export-static/{dashboard_id}`` — owner-gated; enqueues the build as a
  Celery task and returns a ``job_id``.
* ``GET  /export-static/status/{job_id}`` — poll; settles pending jobs against
  their Celery result.
* ``GET  /export-static/download/{job_id}`` — proxies the finished bundle out of
  S3 so the browser never needs to reach MinIO directly.

Job docs live in the ``static_exports`` collection (plain dicts + pymongo, no
Beanie) and are readable only by their owner or an admin — a leaked job_id must
not expose someone else's dashboard.
"""

from __future__ import annotations

import functools
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import anyio.to_thread
import boto3
from bson import ObjectId
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from depictio.api.celery_app import celery_app
from depictio.api.v1.celery_tasks import export_static_bundle as export_static_bundle_task
from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, static_exports_collection
from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.api.v1.s3 import s3_client
from depictio.serverless.producer_a import ProducerAError, export_static

serverless_endpoint_router = APIRouter()

_PRESIGN_EXPIRY_SECONDS = 24 * 3600
_TIER_COUNT_KEYS = ("live", "partial", "frozen", "omitted")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enum_value(value: Any) -> Any:
    """Enum → its ``.value``; anything else (incl. ``None``) unchanged."""
    return getattr(value, "value", value)


def _external_s3_endpoint() -> str | None:
    """A browser-reachable S3 endpoint, or ``None`` when only the internal one exists.

    In server context ``settings.minio.endpoint_url`` resolves to the
    compose-internal ``http://minio:9000`` (``ServiceConfig.url``). A URL signed
    against that host is unreachable from a browser *and* looks like a working
    link, so we only presign when the deployment declares a public endpoint —
    ``public_url``, or a MinIO/S3 living outside the compose network.
    """
    minio = settings.minio
    if minio.public_url:
        return minio.public_url
    if minio.external_service:
        return minio.external_url
    return None


def _presigned_download_url(bucket: str | None, key: str | None) -> str | None:
    """Best-effort 24h presigned GET for the exported bundle, else ``None``.

    Callers fall back to the proxied ``/export-static/download/{job_id}`` route,
    which always works — the presigned URL is only an optimisation that lets the
    browser pull the artifact straight from object storage.
    """
    endpoint = _external_s3_endpoint()
    if not endpoint or not bucket or not key:
        return None
    try:
        client = boto3.client(
            "s3",
            aws_access_key_id=settings.minio.aws_access_key_id,
            aws_secret_access_key=settings.minio.aws_secret_access_key,
            endpoint_url=endpoint,
            verify=settings.minio.verify_tls,
        )
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=_PRESIGN_EXPIRY_SECONDS,
        )
    except Exception as exc:
        logger.warning(f"Could not presign static export {bucket}/{key}: {exc}")
        return None


def _error_text(async_result: Any) -> str:
    """Best-effort failure message for a task the poll found in FAILURE state.

    ``AsyncResult.result`` is the exception instance when the API process can
    reconstruct it, but a worker-side exception class it cannot import arrives as
    a bare string or ``None``; fall back to the traceback's last line, then to the
    Celery state, so the poll never surfaces an empty error.
    """
    raw = getattr(async_result, "result", None)
    text = str(raw) if raw is not None else ""
    if not text.strip():
        traceback = (getattr(async_result, "traceback", None) or "").strip()
        if traceback:
            text = traceback.splitlines()[-1]
        else:
            text = f"task {str(getattr(async_result, 'state', 'failed')).lower()}"
    return text[:500]


def _assert_job_owner(doc: dict, current_user) -> None:
    """Raise 404 unless ``current_user`` owns the export job (admins bypass)."""
    if getattr(current_user, "is_admin", False):
        return
    if doc.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Job not found")


def _load_job(job_id: str, current_user) -> dict:
    doc = static_exports_collection.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_owner(doc, current_user)
    return doc


def _resolve_job(doc: dict) -> dict:
    """Settle a pending job against its Celery result, persisting the verdict.

    Shared by the status and download routes so a job that finished between two
    polls is downloadable straight away.
    """
    if doc.get("status") in ("done", "failed"):
        return doc
    task_id = doc.get("celery_task_id")
    if not task_id:
        return doc

    async_result = AsyncResult(task_id, app=celery_app)
    if not async_result.ready():
        return doc

    completed_at = datetime.now(timezone.utc)
    if async_result.successful():
        update: dict[str, Any] = {
            "status": "done",
            "result": async_result.result,
            "completed_at": completed_at,
        }
    else:
        update = {
            "status": "failed",
            "error": _error_text(async_result),
            "completed_at": completed_at,
        }
    static_exports_collection.update_one({"_id": doc["_id"]}, {"$set": update})
    return {**doc, **update}


def _status_payload(doc: dict) -> dict[str, Any]:
    status = doc.get("status", "pending")
    if status not in ("done", "failed"):
        return {"job_id": doc["_id"], "status": "pending"}
    result = doc.get("result")
    if result:
        result = {
            **result,
            "download_url": _presigned_download_url(result.get("bucket"), result.get("s3_key")),
        }
    return {
        "job_id": doc["_id"],
        "status": status,
        "result": result,
        "error": doc.get("error"),
    }


def _compact_timestamp(built_at: Any) -> str:
    """``built_at`` (ISO) → ``YYYYMMDDTHHMMSSZ`` for the download filename."""
    try:
        parsed = datetime.fromisoformat(str(built_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@serverless_endpoint_router.get("/export-static/{dashboard_id}/preflight")
async def preflight_export_static(
    dashboard_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Per-component (and per-link) tier table for a would-be static export.

    Needs *viewer* on the dashboard's project; reads no Delta data and writes
    nothing. ``export_static`` is synchronous and hits Mongo, so it runs in a
    worker thread rather than on the event loop.
    """
    try:
        result = await anyio.to_thread.run_sync(
            functools.partial(export_static, dashboard_id, check=True, user=current_user)
        )
    except ProducerAError as exc:
        logger.info(f"Static export preflight refused for {dashboard_id}: {exc}")
        raise HTTPException(status_code=404, detail="Dashboard not found or access denied")

    counts = dict.fromkeys(_TIER_COUNT_KEYS, 0)
    tiers = []
    for row in result.tier_rows:
        tier = _enum_value(row.tier)
        if tier in counts:
            counts[tier] += 1
        tiers.append(
            {
                "component_id": row.component_id,
                "title": row.title,
                "component_type": row.component_type,
                "tier": tier,
                "reason": _enum_value(row.reason),
                "detail": row.detail,
            }
        )

    links = [
        {
            "link_id": row.link_id,
            "source": row.source,
            "target": row.target,
            "resolver": row.resolver,
            "tier": _enum_value(row.tier),
            "enabled": row.enabled,
            "entries": row.entries,
            "note": row.note,
        }
        for row in result.link_rows
    ]

    return {"dashboard_id": dashboard_id, "tiers": tiers, "links": links, "counts": counts}


@serverless_endpoint_router.post("/export-static/{dashboard_id}")
def dispatch_export_static(
    dashboard_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Enqueue a static-bundle build; poll ``/export-static/status/{job_id}``.

    Owner-gated (RFC §8 — a bundle is bulk data exfiltration). Denials return 404
    rather than 403 so the endpoint cannot be used to enumerate dashboards.
    """
    try:
        oid = ObjectId(str(dashboard_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Dashboard not found or access denied")

    dashboard = dashboards_collection.find_one({"dashboard_id": oid})
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found or access denied")

    project_id = dashboard.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "owner"):
        raise HTTPException(status_code=404, detail="Dashboard not found or access denied")

    job_id = uuid4().hex
    static_exports_collection.insert_one(
        {
            "_id": job_id,
            "dashboard_id": str(dashboard_id),
            "user_id": str(current_user.id),
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "celery_task_id": None,
        }
    )

    payload = {
        "job_id": job_id,
        "dashboard_id": str(dashboard_id),
        "user": {
            "id": str(current_user.id),
            "email": getattr(current_user, "email", "") or "",
            "is_admin": bool(getattr(current_user, "is_admin", False)),
            "is_anonymous": bool(getattr(current_user, "is_anonymous", False)),
        },
    }
    async_result = export_static_bundle_task.apply_async(args=[payload])
    static_exports_collection.update_one(
        {"_id": job_id}, {"$set": {"celery_task_id": async_result.id}}
    )
    logger.info(
        f"Static export dispatched: job_id={job_id} dashboard={dashboard_id} "
        f"task_id={async_result.id}"
    )
    return {"job_id": job_id, "status": "pending"}


@serverless_endpoint_router.get("/export-static/status/{job_id}")
def poll_export_static(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Status of one export job — ``pending``, ``done`` (with result) or ``failed``."""
    return _status_payload(_resolve_job(_load_job(job_id, current_user)))


@serverless_endpoint_router.get("/export-static/download/{job_id}")
def download_export_static(
    job_id: str,
    current_user=Depends(get_user_or_anonymous),
):
    """Stream the finished bundle through the API.

    The proxy (rather than a redirect) is what makes downloads work on the common
    deployment where MinIO is only reachable inside the compose network.
    """
    doc = _resolve_job(_load_job(job_id, current_user))
    result = doc.get("result") or {}
    if doc.get("status") != "done" or not result.get("s3_key"):
        raise HTTPException(status_code=409, detail="Export not ready")

    bucket = result.get("bucket") or settings.minio.bucket
    key = result["s3_key"]
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        logger.error(f"Static export artifact unreadable ({bucket}/{key}): {exc}")
        raise HTTPException(status_code=404, detail="Export artifact not found")

    def iterfile():
        for chunk in response["Body"].iter_chunks(chunk_size=8192):
            yield chunk

    filename = (
        f"depictio-dashboard-{doc.get('dashboard_id')}-"
        f"{_compact_timestamp(result.get('built_at'))}.html"
    )
    return StreamingResponse(
        iterfile(),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
