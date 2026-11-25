"""The visitor's side of the public offline bundle (#1480).

Two GET routes that read what a worker already built (``depictio.serverless.
public_bundle``) and never queue, compute or build anything:

* ``GET /public-bundle/{dashboard_id}``: whether a bundle can be downloaded,
  its size and build date, and whether a newer one is being built. A project
  owner also learns whether it is ``fresh`` (built from the content as it is).
* ``GET /public-bundle/{dashboard_id}/download``: the file, as a redirect to a
  short presigned URL when object storage has a public endpoint, else streamed
  from S3. ``?file=dashboard`` (the default) is the bundle; ``report`` the
  report + dashboard file and ``pdf`` its PDF, where the instance renders
  reports and a worker has rendered them. Rate-limited per address in Redis, refused (503) when Redis cannot
  be reached: a door open to the whole internet does not open wider during an
  outage.

Both answer 404, alike, when either switch is off, the project is private, its
owner has not turned the download on, the dashboard is unknown, or no bundle
was built yet: nothing tells a caller which of these it met.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.serverless_endpoints.routes import _presigned_download_url
from depictio.api.v1.endpoints.user_endpoints.rate_limit import enforce_rate_limit
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.serverless import public_bundle

#: A presigned link lives long enough to start the download, not to be shared.
PRESIGN_SECONDS = 300
_NOT_FOUND = "No offline copy of this dashboard is available."


def _require_public_download_enabled() -> None:
    if not public_bundle.enabled():
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


public_bundle_router = APIRouter(dependencies=[Depends(_require_public_download_enabled)])


def _s3() -> Any:
    from depictio.api.v1.s3 import s3_client

    return s3_client


def _record_download(dashboard_id: str, request: Request) -> None:
    """Count one download in the usage statistics (no visitor identity)."""
    from depictio.api.v1.services import usage_stats

    record = getattr(usage_stats, "record_download", None)
    if record is not None:
        record(dashboard_id, request)


def _resolve(dashboard_id: str) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """``(main tab id, project, cache document, bundle served)``, or a 404."""
    main_id = public_bundle.main_tab_id(dashboard_id)
    project = public_bundle.project_of(main_id) if main_id else None
    if not main_id or project is None or not public_bundle.eligible(project):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    doc = public_bundle._db().public_bundles_collection.find_one({"_id": main_id}) or {}
    entry = public_bundle.served(doc)
    if entry is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return main_id, project, doc, entry


def _is_owner(project: dict[str, Any], user: Any) -> bool:
    if user is None or getattr(user, "is_anonymous", False):
        return False
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    try:
        return bool(check_project_permission(project["_id"], user, "owner"))
    except Exception:  # noqa: BLE001
        return False


@public_bundle_router.get("/public-bundle/{dashboard_id}")
def public_bundle_status(
    dashboard_id: str, current_user=Depends(get_user_or_anonymous)
) -> dict[str, Any]:
    """What a visitor's Download button shows. Mongo reads only."""
    main_id, project, doc, entry = _resolve(dashboard_id)
    payload: dict[str, Any] = {
        "dashboard_id": main_id,
        "available": True,
        "built_at": entry.get("built_at"),
        "size_bytes": entry.get("size_bytes"),
        "rebuilding": public_bundle.rebuilding(doc),
    }
    if public_bundle.report_enabled():
        report = public_bundle.served_report(doc)
        payload["report"] = {
            "available": report is not None,
            "built_at": (report or {}).get("built_at"),
            "size_bytes": (report or {}).get("size_bytes"),
            "pdf_available": bool((report or {}).get("pdf_s3_key")),
            "pdf_size_bytes": (report or {}).get("pdf_size_bytes"),
            "rebuilding": public_bundle.report_rebuilding(doc),
        }
    if _is_owner(project, current_user):
        current = doc.get("current") or {}
        payload["fresh"] = current.get("key") == public_bundle.content_key(main_id, project)
        payload["status"] = doc.get("status")
        payload["error"] = doc.get("error")
        if "report" in payload:
            report_doc = doc.get("report") or {}
            payload["report"]["status"] = report_doc.get("status")
            payload["report"]["error"] = report_doc.get("error")
    return payload


def _file_of(doc: dict[str, Any], entry: dict[str, Any], file: str) -> tuple[str, str, str, str]:
    """``(S3 key, media type, file name suffix, extension)`` of the asked file, or a 404."""
    if file == "dashboard":
        return entry["s3_key"], "text/html", "", "html"
    report = public_bundle.served_report(doc)
    if report is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if file == "report":
        return report["s3_key"], "text/html", "-report-dashboard", "html"
    if not report.get("pdf_s3_key"):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return report["pdf_s3_key"], "application/pdf", "-report", "pdf"


@public_bundle_router.get("/public-bundle/{dashboard_id}/download")
def public_bundle_download(
    dashboard_id: str,
    request: Request,
    file: Literal["dashboard", "report", "pdf"] = Query("dashboard"),
):
    """A pre-built file. Never builds: 404 until a worker has made it."""
    enforce_rate_limit(
        request,
        "public_bundle_download",
        max_calls=settings.static_export.public_download_per_ip_per_minute,
        fail_closed=True,
        detail="Too many downloads from this address; please wait a minute.",
        unavailable_detail="Downloads are temporarily unavailable; please retry in a moment.",
    )
    main_id, project, doc, entry = _resolve(dashboard_id)
    key, media_type, suffix, ext = _file_of(doc, entry, file)
    try:
        _record_download(main_id, request)
    except Exception as exc:  # noqa: BLE001 - counting must never block a download
        logger.warning(f"public bundle: download of {main_id} not counted: {exc}")

    name = "".join(c if c.isalnum() else "-" for c in str(project.get("name") or "dashboard"))
    stamp = str(entry.get("built_at") or "")[:10]
    slug = name.strip("-").lower() or "dashboard"
    filename = f"depictio-{slug}-{main_id[-6:]}-{stamp}{suffix}.{ext}"
    bucket = settings.s3.bucket
    url = _presigned_download_url(bucket, key, expires_in=PRESIGN_SECONDS, filename=filename)
    if url:
        return RedirectResponse(url, status_code=302)
    try:
        response = _s3().get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        logger.error(f"public bundle: {key} unreadable: {exc}")
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    def iterfile():
        yield from response["Body"].iter_chunks(chunk_size=64 * 1024)

    return StreamingResponse(
        iterfile(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
