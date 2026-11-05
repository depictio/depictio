"""Imports a restart interrupted: marked failed and retryable, bundle kept (#1303 slice 2)."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.migrate_endpoints import requests_routes
from depictio.api.v1.services import migration_import
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now

from .invite_helpers import ADMIN_ID, admin_user, invite_world, make_invite, plain_user, source_for
from .push_helpers import admin, push


@pytest.fixture
def world(monkeypatch, target_db, captures):
    return invite_world(monkeypatch, target_db)


def _stamp(**ago) -> str:
    return (utc_now() - timedelta(**ago)).strftime(TIMESTAMP_FORMAT)


def _doc(world, request_id):
    return world.db.migration_requests_collection.find_one({"_id": ObjectId(request_id)})


def _staged(world):
    return [
        k for k in world.s3.buckets.get("tgt-bucket", {}) if k.startswith("_migration_staging/")
    ]


def _stuck_importing(world, *, minutes_ago=120, lock=True):
    """A pairing-key request that an approval moved to ``importing`` and a restart killed."""
    out = push(world.payload, world.source)
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(out["request_id"])},
        {
            "$set": {
                "status": "importing",
                "updated_at": _stamp(minutes=minutes_ago),
                "decision": {
                    "action": "approve",
                    "by_id": ADMIN_ID,
                    "by_email": "admin@target.org",
                    "at": _stamp(minutes=minutes_ago),
                    "lock": lock,
                    "make_public": False,
                },
            }
        },
    )
    return out["request_id"]


def _retry(request_id, user=None):
    tasks = BackgroundTasks()
    out = asyncio.run(
        requests_routes.retry_request(request_id, tasks, current_user=user or admin_user())
    )
    for task in tasks.tasks:
        task.func(*task.args, **task.kwargs)
    return out, tasks


def test_an_old_importing_request_becomes_failed_and_retryable_with_its_bundle(world):
    rid = _stuck_importing(world)
    before = _staged(world)
    assert before

    assert migration_import.recover_interrupted_requests() == 1

    doc = _doc(world, rid)
    assert doc["status"] == "failed" and doc["retryable"] is True
    assert doc["result"]["error"] == "interrupted by a restart"
    assert doc["updated_at"] > _stamp(minutes=10), "the failure is stamped now"
    assert _staged(world) == before, "the bundle is kept so an admin can retry"
    # The admin list says it can be retried.
    row = requests_routes._summary(doc)
    assert row["retryable"] is True and row["error"] == "interrupted by a restart"
    # And a second sweep has nothing left to do.
    assert migration_import.recover_interrupted_requests() == 0


def test_recent_importing_requests_and_other_statuses_are_left_alone(world):
    recent = _stuck_importing(world, minutes_ago=5)
    pending = push(world.payload, world.source)["request_id"]
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(pending)}, {"$set": {"updated_at": _stamp(hours=5)}}
    )
    assert migration_import.recover_interrupted_requests() == 0
    assert _doc(world, recent)["status"] == "importing" and not _doc(world, recent).get("retryable")
    assert _doc(world, pending)["status"] == "pending"


def test_the_recovery_window_is_a_setting(world, monkeypatch):
    rid = _stuck_importing(world, minutes_ago=10)
    assert migration_import.recover_interrupted_requests() == 0
    monkeypatch.setattr(settings.migration, "interrupted_after_minutes", 5)
    assert migration_import.recover_interrupted_requests() == 1
    assert _doc(world, rid)["status"] == "failed"


def test_retry_runs_the_import_again_with_the_original_decision(world):
    rid = _stuck_importing(world, lock=False)
    migration_import.recover_interrupted_requests()

    out, tasks = _retry(rid)
    assert out == {"id": rid, "status": "importing"}
    assert tasks.tasks[0].args[0] == rid
    doc = _doc(world, rid)
    assert doc["status"] == "imported", doc.get("result")
    assert doc["retryable"] is False
    project = world.db.projects_collection.find_one({"_id": world.ids["project_id"]})
    assert project is not None and not project.get("published_lock"), "the decision said no lock"
    assert [str(o["_id"]) for o in project["permissions"]["owners"]] == [ADMIN_ID]
    assert _staged(world) == [], "the bundle is deleted once imported"


def test_retry_keeps_the_lock_the_decision_asked_for(world):
    rid = _stuck_importing(world, lock=True)
    migration_import.recover_interrupted_requests()
    _retry(rid)
    project = world.db.projects_collection.find_one({"_id": world.ids["project_id"]})
    assert project["published_lock"]["migration_request_id"] == rid
    assert project["published_lock"]["locked_by_id"] == ADMIN_ID


def test_retry_of_an_interrupted_invite_import(world):
    doc, code = make_invite()
    out = push(world.payload, source_for(code))
    # Pretend the process died mid-import: wipe what the import wrote.
    world.db.projects_collection.delete_many({})
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(out["request_id"])},
        {"$set": {"status": "importing", "updated_at": _stamp(hours=2)}},
    )
    world.s3.put("tgt-bucket", f"_migration_staging/{out['request_id']}/bundle.zip", world.payload)
    assert migration_import.recover_interrupted_requests() == 1
    _retry(out["request_id"])
    stored = _doc(world, out["request_id"])
    assert stored["status"] == "imported" and stored["credential_type"] == "invite_code"
    assert world.db.projects_collection.count_documents({}) == 1
    # The use count stays at 1: a retry is not another use.
    assert world.db.migration_invites_collection.find_one({"_id": doc["_id"]})["use_count"] == 1


def test_retry_claims_only_once(world):
    rid = _stuck_importing(world)
    migration_import.recover_interrupted_requests()
    first = migration_import.claim_retry(ObjectId(rid))
    assert first is not None and first["decision"]["lock"] is True
    assert migration_import.claim_retry(ObjectId(rid)) is None
    doc = _doc(world, rid)
    assert doc["status"] == "importing" and doc["retryable"] is False


@pytest.mark.parametrize("status", ["pending", "importing", "imported", "rejected", "failed"])
def test_retry_of_anything_not_retryable_is_a_409(world, status):
    out = push(world.payload, world.source)
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(out["request_id"])}, {"$set": {"status": status, "retryable": False}}
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            requests_routes.retry_request(
                out["request_id"], BackgroundTasks(), current_user=admin_user()
            )
        )
    assert exc.value.status_code == 409
    assert _doc(world, out["request_id"])["status"] == status


def test_a_second_retry_after_a_successful_one_is_a_409(world):
    rid = _stuck_importing(world)
    migration_import.recover_interrupted_requests()
    _retry(rid)
    with pytest.raises(HTTPException) as exc:
        _retry(rid)
    assert exc.value.status_code == 409


def test_retry_needs_an_admin_and_an_existing_request(world):
    rid = _stuck_importing(world)
    migration_import.recover_interrupted_requests()
    with pytest.raises(HTTPException) as exc:
        _retry(rid, plain_user())
    assert exc.value.status_code == 403
    assert _doc(world, rid)["status"] == "failed", "a refused retry changes nothing"
    for bad in ("nope", str(ObjectId())):
        with pytest.raises(HTTPException) as exc:
            _retry(bad)
        assert exc.value.status_code == 404


def test_retry_without_a_stored_decision_falls_back_to_the_caller(world):
    out = push(world.payload, world.source)
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(out["request_id"])},
        {"$set": {"status": "failed", "retryable": True}, "$unset": {"decision": ""}},
    )
    boss = admin()
    _, tasks = _retry(out["request_id"], boss)
    approver = tasks.tasks[0].args[1]
    assert approver["id"] == str(boss.id) and approver["email"] == boss.email
    assert tasks.tasks[0].args[2] is settings.migration.lock_imported_default


def test_the_source_sees_an_interrupted_import_as_retryable_without_the_error_text(world):
    from depictio.api.v1.endpoints.migrate_endpoints import inbound_routes

    doc, code = make_invite()
    out = push(world.payload, source_for(code))
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(out["request_id"])}, {"$set": {"status": "importing"}}
    )
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(out["request_id"])}, {"$set": {"updated_at": _stamp(hours=3)}}
    )
    migration_import.recover_interrupted_requests()
    status = asyncio.run(
        inbound_routes.inbound_request_status(out["request_id"], source=out["status_token"])
    )
    assert status["status"] == "failed" and status["retryable"] is True
    assert "interrupted" not in json.dumps(status), "the error text stays on the target"
    assert doc["_id"]
