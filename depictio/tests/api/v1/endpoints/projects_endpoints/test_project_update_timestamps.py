"""Timestamp behavior of the real project update route (issue #932).

Projects gained a `last_modified` field so the listing can show a meaningful
"Modified" column, while `registration_time` stays write-once.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import routes as proj_routes
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase

TS_FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with patch.object(proj_routes, "projects_collection", database["projects"]):
        yield database


@pytest.fixture
def user():
    u = UserBase(id=ObjectId(), email="owner@example.com")
    u.is_admin = True
    return u


def _project(project_id, owner, *, name="My project", registration_time=None):
    kwargs = {}
    if registration_time is not None:
        kwargs["registration_time"] = registration_time
    return Project(
        id=project_id,
        name=name,
        permissions=Permission(owners=[owner]),
        **kwargs,
    )


def _update(project, user):
    return asyncio.run(proj_routes.update_project(project=project, current_user=user))


class TestUpdateProjectTimestamps:
    def test_update_stamps_last_modified_and_preserves_registration_time(
        self, db, user, monkeypatch
    ):
        project_id = ObjectId()
        db["projects"].insert_one(
            {
                "_id": project_id,
                "name": "My project",
                "registration_time": "2024-01-01 10:00:00",
                "permissions": {
                    "owners": [{"_id": user.id, "email": user.email}],
                    "editors": [],
                    "viewers": [],
                },
            }
        )
        monkeypatch.setattr(proj_routes, "utc_now_str", lambda: "2024-06-01 12:00:00")

        _update(_project(project_id, user, name="Renamed"), user)

        stored = db["projects"].find_one({"_id": project_id})
        assert stored["name"] == "Renamed", "sanity: the update actually landed"
        assert stored["registration_time"] == "2024-01-01 10:00:00", "creation must not move"
        assert stored["last_modified"] == "2024-06-01 12:00:00"
        assert stored["registration_time"] != stored["last_modified"]

    def test_client_cannot_forge_the_registration_time(self, db, user, monkeypatch):
        project_id = ObjectId()
        db["projects"].insert_one(
            {
                "_id": project_id,
                "name": "My project",
                "registration_time": "2024-01-01 10:00:00",
                "permissions": {
                    "owners": [{"_id": user.id, "email": user.email}],
                    "editors": [],
                    "viewers": [],
                },
            }
        )
        monkeypatch.setattr(proj_routes, "utc_now_str", lambda: "2024-06-01 12:00:00")

        forged = _project(project_id, user, registration_time="1999-12-31 23:59:59")
        _update(forged, user)

        stored = db["projects"].find_one({"_id": project_id})
        assert stored["registration_time"] == "2024-01-01 10:00:00"

    def test_update_keeps_a_single_document(self, db, user):
        """`_id` is the project key here; the update must not fan out."""
        project_id = ObjectId()
        db["projects"].insert_one(
            {
                "_id": project_id,
                "name": "My project",
                "registration_time": "2024-01-01 10:00:00",
                "permissions": {
                    "owners": [{"_id": user.id, "email": user.email}],
                    "editors": [],
                    "viewers": [],
                },
            }
        )
        for i in range(3):
            _update(_project(project_id, user, name=f"v{i}"), user)
        assert db["projects"].count_documents({"_id": project_id}) == 1

    def test_registration_time_defaults_to_utc(self):
        """The model default must be UTC, not the server's local time."""
        produced = datetime.strptime(
            Project(
                name="n", permissions=Permission(owners=[UserBase(id=ObjectId(), email="a@b.c")])
            ).registration_time,
            TS_FMT,
        )
        expected_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((produced - expected_utc).total_seconds()) < 5
