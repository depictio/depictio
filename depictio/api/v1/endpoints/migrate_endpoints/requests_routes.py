"""Target side, admin only: the approval queue for inbound requests. (#1303).

Approving does not import in the request: it atomically takes the request from
``pending`` to ``importing`` (so two admins cannot start it twice) and hands the
work to a background task that records its own outcome.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.services import migration_import
from depictio.models.models.migration import MigrationRequest
from depictio.models.models.users import User
from depictio.models.timestamps import utc_now_str
from depictio.version import get_version

requests_router = APIRouter()


def _db():
    return migration_import._db()


def _require_admin(current_user: User) -> None:
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can manage requests")


def _load(request_id: str) -> dict[str, Any]:
    try:
        oid = ObjectId(request_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Request not found")
    doc = _db().migration_requests_collection.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    return doc


def _summary(doc: dict[str, Any]) -> dict[str, Any]:
    report = doc.get("report") or {}
    requester = doc.get("requester") or {}
    return {
        "id": str(doc["_id"]),
        "status": doc.get("status"),
        "source_name": doc.get("source_name"),
        "source_instance": doc.get("source_instance"),
        "source_url": doc.get("source_url"),
        "credential_type": doc.get("credential_type", "pairing_key"),
        "invite_id": doc.get("invite_id"),
        "retryable": bool(doc.get("retryable")),
        "error": (doc.get("result") or {}).get("error") if doc.get("status") == "failed" else None,
        "source_depictio_version": doc.get("source_depictio_version"),
        "requester": {"email": requester.get("email"), "name": requester.get("name")},
        "project_id": doc.get("project_id"),
        "project_name": doc.get("project_name"),
        "transfer_mode": doc.get("transfer_mode"),
        "bundle_bytes": doc.get("bundle_bytes", 0),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "conflict": report.get("conflict", "none"),
        "existing_locked": bool(report.get("existing_locked")),
        "error_count": len(report.get("errors") or []),
        "warning_count": len(report.get("warnings") or []),
    }


@requests_router.get("/")
@requests_router.get("", include_in_schema=False)
async def list_requests(
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    """Requests, newest first, optionally of one status."""
    _require_admin(current_user)
    query = {"status": status} if status else {}
    docs = _db().migration_requests_collection.find(query).sort("created_at", -1)
    return {"requests": [_summary(d) for d in docs]}


def _enrich_report(report: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Give a report the dashboards and collections an admin recognises them by.

    Reports computed from this version on carry both. An older request does
    not: once imported, read them from the project as it now stands here.
    """
    if report.get("dashboards") or report.get("data_collections"):
        return report
    project_id = (doc.get("result") or {}).get("project_id") or doc.get("project_id")
    if doc.get("status") != "imported" or not project_id:
        return report
    from depictio.api.v1.services import project_bundle

    db = _db()
    ids = [
        ObjectId(i)
        for i in {
            *(report.get("dashboards_added") or []),
            *(report.get("dashboards_replaced") or []),
        }
        if ObjectId.is_valid(i)
    ]
    dashboards = list(db.dashboards_collection.find({"_id": {"$in": ids}})) if ids else []
    project = None
    if ObjectId.is_valid(str(project_id)):
        project = db.projects_collection.find_one({"_id": ObjectId(str(project_id))})
    return {
        **report,
        "dashboards": project_bundle.dashboard_summaries(dashboards),
        "data_collections": project_bundle.data_collection_summaries(project or {}),
    }


def _invite_facts(doc: dict[str, Any]) -> dict[str, Any]:
    """The note and code hint of the invite behind a request, never the code."""
    invite_id = doc.get("invite_id")
    if not invite_id or not ObjectId.is_valid(str(invite_id)):
        return {}
    invite = _db().migration_invites_collection.find_one({"_id": ObjectId(str(invite_id))})
    if not invite:
        return {}
    return {"invite_note": invite.get("note"), "invite_code_hint": invite.get("code_hint")}


@requests_router.get("/{request_id}")
async def get_request(request_id: str, current_user: User = Depends(get_current_user)):
    """One request in full, with its report recomputed while it is still pending."""
    _require_admin(current_user)
    doc = _load(request_id)
    report = doc.get("report") or {}
    if doc.get("status") == "pending":
        try:
            report = (
                await run_in_threadpool(migration_import.revalidate_request, doc)
            ).model_dump()
        except migration_import.ImportFailed as exc:
            report = {**report, "errors": [*(report.get("errors") or []), str(exc)]}
    body = MigrationRequest.model_validate(doc).model_dump()
    body["report"] = _enrich_report(report, doc)
    body.update(_invite_facts(doc))
    body["requester_has_account"] = (
        migration_import.find_user_by_email((doc.get("requester") or {}).get("email")) is not None
    )
    body["target_depictio_version"] = get_version()
    body["lock_imported_default"] = settings.migration.lock_imported_default
    return body


class ApproveBody(BaseModel):
    lock: bool | None = None
    make_public: bool = False


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


