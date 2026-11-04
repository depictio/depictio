"""A push made with an invite code: imported at once, consumed atomically (#1303 slice 2)."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.migrate_endpoints import inbound_auth, inbound_routes
from depictio.api.v1.services import migration_invites

from .invite_helpers import ADMIN_EMAIL, ADMIN_ID, invite_world, make_invite, source_for
from .push_helpers import push
from .test_bundle_roundtrip import _export_zip


@pytest.fixture
def world(monkeypatch, target_db, captures):
    return invite_world(monkeypatch, target_db)


def _request(world, request_id):
    return world.db.migration_requests_collection.find_one({"_id": ObjectId(request_id)})


def _invite(world, doc):
    return world.db.migration_invites_collection.find_one({"_id": doc["_id"]})


def _project(world):
    return world.db.projects_collection.find_one({"_id": world.ids["project_id"]})


def _staged(world):
    return [
        k for k in world.s3.buckets.get("tgt-bucket", {}) if k.startswith("_migration_staging/")
    ]


def _status(request_id, source):
    return asyncio.run(inbound_routes.inbound_request_status(request_id, source=source))


# ---------------------------------------------------------------------------
# Single use
# ---------------------------------------------------------------------------


def test_an_invite_push_imports_immediately_and_spends_the_code(world):
    doc, code = make_invite()
    out = push(world.payload, source_for(code))
    assert out["status"] == "importing" and out["status_token"]

    request = _request(world, out["request_id"])
    assert request["status"] == "imported", request.get("result")
    assert request["credential_type"] == "invite_code"
    assert request["invite_id"] == str(doc["_id"])
    assert request["source_name"] == f"invite:{doc['_id']}"
    assert request["source_instance"].endswith("(invite)")
    assert request["decision"]["action"] == "approve"
    assert request["decision"]["by_id"] == ADMIN_ID
    assert request["decision"]["by_email"] == ADMIN_EMAIL
    assert request["decision"]["reason"] == f"invite {doc['_id']}"

    assert _project(world) is not None
    assert world.s3.buckets["tgt-bucket"][f"{world.ids['table_dc']}/part-0.parquet"] == b"rows"
    assert _staged(world) == [], "the staged bundle is gone after the import"

    stored = _invite(world, doc)
    assert migration_invites.invite_state(stored) == "used"
    assert stored["use_count"] == 1 and stored["request_ids"] == [out["request_id"]]
    hop = _project(world)["provenance"]["imported_from"][-1]
    assert hop["migration_request_id"] == out["request_id"]


@pytest.mark.parametrize("lock", [True, False])
def test_the_lock_follows_the_invite(world, lock):
    _, code = make_invite(lock=lock)
    out = push(world.payload, source_for(code))
    project = _project(world)
    assert bool(project.get("published_lock")) is lock
    if lock:
        assert project["published_lock"]["migration_request_id"] == out["request_id"]
        assert project["published_lock"]["locked_by_id"] == ADMIN_ID
    assert _request(world, out["request_id"])["result"]["locked"] is lock
    assert _status(out["request_id"], source_for_reader(code))["result"]["locked"] is lock


def source_for_reader(code):
    return inbound_auth.require_inbound_reader(None, code, None)


def test_the_invite_never_makes_the_project_public(world):
    _, code = make_invite()
    push(world.payload, source_for(code))
    assert _project(world)["is_public"] is False


def test_owner_is_the_requester_when_they_have_an_account(world):
    owner = ObjectId()
    world.db.users_collection.insert_one({"_id": owner, "email": "Author@Source.org"})
    _, code = make_invite()
    out = push(world.payload, source_for(code), email="AUTHOR@source.ORG")
    project = _project(world)
    assert [o["_id"] for o in project["permissions"]["owners"]] == [owner]
    assert "pending_owner_email" not in project
    assert _request(world, out["request_id"])["result"]["owner_id"] == str(owner)


def test_an_unknown_requester_is_parked_on_the_invite_creator(world):
    _, code = make_invite()
    out = push(world.payload, source_for(code), email="New.Person@Source.org")
    project = _project(world)
    assert [str(o["_id"]) for o in project["permissions"]["owners"]] == [ADMIN_ID]
    assert project["pending_owner_email"] == "new.person@source.org"
    assert _request(world, out["request_id"])["result"]["pending_owner_email"] == (
        "new.person@source.org"
    )


def test_a_second_push_with_a_spent_single_use_code_is_a_403(world):
    _, code = make_invite()
    push(world.payload, source_for(code))
    with pytest.raises(HTTPException) as exc:
        source_for(code)
    assert exc.value.status_code == 403 and "used" in exc.value.detail
    assert world.db.migration_requests_collection.count_documents({}) == 1


def test_a_refused_bundle_leaves_the_code_usable(world):
    doc, code = make_invite()
    # Checksum mismatch.
    with pytest.raises(HTTPException) as exc:
        push(world.payload, source_for(code), sha="0" * 64)
    assert exc.value.status_code == 400
    # Not a zip.
    assert push(b"not a zip", source_for(code)).status_code == 422
    # A stray key outside the project's prefixes.
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(world.payload)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("s3_data/unrelated/file", b"x")
    response = push(out.getvalue(), source_for(code))
    assert response.status_code == 422 and json.loads(response.body)["errors"]

    stored = _invite(world, doc)
    assert migration_invites.invite_state(stored) == "active" and stored["use_count"] == 0
    assert world.db.migration_requests_collection.count_documents({}) == 0
    assert _staged(world) == []
    # And the real bundle still goes through with the same code.
    assert push(world.payload, source_for(code))["status"] == "importing"


def test_the_claim_losing_a_race_is_a_409_and_drops_the_staged_bundle(world, monkeypatch):
    doc, code = make_invite()
    src = source_for(code)  # authenticated while the code is still unspent
    real = migration_invites.claim_invite

    def raced(invite_id, **kwargs):
        # Another upload wins between validation and our claim.
        assert real(invite_id, **{**kwargs, "request_id": ObjectId()}) is not None
        return real(invite_id, **kwargs)

    monkeypatch.setattr(migration_invites, "claim_invite", raced)
    with pytest.raises(HTTPException) as exc:
        push(world.payload, src)
    assert exc.value.status_code == 409
    assert _staged(world) == [], "the loser's staged bundle is deleted"
    assert world.db.migration_requests_collection.count_documents({}) == 0
    assert world.db.projects_collection.count_documents({}) == 0
    assert _invite(world, doc)["use_count"] == 1


def test_an_invite_revoked_after_authentication_cannot_be_claimed(world):
    doc, code = make_invite()
    src = source_for(code)
    migration_invites.revoke_invite(doc["_id"], "admin")
    with pytest.raises(HTTPException) as exc:
        push(world.payload, src)
    assert exc.value.status_code == 409
    assert _staged(world) == []
    assert world.db.projects_collection.count_documents({}) == 0


def test_an_invite_push_that_fails_to_import_still_spends_the_code(world, monkeypatch):
    """The import runs after the claim; its failure is the request's status."""
    from depictio.api.v1.services import migration_import

    def boom(*args, **kwargs):
        raise migration_import.ImportFailed("disk full")

    monkeypatch.setattr(migration_import, "_import", boom)
    doc, code = make_invite()
    out = push(world.payload, source_for(code))
    assert out["status"] == "importing"
    assert _request(world, out["request_id"])["status"] == "failed"
    assert migration_invites.invite_state(_invite(world, doc)) == "used"
    status = _status(out["request_id"], out["status_token"])
    assert status["status"] == "failed" and "disk full" not in json.dumps(status)


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


