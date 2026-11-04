"""Source side, admin only: the registry of instances this one may push to. (#1303).

Two kinds of target: those the operator declared in the environment (trusted,
read-only here) and those an admin added in the UI (only when
``allow_ui_targets``; SSRF-guarded). The pairing key of a UI target is sealed
with ``encrypt_secret`` and never returned by any route.
"""

from __future__ import annotations

import hashlib
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1.configs.config import settings
from depictio.api.v1.crypto import decrypt_secret, encrypt_secret
from depictio.api.v1.db import migration_targets_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.services.outbound_http import (
    ResolvedTarget,
    TargetURLRejected,
    check_target_url,
)
from depictio.models.models.users import User
from depictio.models.timestamps import utc_now_str

targets_router = APIRouter()

__all__ = ["ResolvedTarget", "list_targets", "resolve_target", "targets_router"]


class TargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)
    pairing_key: str = Field(min_length=32, max_length=512)


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _require_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can manage push targets")


def _ui_public(doc: dict[str, Any], *, with_fingerprint: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "url": doc["url"],
        "source": "ui",
        "credential_type": doc.get("credential_type", "pairing_key"),
    }
    if with_fingerprint:
        try:
            out["key_fingerprint"] = _fingerprint(decrypt_secret(doc["pairing_key_enc"]))
        except Exception:  # noqa: BLE001 - an unreadable key must not hide the target
            out["key_fingerprint"] = None
    return out


def list_targets(*, with_fingerprint: bool) -> list[dict[str, Any]]:
    """Env targets then UI targets, without any key material."""
    out: list[dict[str, Any]] = []
    for t in settings.migration.targets:
        item: dict[str, Any] = {
            "id": f"env:{t.name}",
            "name": t.name,
            "url": t.url,
            "source": "env",
            "credential_type": t.credential_type,
        }
        if with_fingerprint:
            item["key_fingerprint"] = _fingerprint(t.pairing_key.get_secret_value())
        out.append(item)
    out.extend(
        _ui_public(d, with_fingerprint=with_fingerprint)
        for d in migration_targets_collection.find({}).sort("created_at", 1)
    )
    return out


def resolve_target(target_id: str) -> ResolvedTarget:
    """The target with its key in the clear. Raises ``KeyError`` when unknown."""
    if target_id.startswith("env:"):
        name = target_id[4:]
        for t in settings.migration.targets:
            if t.name == name:
                return ResolvedTarget(
                    id=target_id,
                    name=t.name,
                    url=t.url,
                    pairing_key=t.pairing_key.get_secret_value(),
                    trusted=True,
                )
        raise KeyError(target_id)
    if not ObjectId.is_valid(target_id):
        raise KeyError(target_id)
    doc = migration_targets_collection.find_one({"_id": ObjectId(target_id)})
    if not doc:
        raise KeyError(target_id)
    return ResolvedTarget(
        id=target_id,
        name=doc["name"],
        url=doc["url"],
        pairing_key=decrypt_secret(doc["pairing_key_enc"]),
        trusted=False,
    )


@targets_router.get("")
@targets_router.get("/", include_in_schema=False)
def get_targets(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    _require_admin(current_user)
    return {
        "targets": list_targets(with_fingerprint=True),
        "allow_ui_targets": bool(settings.migration.allow_ui_targets),
    }


@targets_router.post("", status_code=201)
@targets_router.post("/", status_code=201, include_in_schema=False)
def create_target(body: TargetCreate, current_user: User = Depends(get_current_user)) -> dict:
    """Add a UI target. Admin only; the URL goes through the SSRF guard."""
    _require_admin(current_user)
    if not settings.migration.allow_ui_targets:
        raise HTTPException(status_code=403, detail="Adding targets in the UI is disabled")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Target name is required")
    try:
        check_target_url(
            body.url,
            trusted=False,
            host_allowlist=list(settings.migration.ui_target_host_allowlist),
        )
    except TargetURLRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    env_names = {t.name for t in settings.migration.targets}
    if name in env_names or migration_targets_collection.find_one({"name": name}):
        raise HTTPException(status_code=409, detail="A target with this name already exists")
    doc = {
        "name": name,
        "url": body.url.strip().rstrip("/"),
        "pairing_key_enc": encrypt_secret(body.pairing_key),
        "credential_type": "pairing_key",
        "created_at": utc_now_str(),
        "created_by_id": str(current_user.id),
    }
    doc["_id"] = migration_targets_collection.insert_one(dict(doc)).inserted_id
    return _ui_public(doc, with_fingerprint=True)


@targets_router.delete("/{target_id}")
def delete_target(target_id: str, current_user: User = Depends(get_current_user)) -> dict:
    _require_admin(current_user)
    if target_id.startswith("env:"):
        raise HTTPException(
            status_code=400, detail="Targets from the environment cannot be deleted here"
        )
    if not ObjectId.is_valid(target_id):
        raise HTTPException(status_code=404, detail="Target not found")
    result = migration_targets_collection.delete_one({"_id": ObjectId(target_id)})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Target not found")
    return {"deleted": True}
