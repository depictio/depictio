"""Source-side push: preflight mode choice, background job, status (#1303)."""

from __future__ import annotations

import json
import os
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import mongomock
import pytest
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import MigrationTargetConfig
from depictio.api.v1.endpoints.migrate_endpoints import push_routes, routes, targets_routes
from depictio.api.v1.services import migration_push, outbound_http, project_bundle

from .conftest import COLLECTIONS, FakeS3, make_db, seed_source_project

KEY = "p" * 40


class FakeTarget:
    """A paired instance's inbound API, as httpx sees it."""

    def __init__(self, *, mode="inline", readable=True, ok=True, submit_status=202):
        self.mode, self.readable, self.ok, self.submit_status = mode, readable, ok, submit_status
        self.calls: list[tuple[str, str]] = []
        self.submitted: dict | None = None
        self.remote_status = "pending"
        self.explode = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/migrate/inbound")[1]
        self.calls.append((request.method, path))
        assert request.headers["X-Depictio-Pairing-Key"] == KEY
        if path == "/info":
            return httpx.Response(200, json={"instance_label": "remote"})
        if path == "/preflight":
            self.preflight_body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "ok": self.ok,
                    "transfer_mode": self.mode,
                    "errors": [] if self.ok else ["Project exists"],
                    "warnings": [],
                },
            )
        if path == "/probe":
            return httpx.Response(200, json={"readable": self.readable, "error": None})
        if path == "/requests":
            if self.explode:
                raise RuntimeError("disk on fire")
            body = request.read()
            self.submitted = {"raw": body, "ctype": request.headers["content-type"]}
            if self.submit_status != 202:
                return httpx.Response(self.submit_status, json={"detail": "Quota exceeded"})
            return httpx.Response(202, json={"request_id": "rq1", "status": "pending"})
        if path == "/requests/rq1":
            return httpx.Response(200, json={"request_id": "rq1", "status": self.remote_status})
        return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture
def env(monkeypatch, tmp_path):
    db = make_db()
    ids = seed_source_project(db)
    s3 = FakeS3()
    s3.put("src-bucket", f"{ids['table_dc']}/part-0.parquet", b"rows")
    s3.put("src-bucket", f"{ids['table_dc']}/_delta_log/00000.json", b"{}")
    pushes = mongomock.MongoClient()["t"]["migration_pushes"]
    from depictio.api.v1 import db as dbmod

    patches = [
        patch.object(project_bundle, "_db", lambda: db),
        patch.object(routes, "_instance_s3_client", lambda: s3),
        patch.object(push_routes, "projects_collection", db.projects_collection),
        patch.object(push_routes, "migration_pushes_collection", pushes),
        patch.object(
            targets_routes, "migration_targets_collection", mongomock.MongoClient()["t"]["targets"]
        ),
        patch.object(dbmod, "projects_collection", db.projects_collection),
        patch.object(dbmod, "migration_pushes_collection", pushes),
    ]
    patches += [patch.object(routes, a, getattr(db, a)) for a in COLLECTIONS if hasattr(routes, a)]
    for p in patches:
        p.start()
    monkeypatch.setattr(settings.s3, "bucket", "src-bucket")
    monkeypatch.setattr(settings.migration, "spool_dir", str(tmp_path))
    monkeypatch.setattr(
        settings.migration,
        "targets",
        [MigrationTargetConfig(name="pub", url="http://remote:8058", pairing_key=KEY)],
    )
    fake = FakeTarget()
    real = outbound_http.TargetClient

    def make(target):
        return real(target, transport=httpx.MockTransport(fake))

    monkeypatch.setattr(push_routes, "TargetClient", make)
    monkeypatch.setattr(outbound_http, "TargetClient", make)
    yield SimpleNamespace(db=db, ids=ids, pushes=pushes, fake=fake, tmp=tmp_path)
    for p in reversed(patches):
        p.stop()


