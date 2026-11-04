"""Source side: preflight, push and status of an outbound push. (#1303).

A project owner (or an admin) pushes a project to a paired instance. The
requester identity sent to the target is read from the session, never from the
request body, and the work after the 202 runs in a background thread
(``migration_push.run_push``) that records its own progress in
``migration_pushes``.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import migration_pushes_collection, projects_collection
from depictio.api.v1.endpoints.migrate_endpoints.targets_routes import (
    list_targets,
    resolve_target,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.permissions import get_user_group_ids, has_permission
from depictio.api.v1.services import project_bundle
from depictio.api.v1.services.migration_push import (
    BundleListingError,
    list_project_objects,
    run_push,
)
from depictio.api.v1.services.outbound_http import RemoteError, ResolvedTarget, TargetClient
from depictio.models.models.migration import BUNDLE_FORMAT_VERSION, MigrationPush
from depictio.models.models.users import User
from depictio.models.timestamps import utc_now_str
from depictio.version import get_version

push_router = APIRouter()


class PreflightRequest(BaseModel):
    project_id: str
    target_id: str


class PushRequest(PreflightRequest):
    message: str | None = Field(default=None, max_length=2000)


def _acts_as_admin(user: User) -> bool:
    """Single-user mode's auto-provisioned user is the instance's only admin."""
    return bool(user.is_admin or settings.auth.is_single_user_mode)


def _require_pusher(user: User) -> None:
    if settings.auth.is_single_user_mode:
        return
    if user.is_anonymous or user.is_temporary:
        raise HTTPException(status_code=403, detail="Sign in to push a project")


def _load_project(project_id: str, user: User) -> dict[str, Any]:
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    project = projects_collection.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _acts_as_admin(user) and not has_permission(
        project, user, "owner", get_user_group_ids(user.id)
    ):
        raise HTTPException(status_code=403, detail="Only the project owner can push a project")
    return project


def _resolve(target_id: str) -> ResolvedTarget:
    try:
        return resolve_target(target_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Target not found")


def _plan(project: dict[str, Any], target: ResolvedTarget, user: User) -> dict[str, Any]:
    """Ask the target whether it would take this project, and pick the transfer mode.

    ``server_side_copy`` only when the target says both instances share the S3
    endpoint AND it can really read the first object with its own credentials;
    a bucket policy the target cannot cross would otherwise fail the import
    after approval.
    """
    scope = project_bundle.resolve_project_scope(project)
    try:
        _, objects = list_project_objects(scope)
    except BundleListingError:
        raise HTTPException(status_code=502, detail="Could not list the project's data")
    total_bytes = sum(o.size for o in objects)
    errors: list[str] = []
    warnings: list[str] = []
    remote_info: dict[str, Any] = {}
    remote_pre: dict[str, Any] = {}
    mode = "inline"
    try:
        with TargetClient(target) as client:
            remote_info = client.info()
            remote_pre = client.preflight(
                {
                    "project_id": str(scope.project_id),
                    "project_name": project.get("name"),
                    "requester_email": user.email,
                    "source_depictio_version": get_version(),
                    "bundle_format_version": BUNDLE_FORMAT_VERSION,
                    "total_bytes": total_bytes,
                    "source_s3_endpoint": _normalized_s3_endpoint(),
                    "source_bucket": settings.s3.bucket,
                }
            )
            if remote_pre.get("transfer_mode") == "server_side_copy" and objects:
                try:
                    probe = client.probe(settings.s3.bucket, objects[0].key)
                except RemoteError as exc:
                    probe = {"readable": False, "error": exc.detail}
                if probe.get("readable"):
                    mode = "server_side_copy"
                else:
                    warnings.append(
                        "The target shares this storage but cannot read it; "
                        "the data will travel inside the bundle."
                    )
    except RemoteError as exc:
        errors.append(f"Target: {exc.detail}")
    errors.extend(str(e) for e in remote_pre.get("errors") or [])
    warnings.extend(str(w) for w in remote_pre.get("warnings") or [])
    if remote_pre and remote_pre.get("ok") is False and not errors:
        errors.append("The target would not accept this project")
    return {
        "target": {"id": target.id, "name": target.name},
        "remote_info": remote_info,
        "preflight": remote_pre,
        "transfer_mode": mode,
        "total_bytes": total_bytes,
        "object_count": len(objects),
        "can_push": not errors and bool(remote_pre),
        "errors": errors,
        "warnings": warnings,
    }


def _normalized_s3_endpoint() -> str | None:
    from depictio.api.v1.endpoints.migrate_endpoints import routes

    return routes._normalize_endpoint(settings.s3.endpoint_url or "")


def _push_json(doc: dict[str, Any]) -> dict[str, Any]:
    return MigrationPush.model_validate(doc).model_dump()


@push_router.get("/targets")
def push_targets(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    _require_pusher(current_user)
    return {"targets": list_targets(with_fingerprint=False)}


@push_router.post("/preflight")
def preflight(body: PreflightRequest, current_user: User = Depends(get_current_user)) -> dict:
    _require_pusher(current_user)
    project = _load_project(body.project_id, current_user)
    return _plan(project, _resolve(body.target_id), current_user)


@push_router.post("", status_code=202)
@push_router.post("/", status_code=202, include_in_schema=False)
def start_push(
    body: PushRequest,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Record the push and build/upload it in the background."""
    _require_pusher(current_user)
    project = _load_project(body.project_id, current_user)
    target = _resolve(body.target_id)
    plan = _plan(project, target, current_user)
    if not plan["can_push"]:
        raise HTTPException(status_code=422, detail={"errors": plan["errors"]})
    doc = MigrationPush(
        project_id=str(project["_id"]),
        project_name=project.get("name"),
        target_id=target.id,
        target_name=target.name,
        requested_by_id=str(current_user.id),
        requested_by_email=str(current_user.email),
        message=body.message,
        transfer_mode=plan["transfer_mode"],
    ).model_dump(exclude={"id"})
    push_id = str(migration_pushes_collection.insert_one(doc).inserted_id)
    background.add_task(run_push, push_id)
    return {"push_id": push_id, "status": "building"}


@push_router.get("")
@push_router.get("/", include_in_schema=False)
def list_pushes(
    project_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_pusher(current_user)
    query: dict[str, Any] = {}
    if project_id:
        query["project_id"] = project_id
    if not _acts_as_admin(current_user):
        query["requested_by_id"] = str(current_user.id)
    docs = migration_pushes_collection.find(query).sort("created_at", -1).limit(200)
    return {"pushes": [_push_json(d) for d in docs]}


@push_router.get("/{push_id}")
def get_push(push_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    _require_pusher(current_user)
    if not ObjectId.is_valid(push_id):
        raise HTTPException(status_code=404, detail="Push not found")
    doc = migration_pushes_collection.find_one({"_id": ObjectId(push_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Push not found")
    if not _acts_as_admin(current_user) and doc.get("requested_by_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your push")
    if doc.get("remote_request_id"):
        try:
            with TargetClient(resolve_target(doc["target_id"])) as client:
                status = client.request_status(doc["remote_request_id"]).get("status")
            if status and status != doc.get("remote_status"):
                doc["remote_status"] = status
                doc["updated_at"] = utc_now_str()
                migration_pushes_collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"remote_status": status, "updated_at": doc["updated_at"]}},
                )
        except (RemoteError, KeyError) as exc:
            logger.info("migrate push %s: remote status unavailable: %s", push_id, type(exc))
    return _push_json(doc)
