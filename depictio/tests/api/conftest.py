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
