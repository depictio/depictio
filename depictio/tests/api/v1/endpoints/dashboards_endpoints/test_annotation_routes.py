"""Per-user session annotation endpoints.

Route functions are exercised directly with a mongomock-backed Beanie and a
fake dashboards collection, as in ``test_filter_state_routes.py``.
"""

import functools
from typing import cast

import pytest
from beanie import init_beanie
from bson import ObjectId
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.api.v1.endpoints.dashboards_endpoints import annotation_routes
from depictio.api.v1.endpoints.dashboards_endpoints.annotation_routes import (
    delete_annotations,
    get_annotation_tables,
    get_annotations,
    put_annotations,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboard_annotations import (
    DashboardAnnotationsBeanie,
    DashboardAnnotationsPayload,
)
from depictio.models.models.users import UserBase

MAIN_ID = PyObjectId()
CHILD_ID = PyObjectId()
FORBIDDEN_ID = PyObjectId()
PROJECT_ID = ObjectId()
FORBIDDEN_PROJECT_ID = ObjectId()
SHEET_ID = "646b0f3c1e4a2d7f5c8e9a01"
STATS_ID = "646b0f3c1e4a2d7f5c8e9a02"


def beanie_setup(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        client = AsyncMongoMockClient()
        await init_beanie(
            database=cast(AsyncDatabase, client.test_db),
            document_models=[DashboardAnnotationsBeanie],
        )
        return await func(*args, **kwargs)

    return pytest.mark.asyncio(wrapper)


class _FakeDashboards:
    def __init__(self):
        self.docs = {
            ObjectId(str(MAIN_ID)): {"project_id": PROJECT_ID},
            ObjectId(str(CHILD_ID)): {
                "project_id": PROJECT_ID,
                "parent_dashboard_id": ObjectId(str(MAIN_ID)),
            },
            ObjectId(str(FORBIDDEN_ID)): {"project_id": FORBIDDEN_PROJECT_ID},
        }

    def find_one(self, query, projection=None):
        doc = self.docs.get(query.get("dashboard_id"))
        return {"dashboard_id": query["dashboard_id"], **doc} if doc else None


class _FakeProjects:
    doc = {
        "_id": PROJECT_ID,
        "workflows": [
            {
                "name": "wf",
                "data_collections": [
                    {
                        "_id": SHEET_ID,
                        "data_collection_tag": "samplesheet",
                        "config": {"type": "table"},
                    },
                    {
                        "_id": STATS_ID,
                        "data_collection_tag": "stats",
                        "config": {"type": "table", "metatype": "Aggregate"},
                    },
                ],
            }
        ],
        "links": [
            {"source_dc_id": SHEET_ID, "source_column": "sample", "target_dc_id": STATS_ID},
            {"source_dc_id": STATS_ID, "source_column": "sample", "target_dc_id": SHEET_ID},
        ],
        "joins": [],
    }

    def find_one(self, query, projection=None):
        return self.doc if query.get("_id") == PROJECT_ID else None


class _Settings:
    class auth:
        is_single_user_mode = False


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setattr(annotation_routes, "dashboards_collection", _FakeDashboards())
    monkeypatch.setattr(annotation_routes, "projects_collection", _FakeProjects())
    monkeypatch.setattr(
        annotation_routes,
        "annotatable_tables",
        lambda project: annotation_routes.classify_tables(project, lambda _dc_id: 12),
    )
    monkeypatch.setattr(
        annotation_routes,
        "check_project_permission",
        lambda project_id, user, level: project_id != FORBIDDEN_PROJECT_ID,
    )
    settings = _Settings()
    settings.auth.is_single_user_mode = False
    monkeypatch.setattr(annotation_routes, "settings", settings)
    return settings


def _user(email="alice@example.com", **kwargs) -> UserBase:
    return UserBase(id=PyObjectId(), email=email, **kwargs)


def _payload(label="responder", dc_id=SHEET_ID, key="sample") -> DashboardAnnotationsPayload:
    return DashboardAnnotationsPayload.model_validate(
        {
            "version": 2,
            "columns": [
                {
                    "id": "c1",
                    "name": "response",
                    "dcId": dc_id,
                    "keyColumn": key,
                    "values": {"S1": label},
                }
            ],
            "activeColumnId": "c1",
        }
    )


class TestRoundTrip:
    @beanie_setup
    async def test_absent_is_empty_not_404(self):
        out = await get_annotations(MAIN_ID, _user())
        assert out == {"annotations": None, "updated_at": None, "persisted": False}

    @beanie_setup
    async def test_put_then_get(self):
        user = _user()
        put = await put_annotations(MAIN_ID, _payload(), user)
        assert put["persisted"] is True
        out = await get_annotations(MAIN_ID, user)
        assert out["persisted"] is True
        assert out["annotations"]["columns"][0]["keyColumn"] == "sample"
        assert out["annotations"]["columns"][0]["values"] == {"S1": "responder"}

    @beanie_setup
    async def test_put_replaces(self):
        user = _user()
        await put_annotations(MAIN_ID, _payload("a"), user)
        await put_annotations(MAIN_ID, _payload("b"), user)
        out = await get_annotations(MAIN_ID, user)
        assert out["annotations"]["columns"][0]["values"] == {"S1": "b"}
        assert await DashboardAnnotationsBeanie.find_all().count() == 1

    @beanie_setup
    async def test_child_tab_reaches_the_family_document(self):
        user = _user()
        await put_annotations(CHILD_ID, _payload(), user)
        out = await get_annotations(MAIN_ID, user)
        assert out["persisted"] is True
        doc = await DashboardAnnotationsBeanie.find_one()
        assert doc is not None and str(doc.dashboard_id) == str(MAIN_ID)

    @beanie_setup
    async def test_old_shape_reads_as_absent(self):
        user = _user()
        await DashboardAnnotationsBeanie.get_pymongo_collection().insert_one(
            {
                "user_id": ObjectId(str(user.id)),
                "dashboard_id": ObjectId(str(MAIN_ID)),
                "annotations": {"version": 1, "dc_id": SHEET_ID, "key_column": "s", "columns": []},
                "updated_at": None,
            }
        )
        out = await get_annotations(MAIN_ID, user)
        assert out["persisted"] is False


class TestTables:
    @beanie_setup
    async def test_lists_tables_with_their_verdict(self):
        out = await get_annotation_tables(MAIN_ID, _user())
        tables = {t["tag"]: t for t in out["tables"]}
        assert tables["samplesheet"]["eligible"] is True
        assert tables["samplesheet"]["key_columns"] == ["sample"]
        assert tables["stats"]["code"] == "not_metadata"

    @beanie_setup
    async def test_open_to_a_temporary_account(self):
        out = await get_annotation_tables(CHILD_ID, _user(is_temporary=True))
        assert len(out["tables"]) == 2

    @beanie_setup
    async def test_needs_read_access(self):
        with pytest.raises(HTTPException) as exc:
            await get_annotation_tables(FORBIDDEN_ID, _user())
        assert exc.value.status_code == 403

    @beanie_setup
    async def test_put_refuses_a_table_that_cannot_be_labelled(self):
        with pytest.raises(HTTPException) as exc:
            await put_annotations(MAIN_ID, _payload(dc_id=STATS_ID), _user())
        assert exc.value.status_code == 422
        assert "metadata table" in exc.value.detail

    @beanie_setup
    async def test_put_refuses_an_unknown_table(self):
        with pytest.raises(HTTPException) as exc:
            await put_annotations(MAIN_ID, _payload(dc_id="0" * 24), _user())
        assert exc.value.status_code == 422

    @beanie_setup
    async def test_put_refuses_a_key_no_link_uses(self):
        with pytest.raises(HTTPException) as exc:
            await put_annotations(MAIN_ID, _payload(key="other"), _user())
        assert exc.value.status_code == 422
        assert await DashboardAnnotationsBeanie.find_all().count() == 0


class TestOwnDocumentOnly:
    @beanie_setup
    async def test_other_user_sees_nothing(self):
        await put_annotations(MAIN_ID, _payload(), _user("alice@example.com"))
        out = await get_annotations(MAIN_ID, _user("bob@example.com"))
        assert out["persisted"] is False

    @beanie_setup
    async def test_delete_only_removes_own(self):
        alice, bob = _user("alice@example.com"), _user("bob@example.com")
        await put_annotations(MAIN_ID, _payload(), alice)
        await put_annotations(MAIN_ID, _payload(), bob)
        await delete_annotations(MAIN_ID, alice)
        assert (await get_annotations(MAIN_ID, alice))["persisted"] is False
        assert (await get_annotations(MAIN_ID, bob))["persisted"] is True


class TestAccess:
    @beanie_setup
    async def test_unknown_dashboard_404(self):
        with pytest.raises(HTTPException) as exc:
            await get_annotations(PyObjectId(), _user())
        assert exc.value.status_code == 404

    @pytest.mark.parametrize("call", ["get", "put", "delete"])
    @beanie_setup
    async def test_no_read_access_403_on_every_call(self, call):
        user = _user()
        with pytest.raises(HTTPException) as exc:
            if call == "get":
                await get_annotations(FORBIDDEN_ID, user)
            elif call == "put":
                await put_annotations(FORBIDDEN_ID, _payload(), user)
            else:
                await delete_annotations(FORBIDDEN_ID, user)
        assert exc.value.status_code == 403

    @beanie_setup
    async def test_access_lost_after_save_403(self, monkeypatch):
        user = _user()
        await put_annotations(MAIN_ID, _payload(), user)
        monkeypatch.setattr(
            annotation_routes, "check_project_permission", lambda project_id, user, level: False
        )
        with pytest.raises(HTTPException) as exc:
            await get_annotations(MAIN_ID, user)
        assert exc.value.status_code == 403


class TestAccountKinds:
    @pytest.mark.parametrize("kind", [{"is_temporary": True}, {"is_anonymous": True}])
    @beanie_setup
    async def test_temporary_and_anonymous_refused(self, kind):
        user = _user(**kind)
        for call in (
            get_annotations(MAIN_ID, user),
            put_annotations(MAIN_ID, _payload(), user),
            delete_annotations(MAIN_ID, user),
        ):
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.status_code == 403
        assert await DashboardAnnotationsBeanie.find_all().count() == 0

    @beanie_setup
    async def test_temporary_refused_even_in_single_user_mode(self, environment):
        environment.auth.is_single_user_mode = True
        with pytest.raises(HTTPException) as exc:
            await get_annotations(MAIN_ID, _user(is_temporary=True))
        assert exc.value.status_code == 403

    @beanie_setup
    async def test_single_user_mode_stores_for_the_shared_user(self, environment):
        environment.auth.is_single_user_mode = True
        user = _user("anonymous@depictio.io", is_anonymous=True)
        await put_annotations(MAIN_ID, _payload(), user)
        assert (await get_annotations(MAIN_ID, user))["persisted"] is True


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_path_resolves_to_the_annotation_routes(method):
    """No earlier `/dashboards/{...}` route captures the path: a temporary
    account gets this module's own refusal, before any database call."""
    from fastapi.testclient import TestClient

    from depictio.api.main import app
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    app.dependency_overrides[get_user_or_anonymous] = lambda: _user(is_temporary=True)
    try:
        body = _payload().model_dump(by_alias=True) if method == "PUT" else None
        resp = TestClient(app).request(
            method, f"/depictio/api/v1/dashboards/annotations/{MAIN_ID}", json=body
        )
    finally:
        app.dependency_overrides.pop(get_user_or_anonymous, None)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "A temporary account keeps its annotations in the browser."


def test_tables_path_resolves_to_the_annotation_routes():
    from fastapi.testclient import TestClient

    from depictio.api.main import app
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    app.dependency_overrides[get_user_or_anonymous] = lambda: _user(is_temporary=True)
    try:
        resp = TestClient(app).get(f"/depictio/api/v1/dashboards/annotations/{MAIN_ID}/tables")
    finally:
        app.dependency_overrides.pop(get_user_or_anonymous, None)
    assert resp.status_code == 200
    assert {t["tag"] for t in resp.json()["tables"]} == {"samplesheet", "stats"}
