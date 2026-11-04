"""Approving a pushed project: data first, documents last, lock and owner decided here (#1303)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.migrate_endpoints import requests_routes
from depictio.api.v1.services import migration_import
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now

from .push_helpers import admin, approve, build_world, manifest_zip, push


@pytest.fixture
def world(monkeypatch, target_db, captures):
    return build_world(monkeypatch, target_db)


def _request(world, request_id):
    return world.db.migration_requests_collection.find_one({"_id": ObjectId(request_id)})


def _project(world):
    return world.db.projects_collection.find_one({"_id": world.ids["project_id"]})


def _staged(world):
    return [
        k for k in world.s3.buckets.get("tgt-bucket", {}) if k.startswith("_migration_staging/")
    ]


def test_approve_with_an_existing_owner_by_email_case_insensitive(world):
    owner = ObjectId()
    world.db.users_collection.insert_one({"_id": owner, "email": "Author@Source.org"})
    out = push(world.payload, world.source, email="AUTHOR@source.ORG")
    result = approve(out["request_id"], admin())
    assert result["status"] == "importing"

    doc = _request(world, out["request_id"])
    assert doc["status"] == "imported", doc.get("result")
    project = _project(world)
    assert [o["_id"] for o in project["permissions"]["owners"]] == [owner]
    assert "pending_owner_email" not in project
    assert doc["result"]["owner_id"] == str(owner) and doc["result"]["pending_owner_email"] is None
    # Data landed under the target bucket; the staged bundle is gone.
    assert world.s3.buckets["tgt-bucket"][f"{world.ids['table_dc']}/part-0.parquet"] == b"rows"
    assert _staged(world) == []
    # Source-local shares are dropped, the bundle's visibility is not taken.
    assert project["permissions"]["editors"] == []
    assert project["is_public"] is False
    hop = project["provenance"]["imported_from"][-1]
    assert hop["via"] == "push" and hop["source_instance"] == "lab"
    assert hop["migration_request_id"] == out["request_id"]


def test_an_unknown_requester_is_parked_on_the_approving_admin(world):
    out = push(world.payload, world.source, email="New.Person@Source.org")
    boss = admin()
    approve(out["request_id"], boss)
    project = _project(world)
    assert [o["_id"] for o in project["permissions"]["owners"]] == [boss.id]
    assert project["pending_owner_email"] == "new.person@source.org"
    assert _request(world, out["request_id"])["result"]["pending_owner_email"] == (
        "new.person@source.org"
    )


def test_the_lock_covers_the_imported_dashboards(world):
    out = push(world.payload, world.source)
    boss = admin()
    approve(out["request_id"], boss, lock=True)
    lock = _project(world)["published_lock"]
    assert lock["source"] == "migration" and lock["migration_request_id"] == out["request_id"]
    assert sorted(lock["dashboard_ids"]) == sorted(
        [str(world.ids["main_dash"]), str(world.ids["child_dash"])]
    )
    assert lock["locked_by_email"] == boss.email
    assert _request(world, out["request_id"])["result"]["locked"] is True


def test_no_lock_when_unticked_and_make_public_cascades(world):
    out = push(world.payload, world.source)
    approve(out["request_id"], admin(), lock=False, make_public=True)
    project = _project(world)
    assert "published_lock" not in project
    assert project["is_public"] is True
    assert all(d["is_public"] for d in world.db.dashboards_collection.find({}))
    result = _request(world, out["request_id"])["result"]
    assert result["locked"] is False and result["made_public"] is True


def test_lock_defaults_to_the_instance_setting(world, monkeypatch):
    monkeypatch.setattr(settings.migration, "lock_imported_default", True)
    out = push(world.payload, world.source)
    approve(out["request_id"], admin())
    assert _project(world)["published_lock"]


def test_a_repush_adds_an_import_version_and_keeps_a_visitors_copy(world, captures):
    first = push(world.payload, world.source)
    approve(first["request_id"], admin(), lock=True)
    copy_id = ObjectId()
    world.db.dashboards_collection.insert_one(
        {
            "_id": copy_id,
            "dashboard_id": copy_id,
            "project_id": world.ids["project_id"],
            "is_main_tab": True,
        }
    )
    captures.clear()

    second = push(world.payload, world.source)
    approve(second["request_id"], admin(), lock=False)

    assert _request(world, second["request_id"])["status"] == "imported"
    kinds = [c[1] for c in captures]
    assert "import" in kinds and kinds.index("explicit") < kinds.index("import")
    assert any("Migrated from lab" in (c[2] or "") for c in captures)
    assert world.db.dashboards_collection.find_one({"_id": copy_id}) is not None
    project = _project(world)
    assert "published_lock" not in project, "re-push with lock off unlocks"
    # The chain is the bundle's own plus this import: the latest hop is the second request.
    assert (
        project["provenance"]["imported_from"][-1]["migration_request_id"] == (second["request_id"])
    )


def test_server_side_copy_moves_delta_log_last(monkeypatch, target_db, captures):
    world = build_world(monkeypatch, target_db, allowed_source_buckets=["src-bucket"])
    bundle = manifest_zip(world.payload, world.s3)
    out = push(bundle, world.source, mode="server_side_copy")
    assert out["status"] == "pending"
    approve(out["request_id"], admin())
    doc = _request(world, out["request_id"])
    assert doc["status"] == "imported", doc.get("result")
    assert world.s3.copy_log and world.s3.copy_log[-1].endswith("_delta_log/00000.json")
    assert world.s3.buckets["tgt-bucket"][f"{world.ids['table_dc']}/part-0.parquet"] == b"rows"
    assert doc["result"]["s3_objects"] == 3


def test_a_changed_source_object_fails_the_import_and_writes_no_documents(
    monkeypatch, target_db, captures
):
    world = build_world(monkeypatch, target_db, allowed_source_buckets=["src-bucket"])
    out = push(manifest_zip(world.payload, world.s3), world.source, mode="server_side_copy")
    # The source rewrites an object after the bundle was built: its etag moves on.
    world.s3.put("src-bucket", f"{world.ids['table_dc']}/part-0.parquet", b"changed under us")

    approve(out["request_id"], admin())

    doc = _request(world, out["request_id"])
    assert doc["status"] == "failed"
    assert "part-0.parquet" in doc["result"]["error"]
    assert world.db.projects_collection.count_documents({}) == 0
    assert world.db.dashboards_collection.count_documents({}) == 0
    assert captures == []
    assert _staged(world) == []


def test_a_server_side_bucket_that_is_no_longer_allowed_fails(monkeypatch, target_db, captures):
    world = build_world(monkeypatch, target_db, allowed_source_buckets=["src-bucket"])
    out = push(manifest_zip(world.payload, world.s3), world.source, mode="server_side_copy")
    monkeypatch.setattr(world.source, "allowed_source_buckets", [])
    approve(out["request_id"], admin())
    assert _request(world, out["request_id"])["status"] == "failed"
    assert world.db.projects_collection.count_documents({}) == 0


def test_a_bundle_that_stopped_validating_fails_without_writing(world):
    out = push(world.payload, world.source)
    world.db.projects_collection.insert_one(
        {"_id": ObjectId(), "name": "Iris published"}  # another project took the name
    )
    approve(out["request_id"], admin())
    doc = _request(world, out["request_id"])
    assert doc["status"] == "failed" and "named" in doc["result"]["error"]
    assert world.db.projects_collection.count_documents({}) == 1


def test_a_data_write_failure_leaves_mongo_alone(world, monkeypatch):
    out = push(world.payload, world.source)
    monkeypatch.setattr(
        migration_import.project_bundle, "restore_s3_entries", lambda *a, **k: (0, ["boom"])
    )
    approve(out["request_id"], admin())
    doc = _request(world, out["request_id"])
    assert doc["status"] == "failed" and "boom" in doc["result"]["error"]
    assert world.db.projects_collection.count_documents({}) == 0


def test_an_unexpected_error_is_recorded_not_raised(world, monkeypatch):
    out = push(world.payload, world.source)

    def explode(*a, **k):
        raise RuntimeError("kaput")

    monkeypatch.setattr(migration_import.project_bundle, "prepare_docs_for_import", explode)
    approve(out["request_id"], admin())
    doc = _request(world, out["request_id"])
    assert doc["status"] == "failed" and "kaput" in doc["result"]["error"]


def test_reject_deletes_the_staged_bundle(world):
    out = push(world.payload, world.source)
    assert len(_staged(world)) == 1
    res = asyncio.run(
        requests_routes.reject_request(
            out["request_id"], requests_routes.RejectBody(reason="not now"), current_user=admin()
        )
    )
    assert res["status"] == "rejected"
    doc = _request(world, out["request_id"])
    assert doc["decision"]["reason"] == "not now" and doc["decision"]["action"] == "reject"
    assert _staged(world) == []


def test_a_decision_is_taken_once(world):
    out = push(world.payload, world.source)
    approve(out["request_id"], admin())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            requests_routes.approve_request(
                out["request_id"], BackgroundTasks(), None, current_user=admin()
            )
        )
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            requests_routes.reject_request(
                out["request_id"], requests_routes.RejectBody(reason="x"), current_user=admin()
            )
        )
    assert exc.value.status_code == 409


def test_only_admins_reach_the_queue(world):
    out = push(world.payload, world.source)
    plain = admin()
    plain.is_admin = False
    for call in (
        requests_routes.list_requests(None, current_user=plain),
        requests_routes.get_request(out["request_id"], current_user=plain),
        requests_routes.approve_request(
            out["request_id"], BackgroundTasks(), None, current_user=plain
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call)
        assert exc.value.status_code == 403


def test_queue_listing_detail_and_revalidate(world):
    out = push(world.payload, world.source)
    listing = asyncio.run(requests_routes.list_requests("pending", current_user=admin()))
    [row] = listing["requests"]
    assert row["id"] == out["request_id"] and row["conflict"] == "none"
    assert row["requester"]["email"] == "author@source.org" and row["error_count"] == 0
    assert (
        asyncio.run(requests_routes.list_requests("imported", current_user=admin()))["requests"]
        == []
    )

    detail = asyncio.run(requests_routes.get_request(out["request_id"], current_user=admin()))
    assert detail["id"] == out["request_id"] and "_id" not in detail
    assert detail["requester_has_account"] is False
    assert detail["report"]["project_name"] == "Iris published"
    assert "lock_imported_default" in detail and detail["target_depictio_version"]

    # A project took the name since the upload: revalidate says so and stores it.
    world.db.projects_collection.insert_one({"_id": ObjectId(), "name": "Iris published"})
    res = asyncio.run(requests_routes.revalidate_request(out["request_id"], current_user=admin()))
    assert res["report"]["errors"]
    assert _request(world, out["request_id"])["report"]["errors"]


def test_stale_pending_requests_expire_and_lose_their_bundle(world):
    old = push(world.payload, world.source)
    # A second project's request, young enough to survive.
    world.db.migration_requests_collection.insert_one(
        {
            "_id": ObjectId(),
            "status": "pending",
            "source_name": "lab",
            "project_id": "x",
            "created_at": utc_now().strftime(TIMESTAMP_FORMAT),
        }
    )
    stale = (utc_now() - timedelta(days=settings.migration.pending_ttl_days + 1)).strftime(
        TIMESTAMP_FORMAT
    )
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(old["request_id"])}, {"$set": {"created_at": stale}}
    )
    assert migration_import.expire_stale_requests() == 1
    assert _request(world, old["request_id"])["status"] == "expired"
    assert _staged(world) == []
    assert migration_import.expire_stale_requests() == 0
    assert world.db.migration_requests_collection.count_documents({"status": "pending"}) == 1
