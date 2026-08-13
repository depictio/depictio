"""Groups management API.

Group documents live in the ``groups`` collection (see
``depictio.models.models.users.GroupBeanie``); membership arrays are raw
ObjectIds. Reads/writes here use the sync pymongo handles from
``depictio.api.v1.db`` because most mutations must also touch the permission
snapshots embedded in projects/dashboards/workflows/files, which are sync-only.
Creation goes through ``GroupBeanie`` so the model validators (admins/P.I.
auto-membership, description sanitizing) run.
"""

import re

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    files_collection,
    groups_collection,
    projects_collection,
    users_collection,
    workflows_collection,
)
from depictio.api.v1.endpoints.groups_endpoints.models import (
    GroupCreateRequest,
    GroupDetail,
    GroupMemberOut,
    GroupSummary,
    GroupUpdateRequest,
    MyGroup,
)
from depictio.api.v1.endpoints.groups_endpoints.utils import (
    assert_group_admin_or_sysadmin,
    require_admin,
    require_authenticated_user,
    sanitize_group_description,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import GroupBeanie, User

groups_endpoint_router = APIRouter()

# Seeded groups from db_init (static ids) — the permission system bootstraps
# around them, so they must never be deletable.
PROTECTED_GROUP_IDS: frozenset[str] = frozenset(
    {
        "67658ba033c8b59ad489d7c9",  # "admin"
        "67658ba033c8b59ad489d7d0",  # "users"
    }
)

# Collections carrying embedded permission snapshots that reference groups.
_PERMISSION_COLLECTIONS = (
    projects_collection,
    dashboards_collection,
    workflows_collection,
    files_collection,
)
_GROUP_PERMISSION_FIELDS = ("group_owners", "group_editors", "group_viewers")


def _get_group_or_404(group_id: PyObjectId) -> dict:
    group_doc = groups_collection.find_one({"_id": ObjectId(str(group_id))})
    if group_doc is None:
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found.")
    return group_doc


def _get_user_oid_or_404(user_id: PyObjectId) -> ObjectId:
    user_oid = ObjectId(str(user_id))
    if users_collection.find_one({"_id": user_oid}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    return user_oid


def _name_conflict(name: str, exclude_id: ObjectId | None = None) -> bool:
    query: dict = {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    return groups_collection.find_one(query, {"_id": 1}) is not None


def _group_summary(group_doc: dict) -> GroupSummary:
    return GroupSummary(
        id=str(group_doc["_id"]),
        name=group_doc.get("name", ""),
        description=group_doc.get("description"),
        member_count=len(group_doc.get("users_ids") or []),
        sso_managed=bool(group_doc.get("sso_managed", False)),
    )


def _group_detail(group_doc: dict) -> GroupDetail:
    admin_ids = [str(admin_id) for admin_id in group_doc.get("admin_ids") or []]
    pi_id = group_doc.get("pi_id")
    member_oids = [ObjectId(str(user_id)) for user_id in group_doc.get("users_ids") or []]

    user_docs = {
        user_doc["_id"]: user_doc
        for user_doc in users_collection.find(
            {"_id": {"$in": member_oids}}, {"email": 1, "display_name": 1}
        )
    }
    members = []
    for member_oid in member_oids:
        user_doc = user_docs.get(member_oid)
        if user_doc is None:
            continue  # dangling membership ref (deleted user) — skip silently
        members.append(
            GroupMemberOut(
                id=str(member_oid),
                email=user_doc.get("email", ""),
                display_name=user_doc.get("display_name"),
                is_group_admin=str(member_oid) in admin_ids,
                is_pi=pi_id is not None and str(pi_id) == str(member_oid),
            )
        )

    return GroupDetail(
        id=str(group_doc["_id"]),
        name=group_doc.get("name", ""),
        description=group_doc.get("description"),
        sso_managed=bool(group_doc.get("sso_managed", False)),
        pi_id=str(pi_id) if pi_id is not None else None,
        admin_ids=admin_ids,
        members=members,
    )


def _refetch_detail(group_oid: ObjectId) -> GroupDetail:
    group_doc = groups_collection.find_one({"_id": group_oid})
    if group_doc is None:  # deleted concurrently
        raise HTTPException(status_code=404, detail="Group not found.")
    return _group_detail(group_doc)


def _propagate_group_rename(group_oid: ObjectId, new_name: str) -> None:
    """Sync the denormalized group name into every permission snapshot."""
    for collection in _PERMISSION_COLLECTIONS:
        for field in _GROUP_PERMISSION_FIELDS:
            collection.update_many(
                {f"permissions.{field}._id": group_oid},
                {"$set": {f"permissions.{field}.$[g].name": new_name}},
                array_filters=[{"g._id": group_oid}],
            )


def _remove_group_refs(group_oid: ObjectId) -> None:
    """Drop every permission snapshot referencing a deleted group."""
    match = {"$or": [{f"permissions.{field}._id": group_oid} for field in _GROUP_PERMISSION_FIELDS]}
    pull = {f"permissions.{field}": {"_id": group_oid} for field in _GROUP_PERMISSION_FIELDS}
    for collection in _PERMISSION_COLLECTIONS:
        collection.update_many(match, {"$pull": pull})


@groups_endpoint_router.get("/list", response_model=list[GroupSummary])
async def list_groups(current_user: User = Depends(require_authenticated_user)):
    """List all groups (sharing picker). Any authenticated non-anonymous user;
    summaries only, so no member emails are leaked."""
    return [_group_summary(group_doc) for group_doc in groups_collection.find({})]


@groups_endpoint_router.get("/mine", response_model=list[MyGroup])
async def my_groups(current_user: User = Depends(require_authenticated_user)):
    """Groups the caller belongs to, annotated with their role in each."""
    user_oid = ObjectId(str(current_user.id))
    results = []
    for group_doc in groups_collection.find({"users_ids": user_oid}):
        summary = _group_summary(group_doc)
        results.append(
            MyGroup(
                **summary.model_dump(),
                is_group_admin=user_oid in (group_doc.get("admin_ids") or []),
                is_pi=group_doc.get("pi_id") == user_oid,
            )
        )
    return results


@groups_endpoint_router.get("/{group_id}", response_model=GroupDetail)
async def get_group(group_id: PyObjectId, current_user: User = Depends(require_authenticated_user)):
    """Group detail incl. member list — sysadmin, group admins and members only."""
    group_doc = _get_group_or_404(group_id)
    user_id_str = str(current_user.id)
    is_member = any(user_id_str == str(uid) for uid in group_doc.get("users_ids") or [])
    is_group_admin = any(user_id_str == str(aid) for aid in group_doc.get("admin_ids") or [])
    if not (current_user.is_admin or is_member or is_group_admin):
        logger.warning(f"User {current_user.id} denied access to group {group_id} detail")
        raise HTTPException(status_code=403, detail="You are not a member of this group.")
    return _group_detail(group_doc)


@groups_endpoint_router.post("", response_model=GroupDetail, status_code=201)
async def create_group(payload: GroupCreateRequest, current_user: User = Depends(require_admin)):
    """Create a group (sysadmin only). The optional P.I. becomes member + group admin."""
    if _name_conflict(payload.name):
        raise HTTPException(
            status_code=409, detail=f"A group named '{payload.name}' already exists."
        )

    if payload.pi_id is not None:
        _get_user_oid_or_404(payload.pi_id)

    try:
        # GroupBeanie runs the model validators (P.I./admins auto-added to
        # members, description sanitized) and persists raw ObjectId arrays.
        group = GroupBeanie(
            name=payload.name,
            description=payload.description,
            pi_id=payload.pi_id,
            admin_ids=[payload.pi_id] if payload.pi_id is not None else [],
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid group payload: {exc}")

    await group.insert()
    logger.info(f"Group '{group.name}' ({group.id}) created by {current_user.email}")
    return _refetch_detail(ObjectId(str(group.id)))


@groups_endpoint_router.patch("/{group_id}", response_model=GroupDetail)
async def update_group(
    group_id: PyObjectId,
    payload: GroupUpdateRequest,
    current_user: User = Depends(require_authenticated_user),
):
    """Rename / re-describe a group (sysadmin or group admin). Renames are
    propagated into the denormalized permission snapshots."""
    group_doc = _get_group_or_404(group_id)
    assert_group_admin_or_sysadmin(group_doc, current_user)
    group_oid = group_doc["_id"]

    updates: dict = {}
    if payload.name is not None and payload.name != group_doc.get("name"):
        if _name_conflict(payload.name, exclude_id=group_oid):
            raise HTTPException(
                status_code=409, detail=f"A group named '{payload.name}' already exists."
            )
        updates["name"] = payload.name
    if payload.description is not None:
        updates["description"] = sanitize_group_description(payload.description)

    if updates:
        groups_collection.update_one({"_id": group_oid}, {"$set": updates})
        if "name" in updates:
            _propagate_group_rename(group_oid, updates["name"])
            logger.info(
                f"Group {group_oid} renamed to '{updates['name']}' by {current_user.email}; "
                f"permission snapshots updated"
            )
    return _refetch_detail(group_oid)


@groups_endpoint_router.delete("/{group_id}")
async def delete_group(group_id: PyObjectId, current_user: User = Depends(require_admin)):
    """Delete a group (sysadmin only) and scrub its permission snapshots."""
    if str(group_id) in PROTECTED_GROUP_IDS:
        raise HTTPException(
            status_code=400, detail="The built-in 'admin' and 'users' groups cannot be deleted."
        )
    group_doc = _get_group_or_404(group_id)
    group_oid = group_doc["_id"]

    groups_collection.delete_one({"_id": group_oid})
    _remove_group_refs(group_oid)
    logger.info(f"Group '{group_doc.get('name')}' ({group_oid}) deleted by {current_user.email}")
    return {"success": True, "message": f"Group '{group_doc.get('name')}' deleted."}


@groups_endpoint_router.post("/{group_id}/members/{user_id}", response_model=GroupDetail)
async def add_group_member(
    group_id: PyObjectId,
    user_id: PyObjectId,
    current_user: User = Depends(require_authenticated_user),
):
    """Add a member (sysadmin or group admin). Idempotent. Works on sso_managed
    groups too (manual override) — the response carries ``sso_managed`` so the
    UI can warn."""
    group_doc = _get_group_or_404(group_id)
    assert_group_admin_or_sysadmin(group_doc, current_user)
    user_oid = _get_user_oid_or_404(user_id)

    groups_collection.update_one({"_id": group_doc["_id"]}, {"$addToSet": {"users_ids": user_oid}})
    logger.info(f"User {user_oid} added to group {group_doc['_id']} by {current_user.email}")
    return _refetch_detail(group_doc["_id"])


@groups_endpoint_router.delete("/{group_id}/members/{user_id}", response_model=GroupDetail)
async def remove_group_member(
    group_id: PyObjectId,
    user_id: PyObjectId,
    current_user: User = Depends(require_authenticated_user),
):
    """Remove a member (sysadmin or group admin). Idempotent. Also drops their
    group-admin role and clears pi_id if it was them."""
    group_doc = _get_group_or_404(group_id)
    assert_group_admin_or_sysadmin(group_doc, current_user)
    user_oid = _get_user_oid_or_404(user_id)

    admin_ids = group_doc.get("admin_ids") or []
    # Last-admin guard: only a sysadmin may leave the group admin-less.
    if user_oid in admin_ids and not current_user.is_admin:
        if all(admin_id == user_oid for admin_id in admin_ids):
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last group admin. Promote another admin first.",
            )

    update: dict = {"$pull": {"users_ids": user_oid, "admin_ids": user_oid}}
    if group_doc.get("pi_id") == user_oid:
        update["$set"] = {"pi_id": None}
    groups_collection.update_one({"_id": group_doc["_id"]}, update)
    logger.info(f"User {user_oid} removed from group {group_doc['_id']} by {current_user.email}")
    return _refetch_detail(group_doc["_id"])


@groups_endpoint_router.post(
    "/{group_id}/admins/{user_id}/{make_admin}", response_model=GroupDetail
)
async def set_group_admin(
    group_id: PyObjectId,
    user_id: PyObjectId,
    make_admin: bool,
    current_user: User = Depends(require_authenticated_user),
):
    """Promote/demote a group admin (sysadmin or group admin of THIS group).

    Mirrors the /auth/turn_sysadmin guard rails: no self-demotion, and the
    group cannot be left admin-less unless the caller is a sysadmin.
    """
    group_doc = _get_group_or_404(group_id)
    assert_group_admin_or_sysadmin(group_doc, current_user)
    user_oid = _get_user_oid_or_404(user_id)

    if make_admin:
        # Raw update bypasses the model validator, so enforce the
        # admins-are-members invariant here too.
        groups_collection.update_one(
            {"_id": group_doc["_id"]},
            {"$addToSet": {"admin_ids": user_oid, "users_ids": user_oid}},
        )
    else:
        if user_oid == ObjectId(str(current_user.id)):
            raise HTTPException(status_code=400, detail="Group admins cannot demote themselves.")
        admin_ids = group_doc.get("admin_ids") or []
        if (
            user_oid in admin_ids
            and not current_user.is_admin
            and all(admin_id == user_oid for admin_id in admin_ids)
        ):
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last group admin. Promote another admin first.",
            )
        groups_collection.update_one({"_id": group_doc["_id"]}, {"$pull": {"admin_ids": user_oid}})

    logger.info(
        f"User {user_oid} {'promoted to' if make_admin else 'demoted from'} group admin of "
        f"{group_doc['_id']} by {current_user.email}"
    )
    return _refetch_detail(group_doc["_id"])


@groups_endpoint_router.post("/{group_id}/pi/{user_id}", response_model=GroupDetail)
async def set_group_pi(
    group_id: PyObjectId,
    user_id: PyObjectId,
    current_user: User = Depends(require_admin),
):
    """Set the group's P.I. (sysadmin only). The P.I. becomes member + group admin."""
    group_doc = _get_group_or_404(group_id)
    user_oid = _get_user_oid_or_404(user_id)

    groups_collection.update_one(
        {"_id": group_doc["_id"]},
        {
            "$set": {"pi_id": user_oid},
            "$addToSet": {"users_ids": user_oid, "admin_ids": user_oid},
        },
    )
    logger.info(f"User {user_oid} set as P.I. of group {group_doc['_id']} by {current_user.email}")
    return _refetch_detail(group_doc["_id"])
