"""Saved filter states follow the dashboards they belong to."""

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import filter_state_cascade as cascade

USER_A = ObjectId()
USER_B = ObjectId()


@pytest.fixture
def collections(monkeypatch):
    db = mongomock.MongoClient().db
    monkeypatch.setattr(cascade, "dashboard_filter_states_collection", db.states)
    monkeypatch.setattr(cascade, "dashboards_collection", db.dashboards)
    return db


def _state(db, user, dashboard):
    db.states.insert_one(
        {"user_id": user, "dashboard_id": dashboard, "filters": [], "enabled": True}
    )


def test_dashboard_delete_drops_every_users_state_for_those_tabs(collections):
    main, child, other = ObjectId(), ObjectId(), ObjectId()
    for dash in (main, child, other):
        _state(collections, USER_A, dash)
    _state(collections, USER_B, main)

    assert cascade.delete_filter_states_for_dashboards([main, str(child)]) == 3

    left = list(collections.states.find({}, {"_id": 0, "dashboard_id": 1}))
    assert left == [{"dashboard_id": other}]


def test_ignores_missing_and_malformed_ids(collections):
    _state(collections, USER_A, ObjectId())
    assert cascade.delete_filter_states_for_dashboards([None, "not-an-id"]) == 0
    assert collections.states.count_documents({}) == 1


def test_project_delete_drops_states_of_all_its_dashboards(collections):
    project, other_project = ObjectId(), ObjectId()
    mine_1, mine_2, theirs = ObjectId(), ObjectId(), ObjectId()
    for dash, proj in ((mine_1, project), (mine_2, project), (theirs, other_project)):
        collections.dashboards.insert_one({"dashboard_id": dash, "project_id": proj})
        _state(collections, USER_A, dash)

    assert cascade.delete_filter_states_for_project(project) == 2
    assert [s["dashboard_id"] for s in collections.states.find()] == [theirs]


def test_a_storage_failure_never_raises(monkeypatch):
    class Broken:
        def delete_many(self, *_a, **_k):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(cascade, "dashboard_filter_states_collection", Broken())
    assert cascade.delete_filter_states_for_dashboards([ObjectId()]) == 0