def _decide(request_id: str, new_status: str, decision: dict[str, Any]) -> dict[str, Any]:
    """Move a pending request to ``new_status`` once; 404 / 409 otherwise."""
    doc = _load(request_id)
    claimed = _db().migration_requests_collection.find_one_and_update(
        {"_id": doc["_id"], "status": "pending"},
        {"$set": {"status": new_status, "decision": decision, "updated_at": utc_now_str()}},
    )
    if claimed is None:
        raise HTTPException(status_code=409, detail="Request is not pending")
    return claimed


@requests_router.post("/{request_id}/approve", status_code=202)
async def approve_request(
    request_id: str,
    background_tasks: BackgroundTasks,
    body: ApproveBody | None = None,
    current_user: User = Depends(get_current_user),
):
    """Approve a pending request and import it in the background."""
    _require_admin(current_user)
    body = body or ApproveBody()
    lock = settings.migration.lock_imported_default if body.lock is None else body.lock
    approver = {"id": str(current_user.id), "email": getattr(current_user, "email", None)}
    claimed = _decide(
        request_id,
        "importing",
        {
            "action": "approve",
            "by_id": approver["id"],
            "by_email": approver["email"],
            "at": utc_now_str(),
            "lock": lock,
            "make_public": body.make_public,
        },
    )
    background_tasks.add_task(
        migration_import.run_migration_import, str(claimed["_id"]), approver, lock, body.make_public
    )
    return {"id": str(claimed["_id"]), "status": "importing"}


@requests_router.post("/{request_id}/reject")
async def reject_request(
    request_id: str, body: RejectBody, current_user: User = Depends(get_current_user)
):
    """Reject a pending request and delete its staged bundle."""
    _require_admin(current_user)
    claimed = _decide(
        request_id,
        "rejected",
        {
            "action": "reject",
            "by_id": str(current_user.id),
            "by_email": getattr(current_user, "email", None),
            "at": utc_now_str(),
            "reason": body.reason,
        },
    )
    await run_in_threadpool(migration_import.delete_staged_bundle, claimed)
    return {"id": str(claimed["_id"]), "status": "rejected"}


@requests_router.post("/{request_id}/revalidate")
async def revalidate_request(request_id: str, current_user: User = Depends(get_current_user)):
    """Recompute the report of a pending request against the current state."""
    _require_admin(current_user)
    doc = _load(request_id)
    if doc.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Request is not pending")
    try:
        report = await run_in_threadpool(migration_import.revalidate_request, doc)
    except migration_import.ImportFailed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    dumped = report.model_dump()
    _db().migration_requests_collection.update_one(
        {"_id": doc["_id"], "status": "pending"},
        {"$set": {"report": dumped, "updated_at": utc_now_str()}},
    )
    return {"id": str(doc["_id"]), "report": dumped}


@requests_router.post("/{request_id}/retry", status_code=202)
async def retry_request(
    request_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Run again an import that a restart interrupted, with its original decision.

    Only a request marked ``retryable`` qualifies: its staged bundle was kept.
    Any other failure deleted the bundle, and the source must push again.
    """
    _require_admin(current_user)
    doc = _load(request_id)
    claimed = migration_import.claim_retry(doc["_id"])
    if claimed is None:
        raise HTTPException(status_code=409, detail="Only an interrupted import can be retried")
    decision = claimed.get("decision") or {}
    lock = bool(decision.get("lock", settings.migration.lock_imported_default))
    make_public = bool(decision.get("make_public"))
    approver = {
        "id": str(decision.get("by_id") or current_user.id),
        "email": decision.get("by_email") or getattr(current_user, "email", None),
    }
    background_tasks.add_task(
        migration_import.run_migration_import, str(claimed["_id"]), approver, lock, make_public
    )
    return {"id": str(claimed["_id"]), "status": "importing"}


@requests_router.post("/{request_id}/thumbnails", status_code=202)
async def regenerate_thumbnails(request_id: str, current_user: User = Depends(get_current_user)):
    """Queue new thumbnails for the dashboards an imported request brought in.

    A bundle carries no thumbnails, so an imported dashboard shows none until
    something captures it; this asks for that, once, by hand.
    """
    _require_admin(current_user)
    doc = _load(request_id)
    if doc.get("status") != "imported":
        raise HTTPException(status_code=409, detail="Only an imported request has dashboards here")
    if not settings.performance.screenshots_enabled:
        raise HTTPException(status_code=503, detail="Screenshots are disabled on this instance")
    report = doc.get("report") or {}
    refs = {*(report.get("dashboards_added") or []), *(report.get("dashboards_replaced") or [])}
    db = _db()
    dashboard_ids = [
        str(d["dashboard_id"])
        for d in db.dashboards_collection.find(
            {"_id": {"$in": [ObjectId(i) for i in refs if ObjectId.is_valid(i)]}},
            {"dashboard_id": 1},
        )
        if d.get("dashboard_id")
    ]
    from depictio.api.celery_app import generate_dashboard_screenshot_dual

    user_id = str(current_user.id)
    queued = 0
    for dashboard_id in dashboard_ids:
        try:
            generate_dashboard_screenshot_dual.delay(dashboard_id, user_id, force=True)
            queued += 1
        except Exception:  # noqa: BLE001 — a broker outage must not 500 the page
            continue
    return {"id": str(doc["_id"]), "queued": queued, "dashboards": len(dashboard_ids)}
