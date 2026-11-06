"""What an admin reads on a migration request: where it came from, what it holds (#1303)."""

from __future__ import annotations

import asyncio

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.migrate_endpoints import requests_routes
from depictio.api.v1.services import project_bundle

from .invite_helpers import invite_world, make_invite, source_for
from .push_helpers import admin, approve, push


@pytest.fixture
def world(monkeypatch, target_db, captures):
    return invite_world(monkeypatch, target_db)


def _detail(request_id, user=None):
    return asyncio.run(requests_routes.get_request(request_id, user or admin()))


def test_the_report_names_dashboards_and_collections(world):
    out = push(world.payload, world.source)
    report = _detail(out["request_id"])["report"]
    by_id = {d["id"]: d for d in report["dashboards"]}
    assert set(by_id) == set(report["dashboards_added"])
    assert all("title" in d and "icon" in d for d in by_id.values())
    assert report["data_collections"], "the project's collections are listed"
    assert all({"id", "tag", "type"} <= set(dc) for dc in report["data_collections"])


def test_an_invite_request_carries_the_invite_note_and_hint(world):
    invite, code = make_invite(note="publish test")
    out = push(world.payload, source_for(code))
    body = _detail(out["request_id"])
    assert body["invite_note"] == "publish test"
    assert body["invite_code_hint"] == code.replace("-", "")[-4:]
    assert code not in str(body)


def test_a_pairing_key_request_has_no_invite_facts(world):
    out = push(world.payload, world.source)
    body = _detail(out["request_id"])
    assert "invite_note" not in body


def test_the_source_url_is_kept_only_when_http(world):
    assert project_bundle._source_url("https://dev.example.org") == "https://dev.example.org"
    assert project_bundle._source_url("http://10.0.0.1") == "http://10.0.0.1"
    for bad in (None, "", "javascript:alert(1)", "ftp://x", "just-a-host"):
        assert project_bundle._source_url(bad) is None


def test_an_old_imported_request_is_described_from_the_project_now_here(world):
    out = push(world.payload, world.source)
    approve(out["request_id"], admin())
    col = world.db.migration_requests_collection
    doc = col.find_one({"_id": ObjectId(out["request_id"])})
    assert doc["status"] == "imported"
    # A request recorded before reports carried these.
    stripped = {
        k: v for k, v in doc["report"].items() if k not in ("dashboards", "data_collections")
    }
    col.update_one({"_id": doc["_id"]}, {"$set": {"report": stripped}})
    report = _detail(out["request_id"])["report"]
    assert {d["id"] for d in report["dashboards"]} == set(doc["report"]["dashboards_added"])
    assert report["data_collections"]


def test_thumbnails_are_queued_for_an_imported_request(world, monkeypatch):
    queued = []

    class _Task:
        @staticmethod
        def delay(dashboard_id, user_id, force=False):
            queued.append((dashboard_id, force))

    import depictio.api.celery_app as celery_app

    monkeypatch.setattr(celery_app, "generate_dashboard_screenshot_dual", _Task, raising=False)
    monkeypatch.setattr(requests_routes.settings.performance, "screenshots_enabled", True)
    out = push(world.payload, world.source)
    approve(out["request_id"], admin())
    result = asyncio.run(requests_routes.regenerate_thumbnails(out["request_id"], admin()))
    assert result["queued"] == result["dashboards"] == len(queued) > 0
    assert all(force for _, force in queued)


def test_thumbnails_are_refused_until_imported(world, monkeypatch):
    monkeypatch.setattr(requests_routes.settings.performance, "screenshots_enabled", True)
    out = push(world.payload, world.source)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(requests_routes.regenerate_thumbnails(out["request_id"], admin()))
    assert exc.value.status_code == 409


def test_thumbnails_are_for_admins(world):
    out = push(world.payload, world.source)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            requests_routes.regenerate_thumbnails(
                out["request_id"], type("U", (), {"is_admin": False})()
            )
        )
    assert exc.value.status_code == 403
