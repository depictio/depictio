"""Dashboard logos and comment threads travel with the project (#1303)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.migrate_endpoints import routes
from depictio.api.v1.services import project_bundle

from .conftest import FakeS3, make_db, seed_source_project
from .invite_helpers import attach_invites, make_invite, source_for
from .push_helpers import MigS3, configure_target, push
from .test_bundle_roundtrip import _admin, _export_zip, _import_zip

T0 = datetime(2026, 3, 4, 5, 6, 7)
T1 = datetime(2026, 3, 5, 6, 7, 8)
T2 = datetime(2026, 3, 6, 7, 8, 9)


def _thread(pid, dash, *, status="open", with_annotation=False, tid=None):
    doc = {
        "_id": tid or ObjectId(),
        "project_id": str(pid),
        "parent_dashboard_id": str(dash),
        "anchor": {
            "dashboard_id": str(dash),
            "component_index": "c1",
            "view_state": {"filters": [{"column": "species", "value": "setosa"}]},
        },
        "number": 1,
        "status": status,
        "created_by": {"kind": "human", "user_id": "u1", "email": "author@source.org"},
        "created_at": T0,
        "updated_at": T1,
        "comments": [
            {
                "id": "k1",
                "author": {"kind": "human", "user_id": "u1"},
                "body": "first",
                "created_at": T0,
                "edited_at": T1,
            },
            {
                "id": "k2",
                "author": {"kind": "human", "user_id": "u2"},
                "body": "second",
                "created_at": T1,
            },
        ],
    }
    if with_annotation:
        doc["annotation"] = {
            "kind": "range",
            "geometry": {"kind": "x_range", "x0": 1.5, "x1": 3},
            "label": "outliers",
            "color": "red",
            "published": True,
        }
    if status == "resolved":
        doc["resolved_by"] = "u1"
        doc["resolved_at"] = T2
    return doc


def _seed_extras(db, ids):
    """A logo and two threads on the project, plus a foreign dashboard's logo and thread."""
    pid, main = ids["project_id"], ids["main_dash"]
    logo = {
        "_id": project_bundle.dashboard_logo_key(main),
        "content_type": "image/png",
        "data_b64": "iVBORw0KGgo=",
        "updated_at": T1,
    }
    db.branding_assets_collection.insert_one(logo)
    other_dash = ObjectId()
    db.branding_assets_collection.insert_one(
        {**logo, "_id": project_bundle.dashboard_logo_key(other_dash), "data_b64": "AAAA"}
    )
    threads = [
        _thread(pid, main, with_annotation=True),
        _thread(pid, ids["child_dash"], status="resolved"),
    ]
    db.comment_threads_collection.insert_many(threads)
    foreign = _thread(ObjectId(), other_dash)
    db.comment_threads_collection.insert_one(foreign)
    return logo, threads, foreign


@pytest.fixture
def source():
    db = make_db()
    ids = seed_source_project(db)
    extras = _seed_extras(db, ids)
    s3 = FakeS3()
    s3.put("src-bucket", f"{ids['table_dc']}/part-0.parquet", b"rows")
    s3.put("src-bucket", f"{ids['mqc_dc']}/abc/multiqc.parquet", b"mqc")
    return db, ids, s3, extras


def _bundle(payload: bytes):
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return (
            json.loads(zf.read("migrate_metadata.json")),
            json.loads(zf.read("bundle.json")),
        )


def test_export_carries_this_projects_logos_and_threads_only(source, monkeypatch):
    db, ids, s3, (logo, threads, foreign) = source
    _, data = _bundle(_export_zip((db, ids, s3), monkeypatch))
    assert [d["_id"] for d in data["branding_assets"]] == [logo["_id"]]
    assert sorted(d["_id"] for d in data["comment_threads"]) == sorted(
        str(t["_id"]) for t in threads
    )
    assert str(foreign["_id"]) not in {d["_id"] for d in data["comment_threads"]}


def test_round_trip_restores_logo_and_threads(source, target_db, captures, monkeypatch):
    db, ids, s3, (logo, threads, _) = source
    payload = _export_zip((db, ids, s3), monkeypatch)
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    result = _import_zip(payload, _admin())
    assert result.success, result.message
    assert result.upserted.get("branding_assets") == 1
    assert result.upserted.get("comment_threads") == 2

    got = target_db.branding_assets_collection.find_one({"_id": logo["_id"]})
    assert got["data_b64"] == logo["data_b64"] and got["content_type"] == logo["content_type"]
    assert target_db.branding_assets_collection.count_documents({}) == 1

    assert target_db.comment_threads_collection.count_documents({}) == 2
    for original in threads:
        stored = target_db.comment_threads_collection.find_one({"_id": original["_id"]})
        assert stored is not None and isinstance(stored["_id"], ObjectId)
        for key in ("created_at", "updated_at"):
            assert isinstance(stored[key], datetime)
        assert isinstance(stored["comments"][0]["created_at"], datetime)
        assert isinstance(stored["comments"][0]["edited_at"], datetime)
        assert stored["project_id"] == original["project_id"]
        assert stored["parent_dashboard_id"] == original["parent_dashboard_id"]
        assert stored["anchor"] == original["anchor"]
        assert stored == original
    annotated = target_db.comment_threads_collection.find_one({"_id": threads[0]["_id"]})
    assert annotated["annotation"]["label"] == "outliers"
    resolved = target_db.comment_threads_collection.find_one({"_id": threads[1]["_id"]})
    assert resolved["status"] == "resolved" and resolved["resolved_at"] == T2


