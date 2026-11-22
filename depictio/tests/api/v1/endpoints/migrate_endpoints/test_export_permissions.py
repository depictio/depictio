"""Who may export a project, and whose emails a bundle carries.

A bundle is a full copy of a project's data, so exporting needs at least editor
access; a non-admin's bundle keeps user ids but no other user's email address.
"""

from __future__ import annotations

import asyncio
import json
import os
import zipfile
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.migrate_endpoints import routes
from depictio.api.v1.endpoints.migrate_endpoints.routes import MigrateExportRequest
from depictio.api.v1.services import project_bundle
from depictio.models.models.users import UserBase

from .conftest import COLLECTIONS, FakeS3, make_db, seed_source_project
from .test_bundle_roundtrip import _admin


def _user(email: str, **flags) -> UserBase:
    return UserBase(id=ObjectId(), email=email, **flags)


@pytest.fixture
def source():
    db = make_db()
    ids = seed_source_project(db)
    editor_id = db.projects_collection.find_one({"_id": ids["project_id"]})["permissions"][
        "editors"
    ][0]["_id"]
    ids["editor_id"] = editor_id
    return db, ids, FakeS3()


def _export_as(
    source, user, monkeypatch, *, project_id=None, target_s3_config=None, public=True
) -> dict:
    """Run the real export route as ``user`` and return the bundled documents.

    Public mode by default: that is where non-admins may export at all.
    """
    db, ids, s3 = source
    monkeypatch.setattr(routes.settings.auth, "public_mode", public)
    patches = [patch.object(project_bundle, "_db", lambda: db)]
    patches += [patch.object(routes, a, getattr(db, a)) for a in COLLECTIONS if hasattr(routes, a)]
    patches.append(patch.object(routes, "_instance_s3_client", lambda: s3))
    # Groups live outside the mongomock database this folder wires in.
    patches.append(patch.object(routes, "get_user_group_ids", lambda uid: []))
    monkeypatch.setattr(routes.settings.s3, "bucket", "src-bucket")
    for p in patches:
        p.start()
    try:
        response = asyncio.run(
            routes.export_project(
                MigrateExportRequest(
                    project_id=str(project_id or ids["project_id"]),
                    mode="metadata",
                    target_s3_config=target_s3_config,
                ),
                current_user=user,
            )
        )
        with zipfile.ZipFile(response.path) as zf:
            data = json.loads(zf.read("bundle.json"))
        os.unlink(response.path)
        return data
    finally:
        for p in reversed(patches):
            p.stop()


def _project_perms(data: dict) -> dict:
    return data["projects"][0]["permissions"]


# ---------------------------------------------------------------------------
# Who gets a bundle
# ---------------------------------------------------------------------------


def test_anonymous_export_is_403(source, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _export_as(source, _user("anon@example.org", is_anonymous=True), monkeypatch)
    assert exc.value.status_code == 403
    assert "Only owners and editors" in str(exc.value.detail)


def test_viewer_export_is_403(source, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _export_as(source, _user("viewer@target.org"), monkeypatch)
    assert exc.value.status_code == 403


def test_project_a_non_admin_cannot_see_is_404(source, monkeypatch):
    db, ids, s3 = source
    private_id = ObjectId()
    db.projects_collection.insert_one(
        {
            "_id": private_id,
            "name": "Private",
            "is_public": False,
            "permissions": {"owners": [{"_id": ObjectId(), "email": "someone@x.org"}]},
        }
    )
    with pytest.raises(HTTPException) as exc:
        _export_as(source, _user("viewer@target.org"), monkeypatch, project_id=private_id)
    assert exc.value.status_code == 404


def test_non_admin_cannot_pick_a_target_s3_config(source, monkeypatch):
    _, ids, _ = source
    owner = _user("author@source.org")
    with pytest.raises(HTTPException) as exc:
        _export_as(
            source,
            owner,
            monkeypatch,
            target_s3_config={"bucket": "attacker-bucket"},
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Whose emails travel in the bundle
# ---------------------------------------------------------------------------


def test_admin_export_carries_every_email(source, monkeypatch):
    data = _export_as(source, _admin("admin@target.org"), monkeypatch)
    perms = _project_perms(data)
    assert perms["owners"][0]["email"] == "author@source.org"
    assert perms["editors"][0]["email"] == "editor@source.org"


def test_owner_export_keeps_ids_and_own_email_only(source, monkeypatch):
    _, ids, _ = source
    owner = UserBase(id=ids["owner_id"], email="author@source.org")
    data = _export_as(source, owner, monkeypatch)
    perms = _project_perms(data)
    # The exporter's own entry is intact.
    assert perms["owners"][0]["_id"] == str(ids["owner_id"])
    assert perms["owners"][0]["email"] == "author@source.org"
    # The editor keeps their id, not their address.
    assert perms["editors"][0]["_id"] == str(ids["editor_id"])
    assert "email" not in perms["editors"][0]
    # The wildcard stays a wildcard.
    assert perms["viewers"] == ["*"]
    # Dashboards carry the same scrubbed permissions.
    dash = next(d for d in data["dashboards"] if d["is_main_tab"])
    assert "email" not in dash["permissions"]["editors"][0]


def test_editor_export_keeps_own_email_only(source, monkeypatch):
    _, ids, _ = source
    editor = UserBase(id=ids["editor_id"], email="editor@source.org")
    data = _export_as(source, editor, monkeypatch)
    perms = _project_perms(data)
    assert perms["editors"][0]["email"] == "editor@source.org"
    assert perms["owners"][0]["_id"] == str(ids["owner_id"])
    assert "email" not in perms["owners"][0]


def test_standard_instance_export_stays_admin_only(source, monkeypatch):
    """Outside public mode even the project's owner gets 403: export is an admin tool."""
    db, ids, _ = source
    owner_id = db.projects_collection.find_one({"_id": ids["project_id"]})["permissions"]["owners"][
        0
    ]["_id"]
    owner = UserBase(id=owner_id, email="owner@example.org")
    with pytest.raises(HTTPException) as exc:
        _export_as(source, owner, monkeypatch, public=False)
    assert exc.value.status_code == 403
    assert _export_as(source, _admin("admin@target.org"), monkeypatch, public=False)
