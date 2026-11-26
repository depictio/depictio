"""The pre-built offline bundle a public project's visitors download (#1480).

A visitor never builds: the bundle is built by a worker after a save or an
ingestion, cached per content version, and handed out by a route that does no
work. Everything runs offline: Mongo is mongomock, S3 a recording fake, Redis a
dict, and the Celery dispatch a recorder, so a test can assert that a download
queued nothing.
"""

from __future__ import annotations

from typing import Any

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.serverless_endpoints import public_bundle_routes as routes_mod
from depictio.api.v1.endpoints.user_endpoints import rate_limit
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User
from depictio.serverless import public_bundle

PROJECT_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c9d")
MAIN_OID = ObjectId("6824cb3b89d2b72169309737")
CHILD_OID = ObjectId("6824cb3b89d2b72169309741")
DC_OID = ObjectId("6824cb3b89d2b72169309801")
OWNER_OID = ObjectId("507f1f77bcf86cd799439011")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Body:
    def __init__(self, payload: bytes):
        self.payload = payload

    def iter_chunks(self, chunk_size: int = 8192):
        yield self.payload


class _FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.get_calls: list[str] = []

    def put_object(self, Bucket: str, Key: str, Body: bytes, **kw: Any):
        self.objects[Key] = Body

    def get_object(self, Bucket: str, Key: str):
        self.get_calls.append(Key)
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(self.objects[Key])}

    def delete_objects(self, Bucket: str, Delete: dict[str, Any]):
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)

    def get_paginator(self, name: str):
        fake = self

        class _P:
            def paginate(self, Bucket: str, Prefix: str):
                yield {"Contents": [{"Key": k} for k in fake.objects if k.startswith(Prefix)]}

        return _P()


class _FakeRedis:
    def __init__(self, broken: bool = False):
        self.counts: dict[str, int] = {}
        self.broken = broken

    def incr(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def switches(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.static_export, "enabled", True)
    monkeypatch.setattr(settings.static_export, "public_download_enabled", True)
    monkeypatch.setattr(settings.static_export, "public_download_per_ip_per_minute", 10)
    monkeypatch.setattr(settings.static_export, "public_rebuild_delay_s", 120)
    # The rendered report is its own switch (its tests turn it on).
    monkeypatch.setattr(settings.notebook_export, "render_enabled", False)


@pytest.fixture
def mongo(monkeypatch: pytest.MonkeyPatch, switches):
    """A public project with the download on, a two-tab dashboard, one collection."""
    from depictio.api.v1 import db as db_mod
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dashboards_routes

    database = mongomock.MongoClient().db
    for name in (
        "dashboards_collection",
        "projects_collection",
        "deltatables_collection",
        "multiqc_collection",
        "public_bundles_collection",
    ):
        monkeypatch.setattr(db_mod, name, database[name])
    monkeypatch.setattr(dashboards_routes, "projects_collection", database["projects_collection"])
    database["projects_collection"].insert_one(
        {
            "_id": PROJECT_OID,
            "name": "Penguins",
            "is_public": True,
            "public_offline_download": True,
            "permissions": {"owners": [{"_id": OWNER_OID}], "editors": [], "viewers": []},
            "data_collections": [{"_id": DC_OID, "data_collection_tag": "penguins"}],
            "workflows": [],
        }
    )
    database["dashboards_collection"].insert_many(
        [
            {
                "dashboard_id": MAIN_OID,
                "project_id": PROJECT_OID,
                "is_main_tab": True,
                "title": "Overview",
                "stored_metadata": [],
            },
            {
                "dashboard_id": CHILD_OID,
                "project_id": PROJECT_OID,
                "is_main_tab": False,
                "parent_dashboard_id": MAIN_OID,
                "tab_order": 1,
                "title": "Details",
                "stored_metadata": [],
            },
        ]
    )
    database["deltatables_collection"].insert_one(
        {"data_collection_id": DC_OID, "aggregation": [{"aggregation_version": 1}]}
    )
    return database


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> _FakeS3:
    fake = _FakeS3()
    monkeypatch.setattr(public_bundle, "_s3", lambda: fake)
    monkeypatch.setattr(routes_mod, "_s3", lambda: fake)
    monkeypatch.setattr(routes_mod, "_presigned_download_url", lambda *a, **k: None)
    return fake


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Every build a test queues: ``(main tab id, countdown)``."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        public_bundle, "_dispatch", lambda main_id, delay: calls.append((main_id, delay))
    )
    return calls


