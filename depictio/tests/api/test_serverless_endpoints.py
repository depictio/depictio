"""Tests for the serverless static-export HTTP surface (producer C).

Everything runs offline: a mini FastAPI app mounts the real router, Mongo
collections are dict-backed fakes monkeypatched onto the routes module, and
Celery/S3 are replaced by recording stubs. The permission gate is exercised
against the *real* ``check_project_permission`` over a fake projects
collection, so the owner rule is genuinely tested rather than mocked away.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.serverless_endpoints import routes as routes_mod
from depictio.models.models.base import PyObjectId
from depictio.models.models.serverless import ComponentTier, TierReason
from depictio.models.models.users import User
from depictio.serverless.preflight import LinkRow, TabRow, TierRow
from depictio.serverless.producer_a import ExportResult, ProducerAError

DASHBOARD_OID = ObjectId("6824cb3b89d2b72169309737")
PROJECT_OID = ObjectId("646b0f3c1e4a2d7f8e5b8c9d")
OWNER_OID = ObjectId("507f1f77bcf86cd799439011")
OTHER_OID = ObjectId("507f1f77bcf86cd799439012")
ADMIN_OID = ObjectId("507f1f77bcf86cd799439013")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCollection:
    """Read-only dict-list collection (dashboards / projects)."""

    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def find_one(self, query: dict[str, Any], projection: Any = None) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None


class _FakeJobs:
    """Minimal ``static_exports`` stand-in (``_id``-keyed)."""

    def __init__(self, docs: list[dict[str, Any]] | None = None):
        self.docs: dict[str, dict[str, Any]] = {d["_id"]: dict(d) for d in (docs or [])}

    def find_one(self, query: dict[str, Any], projection: Any = None) -> dict[str, Any] | None:
        return self.docs.get(query.get("_id"))

    def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs[doc["_id"]] = dict(doc)

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        doc = self.docs.get(query.get("_id"))
        if doc is not None:
            doc.update(update.get("$set", {}))


class _FakeTask:
    def __init__(self, task_id: str = "task-123"):
        self.task_id = task_id
        self.calls: list[list[Any]] = []

    def apply_async(self, args: list[Any]):
        self.calls.append(args)
        return type("_R", (), {"id": self.task_id})()


class _FakeAsyncResult:
    """Stand-in for ``celery.result.AsyncResult`` (constructed as ``(id, app=...)``)."""

    def __init__(self, ready: bool, successful: bool = True, result: Any = None, traceback=None):
        self._ready = ready
        self._successful = successful
        self.result = result
        self.traceback = traceback
        self.state = "SUCCESS" if successful else "FAILURE"

    def as_factory(self):
        outer = self

        def _factory(task_id, app=None):
            return outer

        return _factory

    def ready(self) -> bool:
        return self._ready

    def successful(self) -> bool:
        return self._successful


class _FakeBody:
    def __init__(self, payload: bytes):
        self.payload = payload

    def iter_chunks(self, chunk_size: int = 8192):
        for i in range(0, len(self.payload), chunk_size):
            yield self.payload[i : i + chunk_size]


class _FakeS3:
    def __init__(self, payload: bytes = b"<html>bundle</html>"):
        self.payload = payload
        self.get_calls: list[tuple[str, str]] = []
        self.put_calls: list[dict[str, Any]] = []

    def get_object(self, Bucket: str, Key: str):
        self.get_calls.append((Bucket, Key))
        return {"Body": _FakeBody(self.payload)}

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _user(oid: ObjectId, *, is_admin: bool = False) -> User:
    return User(
        id=PyObjectId(str(oid)),
        email=f"{oid}@example.com",
        password="$2b$12$example.hashed.password.string",
        is_admin=is_admin,
        is_active=True,
        is_verified=True,
    )


@pytest.fixture
def owner() -> User:
    return _user(OWNER_OID)


@pytest.fixture
def stranger() -> User:
    return _user(OTHER_OID)


@pytest.fixture
def admin() -> User:
    return _user(ADMIN_OID, is_admin=True)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_mod.serverless_endpoint_router, prefix="/serverless")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _as_user(client: TestClient, user: User) -> None:
    client.app.dependency_overrides[routes_mod.get_user_or_anonymous] = lambda: user


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> _FakeJobs:
    fake = _FakeJobs()
    monkeypatch.setattr(routes_mod, "static_exports_collection", fake)
    return fake


@pytest.fixture
def dashboards(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        routes_mod,
        "dashboards_collection",
        _FakeCollection([{"dashboard_id": DASHBOARD_OID, "project_id": PROJECT_OID}]),
    )


def _patch_project(monkeypatch: pytest.MonkeyPatch, owners: list[ObjectId]) -> None:
    """Point the REAL ``check_project_permission`` at a fake private project."""
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dashboards_routes_mod

    monkeypatch.setattr(
        dashboards_routes_mod,
        "projects_collection",
        _FakeCollection(
            [
                {
                    "_id": PROJECT_OID,
                    "is_public": False,
                    "permissions": {
                        "owners": [{"_id": oid} for oid in owners],
                        "editors": [],
                        "viewers": [],
                    },
                }
            ]
        ),
    )


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


MAIN_TAB_ID = str(DASHBOARD_OID)
CHILD_TAB_ID = "6824cb3b89d2b72169309741"


def _fake_export_result() -> ExportResult:
    """A two-tab family: one live component on the main tab, one omitted
    compute on the child — the shape the preflight endpoint reshapes."""
    return ExportResult(
        manifest=None,
        tier_rows=[
            TierRow("c1", "Card", "card", ComponentTier.LIVE, tab_id=MAIN_TAB_ID),
            TierRow(
                "c2",
                "Heatmap",
                "advanced_viz",
                ComponentTier.OMITTED,
                TierReason.CELERY_COMPUTE,
                "needs a Celery worker",
                tab_id=CHILD_TAB_ID,
            ),
        ],
        link_rows=[
            LinkRow("l1", "dcA", "dcB", "exact", "tier B", True, 42, "precomputed"),
        ],
        tabs=[
            TabRow(MAIN_TAB_ID, "Overview", 0, True),
            TabRow(CHILD_TAB_ID, "Clusters", 2, False),
        ],
    )


def test_preflight_happy_path(client, owner, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def fake_export_static(dashboard_id, out_path=None, mode=None, check=False, user=None):
        captured.update(dashboard_id=dashboard_id, check=check, user=user)
        return _fake_export_result()

    monkeypatch.setattr(routes_mod, "export_static", fake_export_static)
    _as_user(client, owner)

    resp = client.get(f"/serverless/export-static/{DASHBOARD_OID}/preflight")

    assert resp.status_code == 200
    assert captured["check"] is True
    assert captured["user"] is owner
    assert resp.json() == {
        "dashboard_id": str(DASHBOARD_OID),
        "tiers": [
            {
                "component_id": "c1",
                "title": "Card",
                "component_type": "card",
                "tier": "live",
                "reason": None,
                "detail": None,
                "tab_id": MAIN_TAB_ID,
                "provisional": False,
            },
            {
                "component_id": "c2",
                "title": "Heatmap",
                "component_type": "advanced_viz",
                "tier": "omitted",
                "reason": "celery_compute",
                "detail": "needs a Celery worker",
                "tab_id": CHILD_TAB_ID,
                "provisional": False,
            },
        ],
        "tabs": [
            {
                "id": MAIN_TAB_ID,
                "title": "Overview",
                "tab_order": 0,
                "is_main_tab": True,
                "counts": {"live": 1, "partial": 0, "frozen": 0, "omitted": 0},
            },
            {
                "id": CHILD_TAB_ID,
                "title": "Clusters",
                "tab_order": 2,
                "is_main_tab": False,
                "counts": {"live": 0, "partial": 0, "frozen": 0, "omitted": 1},
            },
        ],
        "links": [
            {
                "link_id": "l1",
                "source": "dcA",
                "target": "dcB",
                "resolver": "exact",
                "tier": "tier B",
                "enabled": True,
                "entries": 42,
                "note": "precomputed",
            }
        ],
        "counts": {"live": 1, "partial": 0, "frozen": 0, "omitted": 1},
    }


def test_preflight_producer_error_is_404(client, stranger, monkeypatch: pytest.MonkeyPatch):
    def boom(*args, **kwargs):
        raise ProducerAError("permission denied: exporting needs 'viewer'")

    monkeypatch.setattr(routes_mod, "export_static", boom)
    _as_user(client, stranger)

    resp = client.get(f"/serverless/export-static/{DASHBOARD_OID}/preflight")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Dashboard not found or access denied"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_dispatch_creates_job_and_enqueues(
    client, owner, jobs, dashboards, monkeypatch: pytest.MonkeyPatch
):
    _patch_project(monkeypatch, [OWNER_OID])
    task = _FakeTask()
    monkeypatch.setattr(routes_mod, "export_static_bundle_task", task)
    _as_user(client, owner)

    resp = client.post(f"/serverless/export-static/{DASHBOARD_OID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    job_id = body["job_id"]

    assert task.calls == [
        [
            {
                "job_id": job_id,
                "dashboard_id": str(DASHBOARD_OID),
                "user": {
                    "id": str(OWNER_OID),
                    "email": owner.email,
                    "is_admin": False,
                    "is_anonymous": False,
                },
            }
        ]
    ]
    doc = jobs.docs[job_id]
    assert doc["dashboard_id"] == str(DASHBOARD_OID)
    assert doc["user_id"] == str(OWNER_OID)
    assert doc["status"] == "pending"
    assert doc["celery_task_id"] == task.task_id
    assert isinstance(doc["created_at"], datetime)


def test_dispatch_non_owner_is_404_without_dispatch(
    client, stranger, jobs, dashboards, monkeypatch: pytest.MonkeyPatch
):
    _patch_project(monkeypatch, [OWNER_OID])  # stranger is not an owner
    task = _FakeTask()
    monkeypatch.setattr(routes_mod, "export_static_bundle_task", task)
    _as_user(client, stranger)

    resp = client.post(f"/serverless/export-static/{DASHBOARD_OID}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Dashboard not found or access denied"
    assert task.calls == []
    assert jobs.docs == {}


def test_dispatch_unknown_dashboard_is_404(
    client, owner, jobs, dashboards, monkeypatch: pytest.MonkeyPatch
):
    task = _FakeTask()
    monkeypatch.setattr(routes_mod, "export_static_bundle_task", task)
    _as_user(client, owner)

    resp = client.post(f"/serverless/export-static/{ObjectId()}")

    assert resp.status_code == 404
    assert task.calls == []


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _pending_job(job_id: str = "job-1", *, user_id: ObjectId = OWNER_OID, task_id="task-123"):
    return {
        "_id": job_id,
        "dashboard_id": str(DASHBOARD_OID),
        "user_id": str(user_id),
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "celery_task_id": task_id,
    }


_RESULT = {
    "s3_key": f"serverless-exports/{DASHBOARD_OID}/20260101T101112Z.html",
    "bucket": "depictio-bucket",
    "size_bytes": 4321,
    "built_at": "2026-01-01T10:11:12+00:00",
}


def test_status_pending_passthrough(client, owner, jobs, monkeypatch: pytest.MonkeyPatch):
    jobs.insert_one(_pending_job())
    monkeypatch.setattr(routes_mod, "AsyncResult", _FakeAsyncResult(ready=False).as_factory())
    _as_user(client, owner)

    resp = client.get("/serverless/export-static/status/job-1")
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job-1", "status": "pending"}
    assert jobs.docs["job-1"]["status"] == "pending"


def test_status_transitions_to_done(client, owner, jobs, monkeypatch: pytest.MonkeyPatch):
    jobs.insert_one(_pending_job())
    monkeypatch.setattr(
        routes_mod,
        "AsyncResult",
        _FakeAsyncResult(ready=True, successful=True, result=dict(_RESULT)).as_factory(),
    )
    monkeypatch.setattr(routes_mod, "_presigned_download_url", lambda bucket, key: None)
    _as_user(client, owner)

    resp = client.get("/serverless/export-static/status/job-1")

    assert resp.status_code == 200
    assert resp.json() == {
        "job_id": "job-1",
        "status": "done",
        "result": {**_RESULT, "download_url": None},
        "error": None,
    }
    stored = jobs.docs["job-1"]
    assert stored["status"] == "done"
    assert stored["result"] == _RESULT
    assert isinstance(stored["completed_at"], datetime)


def test_status_transitions_to_failed(client, owner, jobs, monkeypatch: pytest.MonkeyPatch):
    jobs.insert_one(_pending_job())
    monkeypatch.setattr(
        routes_mod,
        "AsyncResult",
        _FakeAsyncResult(
            ready=True, successful=False, result=RuntimeError("static-runtime bundle not built")
        ).as_factory(),
    )
    _as_user(client, owner)

    resp = client.get("/serverless/export-static/status/job-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert "static-runtime bundle not built" in body["error"]
    assert jobs.docs["job-1"]["status"] == "failed"


def test_status_failed_without_result_falls_back_to_traceback(
    client, owner, jobs, monkeypatch: pytest.MonkeyPatch
):
    jobs.insert_one(_pending_job())
    monkeypatch.setattr(
        routes_mod,
        "AsyncResult",
        _FakeAsyncResult(
            ready=True,
            successful=False,
            result=None,
            traceback="Traceback...\nProducerBError: template missing\n",
        ).as_factory(),
    )
    _as_user(client, owner)

    resp = client.get("/serverless/export-static/status/job-1")
    assert resp.json()["error"] == "ProducerBError: template missing"


def test_status_foreign_job_is_404(client, stranger, jobs):
    jobs.insert_one(_pending_job())
    _as_user(client, stranger)

    resp = client.get("/serverless/export-static/status/job-1")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"


def test_status_unknown_job_is_404(client, owner, jobs):
    _as_user(client, owner)
    resp = client.get("/serverless/export-static/status/nope")
    assert resp.status_code == 404


def test_status_admin_sees_foreign_job(client, admin, jobs, monkeypatch: pytest.MonkeyPatch):
    jobs.insert_one(_pending_job())
    monkeypatch.setattr(routes_mod, "AsyncResult", _FakeAsyncResult(ready=False).as_factory())
    _as_user(client, admin)

    resp = client.get("/serverless/export-static/status/job-1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def test_download_not_ready_is_409(client, owner, jobs, monkeypatch: pytest.MonkeyPatch):
    jobs.insert_one(_pending_job())
    monkeypatch.setattr(routes_mod, "AsyncResult", _FakeAsyncResult(ready=False).as_factory())
    _as_user(client, owner)

    resp = client.get("/serverless/export-static/download/job-1")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Export not ready"}


def test_download_streams_artifact(client, owner, jobs, monkeypatch: pytest.MonkeyPatch):
    jobs.insert_one({**_pending_job(), "status": "done", "result": dict(_RESULT)})
    fake_s3 = _FakeS3(b"<html>bundle</html>")
    monkeypatch.setattr(routes_mod, "s3_client", fake_s3)
    _as_user(client, owner)

    resp = client.get("/serverless/export-static/download/job-1")

    assert resp.status_code == 200
    assert resp.content == b"<html>bundle</html>"
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["content-disposition"] == (
        f'attachment; filename="depictio-dashboard-{DASHBOARD_OID}-20260101T101112Z.html"'
    )
    assert fake_s3.get_calls == [("depictio-bucket", _RESULT["s3_key"])]


def test_download_foreign_job_is_404(client, stranger, jobs):
    jobs.insert_one({**_pending_job(), "status": "done", "result": dict(_RESULT)})
    _as_user(client, stranger)

    resp = client.get("/serverless/export-static/download/job-1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Presign helper
# ---------------------------------------------------------------------------


def test_presign_returns_url_when_public_url_set(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.minio, "public_url", "https://s3.example.com")

    class _FakeBoto:
        @staticmethod
        def client(*args, **kwargs):
            assert kwargs["endpoint_url"] == "https://s3.example.com"

            class _C:
                @staticmethod
                def generate_presigned_url(op, Params, ExpiresIn):
                    assert op == "get_object"
                    assert ExpiresIn == 86400
                    return f"https://s3.example.com/{Params['Bucket']}/{Params['Key']}?sig=x"

            return _C()

    monkeypatch.setattr(routes_mod, "boto3", _FakeBoto)
    url = routes_mod._presigned_download_url("depictio-bucket", "serverless-exports/a.html")
    assert url == "https://s3.example.com/depictio-bucket/serverless-exports/a.html?sig=x"


def test_presign_returns_none_for_internal_only_minio(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.minio, "public_url", None)
    monkeypatch.setattr(settings.minio, "external_service", False)

    assert routes_mod._presigned_download_url("depictio-bucket", "a.html") is None


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


def test_export_task_uploads_bundle(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1 import s3 as s3_mod
    from depictio.api.v1.celery_tasks import export_static_bundle
    from depictio.api.v1.configs.config import settings
    from depictio.serverless import producer_a as producer_a_mod

    captured: dict[str, Any] = {}

    def fake_export_static(
        dashboard_id, out_path=None, mode=None, check=False, user=None, single_tab=False
    ):
        captured.update(dashboard_id=dashboard_id, user=user, single_tab=single_tab)
        Path(out_path).write_text("<html>hi</html>", encoding="utf-8")
        return _fake_export_result()

    monkeypatch.setattr(producer_a_mod, "export_static", fake_export_static)
    fake_s3 = _FakeS3()
    monkeypatch.setattr(s3_mod, "s3_client", fake_s3)

    result = export_static_bundle(
        {
            "job_id": "job-1",
            "dashboard_id": str(DASHBOARD_OID),
            "user": {
                "id": str(OWNER_OID),
                "email": "o@example.com",
                "is_admin": False,
                "is_anonymous": False,
            },
        }
    )

    assert captured["dashboard_id"] == str(DASHBOARD_OID)
    assert captured["user"].id == str(OWNER_OID)
    assert captured["single_tab"] is False  # the family is the default
    assert result["bucket"] == settings.minio.bucket
    assert result["size_bytes"] == len("<html>hi</html>")
    assert result["tab_count"] == 2
    assert result["s3_key"].startswith(f"serverless-exports/{DASHBOARD_OID}/")
    assert result["s3_key"].endswith(".html")
    datetime.fromisoformat(result["built_at"])

    (put,) = fake_s3.put_calls
    assert put["Key"] == result["s3_key"]
    assert put["Bucket"] == settings.minio.bucket
    assert put["ContentType"] == "text/html; charset=utf-8"
    assert put["Body"] == b"<html>hi</html>"


def test_export_task_propagates_missing_template(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1 import s3 as s3_mod
    from depictio.api.v1.celery_tasks import export_static_bundle
    from depictio.serverless import producer_a as producer_a_mod
    from depictio.serverless.producer_b import ProducerBError

    def boom(*args, **kwargs):
        raise ProducerBError("static-runtime bundle not built")

    monkeypatch.setattr(producer_a_mod, "export_static", boom)
    fake_s3 = _FakeS3()
    monkeypatch.setattr(s3_mod, "s3_client", fake_s3)

    with pytest.raises(ProducerBError, match="not built"):
        export_static_bundle(
            {
                "job_id": "job-1",
                "dashboard_id": str(DASHBOARD_OID),
                "user": {
                    "id": str(OWNER_OID),
                    "email": "o@example.com",
                    "is_admin": False,
                    "is_anonymous": False,
                },
            }
        )
    assert fake_s3.put_calls == []


# ---------------------------------------------------------------------------
# Template override
# ---------------------------------------------------------------------------


def test_template_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from depictio.serverless import producer_b

    assert producer_b._template_path() == producer_b.TEMPLATE_PATH

    custom = tmp_path / "static.html"
    custom.write_text("__BUNDLE_MANIFEST__", encoding="utf-8")
    monkeypatch.setenv(producer_b.TEMPLATE_PATH_ENV, str(custom))
    assert producer_b._template_path() == custom

    monkeypatch.delenv(producer_b.TEMPLATE_PATH_ENV)
    assert producer_b._template_path() == producer_b.TEMPLATE_PATH
