"""``POST /files/upsert_batch`` writes only into collections the caller may edit.

A File record is a claim on a data collection, so the route is a write into
the project that holds it. Without the check any authenticated caller could
drop file records into another user's data collection and make a dashboard
read rows it was never meant to. The predicate is the same caller-keyed one
``delete_batch`` builds with ``build_access_query``: editors and owners of the
project, admins on top.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.files_endpoints import routes
from depictio.models.models.base import PyObjectId
from depictio.models.models.files import File
from depictio.models.models.users import Permission, UserBase

OWN_DC = ObjectId()
OTHER_DC = ObjectId()
OTHER_PROJECT = ObjectId()


def _make_file(dc_id: ObjectId, location: str = "/data/sample.csv") -> File:
    owner = UserBase(id=PyObjectId(), email="owner@example.com")
    return File(
        file_location=location,
        filename=location.rsplit("/", 1)[-1],
        creation_time="2026-01-01 00:00:00",
        modification_time="2026-01-01 00:00:00",
        data_collection_id=dc_id,
        file_hash="a" * 64,
        filesize=123,
        permissions=Permission(owners=[owner]),
    )


def _project(dc_id: ObjectId, *, owners=(), editors=(), viewers=()) -> dict:
    """A project holding ``dc_id`` whose permissions are entry dicts of ids."""
    return {
        "_id": OTHER_PROJECT,
        "name": "Shared",
        "project_type": "advanced",
        "is_public": False,
        "workflows": [
            {"_id": ObjectId(), "workflow_tag": "wf", "data_collections": [{"_id": dc_id}]}
        ],
        "permissions": {
            "owners": [{"_id": oid} for oid in owners],
            "editors": [{"_id": oid} for oid in editors],
            "viewers": [{"_id": oid} for oid in viewers],
        },
    }


@pytest.fixture
def database():
    db = mongomock.MongoClient()["t"]
    with (
        patch("depictio.api.v1.db.projects_collection", db["projects"]),
        patch.object(routes, "files_collection", db["files"]),
    ):
        yield db


class _FakeBulkResult:
    matched_count = 1
    modified_count = 0
    upserted_count = 1


def _upsert(payload, user, database, captured: list | None = None):
    """Run the route with a stub bulk write; mongomock cannot run the
    operations this pymongo builds. ``captured`` collects what was written."""

    def fake_bulk_write(operations, ordered=True):  # noqa: ANN001, ARG001
        if captured is not None:
            captured.extend(operations)
        return _FakeBulkResult()

    with patch.object(routes.files_collection, "bulk_write", side_effect=fake_bulk_write):
        return asyncio.run(routes.create_file(payload, current_user=user))


def test_into_someone_elses_collection_is_403(database):
    """A user who may only read the project cannot write file records into it."""
    owner_id, caller_id = ObjectId(), ObjectId()
    database["projects"].insert_one(_project(OTHER_DC, owners=[owner_id], viewers=[caller_id]))
    caller = UserBase(id=caller_id, email="caller@example.com")
    caller.is_admin = False
    payload = routes.UpsertFilesBatchRequest(files=[_make_file(OTHER_DC)], update=False)
    with pytest.raises(HTTPException) as exc:
        _upsert(payload, caller, database)
    assert exc.value.status_code == 403
    assert database["files"].count_documents({}) == 0


def test_a_collection_no_project_holds_is_403(database):
    """A DC id that belongs to no project fails closed."""
    caller = UserBase(id=ObjectId(), email="caller@example.com")
    caller.is_admin = False
    payload = routes.UpsertFilesBatchRequest(files=[_make_file(ObjectId())], update=False)
    with pytest.raises(HTTPException) as exc:
        _upsert(payload, caller, database)
    assert exc.value.status_code == 403


def test_into_your_own_collection_still_works(database):
    """The ingest path: the project's owner registers its files as before."""
    caller_id = ObjectId()
    database["projects"].insert_one(_project(OWN_DC, owners=[caller_id]))
    caller = UserBase(id=caller_id, email="caller@example.com")
    captured: list = []
    _upsert(
        routes.UpsertFilesBatchRequest(files=[_make_file(OWN_DC)], update=False),
        caller,
        database,
        captured,
    )
    assert len(captured) == 1


def test_an_editor_of_the_project_may_upsert(database):
    """Editor level is enough, owner level included."""
    editor_id = ObjectId()
    database["projects"].insert_one(_project(OWN_DC, editors=[editor_id]))
    editor = UserBase(id=editor_id, email="editor@example.com")
    captured: list = []
    _upsert(
        routes.UpsertFilesBatchRequest(files=[_make_file(OWN_DC)], update=True),
        editor,
        database,
        captured,
    )
    assert len(captured) == 1


def test_an_admin_may_upsert(database):
    admin = UserBase(id=ObjectId(), email="admin@example.com")
    admin.is_admin = True
    database["projects"].insert_one(_project(OTHER_DC, owners=[ObjectId()]))
    captured: list = []
    _upsert(
        routes.UpsertFilesBatchRequest(files=[_make_file(OTHER_DC)], update=False),
        admin,
        database,
        captured,
    )
    assert len(captured) == 1


def test_a_group_editor_may_upsert(database):
    """A role granted through a group counts as a direct one."""
    editor_group, editor_id = ObjectId(), ObjectId()
    project = _project(OWN_DC)
    project["permissions"]["group_editors"] = [{"_id": editor_group}]
    database["projects"].insert_one(project)
    with patch(
        "depictio.api.v1.db.groups_collection",
        mongomock.MongoClient()["t"]["groups"],
    ) as groups:
        groups.insert_one({"_id": editor_group, "users_ids": [editor_id]})
        editor = UserBase(id=editor_id, email="editor@example.com")
        captured: list = []
        _upsert(
            routes.UpsertFilesBatchRequest(files=[_make_file(OWN_DC)], update=False),
            editor,
            database,
            captured,
        )
    assert len(captured) == 1


def test_every_collection_of_a_mixed_batch_is_checked(database):
    """One stranger's DC in the batch refuses the whole request."""
    caller_id = ObjectId()
    database["projects"].insert_one(_project(OWN_DC, owners=[caller_id]))
    caller = UserBase(id=caller_id, email="caller@example.com")
    payload = routes.UpsertFilesBatchRequest(
        files=[_make_file(OWN_DC), _make_file(OTHER_DC, "/data/other.csv")], update=False
    )
    captured: list = []
    with pytest.raises(HTTPException) as exc:
        _upsert(payload, caller, database, captured)
    assert exc.value.status_code == 403
    assert captured == []
    assert database["files"].count_documents({}) == 0