@pytest.fixture
def reports(monkeypatch: pytest.MonkeyPatch, built) -> dict[str, Any]:
    """The report switches on; renders run in-process with a stand-in that records
    its call, and queued renders are recorded rather than sent."""
    monkeypatch.setattr(settings.notebook_export, "enabled", True)
    monkeypatch.setattr(settings.notebook_export, "render_enabled", True)
    state: dict[str, Any] = {"queued": [], "renders": [], "pdf": b"%PDF-1.7 report"}

    def fake_render(main_id, owner_id):
        state["renders"].append({"main_id": main_id, "owner_id": owner_id})
        return b"<html>report</html>", state["pdf"], "overview"

    monkeypatch.setattr(public_bundle, "_dispatch_report", state["queued"].append)
    monkeypatch.setattr(public_bundle, "_render_report", fake_render)
    return state


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: fake)
    return fake


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch, mongo, s3, dispatched) -> list[dict[str, Any]]:
    """Builds run in-process with a stand-in producer that records its call."""
    calls: list[dict[str, Any]] = []

    def fake_export_static(dashboard_id, out_path=None, **kwargs):
        calls.append({"dashboard_id": dashboard_id, **kwargs})
        title = mongo["dashboards_collection"].find_one({"dashboard_id": MAIN_OID})["title"]
        out_path.write_text(f"<html>{title}</html>")
        return None

    monkeypatch.setattr(public_bundle, "_export_static", fake_export_static)
    return calls


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    # The usage counter writes to the real Mongo; its own test covers it.
    monkeypatch.setattr(routes_mod, "_record_download", lambda dashboard_id, request: None)
    app = FastAPI()
    app.include_router(routes_mod.public_bundle_router, prefix="/serverless")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as(client: TestClient, user: User | None) -> None:
    client.app.dependency_overrides[routes_mod.get_user_or_anonymous] = lambda: user


def _owner() -> User:
    return User(
        id=PyObjectId(str(OWNER_OID)),
        email="owner@example.com",
        password="$2b$12$example.hashed.password.string",
        is_active=True,
        is_verified=True,
    )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def test_a_visitor_downloads_the_built_bundle_and_nothing_is_queued(
    client, built, dispatched, redis, s3
):
    public_bundle.build(str(MAIN_OID))
    dispatched.clear()
    _as(client, None)

    response = client.get(f"/serverless/public-bundle/{MAIN_OID}/download")

    assert response.status_code == 200
    assert response.content == b"<html>Overview</html>"
    assert "attachment" in response.headers["content-disposition"]
    assert dispatched == []


def test_a_child_tab_id_downloads_its_family_bundle(client, built, redis):
    public_bundle.build(str(MAIN_OID))
    _as(client, None)
    assert client.get(f"/serverless/public-bundle/{CHILD_OID}/download").status_code == 200


