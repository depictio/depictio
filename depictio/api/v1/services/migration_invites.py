"""Invite codes: an admin of the target lets a source push without a pairing key (#1303).

The admin creates an invite and reads its code once; the source's user pastes
the target URL and the code. Only ``sha256(code)`` is stored, the lookup goes
through that hash, and the stored hash is compared again in constant time.

An accepted push consumes the invite atomically (``claim_invite``): a
``single_use`` invite is spent, a ``lineage`` invite binds to the project it
first imported and keeps accepting pushes of that project until it expires.
Nothing here works while ``DEPICTIO_MIGRATION_INBOUND_ENABLED`` is off.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.config import settings
from depictio.models.models.migration import InvitePolicy, MigrationInvite
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now, utc_now_str

INVITE_HEADER = "X-Depictio-Invite-Code"
#: Prefix of the source name recorded for a push made with an invite.
INVITE_SOURCE_PREFIX = "invite:"

# Crockford base32 without I, L, O, U: nothing a reader confuses when copying.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_GROUPS, _GROUP_LEN = 6, 4  # 24 symbols = 120 bits
_CODE_SHAPE = re.compile(rf"^[{_ALPHABET}]{{{_GROUPS * _GROUP_LEN}}}$")


def _db():
    from depictio.api.v1.services import migration_import

    return migration_import._db()


def _col():
    return _db().migration_invites_collection


def generate_code() -> str:
    """A fresh code, e.g. ``7KQ2-M9XD-...`` (6 groups of 4)."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(_GROUPS * _GROUP_LEN))
    return "-".join(raw[i : i + _GROUP_LEN] for i in range(0, len(raw), _GROUP_LEN))


def normalize_code(code: str | None) -> str | None:
    """Uppercase, without spaces or dashes; None unless it has the shape of a code."""
    if not code or not isinstance(code, str):
        return None
    cleaned = re.sub(r"[\s-]", "", code).upper()
    return cleaned if _CODE_SHAPE.match(cleaned) else None


def hash_code(normalized: str) -> str:
    return hashlib.sha256(normalized.encode()).hexdigest()


def invite_source_name(invite_id: Any) -> str:
    return f"{INVITE_SOURCE_PREFIX}{invite_id}"


def _ts(dt: datetime) -> str:
    return dt.strftime(TIMESTAMP_FORMAT)


def default_ttl(policy: InvitePolicy) -> timedelta:
    cfg = settings.migration
    if policy == "lineage":
        return timedelta(days=cfg.invite_lineage_ttl_days)
    return timedelta(hours=cfg.invite_single_use_ttl_hours)


def max_ttl() -> timedelta:
    return timedelta(days=settings.migration.invite_max_ttl_days)


def create_invite(
    *,
    policy: InvitePolicy,
    lock_on_import: bool,
    expires_in_hours: int | None,
    note: str | None,
    created_by_id: str,
    created_by_email: str | None,
) -> tuple[dict[str, Any], str]:
    """Store a new invite; return (stored document, code). The code is not stored."""
    ttl = timedelta(hours=expires_in_hours) if expires_in_hours else default_ttl(policy)
    if ttl > max_ttl():
        raise ValueError(
            f"an invite may live at most {settings.migration.invite_max_ttl_days} days"
        )
    code = generate_code()
    normalized = normalize_code(code)
    assert normalized is not None
    invite = MigrationInvite(
        code_sha256=hash_code(normalized),
        code_hint=normalized[-4:],
        policy=policy,
        lock_on_import=lock_on_import,
        note=(note or "").strip()[:500] or None,
        created_by_id=created_by_id,
        created_by_email=created_by_email,
        expires_at=_ts(utc_now() + ttl),
    )
    doc = invite.model_dump(exclude={"id"})
    doc["_id"] = _col().insert_one(dict(doc)).inserted_id
    return doc, code


def invite_state(doc: dict[str, Any], now: str | None = None) -> str:
    """``active``, ``used`` (single-use, spent), ``expired`` or ``revoked``."""
    now = now or utc_now_str()
    if doc.get("revoked_at"):
        return "revoked"
    if doc.get("policy", "single_use") == "single_use" and doc.get("used_at"):
        return "used"
    if (doc.get("expires_at") or "") <= now:
        return "expired"
    return "active"


def find_invite(code: str | None) -> dict[str, Any] | None:
    """The invite this code names, whatever its state; None for an unknown code.

    The lookup is by hash (the hash of a secret tells nothing about the secret),
    and the stored hash is compared once more in constant time.
    """
    normalized = normalize_code(code)
    # Hash even a malformed code, so both paths cost the same.
    presented = hash_code(normalized or (code or "")[:64])
    if normalized is None:
        return None
    doc = _col().find_one({"code_sha256": presented})
    if not doc or not hmac.compare_digest(str(doc.get("code_sha256", "")), presented):
        return None
    return doc


def lineage_error(invite: dict[str, Any], project_id: str | None) -> str | None:
    """Why this invite cannot carry ``project_id``, or None."""
    bound = invite.get("lineage_project_id")
    if invite.get("policy") == "lineage" and bound and str(bound) != str(project_id):
        name = invite.get("lineage_project_name") or bound
        return f"this invite is bound to the project {name!r} it first imported"
    return None


def claim_invite(
    invite_id: Any, *, project_id: str, project_name: str | None, request_id: ObjectId
) -> dict[str, Any] | None:
    """Consume the invite for one accepted push, atomically; None when it no longer can.

    Two uploads racing with one single-use code both pass validation; only one
    of them wins this update.
    """
    now = utc_now_str()
    doc = _col().find_one({"_id": invite_id})
    if not doc:
        return None
    query: dict[str, Any] = {
        "_id": invite_id,
        "revoked_at": None,
        "expires_at": {"$gt": now},
    }
    update: dict[str, Any] = {
        "$set": {"last_used_at": now},
        "$inc": {"use_count": 1},
        "$push": {"request_ids": str(request_id)},
    }
    if doc.get("policy") == "lineage":
        query["$or"] = [{"lineage_project_id": None}, {"lineage_project_id": str(project_id)}]
        update["$set"]["lineage_project_id"] = str(project_id)
        update["$set"]["lineage_project_name"] = project_name
        if not doc.get("used_at"):
            update["$set"]["used_at"] = now
    else:
        query["used_at"] = None
        update["$set"]["used_at"] = now
    return _col().find_one_and_update(query, update)


def revoke_invite(invite_id: ObjectId, by_id: str) -> dict[str, Any] | None:
    return _col().find_one_and_update(
        {"_id": invite_id, "revoked_at": None},
        {"$set": {"revoked_at": utc_now_str(), "revoked_by_id": by_id}},
    )


def public_invite(doc: dict[str, Any]) -> dict[str, Any]:
    """An invite as the admin UI shows it: never the code or its hash."""
    return {
        "id": str(doc["_id"]),
        "state": invite_state(doc),
        "policy": doc.get("policy", "single_use"),
        "lock_on_import": bool(doc.get("lock_on_import", True)),
        "note": doc.get("note"),
        "code_hint": doc.get("code_hint"),
        "created_at": doc.get("created_at"),
        "created_by_email": doc.get("created_by_email"),
        "expires_at": doc.get("expires_at"),
        "revoked_at": doc.get("revoked_at"),
        "used_at": doc.get("used_at"),
        "last_used_at": doc.get("last_used_at"),
        "use_count": int(doc.get("use_count") or 0),
        "request_ids": [str(r) for r in doc.get("request_ids") or []],
        "lineage_project_id": doc.get("lineage_project_id"),
        "lineage_project_name": doc.get("lineage_project_name"),
    }
