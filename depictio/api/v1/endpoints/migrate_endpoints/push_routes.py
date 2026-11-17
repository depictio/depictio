"""Source side: preflight, push and status of an outbound push. (#1303).

A project owner (or an admin) pushes a project to a paired instance, or to an
*ad-hoc destination*: a URL under ``DEPICTIO_MIGRATION_DESTINATION_DOMAINS``
plus an invite code issued on that instance. The code is passed to the
background job in memory and never stored; the status of the request is then
read back with the per-request token the target returns.

The requester identity sent to the target is read from the session, never from
the request body, and the work after the 202 runs in a background thread
(``migration_push.run_push``) that records its own progress in
``migration_pushes``. One push per project may be in flight (409 otherwise).
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.crypto import decrypt_secret
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
from depictio.api.v1.services.outbound_http import (
    INVITE_HEADER,
    REQUEST_TOKEN_HEADER,
    RemoteError,
    ResolvedTarget,
    TargetClient,
    TargetURLRejected,
    check_destination_domain,
    check_target_url,
)
from depictio.models.models.migration import BUNDLE_FORMAT_VERSION, MigrationPush
from depictio.models.models.users import User
from depictio.models.timestamps import utc_now_str
from depictio.version import get_version

push_router = APIRouter()


ADHOC = "adhoc"
IN_FLIGHT = ("building", "uploading")
#: Remote states after which nothing changes any more on the target.
_REMOTE_FINAL = {"imported", "rejected", "expired", "superseded"}


class PreflightRequest(BaseModel):
    """A registered target (``target_id``) or a destination URL + invite code."""

    project_id: str
    target_id: str | None = None
    destination_url: str | None = Field(default=None, max_length=500)
    invite_code: str | None = Field(default=None, max_length=100)


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


def _domains() -> tuple[str, ...]:
    return tuple(settings.migration.destination_domains)


def normalize_destination(url: str) -> str:
    return url.strip().rstrip("/")


def adhoc_target(url: str, credential: str, header: str = INVITE_HEADER) -> ResolvedTarget:
    """A destination URL with the credential for one call. 400 when it is not allowed."""
    url = normalize_destination(url)
    try:
        check_destination_domain(url, _domains())
        check_target_url(
            url, trusted=False, host_allowlist=list(settings.migration.ui_target_host_allowlist)
        )
    except TargetURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from urllib.parse import urlsplit

    return ResolvedTarget(
        id=ADHOC,
        name=urlsplit(url).hostname or url,
        url=url,
        pairing_key=credential,
        trusted=False,
        credential_header=header,
        domain_suffixes=_domains(),
    )


def _target_of(body: PreflightRequest) -> ResolvedTarget:
    if body.target_id:
        return _resolve(body.target_id)
    if body.destination_url and body.invite_code and body.invite_code.strip():
        if not _domains():
            raise HTTPException(
                status_code=403, detail="Publishing to a destination URL is not enabled here"
            )
        return adhoc_target(body.destination_url, body.invite_code.strip())
    raise HTTPException(
        status_code=422, detail="Give a target, or a destination URL and an invite code"
    )


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
    question = {
        "project_id": str(scope.project_id),
        "project_name": project.get("name"),
        "requester_email": user.email,
        "source_depictio_version": get_version(),
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "total_bytes": total_bytes,
        "source_s3_endpoint": _normalized_s3_endpoint(),
        "source_bucket": settings.s3.bucket,
    }
    try:
        with TargetClient(target) as client:
            probe: dict[str, Any] | None = None
            try:
                # One round trip on targets that have /check ...
                answer = client.check(
                    {**question, "probe_key": objects[0].key if objects else None}
                )
                remote_info = answer.get("info") or {}
                remote_pre = answer.get("preflight") or {}
                probe = answer.get("probe")
            except RemoteError as exc:
                if exc.status_code not in (404, 405):
                    raise
                # ... three on targets from before it.
                remote_info = client.info()
                remote_pre = client.preflight(question)
                if remote_pre.get("transfer_mode") == "server_side_copy" and objects:
                    try:
                        probe = client.probe(settings.s3.bucket, objects[0].key)
                    except RemoteError as probe_exc:
                        probe = {"readable": False, "error": probe_exc.detail}
            if remote_pre.get("transfer_mode") == "server_side_copy" and objects:
                if (probe or {}).get("readable"):
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
        "target": {"id": target.id, "name": target.name, "url": target.url},
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


def _status_target(doc: dict[str, Any]) -> ResolvedTarget | None:
    """How to read a push's remote status; None when it cannot be read."""
    if doc.get("target_id") == ADHOC:
        enc = doc.get("status_token_enc")
        if not enc or not doc.get("target_url"):
            return None
        try:
            return adhoc_target(doc["target_url"], decrypt_secret(enc), REQUEST_TOKEN_HEADER)
        except HTTPException:
            return None
    try:
        return resolve_target(doc["target_id"])
    except KeyError:
        return None


def _refresh_remote(doc: dict[str, Any]) -> dict[str, Any]:
    """Read the request's state back from the target, best effort, and store it."""
    if not doc.get("remote_request_id") or doc.get("remote_status") in _REMOTE_FINAL:
        return doc
    target = _status_target(doc)
    if target is None:
        return doc
    try:
        with TargetClient(target) as client:
            answer = client.request_status(doc["remote_request_id"])
    except RemoteError as exc:
        logger.info("migrate push %s: remote status unavailable: %s", doc["_id"], exc.status_code)
        return doc
    status, result = answer.get("status"), answer.get("result")
    if status and (status != doc.get("remote_status") or result != doc.get("remote_result")):
        doc["remote_status"], doc["remote_result"] = status, result
        doc["updated_at"] = utc_now_str()
        migration_pushes_collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "remote_status": status,
                    "remote_result": result,
                    "updated_at": doc["updated_at"],
                }
            },
        )
    return doc