def test_a_public_s3_endpoint_redirects_to_a_short_presigned_url(
    client, built, redis, monkeypatch: pytest.MonkeyPatch
):
    public_bundle.build(str(MAIN_OID))
    seen: dict[str, Any] = {}

    def presign(bucket, key, expires_in=None, filename=None):
        seen.update(key=key, expires_in=expires_in, filename=filename)
        return "https://s3.example.org/signed"

    monkeypatch.setattr(routes_mod, "_presigned_download_url", presign)
    _as(client, None)
    response = client.get(f"/serverless/public-bundle/{MAIN_OID}/download", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://s3.example.org/signed"
    assert seen["expires_in"] == 300
    assert seen["key"].startswith(f"serverless-public/{MAIN_OID}/")
    assert seen["filename"].endswith(".html")


def test_a_download_is_counted_without_the_visitor(
    client, built, redis, monkeypatch: pytest.MonkeyPatch
):
    public_bundle.build(str(MAIN_OID))
    counted: list[str] = []
    monkeypatch.setattr(
        routes_mod, "_record_download", lambda dashboard_id, request: counted.append(dashboard_id)
    )
    _as(client, None)
    client.get(f"/serverless/public-bundle/{CHILD_OID}/download")
    assert counted == [str(MAIN_OID)]


@pytest.mark.parametrize(
    "case",
    [
        "public_download_off",
        "static_export_off",
        "project_private",
        "project_flag_off",
        "no_bundle_yet",
        "unknown_dashboard",
    ],
)
def test_the_routes_answer_404_alike(
    case, client, built, redis, mongo, monkeypatch: pytest.MonkeyPatch
):
    if case != "no_bundle_yet":
        public_bundle.build(str(MAIN_OID))
    dashboard_id = str(MAIN_OID)
    if case == "public_download_off":
        monkeypatch.setattr(settings.static_export, "public_download_enabled", False)
    elif case == "static_export_off":
        monkeypatch.setattr(settings.static_export, "enabled", False)
    elif case == "project_private":
        mongo["projects_collection"].update_one(
            {"_id": PROJECT_OID}, {"$set": {"is_public": False}}
        )
    elif case == "project_flag_off":
        mongo["projects_collection"].update_one(
            {"_id": PROJECT_OID}, {"$set": {"public_offline_download": False}}
        )
    elif case == "unknown_dashboard":
        dashboard_id = str(ObjectId())
    _as(client, None)
    assert client.get(f"/serverless/public-bundle/{dashboard_id}").status_code == 404
    assert client.get(f"/serverless/public-bundle/{dashboard_id}/download").status_code == 404


# ---------------------------------------------------------------------------
# Per-IP limit, failing closed
# ---------------------------------------------------------------------------


def test_downloads_past_the_per_ip_limit_are_refused(client, built, redis):
    public_bundle.build(str(MAIN_OID))
    _as(client, None)
    url = f"/serverless/public-bundle/{MAIN_OID}/download"
    codes = [client.get(url).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429


@pytest.mark.parametrize("redis_state", ["missing", "broken"])
def test_downloads_answer_503_when_redis_is_unreachable(
    redis_state, client, built, monkeypatch: pytest.MonkeyPatch
):
    public_bundle.build(str(MAIN_OID))
    fake = None if redis_state == "missing" else _FakeRedis(broken=True)
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: fake)
    _as(client, None)
    response = client.get(f"/serverless/public-bundle/{MAIN_OID}/download")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# What a public build is
# ---------------------------------------------------------------------------


def test_a_public_build_runs_as_the_owner_without_an_email_python_or_state(built):
    public_bundle.build(str(MAIN_OID))
    (call,) = built
    assert call["public"] is True
    assert call["python_runtime"] == "off"
    assert call.get("state") is None
    user = call["user"]
    assert str(user.id) == str(OWNER_OID)
    assert user.email == ""
    assert user.is_admin is False


def test_a_build_skips_a_project_that_is_no_longer_eligible(built, mongo, s3):
    mongo["projects_collection"].update_one({"_id": PROJECT_OID}, {"$set": {"is_public": False}})
    public_bundle.build(str(MAIN_OID))
    assert built == []
    assert s3.objects == {}


# ---------------------------------------------------------------------------
# Rebuild after a save or an ingestion
# ---------------------------------------------------------------------------


def test_a_save_schedules_one_coalesced_rebuild(built, dispatched):
    public_bundle.notify_dashboard_changed(str(CHILD_OID), str(PROJECT_OID))
    public_bundle.notify_dashboard_changed(str(MAIN_OID), str(PROJECT_OID))
    assert dispatched == [(str(MAIN_OID), 120)]


def test_an_ingestion_schedules_the_dashboards_that_read_the_project(built, dispatched):
    public_bundle.notify_data_changed(str(DC_OID))
    assert dispatched == [(str(MAIN_OID), 120)]


def test_nothing_is_scheduled_for_a_project_without_the_download(built, dispatched, mongo):
    mongo["projects_collection"].update_one(
        {"_id": PROJECT_OID}, {"$set": {"public_offline_download": False}}
    )
    public_bundle.notify_dashboard_changed(str(MAIN_OID), str(PROJECT_OID))
    public_bundle.notify_data_changed(str(DC_OID))
    assert dispatched == []


def test_the_content_key_moves_with_the_dashboard_and_the_data(built, mongo):
    project = mongo["projects_collection"].find_one({"_id": PROJECT_OID})
    first = public_bundle.content_key(str(MAIN_OID), project)
    assert public_bundle.content_key(str(MAIN_OID), project) == first
    mongo["dashboards_collection"].update_one(
        {"dashboard_id": CHILD_OID}, {"$set": {"title": "Renamed"}}
    )
    second = public_bundle.content_key(str(MAIN_OID), project)
    assert second != first
    mongo["deltatables_collection"].update_one(
        {"data_collection_id": DC_OID}, {"$push": {"aggregation": {"aggregation_version": 2}}}
    )
    assert public_bundle.content_key(str(MAIN_OID), project) != second


def test_the_previous_bundle_is_served_while_the_next_one_builds(
    client, built, dispatched, redis, mongo, s3
):
    public_bundle.build(str(MAIN_OID))
    mongo["dashboards_collection"].update_one(
        {"dashboard_id": MAIN_OID}, {"$set": {"title": "Edited"}}
    )
    public_bundle.notify_dashboard_changed(str(MAIN_OID), str(PROJECT_OID))
    _as(client, None)

    status = client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert status["available"] is True
    assert status["rebuilding"] is True
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}/download").content == (
        b"<html>Overview</html>"
    )

    public_bundle.build(str(MAIN_OID))
    status = client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert status["rebuilding"] is False
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}/download").content == (
        b"<html>Edited</html>"
    )
    # Only the bundle served now and the one before it are kept.
    assert len([k for k in s3.objects if k.startswith(f"serverless-public/{MAIN_OID}/")]) == 2


