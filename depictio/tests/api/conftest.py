"""Shared fixtures for the API tests."""

from __future__ import annotations

import mongomock
import pytest


@pytest.fixture(autouse=True)
def _empty_groups_collection(monkeypatch):
    """Resolve group membership against an empty in-memory ``groups`` collection.

    Every access check goes through ``depictio.api.v1.permissions``, which looks
    a user's groups up in ``depictio.api.v1.db.groups_collection``. Tests that
    stub ``projects_collection`` would otherwise dial the real Mongo for that
    lookup. A test that needs members patches ``groups_collection`` itself (the
    later patch wins), or injects a collection into the chokepoint helpers.
    """
    groups = mongomock.MongoClient()["depictio_test_groups"]["groups"]
    monkeypatch.setattr("depictio.api.v1.db.groups_collection", groups)
    yield groups


@pytest.fixture(autouse=True)
def _unlocked_publish_lock_db(monkeypatch):
    """Answer the published-lock helpers from an empty in-memory database.

    Every content-mutating route asks ``projects_endpoints.publish_lock``
    whether its project is published, which reads ``depictio.api.v1.db``.
    Tests that stub only a route module's own collections would otherwise dial
    the real Mongo for that lookup and hang. An empty database holds no lock,
    so nothing is frozen unless a test patches ``publish_lock._db`` itself (the
    later patch wins) and seeds a locked project there.
    """
    from types import SimpleNamespace

    from depictio.api.v1.endpoints.projects_endpoints import publish_lock

    database = mongomock.MongoClient()["depictio_test_publish_lock"]
    fake_db = SimpleNamespace(
        projects_collection=database["projects"],
        dashboards_collection=database["dashboards"],
    )
    monkeypatch.setattr(publish_lock, "_db", lambda: fake_db)
    yield fake_db


@pytest.fixture(autouse=True)
def _no_pending_project_owner_db(monkeypatch):
    """Answer the pending-project-owner claim from an empty in-memory database.

    Every SSO sign-in and admin-created account asks ``pending_owner`` for
    projects parked on the user's email, which reads the synchronous project
    collections. Tests that only initialise Beanie would otherwise dial the real
    MongoDB for it and hang. An empty database holds nothing to claim; a test of
    the claim itself patches ``pending_owner._db`` (the later patch wins).
    """
    from types import SimpleNamespace

    from depictio.api.v1.endpoints.projects_endpoints import pending_owner

    database = mongomock.MongoClient()["depictio_test_pending_owner"]
    fake_db = SimpleNamespace(
        projects_collection=database["projects"], dashboards_collection=database["dashboards"]
    )
    monkeypatch.setattr(pending_owner, "_db", lambda: fake_db)
    yield fake_db