def test_a_lineage_code_accepts_the_same_project_again(world):
    doc, code = make_invite("lineage")
    first = push(world.payload, source_for(code))
    second = push(world.payload, source_for(code))
    assert first["request_id"] != second["request_id"]
    for out in (first, second):
        assert _request(world, out["request_id"])["status"] == "imported"
    stored = _invite(world, doc)
    assert migration_invites.invite_state(stored) == "active"
    assert stored["use_count"] == 2
    assert stored["lineage_project_id"] == str(world.ids["project_id"])
    assert stored["lineage_project_name"] == "Iris published"
    assert stored["request_ids"] == [first["request_id"], second["request_id"]]
    hops = _project(world)["provenance"]["imported_from"]
    assert hops[-1]["migration_request_id"] == second["request_id"]
    assert hops[-1]["source_instance"] == f"invite:{doc['_id']}"


def _second_project_payload(world, monkeypatch):
    """A different project (new ids, own name) exported from a second source."""
    from .conftest import make_db, seed_source_project

    src_db = make_db()
    ids = seed_source_project(src_db)
    src_db.projects_collection.update_one({"_id": ids["project_id"]}, {"$set": {"name": "Other"}})
    s3 = world.s3
    s3.put("src-bucket", f"{ids['table_dc']}/part-0.parquet", b"rows2")
    s3.put("src-bucket", f"{ids['table_dc']}/_delta_log/00000.json", b"{}")
    s3.put("src-bucket", f"{ids['mqc_dc']}/abc/multiqc.parquet", b"mqc2")
    return _export_zip((src_db, ids, s3), monkeypatch), ids


