"""`PUT /projects/update` authorises on the stored project, not on the request body.

The body is a whole project document and carries its own `permissions`. The
check used to read the owners from it, so anyone who could see a project could
send a body naming themselves owner, pass the check and have that block written
over the real one. Ownership is now read from the stored document, and the
update never writes `permissions` at all: sharing has its own endpoint.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.projects_endpoints import routes as proj_routes
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase

PROJECT_ID = ObjectId()


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(proj_routes, "projects_collection", database["projects"]),
        patch(
            "depictio.api.v1.endpoints.projects_endpoints.utils.get_user_group_ids", return_value=[]
        ),
    ):
        yield database


def _user(admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email=f"{ObjectId()}@example.org", is_admin=admin)


def _seed(db, *, owners=(), editors=(), viewers=(), public=False, name="Stored name"):
    def entries(users):
        return [{"_id": u.id, "email": u.email} for u in users]

    db["projects"].insert_one(
        {
            "_id": PROJECT_ID,
            "name": name,
            "project_type": "advanced",
            "is_public": public,
            "registration_time": "2024-01-01 10:00:00",
            "workflows": [],
            "data_collections": [],
            "permissions": {
                "owners": entries(owners),
                "editors": entries(editors),
                "viewers": entries(viewers),
            },
        }
    )


def _body(claimed_owners, name="Renamed") -> Project:
    """What the caller sends: a project that names `claimed_owners` as its owners."""
    return Project(
        id=PROJECT_ID,
        name=name,
        project_type="advanced",
        permissions=Permission(owners=list(claimed_owners), editors=[], viewers=[]),
    )


def _update(project, user):
    return asyncio.run(proj_routes.update_project(project=project, current_user=user))


def _stored(db):
    return db["projects"].find_one({"_id": PROJECT_ID})


def _owner_ids(db):
    return [str(o["_id"]) for o in _stored(db)["permissions"]["owners"]]


class TestUpdateAuthorisation:
    def test_a_viewer_cannot_take_ownership_by_naming_themselves_owner(self, db):
        owner, viewer = _user(), _user()
        _seed(db, owners=[owner], viewers=[viewer])

        with pytest.raises(HTTPException) as exc_info:
            _update(_body([viewer]), viewer)

        assert exc_info.value.status_code == 403
        assert _owner_ids(db) == [str(owner.id)]
        assert _stored(db)["name"] == "Stored name"

    def test_an_editor_cannot_either(self, db):
        owner, editor = _user(), _user()
        _seed(db, owners=[owner], editors=[editor])

        with pytest.raises(HTTPException) as exc_info:
            _update(_body([editor]), editor)

        assert exc_info.value.status_code == 403
        assert _owner_ids(db) == [str(owner.id)]

    def test_nor_anyone_on_a_public_project(self, db):
        owner, stranger = _user(), _user()
        _seed(db, owners=[owner], public=True)

        with pytest.raises(HTTPException) as exc_info:
            _update(_body([stranger]), stranger)

        assert exc_info.value.status_code == 403
        assert _owner_ids(db) == [str(owner.id)]

    def test_someone_who_cannot_see_the_project_gets_a_404(self, db):
        owner, stranger = _user(), _user()
        _seed(db, owners=[owner])

        with pytest.raises(HTTPException) as exc_info:
            _update(_body([stranger]), stranger)

        assert exc_info.value.status_code == 404
        assert _owner_ids(db) == [str(owner.id)]


class TestUpdateAllowed:
    def test_the_stored_owner_can_update_but_not_rewrite_the_owners(self, db):
        owner, friend = _user(), _user()
        _seed(db, owners=[owner])

        _update(_body([owner, friend], name="Renamed"), owner)

        stored = _stored(db)
        assert stored["name"] == "Renamed"
        assert _owner_ids(db) == [str(owner.id)]
        assert stored["permissions"]["viewers"] == []

    def test_a_sysadmin_can_update(self, db):
        owner, admin = _user(), _user(admin=True)
        _seed(db, owners=[owner])

        _update(_body([owner], name="By admin"), admin)

        assert _stored(db)["name"] == "By admin"
        assert _owner_ids(db) == [str(owner.id)]