@push_router.get("/targets")
def push_targets(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    _require_pusher(current_user)
    return {"targets": list_targets(with_fingerprint=False)}


@push_router.get("/destinations")
def push_destinations(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Whether a destination URL may be typed, and the ones this user used lately.

    Only URLs are remembered, never an invite code.
    """
    _require_pusher(current_user)
    recent: list[str] = []
    docs = (
        migration_pushes_collection.find(
            {"target_id": ADHOC, "requested_by_id": str(current_user.id)}, {"target_url": 1}
        )
        .sort("created_at", -1)
        .limit(100)
    )
    for d in docs:
        url = d.get("target_url")
        if url and url not in recent:
            recent.append(url)
    return {"enabled": bool(_domains()), "domains": list(_domains()), "recent": recent[:10]}


@push_router.post("/check")
@push_router.post("/preflight")
def preflight(body: PreflightRequest, current_user: User = Depends(get_current_user)) -> dict:
    """What the target says about this project, before anything is built."""
    _require_pusher(current_user)
    project = _load_project(body.project_id, current_user)
    plan = _plan(project, _target_of(body), current_user)
    plan["in_flight"] = _in_flight(str(project["_id"])) is not None
    return plan


def _in_flight(project_id: str) -> dict[str, Any] | None:
    return migration_pushes_collection.find_one(
        {"project_id": project_id, "status": {"$in": list(IN_FLIGHT)}}, {"_id": 1}
    )


def _start(
    body: PushRequest,
    background: BackgroundTasks,
    user: User,
    *,
    retry_of: str | None = None,
) -> dict[str, Any]:
    _require_pusher(user)
    project = _load_project(body.project_id, user)
    project_id = str(project["_id"])
    busy = "This project already has a push in progress"
    if _in_flight(project_id):
        raise HTTPException(status_code=409, detail=busy)
    target = _target_of(body)
    plan = _plan(project, target, user)
    if not plan["can_push"]:
        raise HTTPException(status_code=422, detail={"errors": plan["errors"]})
    adhoc = target.id == ADHOC
    doc = MigrationPush(
        project_id=project_id,
        project_name=project.get("name"),
        target_id=target.id,
        target_name=target.name,
        target_url=target.url if adhoc else None,
        credential_type="invite_code" if adhoc else "pairing_key",
        in_flight=True,
        retry_of=retry_of,
        requested_by_id=str(user.id),
        requested_by_email=str(user.email),
        message=body.message,
        transfer_mode=plan["transfer_mode"],
    ).model_dump(exclude={"id"})
    try:
        push_id = str(migration_pushes_collection.insert_one(doc).inserted_id)
    except DuplicateKeyError:  # the partial unique index lost a race for us
        raise HTTPException(status_code=409, detail=busy)
    # The invite code travels to the job in memory only.
    background.add_task(run_push, push_id, target.pairing_key if adhoc else None)
    return {"push_id": push_id, "status": "building"}


@push_router.post("", status_code=202)
@push_router.post("/", status_code=202, include_in_schema=False)
def start_push(
    body: PushRequest,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Record the push and build/upload it in the background."""
    return _start(body, background, current_user)


class RetryRequest(BaseModel):
    #: Needed again for a destination URL: the code was never stored.
    invite_code: str | None = Field(default=None, max_length=100)


@push_router.post("/{push_id}/retry", status_code=202)
def retry_push(
    push_id: str,
    background: BackgroundTasks,
    body: RetryRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Start a new push like a failed one (same project, target and message)."""
    _require_pusher(current_user)
    doc = _own_push(push_id, current_user)
    if doc.get("status") != "failed":
        raise HTTPException(status_code=409, detail="Only a failed push can be retried")
    adhoc = doc.get("target_id") == ADHOC
    code = (body.invite_code if body else None) or None
    if adhoc and not code:
        raise HTTPException(
            status_code=422, detail="Enter the invite code again: it is never stored"
        )
    again = PushRequest(
        project_id=doc["project_id"],
        target_id=None if adhoc else doc["target_id"],
        destination_url=doc.get("target_url") if adhoc else None,
        invite_code=code if adhoc else None,
        message=doc.get("message"),
    )
    return _start(again, background, current_user, retry_of=str(doc["_id"]))


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
    docs = list(migration_pushes_collection.find(query).sort("created_at", -1).limit(200))
    # Follow the few pushes whose import may still be running on the target, so
    # a polling list sees them finish. Bounded: each is one call to a target.
    live = [
        d
        for d in docs
        if d.get("status") == "submitted"
        and d.get("remote_status") in (None, "pending", "importing")
    ]
    for doc in live[:5]:
        _refresh_remote(doc)
    return {"pushes": [_push_json(d) for d in docs]}


def _own_push(push_id: str, user: User) -> dict[str, Any]:
    if not ObjectId.is_valid(push_id):
        raise HTTPException(status_code=404, detail="Push not found")
    doc = migration_pushes_collection.find_one({"_id": ObjectId(push_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Push not found")
    if not _acts_as_admin(user) and doc.get("requested_by_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Not your push")
    return doc


@push_router.get("/{push_id}")
def get_push(push_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    _require_pusher(current_user)
    return _push_json(_refresh_remote(_own_push(push_id, current_user)))