def test_a_lineage_code_bound_to_one_project_refuses_another(world, monkeypatch):
    doc, code = make_invite("lineage")
    push(world.payload, source_for(code))
    other_payload, other_ids = _second_project_payload(world, monkeypatch)

    response = push(other_payload, source_for(code))
    assert response.status_code == 422
    errors = json.loads(response.body)["errors"]
    assert any("bound to the project 'Iris published'" in e for e in errors)
    stored = _invite(world, doc)
    assert stored["lineage_project_id"] == str(world.ids["project_id"])
    assert stored["use_count"] == 1
    assert world.db.projects_collection.find_one({"_id": other_ids["project_id"]}) is None
    assert _staged(world) == []
    # The bound project still goes through.
    assert push(world.payload, source_for(code))["status"] == "importing"


def test_an_unbound_lineage_code_binds_on_its_first_push(world, monkeypatch):
    doc, code = make_invite("lineage")
    assert "lineage_project_id" not in _invite(world, doc) or not _invite(world, doc).get(
        "lineage_project_id"
    )
    other_payload, other_ids = _second_project_payload(world, monkeypatch)
    assert push(other_payload, source_for(code))["status"] == "importing"
    assert _invite(world, doc)["lineage_project_id"] == str(other_ids["project_id"])
    assert push(world.payload, source_for(code)).status_code == 422


# ---------------------------------------------------------------------------
# Status token
# ---------------------------------------------------------------------------


def test_the_status_token_reads_exactly_its_own_request(world):
    doc, code = make_invite("lineage")
    first = push(world.payload, source_for(code))
    second = push(world.payload, source_for(code))
    token = first["status_token"]

    reader = inbound_auth.require_inbound_reader(None, None, token)
    assert reader == token
    status = _status(first["request_id"], reader)
    assert status["status"] == "imported" and status["project_name"] == "Iris published"
    assert status["result"]["project_id"] == str(world.ids["project_id"])
    assert "error" not in status

    for bad_token, rid in (
        ("wrong-token", first["request_id"]),
        (token, second["request_id"]),
        (second["status_token"], first["request_id"]),
        (token, str(ObjectId())),
        (token, "not-an-id"),
    ):
        with pytest.raises(HTTPException) as exc:
            _status(rid, bad_token)
        assert exc.value.status_code == 404, (bad_token, rid)


def test_the_stored_request_holds_only_the_token_hash(world):
    _, code = make_invite()
    out = push(world.payload, source_for(code))
    token = out["status_token"]
    request = _request(world, out["request_id"])
    assert request["status_token_sha256"] == inbound_auth.hash_request_token(token)
    blob = json.dumps(request, default=str)
    assert token not in blob
    assert code not in blob and migration_invites.normalize_code(code) not in blob


