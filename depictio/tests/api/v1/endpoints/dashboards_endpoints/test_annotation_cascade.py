"""Session annotations follow the dashboards, projects and users they belong to."""

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import annotation_cascade as cascade

USER_A = ObjectId()
USER_B = ObjectId()


@pytest.fixture
def db(monkeypatch):
    db = mongomock.MongoClient().db
    monkeypatch.setattr(cascade, "dashboard_annotations_collection", db.annotations)
    monkeypatch.setattr(cascade, "dashboards_collection", db.dashboards)
    return db


def _doc(db, user, dashboard):
    db.annotations.insert_one({"user_id": user, "dashboard_id": dashboard, "annotations": {}})


def _left(db):
    return sorted(
        (d["user_id"], d["dashboard_id"])
        for d in db.annotations.find({}, {"_id": 0, "user_id": 1, "dashboard_id": 1})
    )


def test_dashboard_delete_drops_every_users_annotations(db):
    main, other = ObjectId(), ObjectId()
    _doc(db, USER_A, main)
    _doc(db, USER_B, main)
    _doc(db, USER_A, other)
    assert cascade.delete_annotations_for_dashboards([str(main), None, "bad"]) == 2
    assert _left(db) == [(USER_A, other)]


def test_project_delete_drops_annotations_on_its_dashboards(db):
    project, main, foreign = ObjectId(), ObjectId(), ObjectId()
    db.dashboards.insert_one({"dashboard_id": main, "project_id": project})
    db.dashboards.insert_one({"dashboard_id": foreign, "project_id": ObjectId()})
    _doc(db, USER_A, main)
    _doc(db, USER_A, foreign)
    assert cascade.delete_annotations_for_project(str(project)) == 1
    assert _left(db) == [(USER_A, foreign)]


def test_user_delete_drops_only_that_users_annotations(db):
    dash = ObjectId()
    _doc(db, USER_A, dash)
    _doc(db, USER_A, ObjectId())
    _doc(db, USER_B, dash)
    assert cascade.delete_annotations_for_user(str(USER_A)) == 2
    assert _left(db) == [(USER_B, dash)]


def test_invalid_ids_do_nothing(db):
    _doc(db, USER_A, ObjectId())
    assert cascade.delete_annotations_for_dashboards([]) == 0
    assert cascade.delete_annotations_for_project(None) == 0
    assert cascade.delete_annotations_for_user("nope") == 0
    assert len(_left(db)) == 1


def test_failure_is_logged_not_raised(monkeypatch):
    class Broken:
        def delete_many(self, *_a, **_k):
            raise RuntimeError("down")

    monkeypatch.setattr(cascade, "dashboard_annotations_collection", Broken())
    assert cascade.delete_annotations_for_dashboards([ObjectId()]) == 0
    assert cascade.delete_annotations_for_user(ObjectId()) == 0


# --- user deletion paths -------------------------------------------------------


def test_admin_user_delete_drops_the_users_annotations(monkeypatch):
    from types import SimpleNamespace

    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes

    users = mongomock.MongoClient().db.users
    users.insert_one({"_id": USER_A, "email": "a@example.com"})
    called = []
    monkeypatch.setattr(user_routes, "users_collection", users)
    monkeypatch.setattr(user_routes.avatar_service, "delete_avatar", lambda _id: None)
    monkeypatch.setattr(cascade, "delete_annotations_for_user", called.append)

    out = user_routes.delete_user(str(USER_A), current_user=SimpleNamespace(is_admin=True))
    assert out == {"success": True}
    assert called == [USER_A]


def test_delete_user_from_db_drops_the_users_annotations(monkeypatch):
    from depictio.api.v1 import db as db_module
    from depictio.api.v1.endpoints.user_endpoints.utils import delete_user_from_db

    users = mongomock.MongoClient().db.users
    users.insert_one({"_id": USER_A, "email": "a@example.com"})
    called = []
    monkeypatch.setattr(db_module, "users_collection", users)
    monkeypatch.setattr(cascade, "delete_annotations_for_user", called.append)

    assert delete_user_from_db(email="a@example.com")["success"] is True
    assert called == [USER_A]


@pytest.mark.asyncio
async def test_expired_temporary_user_cleanup_drops_annotations(monkeypatch):
    from datetime import datetime, timedelta
    from typing import cast

    from beanie import init_beanie
    from mongomock_motor import AsyncMongoMockClient
    from pymongo.asynchronous.database import AsyncDatabase

    from depictio.api.v1 import db as db_module
    from depictio.api.v1.endpoints.user_endpoints.core_functions import (
        _cleanup_expired_temporary_users,
    )
    from depictio.models.models.users import TokenBeanie, UserBeanie

    client = AsyncMongoMockClient()
    await init_beanie(
        database=cast(AsyncDatabase, client.test_db), document_models=[UserBeanie, TokenBeanie]
    )
    sync = mongomock.MongoClient().db
    dash = ObjectId()
    user = UserBeanie(
        email="guest@depictio.temp",
        password="$2b$12$" + "x" * 53,
        is_temporary=True,
        expiration_time=datetime.now() - timedelta(hours=1),
    )
    await user.create()
    sync.dashboards.insert_one(
        {"dashboard_id": dash, "permissions": {"owners": [{"_id": user.id}]}}
    )
    for name in ("dashboards", "files", "deltatables"):
        monkeypatch.setattr(db_module, f"{name}_collection", sync[name])
    from depictio.api.v1.endpoints.comments_endpoints import cascade as comments_cascade

    monkeypatch.setattr(comments_cascade, "comment_threads_collection", sync.comment_threads)
    from depictio.api.v1.endpoints.user_endpoints import core_functions

    monkeypatch.setattr(core_functions, "_drop_version_ledger", lambda _id: None)
    by_user, by_dashboard = [], []
    monkeypatch.setattr(cascade, "delete_annotations_for_user", by_user.append)
    monkeypatch.setattr(
        cascade, "delete_annotations_for_dashboards", lambda ids: by_dashboard.extend(ids)
    )

    result = await _cleanup_expired_temporary_users()
    assert result["users_deleted"] == 1
    assert [str(u) for u in by_user] == [str(user.id)]
    assert by_dashboard == [dash]
