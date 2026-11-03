"""Project provenance is server-written (issue #1303).

The API stamps the running Depictio version on creation, and neither create nor
update lets a client claim a version, lift a published lock or park an owner.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import provenance
from depictio.api.v1.endpoints.projects_endpoints import routes as proj_routes
from depictio.models.models.migration import ImportHop, ProjectProvenance, PublishedLock
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase


@pytest.fixture
def db():
    database = mongomock.MongoClient()["depictio_test"]
    with patch.object(proj_routes, "projects_collection", database["projects"]):
        yield database


@pytest.fixture
def user():
    u = UserBase(id=ObjectId(), email="owner@example.com")
    u.is_admin = True
    return u


@pytest.fixture(autouse=True)
def running_version(monkeypatch):
    monkeypatch.setattr(provenance, "get_version", lambda: "9.8.7")


def _forged_fields():
    return {
        "provenance": ProjectProvenance(
            created_with_version="0.0.1",
            imported_from=[ImportHop(source_instance="evil.example.org")],
        ),
        "published_lock": None,
        "pending_owner_email": "attacker@example.org",
    }


def test_create_stamps_the_running_version(db, user):
    project = Project(id=ObjectId(), name="Iris", permissions=Permission(owners=[user]))
    result = asyncio.run(proj_routes.create_project(project=project, current_user=user))

    assert result["success"] is True
    stored = db["projects"].find_one({"_id": project.id})
    assert stored["provenance"] == {"created_with_version": "9.8.7", "imported_from": []}
    assert stored.get("published_lock") is None
    assert stored.get("pending_owner_email") is None


def test_create_ignores_forged_provenance(db, user):
    project = Project(
        id=ObjectId(), name="Iris", permissions=Permission(owners=[user]), **_forged_fields()
    )
    asyncio.run(proj_routes.create_project(project=project, current_user=user))

    stored = db["projects"].find_one({"_id": project.id})
    assert stored["provenance"]["created_with_version"] == "9.8.7"
    assert stored["provenance"]["imported_from"] == []
    assert stored.get("pending_owner_email") is None


def _seed(db, user, **extra):
    project_id = ObjectId()
    db["projects"].insert_one(
        {
            "_id": project_id,
            "name": "Iris",
            "registration_time": "2024-01-01 10:00:00",
            "permissions": {
                "owners": [{"_id": user.id, "email": user.email}],
                "editors": [],
                "viewers": [],
            },
            **extra,
        }
    )
    return project_id


def test_update_cannot_rewrite_server_owned_fields(db, user):
    lock = PublishedLock(reason="released").model_dump()
    original = {"created_with_version": "1.0.0", "imported_from": []}
    project_id = _seed(db, user, provenance=original, published_lock=lock)

    forged = Project(
        id=project_id, name="Renamed", permissions=Permission(owners=[user]), **_forged_fields()
    )
    asyncio.run(proj_routes.update_project(project=forged, current_user=user))

    stored = db["projects"].find_one({"_id": project_id})
    assert stored["name"] == "Renamed", "sanity: the update landed"
    assert stored["provenance"] == original
    assert stored["published_lock"] == lock, "a None in the body must not lift the lock"
    assert "pending_owner_email" not in stored


def test_update_of_a_legacy_project_adds_no_provenance(db, user):
    project_id = _seed(db, user)
    project = Project(id=project_id, name="Renamed", permissions=Permission(owners=[user]))
    asyncio.run(proj_routes.update_project(project=project, current_user=user))

    stored = db["projects"].find_one({"_id": project_id})
    assert "provenance" not in stored, "legacy stays unknown rather than claiming a version"


def test_stamp_new_project_discards_every_server_owned_field():
    payload = {
        "name": "x",
        "provenance": {"created_with_version": "0.0.1"},
        "published_lock": {"reason": "x"},
        "pending_owner_email": "a@b.c",
    }
    stamped = provenance.stamp_new_project(payload)
    assert stamped["provenance"] == {"created_with_version": "9.8.7", "imported_from": []}
    assert "published_lock" not in stamped
    assert "pending_owner_email" not in stamped


def test_project_model_round_trips_provenance():
    owner = UserBase(id=ObjectId(), email="a@b.c")
    project = Project(name="n", permissions=Permission(owners=[owner]), **_forged_fields())
    again = Project.model_validate(project.model_dump())
    assert again.provenance == project.provenance
    assert again.pending_owner_email == "attacker@example.org"


def test_ids_restored_as_object_ids_still_read_back():
    """A backup restore turns every ObjectId-shaped string into an ObjectId.

    That includes the ids kept in ``provenance`` and ``published_lock``; reading
    the project back must not fail on them (``GET /projects/get/all`` was a 500
    after a restore of an imported project).
    """
    from depictio.api.v1.services.mongo_json import restore_complex_objects
    from depictio.models.models.projects import ProjectResponse

    dash = [str(ObjectId()), str(ObjectId())]
    hop = ImportHop(source_instance="a", dashboard_ids=dash, migration_request_id=str(ObjectId()))
    lock = PublishedLock(locked_by_id=str(ObjectId()), dashboard_ids=dash)
    project = Project(
        name="restored",
        permissions=Permission(owners=[UserBase(id=ObjectId(), email="o@example.com")]),
    ).mongo()
    project["provenance"] = ProjectProvenance(imported_from=[hop]).model_dump()
    project["published_lock"] = lock.model_dump()

    restored = restore_complex_objects(project)
    assert isinstance(restored["provenance"]["imported_from"][0]["dashboard_ids"][0], ObjectId)

    response = ProjectResponse.from_mongo(restored)
    assert response.provenance is not None
    assert response.provenance.imported_from[0].dashboard_ids == dash
    assert response.published_lock is not None
    assert response.published_lock.dashboard_ids == dash
    assert response.published_lock.locked_by_id == lock.locked_by_id