def test_reimport_upserts_without_duplicating(source, target_db, captures, monkeypatch):
    db, ids, s3, (logo, threads, _) = source
    payload = _export_zip((db, ids, s3), monkeypatch)
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    assert _import_zip(payload, _admin()).success
    target_db.comment_threads_collection.update_one(
        {"_id": threads[0]["_id"]}, {"$set": {"status": "rejected"}}
    )
    assert _import_zip(payload, _admin(), overwrite=True).success
    assert target_db.comment_threads_collection.count_documents({}) == 2
    assert target_db.branding_assets_collection.count_documents({}) == 1
    assert (
        target_db.comment_threads_collection.find_one({"_id": threads[0]["_id"]})["status"]
        == "open"
    )


def _validate(payload, target_db):
    metadata, data = _bundle(payload)
    return project_bundle.validate_bundle(metadata, data, [], strict=True), data, metadata


def test_validation_refuses_a_thread_id_owned_by_another_project_here(
    source, target_db, monkeypatch
):
    db, ids, s3, (_, threads, _) = source
    payload = _export_zip((db, ids, s3), monkeypatch)
    target_db.comment_threads_collection.insert_one(
        {"_id": threads[0]["_id"], "project_id": str(ObjectId())}
    )
    report, _, _ = _validate(payload, target_db)
    assert any("comment thread id" in e and "another project here" in e for e in report.errors)


def test_validation_accepts_a_thread_id_of_the_same_project(source, target_db, monkeypatch):
    db, ids, s3, (_, threads, _) = source
    payload = _export_zip((db, ids, s3), monkeypatch)
    target_db.comment_threads_collection.insert_one(
        {"_id": threads[0]["_id"], "project_id": str(ids["project_id"])}
    )
    report, _, _ = _validate(payload, target_db)
    assert report.errors == []


def test_validation_refuses_a_thread_of_another_project_in_the_bundle(
    source, target_db, monkeypatch
):
    db, ids, s3, _ = source
    payload = _export_zip((db, ids, s3), monkeypatch)
    metadata, data = _bundle(payload)
    data["comment_threads"][0]["project_id"] = str(ObjectId())
    report = project_bundle.validate_bundle(metadata, data, [], strict=True)
    assert any("comment thread" in e and "belongs to another project" in e for e in report.errors)


@pytest.mark.parametrize("key", [lambda: f"dashboard-{ObjectId()}", lambda: "logo-x"])
def test_validation_refuses_a_logo_that_is_not_a_bundled_dashboards(
    source, target_db, monkeypatch, key
):
    db, ids, s3, _ = source
    payload = _export_zip((db, ids, s3), monkeypatch)
    metadata, data = _bundle(payload)
    bad = key()
    data["branding_assets"][0]["_id"] = bad
    report = project_bundle.validate_bundle(metadata, data, [], strict=True)
    assert any("is not one of the bundled dashboards" in e and bad in e for e in report.errors)


def test_a_bundle_without_the_new_sections_still_imports(source, target_db, captures, monkeypatch):
    db, ids, s3, _ = source
    payload = _export_zip((db, ids, s3), monkeypatch)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            blob = src.read(info.filename)
            if info.filename == "bundle.json":
                data = json.loads(blob)
                data.pop("branding_assets"), data.pop("comment_threads")
                blob = json.dumps(data).encode()
            dst.writestr(info, blob)
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    assert _import_zip(out.getvalue(), _admin()).success
    assert target_db.comment_threads_collection.count_documents({}) == 0


def test_invite_push_carries_threads_and_logo_end_to_end(source, target_db, captures, monkeypatch):
    db, ids, s3, (logo, threads, _) = source
    mig = MigS3()
    mig.buckets = s3.buckets
    payload = _export_zip((db, ids, mig), monkeypatch)
    configure_target(monkeypatch, target_db, mig)
    attach_invites(target_db)
    _, code = make_invite()
    out = push(payload, source_for(code))
    assert out["status"] == "importing"
    request = target_db.migration_requests_collection.find_one({"_id": ObjectId(out["request_id"])})
    assert request["status"] == "imported", request.get("result")
    assert (
        target_db.branding_assets_collection.find_one({"_id": logo["_id"]})["data_b64"]
        == (logo["data_b64"])
    )
    stored = {t["_id"]: t for t in target_db.comment_threads_collection.find({})}
    assert set(stored) == {t["_id"] for t in threads}
    assert stored[threads[0]["_id"]] == threads[0]