def _owner(env, **kw):
    return SimpleNamespace(
        id=env.ids["owner_id"],
        email="author@source.org",
        is_admin=False,
        is_anonymous=False,
        is_temporary=False,
        **kw,
    )


def _body(env):
    return push_routes.PreflightRequest(project_id=str(env.ids["project_id"]), target_id="env:pub")


def test_preflight_inline_when_remote_says_inline(env):
    out = push_routes.preflight(_body(env), current_user=_owner(env))
    assert out["transfer_mode"] == "inline" and out["can_push"]
    assert out["object_count"] == 2 and out["total_bytes"] == 6
    assert ("POST", "/probe") not in env.fake.calls
    assert env.fake.preflight_body["requester_email"] == "author@source.org"


def test_preflight_server_side_copy_after_probe(env):
    env.fake.mode = "server_side_copy"
    out = push_routes.preflight(_body(env), current_user=_owner(env))
    assert out["transfer_mode"] == "server_side_copy"
    assert ("POST", "/probe") in env.fake.calls


def test_preflight_probe_failure_falls_back_to_inline(env):
    env.fake.mode, env.fake.readable = "server_side_copy", False
    out = push_routes.preflight(_body(env), current_user=_owner(env))
    assert out["transfer_mode"] == "inline" and out["can_push"]
    assert any("cannot read" in w for w in out["warnings"])


def test_preflight_remote_refusal_blocks_push(env):
    env.fake.ok = False
    out = push_routes.preflight(_body(env), current_user=_owner(env))
    assert not out["can_push"] and out["errors"] == ["Project exists"]


def test_non_owner_forbidden(env):
    other = SimpleNamespace(
        id=ObjectId(), email="x@y.org", is_admin=False, is_anonymous=False, is_temporary=False
    )
    with pytest.raises(HTTPException) as exc:
        push_routes.preflight(_body(env), current_user=other)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("flag", ["is_anonymous", "is_temporary"])
def test_anonymous_and_temporary_forbidden(env, flag):
    visitor = _owner(env)
    setattr(visitor, flag, True)
    with pytest.raises(HTTPException) as exc:
        push_routes.start_push(
            push_routes.PushRequest(**_body(env).model_dump()),
            BackgroundTasks(),
            current_user=visitor,
        )
    assert exc.value.status_code == 403


def test_single_user_mode_may_push(env, monkeypatch):
    monkeypatch.setattr(settings.auth, "single_user_mode", True)
    solo = SimpleNamespace(
        id=ObjectId(), email="solo@local", is_admin=False, is_anonymous=True, is_temporary=False
    )
    out = push_routes.preflight(_body(env), current_user=solo)
    assert out["can_push"]
    started = push_routes.start_push(
        push_routes.PushRequest(**_body(env).model_dump()), BackgroundTasks(), current_user=solo
    )
    assert started["status"] == "building"


def test_push_builds_bundle_and_identity_comes_from_session(env):
    tasks = BackgroundTasks()
    body = push_routes.PushRequest(**_body(env).model_dump(), message="please")
    started = push_routes.start_push(body, tasks, current_user=_owner(env))
    assert started["status"] == "building" and len(tasks.tasks) == 1
    migration_push.run_push(started["push_id"])
    doc = env.pushes.find_one({"_id": ObjectId(started["push_id"])})
    assert doc["status"] == "submitted" and doc["remote_request_id"] == "rq1"
    assert doc["requested_by_email"] == "author@source.org"
    assert doc["bundle_sha256"] and doc["bundle_bytes"] > 0
    raw = env.fake.submitted["raw"]
    assert b'name="requester_email"\r\n\r\nauthor@source.org' in raw
    assert b'name="source_user_id"\r\n\r\n' + str(env.ids["owner_id"]).encode() in raw
    assert f'name="sha256"\r\n\r\n{doc["bundle_sha256"]}'.encode() in raw
    assert b'name="transfer_mode"\r\n\r\ninline' in raw
    assert b'name="message"\r\n\r\nplease' in raw
    assert not [f for f in os.listdir(env.tmp) if f.endswith(".zip")]


