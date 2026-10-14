"""Shared dependencies and helpers for the groups management router."""

from fastapi import Depends, HTTPException
from pydantic import ValidationError

from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.users import Group, User


async def require_authenticated_user(current_user: User = Depends(get_current_user)) -> User:
    """Any authenticated NON-anonymous user.

    Anonymous sessions can hold valid tokens in public/single-user modes, so
    ``get_current_user`` alone is not enough — group management is explicitly
    closed to them.
    """
    if getattr(current_user, "is_anonymous", False):
        raise HTTPException(
            status_code=403, detail="Anonymous users cannot access group management."
        )
    return current_user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Sysadmin-only dependency (anonymous callers are rejected outright)."""
    if getattr(current_user, "is_anonymous", False) or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return current_user


def assert_group_admin_or_sysadmin(group_doc: dict, user) -> None:
    """Raise 403 unless ``user`` is a sysadmin or a group admin of ``group_doc``."""
    if getattr(user, "is_admin", False):
        return
    if any(str(admin_id) == str(user.id) for admin_id in group_doc.get("admin_ids") or []):
        return
    raise HTTPException(
        status_code=403,
        detail="Sysadmin or group admin privileges are required for this group.",
    )


def sanitize_group_description(value: str | None) -> str | None:
    """Sanitize a description through the MongoModel validator.

    Raw pymongo updates bypass pydantic, so re-run the exact sanitizer the
    persisted ``Group`` model uses (single source of truth, no duplicated
    bleach/escape logic) via a throwaway instance.
    """
    try:
        return Group(name="_sanitize_", description=value).description
    except ValidationError as exc:
        first_error = exc.errors()[0].get("msg", "invalid value") if exc.errors() else str(exc)
        raise HTTPException(status_code=400, detail=f"Invalid description: {first_error}")