def test_a_spent_invite_still_reads_its_own_status_until_revoked(world):
    doc, code = make_invite()
    out = push(world.payload, source_for(code))
    reader = inbound_auth.require_inbound_reader(None, code, None)
    assert _status(out["request_id"], reader)["status"] == "imported"
    # Another invite's source cannot read it.
    other_doc, other_code = make_invite()
    other = inbound_auth.require_inbound_reader(None, other_code, None)
    with pytest.raises(HTTPException) as exc:
        _status(out["request_id"], other)
    assert exc.value.status_code == 404
    # Revoking the invite closes the read.
    migration_invites.revoke_invite(doc["_id"], "admin")
    with pytest.raises(HTTPException) as exc:
        inbound_auth.require_inbound_reader(None, code, None)
    assert exc.value.status_code == 403
    assert other_doc["_id"] != doc["_id"]


def test_pairing_key_requests_have_no_status_token(world):
    out = push(world.payload, world.source)
    assert out["status"] == "pending" and "status_token" not in out
    request = _request(world, out["request_id"])
    assert request["credential_type"] == "pairing_key" and "status_token_sha256" not in request
    with pytest.raises(HTTPException) as exc:
        _status(out["request_id"], "anything")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# /check
# ---------------------------------------------------------------------------


def _check(world, source, **over):
    body = inbound_routes.CheckBody(
        project_id=over.pop("project_id", str(world.ids["project_id"])),
        project_name=over.pop("project_name", "Iris published"),
        requester_email="author@source.org",
        total_bytes=10,
        source_s3_endpoint="http://s3:9000",
        source_bucket="src-bucket",
        **over,
    )
    return asyncio.run(inbound_routes.inbound_check(body, source=source))


def test_check_answers_info_preflight_and_probe_for_an_invite(world):
    _, code = make_invite(lock=False)
    out = _check(world, source_for(code))
    assert set(out) == {"info", "preflight", "probe"}
    assert out["info"]["credential_type"] == "invite_code"
    assert out["info"]["invite"]["lock_on_import"] is False
    assert out["info"]["lock_imported_default"] is False
    assert out["info"]["invite"]["imports_immediately"] is True
    assert out["info"]["server_side_copy_buckets"] == []
    assert out["preflight"]["ok"] and out["preflight"]["transfer_mode"] == "inline"
    assert out["probe"] is None, "an invite never copies server side"
    blob = json.dumps(out, default=str)
    assert code not in blob and migration_invites.normalize_code(code) not in blob


def test_check_for_a_pairing_key_source(monkeypatch, target_db):
    world = invite_world(monkeypatch, target_db, allowed_source_buckets=["src-bucket"])
    out = _check(world, world.source, probe_key=f"{world.ids['table_dc']}/part-0.parquet")
    assert out["info"]["credential_type"] == "pairing_key" and out["info"]["invite"] is None
    assert out["preflight"]["transfer_mode"] == "server_side_copy"
    assert out["probe"] == {"readable": True, "error": None}
    unsafe = _check(world, world.source, probe_key="../etc/passwd")
    assert unsafe["probe"] is None


def test_check_shows_a_lineage_binding_to_another_project(world):
    doc, code = make_invite("lineage")
    push(world.payload, source_for(code))
    other = str(ObjectId())
    out = _check(world, source_for(code), project_id=other, project_name="Elsewhere")
    assert out["preflight"]["ok"] is False
    assert any("bound to the project 'Iris published'" in e for e in out["preflight"]["errors"])
    assert out["info"]["invite"]["lineage_project_id"] == str(world.ids["project_id"])
    # The bound project itself is fine.
    same = _check(world, source_for(code))
    assert same["preflight"]["ok"] and same["preflight"]["conflict"] == "re_push"
    assert doc["_id"]


def test_preflight_route_applies_the_lineage_rule_too(world):
    _, code = make_invite("lineage")
    push(world.payload, source_for(code))
    body = inbound_routes.PreflightBody(project_id=str(ObjectId()), total_bytes=1)
    out = asyncio.run(inbound_routes.inbound_preflight(body, source=source_for(code)))
    assert not out["ok"] and any("bound to the project" in e for e in out["errors"])


def test_info_for_an_invite_hides_the_code(world):
    _, code = make_invite()
    info = asyncio.run(inbound_routes.inbound_info(source=source_for(code)))
    assert info["credential_type"] == "invite_code"
    assert code not in json.dumps(info, default=str)