def test_server_side_copy_bundle_has_manifest_and_no_data(env):
    built = migration_push.build_project_bundle_file(
        env.db.projects_collection.find_one({}), transfer_mode="server_side_copy"
    )
    try:
        with zipfile.ZipFile(built.path) as zf:
            assert not [n for n in zf.namelist() if n.startswith("s3_data/")]
            s3meta = json.loads(zf.read("s3_metadata.json"))
            meta = json.loads(zf.read("migrate_metadata.json"))
        assert s3meta["transfer_mode"] == "server_side_copy"
        assert s3meta["source_bucket"] == "src-bucket" and meta["s3_bucket"] == "src-bucket"
        assert {m["key"] for m in s3meta["manifest"]} == {m["key"] for m in built.manifest}
        assert all(m["etag"] for m in s3meta["manifest"]) and built.s3_object_count == 2
        keys = [m.key for m in project_bundle.manifest_from_s3_metadata(s3meta)]
        assert keys[-1].endswith("_delta_log/00000.json")
    finally:
        os.unlink(built.path)


def test_failure_marks_push_failed_and_removes_temp_file(env):
    env.fake.submit_status = 429
    started = push_routes.start_push(
        push_routes.PushRequest(**_body(env).model_dump()), BackgroundTasks(), _owner(env)
    )
    migration_push.run_push(started["push_id"])
    doc = env.pushes.find_one({"_id": ObjectId(started["push_id"])})
    assert doc["status"] == "failed" and "Quota exceeded" in doc["error"]
    assert KEY not in json.dumps(doc, default=str)
    assert not [f for f in os.listdir(env.tmp) if f.endswith(".zip")]


def test_unexpected_error_marks_failed_and_cleans_up(env, monkeypatch):
    started = push_routes.start_push(
        push_routes.PushRequest(**_body(env).model_dump()), BackgroundTasks(), _owner(env)
    )

    env.fake.explode = True
    migration_push.run_push(started["push_id"])
    doc = env.pushes.find_one({"_id": ObjectId(started["push_id"])})
    assert doc["status"] == "failed"
    assert not [f for f in os.listdir(env.tmp) if f.endswith(".zip")]


def test_get_push_refreshes_remote_status_and_scopes_listing(env):
    started = push_routes.start_push(
        push_routes.PushRequest(**_body(env).model_dump()), BackgroundTasks(), _owner(env)
    )
    migration_push.run_push(started["push_id"])
    env.fake.remote_status = "imported"
    got = push_routes.get_push(started["push_id"], current_user=_owner(env))
    assert got["remote_status"] == "imported" and got["id"] == started["push_id"]
    assert env.pushes.find_one({})["remote_status"] == "imported"
    assert len(push_routes.list_pushes(None, current_user=_owner(env))["pushes"]) == 1
    other = SimpleNamespace(
        id=ObjectId(), email="x@y.org", is_admin=False, is_anonymous=False, is_temporary=False
    )
    assert push_routes.list_pushes(None, current_user=other)["pushes"] == []
    with pytest.raises(HTTPException) as exc:
        push_routes.get_push(started["push_id"], current_user=other)
    assert exc.value.status_code == 403


def test_get_push_survives_unreachable_target(env):
    started = push_routes.start_push(
        push_routes.PushRequest(**_body(env).model_dump()), BackgroundTasks(), _owner(env)
    )
    migration_push.run_push(started["push_id"])
    env.fake.remote_status = None
    env.fake.__class__.__call__ = lambda self, r: httpx.Response(500, json={"detail": "down"})
    got = push_routes.get_push(started["push_id"], current_user=_owner(env))
    assert got["status"] == "submitted"


def test_push_targets_list_has_no_fingerprint(env):
    out = push_routes.push_targets(current_user=_owner(env))
    assert out["targets"][0]["id"] == "env:pub" and "key_fingerprint" not in out["targets"][0]
    assert KEY not in json.dumps(out)
