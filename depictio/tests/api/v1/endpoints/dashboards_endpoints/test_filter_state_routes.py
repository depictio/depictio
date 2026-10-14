"""Per-user dashboard filter-state endpoints.

The route functions are exercised directly (no HTTP) with a mongomock-backed
Beanie and monkeypatched dashboard-lookup/permission helpers, mirroring the
approach of the user_endpoints tests.
"""

import functools
from typing import cast

import pytest
from beanie import init_beanie
from bson import ObjectId
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.api.v1.endpoints.dashboards_endpoints import filter_state_routes
from depictio.api.v1.endpoints.dashboards_endpoints.filter_state_routes import (
    delete_filter_state,
    get_filter_state,
    put_filter_state,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboard_filter_state import (
    DashboardFilterStateBeanie,
    DashboardFilterStatePayload,
)
from depictio.models.models.users import UserBase

DASHBOARD_ID = PyObjectId()
PROJECT_ID = ObjectId()


def beanie_setup(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        client = AsyncMongoMockClient()
        await init_beanie(
            database=cast(AsyncDatabase, client.test_db),
            document_models=[DashboardFilterStateBeanie],
        )
        return await func(*args, **kwargs)

    return pytest.mark.asyncio(wrapper)


class _FakeDashboards:
    """Stand-in for the sync pymongo dashboards collection."""

    def __init__(self, known_ids: set[ObjectId]):
        self.known_ids = known_ids

    def find_one(self, query, projection=None):
        if query.get("dashboard_id") in self.known_ids:
            return {"dashboard_id": query["dashboard_id"], "project_id": PROJECT_ID}
        return None


@pytest.fixture(autouse=True)
def dashboard_exists(monkeypatch):
    monkeypatch.setattr(
        filter_state_routes,
        "dashboards_collection",
        _FakeDashboards({ObjectId(str(DASHBOARD_ID))}),
    )
    monkeypatch.setattr(
        filter_state_routes, "check_project_permission", lambda project_id, user, level: True
    )


def _user(email="alice@example.com", **kwargs) -> UserBase:
    return UserBase(id=PyObjectId(), email=email, **kwargs)


SAMPLE_FILTERS = [
    {"index": "abc", "value": ["a"], "column_name": "col"},
    {"index": "def", "value": ["p1", "p2"], "source": "scatter_selection"},
]


class TestGet:
    @beanie_setup
    async def test_no_state_yet_is_a_normal_answer(self):
        res = await get_filter_state(DASHBOARD_ID, _user())
        assert res == {"filters": [], "enabled": True, "updated_at": None, "persisted": False}

    @beanie_setup
    async def test_missing_dashboard_404(self, monkeypatch):
        monkeypatch.setattr(filter_state_routes, "dashboards_collection", _FakeDashboards(set()))
        with pytest.raises(HTTPException) as exc:
            await get_filter_state(DASHBOARD_ID, _user())
        assert exc.value.status_code == 404

    @beanie_setup
    async def test_no_viewer_permission_403(self, monkeypatch):
        monkeypatch.setattr(filter_state_routes, "check_project_permission", lambda *a: False)
        with pytest.raises(HTTPException) as exc:
            await get_filter_state(DASHBOARD_ID, _user())
        assert exc.value.status_code == 403


class TestPutGetRoundTrip:
    @beanie_setup
    async def test_round_trip(self):
        user = _user()
        put_res = await put_filter_state(
            DASHBOARD_ID, DashboardFilterStatePayload(filters=SAMPLE_FILTERS), user
        )
        assert put_res["persisted"] is True

        got = await get_filter_state(DASHBOARD_ID, user)
        assert got["persisted"] is True
        assert got["filters"] == SAMPLE_FILTERS
        assert got["enabled"] is True
        assert got["updated_at"] is not None

    @beanie_setup
    async def test_second_put_updates_single_document(self):
        user = _user()
        await put_filter_state(
            DASHBOARD_ID, DashboardFilterStatePayload(filters=SAMPLE_FILTERS), user
        )
        await put_filter_state(
            DASHBOARD_ID,
            DashboardFilterStatePayload(filters=[{"index": "abc", "value": ["z"]}]),
            user,
        )
        assert await DashboardFilterStateBeanie.count() == 1
        got = await get_filter_state(DASHBOARD_ID, user)
        assert got["filters"] == [{"index": "abc", "value": ["z"]}]

    @beanie_setup
    async def test_states_are_per_user(self):
        alice, bob = _user("alice@example.com"), _user("bob@example.com")
        await put_filter_state(
            DASHBOARD_ID, DashboardFilterStatePayload(filters=SAMPLE_FILTERS), alice
        )
        assert (await get_filter_state(DASHBOARD_ID, bob))["persisted"] is False
        assert (await get_filter_state(DASHBOARD_ID, alice))["filters"] == SAMPLE_FILTERS

    @beanie_setup
    async def test_disabled_toggle_roams(self):
        user = _user()
        await put_filter_state(
            DASHBOARD_ID, DashboardFilterStatePayload(filters=[], enabled=False), user
        )
        got = await get_filter_state(DASHBOARD_ID, user)
        assert got["enabled"] is False
        assert got["filters"] == []
        assert got["persisted"] is True


class TestAnonymous:
    """The shared anonymous user must never persist server-side."""

    @beanie_setup
    async def test_put_is_a_noop(self):
        anon = _user("anon@example.com", is_anonymous=True)
        res = await put_filter_state(
            DASHBOARD_ID, DashboardFilterStatePayload(filters=SAMPLE_FILTERS), anon
        )
        assert res == {"persisted": False}
        assert await DashboardFilterStateBeanie.count() == 0

    @beanie_setup
    async def test_get_is_empty(self):
        anon = _user("anon@example.com", is_anonymous=True)
        res = await get_filter_state(DASHBOARD_ID, anon)
        assert res["persisted"] is False

    @beanie_setup
    async def test_delete_is_a_noop(self):
        anon = _user("anon@example.com", is_anonymous=True)
        res = await delete_filter_state(DASHBOARD_ID, anon)
        assert res.status_code == 204


class TestDelete:
    @beanie_setup
    async def test_delete_removes_state(self):
        user = _user()
        await put_filter_state(
            DASHBOARD_ID, DashboardFilterStatePayload(filters=SAMPLE_FILTERS), user
        )
        res = await delete_filter_state(DASHBOARD_ID, user)
        assert res.status_code == 204
        assert await DashboardFilterStateBeanie.count() == 0