def test_an_unchanged_key_builds_nothing(built):
    public_bundle.build(str(MAIN_OID))
    public_bundle.build(str(MAIN_OID))
    assert len(built) == 1


def test_the_owner_sees_whether_the_bundle_is_fresh(client, built, mongo, redis):
    public_bundle.build(str(MAIN_OID))
    _as(client, _owner())
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}").json()["fresh"] is True
    mongo["dashboards_collection"].update_one(
        {"dashboard_id": MAIN_OID}, {"$set": {"title": "Edited"}}
    )
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}").json()["fresh"] is False
    _as(client, None)
    assert "fresh" not in client.get(f"/serverless/public-bundle/{MAIN_OID}").json()


def test_dropping_a_project_removes_its_bundles(built, mongo, s3):
    public_bundle.build(str(MAIN_OID))
    assert s3.objects
    public_bundle.drop_project(str(PROJECT_OID))
    assert s3.objects == {}
    assert mongo["public_bundles_collection"].count_documents({}) == 0


# ---------------------------------------------------------------------------
# The report and its PDF
# ---------------------------------------------------------------------------


def test_no_report_is_queued_while_the_instance_does_not_render_reports(
    client, built, redis, monkeypatch: pytest.MonkeyPatch
):
    queued: list[str] = []
    monkeypatch.setattr(public_bundle, "_dispatch_report", queued.append)
    public_bundle.build(str(MAIN_OID))
    assert queued == []
    _as(client, None)
    assert "report" not in client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}/download?file=report").status_code == (
        404
    )


