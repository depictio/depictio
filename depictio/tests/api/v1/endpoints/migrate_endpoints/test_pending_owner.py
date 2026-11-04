"""Projects pushed for an address with no account are claimed at first verified sign-in (#1303)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import pending_owner
from depictio.api.v1.endpoints.projects_endpoints.pending_owner import (
    claim_pending_project_ownership,
    claim_pending_project_ownership_quietly,
)


@pytest.fixture
def cols(monkeypatch):
    database = mongomock.MongoClient()["pending_owner"]
    cols = SimpleNamespace(projects=database["projects"], dashboards=database["dashboards"])
    fake_db = SimpleNamespace(
        projects_collection=cols.projects, dashboards_collection=cols.dashboards
    )
    monkeypatch.setattr(pending_owner, "_db", lambda: fake_db)
    return cols


def _seed(cols, *, email="New.Person@Source.org"):
    admin_id, dash, copy = ObjectId(), ObjectId(), ObjectId()
    pid = ObjectId()
    cols.projects.insert_one(
        {
            "_id": pid,
            "name": "Iris",
            "pending_owner_email": email,
            "permissions": {
                "owners": [{"_id": admin_id, "email": "admin@t.org"}],
                "editors": [{"_id": ObjectId(), "email": "ed@t.org"}],
                "viewers": ["*"],
            },
            "provenance": {"imported_from": [{"dashboard_ids": [str(dash)]}]},
        }
    )
    placeholder = {"owners": [{"_id": admin_id, "email": "admin@t.org"}]}
    cols.dashboards.insert_many(
        [
            {"_id": dash, "project_id": pid, "permissions": placeholder},
            {"_id": copy, "project_id": pid, "permissions": {"owners": [{"_id": ObjectId()}]}},
        ]
    )
    return pid, dash, copy


def _user(email="new.person@source.org"):
    return SimpleNamespace(id=ObjectId(), email=email)


def test_the_claimant_replaces_the_placeholder_owner(cols):
    pid, dash, copy = _seed(cols)
    user = _user()
    assert asyncio.run(claim_pending_project_ownership(user)) == ["Iris"]
    project = cols.projects.find_one({"_id": pid})
    assert [o["_id"] for o in project["permissions"]["owners"]] == [user.id]
    assert "pending_owner_email" not in project
    assert (
        project["permissions"]["viewers"] == ["*"] and len(project["permissions"]["editors"]) == 1
    )
    # The imported dashboards follow; a visitor's copy keeps its owner.
    assert [o["_id"] for o in cols.dashboards.find_one({"_id": dash})["permissions"]["owners"]] == [
        user.id
    ]
    assert cols.dashboards.find_one({"_id": copy})["permissions"]["owners"][0]["_id"] != user.id


def test_another_address_claims_nothing_and_a_replay_is_a_noop(cols):
    pid, *_ = _seed(cols)
    assert asyncio.run(claim_pending_project_ownership(_user("someone@else.org"))) == []
    assert cols.projects.find_one({"_id": pid})["pending_owner_email"]
    user = _user()
    asyncio.run(claim_pending_project_ownership(user))
    assert asyncio.run(claim_pending_project_ownership(user)) == []


def test_a_failure_never_breaks_a_login(cols, monkeypatch):
    _seed(cols)

    async def boom(user):
        raise RuntimeError("db down")

    monkeypatch.setattr(pending_owner, "claim_pending_project_ownership", boom)
    asyncio.run(claim_pending_project_ownership_quietly(_user()))


@pytest.mark.parametrize("flag,expected", [(True, 1), (False, 0)])
def test_only_admin_created_accounts_claim_on_creation(monkeypatch, flag, expected):
    """Password self-registration verifies nothing, so it must not take over a parked project."""
    from typing import cast
    from unittest.mock import AsyncMock

    from beanie import init_beanie
    from mongomock_motor import AsyncMongoMockClient
    from pymongo.asynchronous.database import AsyncDatabase

    from depictio.api.v1.endpoints.user_endpoints import core_functions
    from depictio.models.models.users import UserBeanie

    claim = AsyncMock()
    monkeypatch.setattr(core_functions, "claim_pending_project_ownership_quietly", claim)

    async def run():
        client = AsyncMongoMockClient()
        await init_beanie(
            database=cast(AsyncDatabase, client.claim_db), document_models=[UserBeanie]
        )
        return await core_functions._create_user_in_db(
            "someone@example.org", "Start-1234", claim_pending_owner=flag
        )

    result = asyncio.run(run())
    assert result and result["success"]
    assert claim.await_count == expected
