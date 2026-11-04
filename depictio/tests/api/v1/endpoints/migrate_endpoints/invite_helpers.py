"""Pieces shared by the invite tests (#1303 slice 2): an invite collection on the
target database, a way to issue invites and to authenticate with one."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from bson import ObjectId

from depictio.api.v1.endpoints.migrate_endpoints import inbound_auth
from depictio.api.v1.services import migration_invites

from .push_helpers import KEY, MigS3, build_world, configure_target

ADMIN_ID = str(ObjectId())
ADMIN_EMAIL = "admin@target.org"


def attach_invites(target_db) -> None:
    """The mongomock database has no invite collection until it is added."""
    target_db.migration_invites_collection = target_db.projects_collection.database[
        "migration_invites"
    ]


def bare_target(monkeypatch, target_db):
    """A target with inbound enabled, one pairing-key source, and no bundle."""
    s3 = MigS3()
    attach_invites(target_db)
    return configure_target(monkeypatch, target_db, s3)


def invite_world(monkeypatch, target_db, **source_opts):
    """``build_world`` plus an invite collection."""
    world = build_world(monkeypatch, target_db, **source_opts)
    attach_invites(target_db)
    return world


def make_invite(
    policy: str = "single_use", lock: bool = True, hours: int | None = None, note=None
) -> tuple[dict[str, Any], str]:
    return migration_invites.create_invite(
        policy=policy,  # type: ignore[arg-type]
        lock_on_import=lock,
        expires_in_hours=hours,
        note=note,
        created_by_id=ADMIN_ID,
        created_by_email=ADMIN_EMAIL,
    )


def source_for(code: str):
    """Authenticate the way the dependency does when only an invite code is sent."""
    return inbound_auth.require_inbound_source(None, code)


def admin_user():
    return SimpleNamespace(id=ObjectId(ADMIN_ID), email=ADMIN_EMAIL, is_admin=True)


def plain_user():
    return SimpleNamespace(id=ObjectId(), email="u@target.org", is_admin=False)


__all__ = [
    "ADMIN_EMAIL",
    "ADMIN_ID",
    "KEY",
    "admin_user",
    "attach_invites",
    "bare_target",
    "invite_world",
    "make_invite",
    "plain_user",
    "source_for",
]