def test_a_built_bundle_queues_its_report_once(reports):
    public_bundle.build(str(MAIN_OID))
    assert reports["queued"] == [str(MAIN_OID)]
    # The same content again: the render already queued covers it.
    public_bundle.build(str(MAIN_OID))
    assert reports["queued"] == [str(MAIN_OID)]


def test_a_visitor_downloads_the_report_and_its_pdf_and_nothing_is_queued(
    client, reports, dispatched, redis
):
    public_bundle.build(str(MAIN_OID))
    public_bundle.build_report(str(MAIN_OID))
    assert reports["renders"] == [{"main_id": str(MAIN_OID), "owner_id": OWNER_OID}]
    dispatched.clear()
    reports["queued"].clear()
    _as(client, None)

    status = client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert status["report"]["available"] is True
    assert status["report"]["pdf_available"] is True
    assert status["report"]["rebuilding"] is False
    assert "status" not in status["report"]

    report = client.get(f"/serverless/public-bundle/{MAIN_OID}/download?file=report")
    assert report.status_code == 200
    assert report.content == b"<html>report</html>"
    assert "-report-dashboard.html" in report.headers["content-disposition"]
    pdf = client.get(f"/serverless/public-bundle/{MAIN_OID}/download?file=pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert dispatched == [] and reports["queued"] == []


def test_a_failed_pdf_leaves_the_report(client, reports, redis):
    reports["pdf"] = None
    public_bundle.build(str(MAIN_OID))
    public_bundle.build_report(str(MAIN_OID))
    _as(client, None)
    status = client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert status["report"]["available"] is True
    assert status["report"]["pdf_available"] is False
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}/download?file=pdf").status_code == 404
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}/download?file=report").status_code == (
        200
    )


def test_a_report_waits_for_its_bundle(reports, dispatched, mongo):
    public_bundle.build(str(MAIN_OID))
    mongo["dashboards_collection"].update_one(
        {"dashboard_id": MAIN_OID}, {"$set": {"title": "Edited"}}
    )
    result = public_bundle.build_report(str(MAIN_OID))
    assert result["status"] == "waiting for the bundle"
    assert reports["renders"] == []
    assert dispatched == [(str(MAIN_OID), 0)]


def test_the_previous_report_is_served_while_the_next_one_renders(
    client, reports, redis, mongo, s3
):
    public_bundle.build(str(MAIN_OID))
    public_bundle.build_report(str(MAIN_OID))
    mongo["dashboards_collection"].update_one(
        {"dashboard_id": MAIN_OID}, {"$set": {"title": "Edited"}}
    )
    public_bundle.build(str(MAIN_OID))
    _as(client, None)
    status = client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert status["report"]["available"] is True
    assert status["report"]["rebuilding"] is True

    public_bundle.build_report(str(MAIN_OID))
    status = client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert status["report"]["rebuilding"] is False
    # Two bundles, two reports and two PDFs: the served ones and those before.
    assert len([k for k in s3.objects if k.startswith(f"serverless-public/{MAIN_OID}/")]) == 6


def test_turning_the_render_off_withdraws_the_report(client, reports, redis, monkeypatch):
    public_bundle.build(str(MAIN_OID))
    public_bundle.build_report(str(MAIN_OID))
    monkeypatch.setattr(settings.notebook_export, "render_enabled", False)
    _as(client, None)
    assert "report" not in client.get(f"/serverless/public-bundle/{MAIN_OID}").json()
    assert client.get(f"/serverless/public-bundle/{MAIN_OID}/download?file=pdf").status_code == 404


