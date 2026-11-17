"""Deferred project ownership: claiming projects parked on an email address (#1303).

An approved push whose requester has no account here is owned by the approving
admin, with the requester's address parked on the project as
``pending_owner_email``. Like a group's pending P.I. (``pending_pi``), the
designation is applied when that address first proves it is theirs: an SSO
sign-in (the IdP verified the email) or an admin-created account. Password
self-registration is deliberately not a claim path: it does not verify the
address, so anyone could register an email and take over a parked project.

Import-light (logger only at module level) for the same reason as
``pending_pi``: the user-creation modules that call it sit in an import cycle.
"""

from __future__ import annotations

import re
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.models.timestamps import utc_now_str


def _db():
    """The live collections, imported late so tests can patch this one place."""
    from depictio.api.v1 import db

    return db


def _owner_entry(user: Any) -> dict[str, Any]:
    return {"_id": ObjectId(str(user.id)), "email": user.email}


def _imported_dashboard_ids(project: dict[str, Any]) -> list[ObjectId]:
    """Dashboards any import wrote; a visitor's copy keeps its own owner."""
    ids: list[ObjectId] = []
    hops = (project.get("provenance") or {}).get("imported_from") or []
    for hop in hops:
        if not isinstance(hop, dict):
            continue
        for raw in hop.get("dashboard_ids") or []:
            try:
                ids.append(ObjectId(str(raw)))
            except Exception:  # noqa: BLE001 — a malformed id cannot match a dashboard
                continue
    return ids


async def claim_pending_project_ownership(user: Any) -> list[str]:
    """Make ``user`` the owner of every project parked on their email.

    The owner list is *replaced* (the placeholder admin was never the intended
    owner); editors and viewers are left alone. The imported dashboards carry a
    copy of the project's permissions, so their owners follow. Idempotent: a
    claimed project no longer carries the email. Returns the claimed project
    names.
    """
    email = (getattr(user, "email", None) or "").strip()
    if not email or getattr(user, "id", None) is None:
        return []

    db = _db()
    pattern = {"$regex": f"^{re.escape(email)}$", "$options": "i"}
    claimed: list[str] = []
    for project in list(db.projects_collection.find({"pending_owner_email": pattern})):
        entry = _owner_entry(user)
        db.projects_collection.update_one(
            {"_id": project["_id"]},
            {
                "$set": {"permissions.owners": [entry], "last_modified": utc_now_str()},
                "$unset": {"pending_owner_email": ""},
            },
        )
        dashboard_ids = _imported_dashboard_ids(project)
        if dashboard_ids:
            db.dashboards_collection.update_many(
                {"_id": {"$in": dashboard_ids}}, {"$set": {"permissions.owners": [entry]}}
            )
        claimed.append(project.get("name", str(project["_id"])))
        logger.info(f"Pending owner claimed: {email} now owns project '{claimed[-1]}'")
    return claimed


async def claim_pending_project_ownership_quietly(user: Any) -> None:
    """The claim as every login path calls it: a failure is logged, never raised."""
    try:
        await claim_pending_project_ownership(user)
    except Exception as exc:  # noqa: BLE001 — an unclaimed project stays parked for the next login
        logger.error(
            f"Pending project-owner claim failed for {getattr(user, 'email', '?')} "
            f"(projects stay parked): {exc}"
        )
