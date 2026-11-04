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
async def list_requests(
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    """Requests, newest first, optionally of one status."""
    _require_admin(current_user)
    query = {"status": status} if status else {}
    docs = _db().migration_requests_collection.find(query).sort("created_at", -1)
    return {"requests": [_summary(d) for d in docs]}


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
    body["report"] = report
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
