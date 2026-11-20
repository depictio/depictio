"""Project roles on the links API, for users who are not sysadmins.

A stored project holds its roles as user documents
(``permissions.owners/editors/viewers`` = ``[{_id, email, is_admin}, ...]``).
The links routes used to compare ``current_user.email`` with those lists, which
never matched: every non-admin owner of a private project got a 403 on
``GET /links/{project_id}``, and nobody but a sysadmin could create, update or
delete a link. The other links tests all run as a sysadmin, which is how it went
unnoticed. These call the route functions directly against a mongomock project.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1 import permissions as permissions_module
from depictio.api.v1.endpoints.links_endpoints import routes as links_routes
from depictio.api.v1.endpoints.projects_endpoints import publish_lock
from depictio.models.models.links import LinkCreateRequest, LinkUpdateRequest
from depictio.models.models.users import UserBase

SOURCE_DC = str(ObjectId())
TARGET_DC = str(ObjectId())
LINK_ID = str(ObjectId())


def _user(email: str, *, is_admin: bool = False, is_anonymous: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email=email, is_admin=is_admin, is_anonymous=is_anonymous)


OWNER = _user("owner@example.org")
EDITOR = _user("editor@example.org")
VIEWER = _user("viewer@example.org")
STRANGER = _user("stranger@example.org")
GROUP_EDITOR = _user("group-editor@example.org")
ANONYMOUS = _user("anonymous@example.org", is_anonymous=True)
GROUP_ID = ObjectId()


def _entry(user: UserBase) -> dict:
    """A role entry as a project document stores it."""
    return {"_id": ObjectId(user.id), "email": user.email, "is_admin": user.is_admin}


@pytest.fixture
def make_project():
    """Factory: seed one project (private or public) and wire the routes to it."""
    client = mongomock.MongoClient()
    db = client["links_permissions"]
    db["groups"].insert_one(
        {"_id": GROUP_ID, "name": "lab", "users_ids": [ObjectId(GROUP_EDITOR.id)]}
    )
    lock_db = type("LockDb", (), {"projects_collection": db["projects"]})

    def _make(*, is_public: bool) -> tuple[str, mongomock.Collection]:
        project_id = ObjectId()
        db["projects"].insert_one(
            {
                "_id": project_id,
                "name": "Learner project",
                "is_public": is_public,
                "permissions": {
                    "owners": [_entry(OWNER)],
                    "editors": [_entry(EDITOR)],
                    "viewers": [_entry(VIEWER)],
                    "group_editors": [{"_id": GROUP_ID, "name": "lab"}],
                },
                "links": [
                    {
                        "id": LINK_ID,
                        "source_dc_id": SOURCE_DC,
                        "source_column": "sample",
                        "target_dc_id": TARGET_DC,
                        "target_type": "table",
                        "enabled": True,
                        "link_config": {"resolver": "direct"},
                    }
                ],
            }
        )
        return str(project_id), db["projects"]

    with (
        patch.object(links_routes, "projects_collection", db["projects"]),
        patch.object(publish_lock, "_db", lambda: lock_db),
        patch.object(permissions_module, "_default_groups_collection", lambda: db["groups"]),
    ):
        yield _make
    client.close()


def _create(project_id: str, user: UserBase):
    request = LinkCreateRequest(
        source_dc_id=SOURCE_DC,
        source_column="sample",
        target_dc_id=TARGET_DC,
        target_type="table",
    )
    return asyncio.run(
        links_routes.create_link(request=request, project_id=project_id, current_user=user)
    )


def _list(project_id: str, user: UserBase):
    return asyncio.run(links_routes.get_project_links(project_id=project_id, current_user=user))


def _resolvers(project_id: str, user: UserBase):
    return asyncio.run(
        links_routes.list_available_resolvers(project_id=project_id, current_user=user)
    )


def _forbidden(call) -> str:
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 403
    return exc.value.detail


# --- reading ----------------------------------------------------------------


@pytest.mark.parametrize("user", [OWNER, EDITOR, VIEWER, GROUP_EDITOR], ids=lambda u: u.email)
def test_members_read_links_of_a_private_project(make_project, user):
    project_id, _ = make_project(is_public=False)

    links = _list(project_id, user)

    assert [str(link.id) for link in links] == [LINK_ID]
    assert "direct" in _resolvers(project_id, user)
    by_source = asyncio.run(
        links_routes.get_links_by_source_dc(
            project_id=project_id, dc_id=SOURCE_DC, current_user=user
        )
    )
    assert len(by_source) == 1


def test_stranger_refused_on_a_private_project(make_project):
    project_id, _ = make_project(is_public=False)

    assert _forbidden(lambda: _list(project_id, STRANGER)) == "Access denied to project"
    assert _forbidden(lambda: _resolvers(project_id, STRANGER)) == "Access denied to project"
    _forbidden(lambda: _create(project_id, STRANGER))


@pytest.mark.parametrize("user", [STRANGER, ANONYMOUS], ids=lambda u: u.email)
def test_anyone_reads_links_of_a_public_project(make_project, user):
    project_id, _ = make_project(is_public=True)

    assert [str(link.id) for link in _list(project_id, user)] == [LINK_ID]


# --- writing ----------------------------------------------------------------


@pytest.mark.parametrize("user", [OWNER, EDITOR, GROUP_EDITOR], ids=lambda u: u.email)
def test_owner_and_editors_create_links(make_project, user):
    project_id, projects = make_project(is_public=False)

    created = _create(project_id, user)

    stored = projects.find_one({"_id": ObjectId(project_id)})["links"]
    assert [link["id"] for link in stored] == [LINK_ID, str(created.id)]


def test_owner_updates_and_deletes_links(make_project):
    project_id, projects = make_project(is_public=False)

    updated = asyncio.run(
        links_routes.update_link(
            request=LinkUpdateRequest(description="renamed"),
            project_id=project_id,
            link_id=LINK_ID,
            current_user=OWNER,
        )
    )
    assert updated.description == "renamed"

    asyncio.run(
        links_routes.delete_link(project_id=project_id, link_id=LINK_ID, current_user=EDITOR)
    )
    assert projects.find_one({"_id": ObjectId(project_id)})["links"] == []


def test_viewer_reads_but_cannot_write(make_project):
    project_id, projects = make_project(is_public=False)

    assert _forbidden(lambda: _create(project_id, VIEWER)) == (
        "Edit permission required to create links"
    )
    assert _forbidden(
        lambda: asyncio.run(
            links_routes.update_link(
                request=LinkUpdateRequest(description="x"),
                project_id=project_id,
                link_id=LINK_ID,
                current_user=VIEWER,
            )
        )
    ) == ("Edit permission required to update links")
    assert _forbidden(
        lambda: asyncio.run(
            links_routes.delete_link(project_id=project_id, link_id=LINK_ID, current_user=VIEWER)
        )
    ) == ("Edit permission required to delete links")
    assert len(projects.find_one({"_id": ObjectId(project_id)})["links"]) == 1


@pytest.mark.parametrize("user", [STRANGER, ANONYMOUS], ids=lambda u: u.email)
def test_public_project_refuses_link_creation_to_non_members(make_project, user):
    project_id, projects = make_project(is_public=True)

    assert _forbidden(lambda: _create(project_id, user)) == (
        "Edit permission required to create links"
    )
    assert len(projects.find_one({"_id": ObjectId(project_id)})["links"]) == 1


def test_owner_creates_links_on_a_public_project(make_project):
    project_id, projects = make_project(is_public=True)

    _create(project_id, OWNER)

    assert len(projects.find_one({"_id": ObjectId(project_id)})["links"]) == 2
