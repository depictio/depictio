"""Import hardening: what a ZIP or JSON bundle may not smuggle in.

A ZIP import restores S3 objects only under the imported project's own
prefixes, a dashboard id another dashboard here already holds is refused with
409, and the JSON import body is capped.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest
from bson import ObjectId
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from depictio.api.v1.endpoints.migrate_endpoints import routes
from depictio.api.v1.services import project_bundle

from .conftest import FakeS3, make_db, seed_source_project
from .test_bundle_roundtrip import _admin, _export_zip, _import_zip


def _zip_with_extra_member(payload: bytes, name: str, body: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr(name, body)
    return out.getvalue()


@pytest.fixture
def source(monkeypatch):
    db = make_db()
    ids = seed_source_project(db)
    s3 = FakeS3()
    s3.put("src-bucket", f"{ids['table_dc']}/part-0.parquet", b"rows")
    s3.put("src-bucket", f"{ids['table_dc']}/_delta_log/00000.json", b"{}")
    s3.put("src-bucket", f"{ids['mqc_dc']}/abc/multiqc.parquet", b"mqc")
    payload = _export_zip((db, ids, s3), monkeypatch)
    return db, ids, s3, payload


def _cli_bundle(payload: bytes) -> dict:
    """The JSON body the CLI posts for the same export (no data files)."""
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {
            "bundle": {
                "data": json.loads(zf.read("bundle.json")),
                "migrate_metadata": json.loads(zf.read("migrate_metadata.json")),
            }
        }


# ---------------------------------------------------------------------------
# S3 keys outside the project's prefixes
# ---------------------------------------------------------------------------


def test_zip_import_refuses_s3_keys_outside_the_project(source, target_db, captures, monkeypatch):
    _, _, _, payload = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    smuggled = _zip_with_extra_member(payload, "s3_data/somewhere-else/secret.bin", b"stolen")
    target_s3 = FakeS3()

    with pytest.raises(HTTPException) as exc:
        _import_zip(smuggled, _admin(), s3=target_s3)

    assert exc.value.status_code == 400
    assert "outside the imported project's prefixes" in str(exc.value.detail)
    # Nothing was restored and nothing was written.
    assert target_s3.buckets.get("tgt-bucket") in (None, {})
    assert target_db.projects_collection.count_documents({}) == 0


def test_zip_import_dry_run_refuses_stray_s3_keys_too(source, target_db, captures, monkeypatch):
    _, _, _, payload = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    smuggled = _zip_with_extra_member(payload, "s3_data/somewhere-else/secret.bin", b"stolen")

    with pytest.raises(HTTPException) as exc:
        _import_zip(smuggled, _admin(), dry_run=True, s3=FakeS3())

    assert exc.value.status_code == 400


def test_restore_s3_entries_keeps_keys_outside_the_allowed_scope():
    """The allowed hook is the second fence: a skipped key counts as a failure."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bundle.json", b"{}")
        zf.writestr("migrate_metadata.json", b"{}")
        zf.writestr("s3_data/dc/a.parquet", b"a")
        zf.writestr("s3_data/other/b.parquet", b"b")
    buf.seek(0)
    opened = project_bundle.open_bundle_zip(buf)
    try:
        s3 = FakeS3()
        uploaded, failures = project_bundle.restore_s3_entries(
            opened, s3, "tgt-bucket", allowed=lambda key: key.startswith("dc/")
        )
        assert uploaded == 1
        assert failures == ["other/b.parquet: outside the project's prefixes"]
        assert s3.buckets["tgt-bucket"]["dc/a.parquet"] == b"a"
    finally:
        opened.close()


# ---------------------------------------------------------------------------
# Dashboard ids that already exist here
# ---------------------------------------------------------------------------


