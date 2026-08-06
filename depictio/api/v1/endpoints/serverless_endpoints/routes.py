"""HTTP surface for the serverless static-bundle exporter (producer A).

Four thin endpoints around ``depictio.serverless.producer_a.export_static``:

* ``GET  /export-static/{dashboard_id}/preflight`` — the ``--check`` tier table,
  per component and per tab of the dashboard's family, plus the bundle's
  estimated size against the two ceilings (viewer permission, writes nothing).
  It *does* read data: deciding a figure's tier means running the
  bind-and-refill builder over the frame the bundle would carry, so this is a
  seconds-long call, not an instant one — and it is bounded by the same hard
  size ceiling the build is, which it reports as a 413 rather than a 404.
* ``POST /export-static/{dashboard_id}`` — owner-gated; enqueues the build as a
  Celery task and returns a ``job_id``. The bundle carries the whole tab family,
  entered on the requested tab.
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
from depictio.serverless.preflight import rows_for_tab, tier_counts
from depictio.serverless.producer_a import (
    BYTES_PER_MB,
    BundleSize,
    BundleTooLargeError,
    ProducerAError,
    export_static,
)

serverless_endpoint_router = APIRouter()

_PRESIGN_EXPIRY_SECONDS = 24 * 3600
_TIER_COUNT_KEYS = ("live", "partial", "frozen", "omitted")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enum_value(value: Any) -> Any:
    """Enum → its ``.value``; anything else (incl. ``None``) unchanged."""
    return getattr(value, "value", value)


def _size_estimate_payload(size: BundleSize | None) -> dict[str, Any] | None:
    """The preflight's size block, or ``None`` when nothing was sized.

    Every number is bytes so the caller never has to guess a unit; the two
    ceilings are echoed in MB because that is how they are configured, and a
    ceiling of 0 means that check is disabled. ``verdict`` is the thresholds
    already applied, so a modal does not re-derive them and cannot disagree with
    the producer that will run the build.

    ``estimated_data_bytes`` really is an estimate: the preflight prunes every
    frame but never serialises one, so its data figure is ``rows × columns × 2
    bytes × 4/3`` (RFC §8.1) rather than a measurement. ``runtime_bytes`` — the
    static runtime every bundle carries whatever its data — is exact, and on a
    small dashboard it is most of the total.

    ``verdict`` is therefore an advance warning, not a decision: it applies the
    same thresholds the build applies, to a number of a different kind. The
    density runs ~2x high on compressible frames, and neither figure counts the
    frozen payloads. A preflight whose *running* total crosses the hard ceiling
    does not return a verdict at all — it is refused outright (413), the same
    way the build is.
    """
    if size is None:
        return None
    return {
        "estimated_total_bytes": size.total_bytes,
        "estimated_data_bytes": size.data_bytes,
        "runtime_bytes": size.runtime_bytes,
        "soft_limit_mb": size.soft_limit_bytes // BYTES_PER_MB,
        "hard_limit_mb": size.hard_limit_bytes // BYTES_PER_MB,
        "verdict": size.verdict,
    }


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
    """Per-component (and per-tab, per-link) tier table for a would-be static export.

    Covers the whole tab family the dashboard belongs to, because that is what a
    bundle carries: every tier row names its ``tab_id`` and ``tabs`` repeats the
    per-tab counts. The top-level ``counts`` stay family-wide.

    The FIGURE tiers are the real ones, not a plan: ``export_static``'s default
    preflight runs the export's own body — it loads and prunes the data
    collections and puts every figure through the bind-and-refill builder — and
    stops before it builds anything, so no figure row comes back
    ``provisional``. That costs data reads and a server-side figure build per
    unbound figure. A full export of the reference dashboards takes 5-15 s wall
    clock, most of it in the Celery computes this skips entirely (no compute, no
    frozen payload, no Parquet, no HTML), so expect a few seconds rather than a
    few milliseconds.

    Everything that is not a figure keeps its planned tier, and the build can
    still move one: a frozen payload that fails to compute drops to ``omitted``,
    and so does a Celery compute the build's wall-clock budget cannot cover —
    that one by policy, not by failure, so a dashboard with many computes can
    report ``frozen`` here and ship ``omitted``.

    ``size_estimate`` predicts how big the bundle would be and which side of the
    two ceilings it lands on (``ok`` / ``over_soft_limit`` / ``would_be_refused``
    — see :func:`_size_estimate_payload`), so the size can be shown before the
    build is paid for. It is an advance warning rather than the build's own
    decision: same ceilings, but applied to an estimate that runs high on
    compressible data. Crossing the hard ceiling *while loading* is a 413 here
    exactly as it is a refusal there — the ceiling bounds this path's memory
    too.

    Needs *viewer* on the dashboard's project — every row it reads is a row the
    normal render endpoints would already serve that viewer — and writes nothing.
    ``export_static`` is synchronous and blocks on Mongo, S3 and plotly, so it
    runs in a worker thread rather than on the event loop.
    """
    try:
        result = await anyio.to_thread.run_sync(
            functools.partial(export_static, dashboard_id, check=True, user=current_user)
        )
    except BundleTooLargeError as exc:
        # Not a 404: the dashboard exists and this caller may read it. Answering
        # "not found" for a dashboard whose data is simply too big to bundle
        # sends the reader looking for the wrong problem, and the message here
        # names the ceiling and the data collections that crossed it.
        logger.info(f"Static export preflight over the size ceiling for {dashboard_id}: {exc}")
        raise HTTPException(status_code=413, detail=str(exc))
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
                "tab_id": row.tab_id,
                "provisional": row.provisional,
            }
        )

    tabs = [
        {
            "id": tab.id,
            "title": tab.title,
            "tab_order": tab.tab_order,
            "is_main_tab": tab.is_main_tab,
            "counts": {
                key: value
                for key, value in tier_counts(rows_for_tab(result.tier_rows, tab.id)).items()
                if key in _TIER_COUNT_KEYS
            },
        }
        for tab in result.tabs
    ]

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

    return {
        "dashboard_id": dashboard_id,
        "tiers": tiers,
        "tabs": tabs,
        "links": links,
        "counts": counts,
        "size_estimate": _size_estimate_payload(result.size),
    }


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