def test_dropping_a_project_removes_its_reports(reports, s3):
    public_bundle.build(str(MAIN_OID))
    public_bundle.build_report(str(MAIN_OID))
    assert any(k.endswith("-report.pdf") for k in s3.objects)
    public_bundle.drop_project(str(PROJECT_OID))
    assert s3.objects == {}


def test_a_public_report_has_no_exporter_and_no_author_code(monkeypatch: pytest.MonkeyPatch):
    """The visitor's report plan: default state, no "exported by", the server
    never runs the author's Python and the document carries none of it."""
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export
    from depictio.api.v1.services.notebook_export.generator import ExportPlan
    from depictio.serverless import public_report

    secret = "import os; os.environ['SECRET']"
    seen: dict[str, Any] = {}

    def fake_plan(dashboard_id, state, user, token, **kwargs):
        seen.update(state=state, user=user, kwargs=kwargs)
        return ExportPlan(
            tabs=[
                {
                    "dashboard_id": str(MAIN_OID),
                    "stored_metadata": [
                        {"component_type": "figure", "mode": "code", "code_content": secret}
                    ],
                }
            ],
            project=None,
            state=state,
            stages=[],
            title="Overview",
            exported_by="owner@example.com",
        )

    monkeypatch.setattr(notebook_export, "build_export_plan", fake_plan)
    plan = public_report.public_plan(str(MAIN_OID), public_report._Owner(id=OWNER_OID), "t")

    assert plan.exported_by is None
    assert plan.author_code is False
    assert secret not in repr(plan.tabs)
    assert seen["user"].email == ""
    assert seen["state"].filters_as_payload() == []
    assert seen["kwargs"]["embed_runtime"] is True and seen["kwargs"]["pdf"] is True


# ---------------------------------------------------------------------------
# The offer: on by default, the owner's choice wins
# ---------------------------------------------------------------------------


def test_a_public_project_offers_its_copies_until_its_owner_decides(
    mongo, monkeypatch: pytest.MonkeyPatch
):
    project = mongo["projects_collection"].find_one({"_id": PROJECT_OID})
    project.pop("public_offline_download")
    monkeypatch.setattr(settings.static_export, "public_download_default", True)
    assert public_bundle.eligible(project) is True
    assert public_bundle.eligible({**project, "public_offline_download": False}) is False
    monkeypatch.setattr(settings.static_export, "public_download_default", False)
    assert public_bundle.eligible(project) is False
    assert public_bundle.eligible({**project, "public_offline_download": True}) is True
    assert public_bundle.eligible(
        {**project, "public_offline_download": True, "is_public": False}
    ) is (False)


def test_an_ingestion_reaches_a_project_offering_by_default(
    built, dispatched, mongo, monkeypatch: pytest.MonkeyPatch
):
    mongo["projects_collection"].update_one(
        {"_id": PROJECT_OID}, {"$unset": {"public_offline_download": ""}}
    )
    monkeypatch.setattr(settings.static_export, "public_download_default", True)
    public_bundle.notify_data_changed(str(DC_OID))
    assert dispatched == [(str(MAIN_OID), 120)]


def test_missing_copies_are_queued_once(built, dispatched, mongo, monkeypatch: pytest.MonkeyPatch):
    """At startup: every offered public dashboard without a copy, once, whatever
    the number of API workers that ask."""
    mongo["projects_collection"].update_one(
        {"_id": PROJECT_OID}, {"$unset": {"public_offline_download": ""}}
    )
    monkeypatch.setattr(settings.static_export, "public_download_default", True)
    assert public_bundle.schedule_missing() == 1
    assert public_bundle.schedule_missing() == 0
    assert dispatched == [(str(MAIN_OID), 120)]
    public_bundle.build(str(MAIN_OID))
    dispatched.clear()
    assert public_bundle.schedule_missing() == 0
    assert dispatched == []