def test_zip_import_refuses_a_dashboard_id_used_in_another_project(
    source, target_db, captures, monkeypatch
):
    _, ids, _, payload = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    admin = _admin()
    assert _import_zip(payload, admin).success

    # A dashboard of another project claims the ref the bundle's child tab uses.
    other = ObjectId()
    target_db.dashboards_collection.insert_one(
        {
            "_id": other,
            "dashboard_id": ids["child_dash"],
            "project_id": other,
            "title": "Other project's tab",
        }
    )

    with pytest.raises(HTTPException) as exc:
        _import_zip(payload, admin, overwrite=True)

    assert exc.value.status_code == 409
    assert str(ids["child_dash"]) in str(exc.value.detail)
    # The other project's dashboard is untouched.
    doc = target_db.dashboards_collection.find_one({"_id": other})
    assert doc["title"] == "Other project's tab"


def test_zip_import_refuses_a_dashboard_id_of_a_kept_copy_in_the_same_project(
    source, target_db, captures, monkeypatch
):
    _, ids, _, payload = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    admin = _admin()
    assert _import_zip(payload, admin).success

    # A visitor's copy in the same project claims the main tab's ref: importing
    # would leave two dashboards sharing one id and its logo binding.
    visitor = ObjectId()
    target_db.dashboards_collection.insert_one(
        {"_id": visitor, "dashboard_id": ids["main_dash"], "project_id": ids["project_id"]}
    )

    with pytest.raises(HTTPException) as exc:
        _import_zip(payload, admin, overwrite=True)

    assert exc.value.status_code == 409


def test_reimport_replacing_its_own_dashboards_stays_allowed(
    source, target_db, captures, monkeypatch
):
    _, _, _, payload = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    admin = _admin()
    assert _import_zip(payload, admin).success
    assert _import_zip(payload, admin, overwrite=True).success


def test_cli_import_refuses_a_dashboard_id_used_elsewhere(source, target_db, captures, monkeypatch):
    _, ids, _, payload = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    other = ObjectId()
    target_db.dashboards_collection.insert_one(
        {"_id": other, "dashboard_id": ids["main_dash"], "project_id": other}
    )
    body = json.dumps(_cli_bundle(payload)).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
        "path": "/depictio/api/v1/migrate/import-project",
        "query_string": b"",
    }

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.import_project(Request(scope, receive), current_user=_admin()))

    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# The JSON import body cap
# ---------------------------------------------------------------------------


@pytest.fixture
def client(target_db, captures):
    """A small app exposing the migrate import endpoint as an admin."""
    from fastapi import FastAPI

    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    app = FastAPI()
    app.include_router(routes.migrate_endpoint_router, prefix="/migrate")
    app.dependency_overrides[get_user_or_anonymous] = lambda: _admin()
    return TestClient(app)


def test_import_project_body_over_the_cap_is_413(source, client, monkeypatch):
    monkeypatch.setattr(routes, "_max_import_body_bytes", lambda: 256)
    response = client.post("/migrate/import-project", json=_cli_bundle(source[3]))
    assert response.status_code == 413


def test_import_project_body_under_the_cap_imports(
    source, client, target_db, captures, monkeypatch
):
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    monkeypatch.setattr(routes, "_max_import_body_bytes", lambda: 64 * 1024 * 1024)
    response = client.post("/migrate/import-project", json=_cli_bundle(source[3]))
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert target_db.dashboards_collection.count_documents({}) == 2


def test_import_project_invalid_json_is_400(client, monkeypatch):
    monkeypatch.setattr(routes, "_max_import_body_bytes", lambda: 1024 * 1024)
    response = client.post(
        "/migrate/import-project",
        content=b"not json at all",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


def test_declared_length_over_the_cap_is_413_before_the_body_is_read(monkeypatch):
    """A client that declares the size is refused without the body being read."""
    monkeypatch.setattr(routes, "_max_import_body_bytes", lambda: 16)

    async def refuse():
        raise AssertionError("the body must not be read")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "headers": [(b"content-length", b"9999999999")],
        "path": "/depictio/api/v1/migrate/import-project",
        "query_string": b"",
    }

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.import_project(Request(scope, refuse), current_user=_admin()))

    assert exc.value.status_code == 413
