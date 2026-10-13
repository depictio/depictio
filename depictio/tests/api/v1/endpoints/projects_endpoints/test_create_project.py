"""Duplicate checks of the real project create route.

The route answers HTTP 200 with a `{"success": False, "status_code": ...}` body,
which the CLI (`_project_write_outcome`) and the viewer (`createProject`) read.
A taken name used to fail with a 500, and a taken id was never checked.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import routes as proj_routes
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


def _create(user, *, name, project_id=None):
    project = Project(id=project_id or ObjectId(), name=name, permissions=Permission(owners=[user]))
    return asyncio.run(proj_routes.create_project(project=project, current_user=user))


def test_new_project_is_created(db, user):
    result = _create(user, name="Iris")

    assert result["success"] is True
    assert db["projects"].count_documents({"name": "Iris"}) == 1


def test_taken_name_is_a_409(db, user):
    _create(user, name="Iris")

    result = _create(user, name="Iris")

    assert result == {
        "success": False,
        "message": "Project already exists using this name.",
        "status_code": 409,
    }
    assert db["projects"].count_documents({}) == 1


def test_taken_id_is_a_409_even_with_a_free_name(db, user):
    project_id = ObjectId()
    _create(user, name="Iris", project_id=project_id)

    result = _create(user, name="Penguins", project_id=project_id)

    assert result["status_code"] == 409
    assert result["message"] == "Project already exists using this id."
    assert db["projects"].count_documents({}) == 1


def test_id_of_a_project_the_user_cannot_see_is_a_409(db, user):
    """The id lookup only sees the user's projects, so the insert met the id: a 500."""
    project_id = ObjectId()
    _create(user, name="Iris", project_id=project_id)
    other = UserBase(id=ObjectId(), email="other@example.com")
    other.is_admin = False

    result = _create(other, name="Penguins", project_id=project_id)

    assert result == {
        "success": False,
        "message": "Project already exists using this id.",
        "status_code": 409,
    }
    assert db["projects"].count_documents({}) == 1
