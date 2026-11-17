"""A pushed bundle is checked, parked and queued, never imported (#1303)."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.migrate_endpoints import inbound_routes
from depictio.models.timestamps import utc_now_str

from .push_helpers import SOURCE, build_world, push


@pytest.fixture
def world(monkeypatch, target_db):
    return build_world(monkeypatch, target_db)


def _requests(world):
    return list(world.db.migration_requests_collection.find({}))


def _status(world, request_id, source=None):
    return asyncio.run(
        inbound_routes.inbound_request_status(request_id, source=source or world.source)
    )


def test_info_reports_this_instance(world):
    info = asyncio.run(inbound_routes.inbound_info(source=world.source))
    assert info["s3_bucket"] == "tgt-bucket"
    assert info["s3_endpoint"] == "http://s3:9000"
    assert info["server_side_copy_buckets"] == []


def test_a_valid_bundle_is_staged_and_queued_not_imported(world):
    out = push(world.payload, world.source)
    assert out["status"] == "pending"
    [doc] = _requests(world)
    assert str(doc["_id"]) == out["request_id"]
    assert doc["source_name"] == SOURCE and doc["status"] == "pending"
    assert doc["requester"]["email"] == "author@source.org"
    assert doc["project_name"] == "Iris published"
    bucket, _, key = doc["staging_key"][len("s3://") :].partition("/")
    assert key == f"{settings.migration.staging_prefix}/{out['request_id']}/bundle.zip"
    assert world.s3.buckets[bucket][key] == world.payload
    assert doc["dc_ids"], "the orphan sweep needs the collection ids"
    assert world.db.projects_collection.count_documents({}) == 0, "nothing is imported yet"


def test_a_checksum_mismatch_is_a_400_and_stores_nothing(world):
    with pytest.raises(HTTPException) as exc:
        push(world.payload, world.source, sha="0" * 64)
    assert exc.value.status_code == 400
    assert _requests(world) == []


def test_a_bundle_over_the_cap_is_a_413(monkeypatch, target_db):
    world = build_world(monkeypatch, target_db, max_bundle_bytes=100)
    with pytest.raises(HTTPException) as exc:
        push(world.payload, world.source)
    assert exc.value.status_code == 413
    assert _requests(world) == []


def test_the_daily_quota_is_a_429(monkeypatch, target_db):
    world = build_world(monkeypatch, target_db, max_per_day=1)
    push(world.payload, world.source)
    with pytest.raises(HTTPException) as exc:
        push(world.payload, world.source)
    assert exc.value.status_code == 429


def test_too_many_pending_is_a_429_but_a_repush_replaces(monkeypatch, target_db):
    world = build_world(monkeypatch, target_db, max_pending=1)
    first = push(world.payload, world.source)
    # Same project again: it supersedes the pending one, so it is not "one more".
    second = push(world.payload, world.source)
    assert first["request_id"] != second["request_id"]
    # A different project would be one more.
    world.db.migration_requests_collection.update_one(
        {"_id": ObjectId(second["request_id"])}, {"$set": {"project_id": str(ObjectId())}}
    )
    with pytest.raises(HTTPException) as exc:
        push(world.payload, world.source)
    assert exc.value.status_code == 429


def test_an_invalid_bundle_is_a_422_and_stores_nothing(world):
    # A stray key outside the project's prefixes is an error on the push path.
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(world.payload)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("s3_data/unrelated/file", b"x")
    response = push(out.getvalue(), world.source)
    assert response.status_code == 422
    assert json.loads(response.body)["errors"]
    assert _requests(world) == []
    assert world.s3.buckets.get("tgt-bucket", {}) == {}, "nothing staged"


def test_not_a_zip_is_a_422(world):
    assert push(b"not a zip", world.source).status_code == 422


def test_a_newer_push_supersedes_the_older_pending_one(world):
    first = push(world.payload, world.source)
    second = push(world.payload, world.source)
    old = world.db.migration_requests_collection.find_one({"_id": ObjectId(first["request_id"])})
    assert old["status"] == "superseded" and old["superseded_by"] == second["request_id"]
    assert not any(
        key.endswith(f"{first['request_id']}/bundle.zip")
        for key in world.s3.buckets.get("tgt-bucket", {})
    ), "the superseded bundle is deleted"
    assert _status(world, second["request_id"])["status"] == "pending"


def test_status_is_only_readable_by_the_source_that_pushed(world):
    from depictio.api.v1.configs.settings_models import MigrationInboundSource

    out = push(world.payload, world.source)
    status = _status(world, out["request_id"])
    assert status["project_name"] == "Iris published" and status["result"] is None
    other = MigrationInboundSource(name="intruder", pairing_key="z" * 40)
    with pytest.raises(HTTPException) as exc:
        _status(world, out["request_id"], source=other)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _status(world, "not-an-id")
    assert exc.value.status_code == 404


def test_the_probe_refuses_a_bucket_that_is_not_allowed(monkeypatch, target_db):
    world = build_world(monkeypatch, target_db, allowed_source_buckets=["src-bucket"])
    for bucket in ("other", "tgt-bucket"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                inbound_routes.inbound_probe(
                    inbound_routes.ProbeBody(bucket=bucket, key="a/b"), source=world.source
                )
            )
        assert exc.value.status_code == 400
    ok = asyncio.run(
        inbound_routes.inbound_probe(
            inbound_routes.ProbeBody(
                bucket="src-bucket", key=next(iter(world.s3.buckets["src-bucket"]))
            ),
            source=world.source,
        )
    )
    assert ok == {"readable": True, "error": None}
    missing = asyncio.run(
        inbound_routes.inbound_probe(
            inbound_routes.ProbeBody(bucket="src-bucket", key="nope"), source=world.source
        )
    )
    assert missing["readable"] is False


def _preflight(world, **over):
    body = inbound_routes.PreflightBody(
        project_id=str(world.ids["project_id"]),
        project_name="Iris published",
        requester_email="author@source.org",
        total_bytes=10,
        source_s3_endpoint="http://S3:9000/",
        source_bucket="src-bucket",
        **over,
    )
    return asyncio.run(inbound_routes.inbound_preflight(body, source=world.source))


def test_preflight_picks_the_transfer_mode(monkeypatch, target_db):
    plain = build_world(monkeypatch, target_db)
    assert _preflight(plain)["transfer_mode"] == "inline"
    copy = build_world(monkeypatch, target_db, allowed_source_buckets=["src-bucket"])
    out = _preflight(copy)
    assert out["transfer_mode"] == "server_side_copy"
    assert out["ok"] and out["conflict"] == "none" and out["remaining_today"] > 0


def test_preflight_flags_a_foreign_project_and_a_missing_account(world):
    world.db.projects_collection.insert_one(
        {"_id": world.ids["project_id"], "name": "Iris published", "created": utc_now_str()}
    )
    out = _preflight(world)
    assert out["conflict"] == "foreign" and not out["ok"]
    assert out["requester_has_account"] is False
