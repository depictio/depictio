"""Target side, admin only: invite codes that let a source push here. (#1303).

``POST`` returns the code once; afterwards only its last four characters are
shown. An invite is usable only while ``DEPICTIO_MIGRATION_INBOUND_ENABLED``
is on, so creating one is refused (409) while it is off.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.services import migration_invites
from depictio.models.models.migration import InvitePolicy
from depictio.models.models.users import User

invites_router = APIRouter()


class InviteCreate(BaseModel):
    policy: InvitePolicy = "single_use"
    lock_on_import: bool = True
    #: Lifetime; the policy's default when omitted.
    expires_in_hours: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=500)


def _require_admin(user: User) -> None:
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can manage invites")


def _oid(invite_id: str) -> ObjectId:
    if not ObjectId.is_valid(invite_id):
        raise HTTPException(status_code=404, detail="Invite not found")
    return ObjectId(invite_id)


@invites_router.get("")
@invites_router.get("/", include_in_schema=False)
def list_invites(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    _require_admin(current_user)
    col = migration_invites._col()
    docs = col.find({}).sort("created_at", -1).limit(200)
    return {
        "invites": [migration_invites.public_invite(d) for d in docs],
        "inbound_enabled": bool(settings.migration.inbound_enabled),
        "defaults": {
            "single_use_ttl_hours": settings.migration.invite_single_use_ttl_hours,
            "lineage_ttl_days": settings.migration.invite_lineage_ttl_days,
            "max_ttl_days": settings.migration.invite_max_ttl_days,
            "lock_on_import": True,
        },
    }


@invites_router.post("", status_code=201)
@invites_router.post("/", status_code=201, include_in_schema=False)
def create_invite(body: InviteCreate, current_user: User = Depends(get_current_user)) -> dict:
    """Issue an invite. The answer is the only time the code is shown."""
    _require_admin(current_user)
    if not settings.migration.inbound_enabled:
        raise HTTPException(
            status_code=409,
            detail="Receiving projects is disabled here (DEPICTIO_MIGRATION_INBOUND_ENABLED)",
        )
    try:
        doc, code = migration_invites.create_invite(
            policy=body.policy,
            lock_on_import=body.lock_on_import,
            expires_in_hours=body.expires_in_hours,
            note=body.note,
            created_by_id=str(current_user.id),
            created_by_email=getattr(current_user, "email", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**migration_invites.public_invite(doc), "code": code}


@invites_router.post("/{invite_id}/revoke")
def revoke_invite(invite_id: str, current_user: User = Depends(get_current_user)) -> dict:
    """Stop an invite from accepting anything, including status reads."""
    _require_admin(current_user)
    oid = _oid(invite_id)
    doc = migration_invites.revoke_invite(oid, str(current_user.id))
    if doc is None:
        existing = migration_invites._col().find_one({"_id": oid})
        if not existing:
            raise HTTPException(status_code=404, detail="Invite not found")
        raise HTTPException(status_code=409, detail="Invite is already revoked")
    return migration_invites.public_invite(migration_invites._col().find_one({"_id": oid}) or doc)
