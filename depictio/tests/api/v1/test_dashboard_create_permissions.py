"""A new dashboard's owners are set by the server, never taken from the client.

Creating a dashboard needs only viewer access to its project; were the client's
``permissions`` kept, a viewer could create a dashboard owned by somebody else,
or one only they and an unwitting owner could change. These call the real
``save_dashboard`` against mongomock, like ``test_dashboard_save_timestamps``.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission, UserBase


@pytest.fixture(autouse=True)
def _no_version_capture():
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning

    with (
        patch.object(versioning, "capture_quietly", return_value=None),
        patch.object(versioning, "ensure_baseline_quietly", return_value=None),
    ):
        yield


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        # Viewer on the project, nothing more.
        patch.object(
            dash_routes,
            "check_project_permission",
            side_effect=lambda pid, user, required="viewer": required == "viewer",
        ),
        patch.object(dash_routes, "get_project_visibility", return_value=False),
    ):
        yield database


def _user(email: str) -> UserBase:
    u = UserBase(id=ObjectId(), email=email)
    u.is_anonymous = False
    return u


def _save(dashboard_id, data, user):
    return asyncio.run(
        dash_routes.save_dashboard(dashboard_id=dashboard_id, data=data, current_user=user)
    )


def _owner_ids(doc) -> list[str]:
    return [str(o["_id"]) for o in doc["permissions"]["owners"]]


def test_a_new_dashboard_is_owned_by_its_creator_whatever_the_client_sends(db):
    creator, victim = _user("viewer@example.org"), _user("owner@example.org")
    project_id, dashboard_id = ObjectId(), ObjectId()
    forged = DashboardData(
        dashboard_id=dashboard_id,
        title="Mine",
        project_id=project_id,
        permissions=Permission(owners=[victim], editors=[creator]),
    )
    _save(dashboard_id, forged, creator)
    doc = db["dashboards"].find_one({"dashboard_id": dashboard_id})
    assert _owner_ids(doc) == [str(creator.id)]
    assert doc["permissions"]["editors"] == [] and doc["permissions"]["viewers"] == []


def test_the_react_client_s_own_payload_creates_the_same_dashboard(db):
    """createDashboard stamps the creator as sole owner: nothing changes for it."""
    creator = _user("me@example.org")
    project_id, dashboard_id = ObjectId(), ObjectId()
    data = DashboardData(
        dashboard_id=dashboard_id,
        title="Mine",
        project_id=project_id,
        permissions=Permission(owners=[creator]),
    )
    _save(dashboard_id, data, creator)
    doc = db["dashboards"].find_one({"dashboard_id": dashboard_id})
    assert _owner_ids(doc) == [str(creator.id)]
    assert doc["permissions"]["owners"][0]["email"] == "me@example.org"


def test_a_tab_takes_its_family_s_permissions_and_needs_edit_rights_on_it(db):
    owner, stranger = _user("owner@example.org"), _user("stranger@example.org")
    project_id, main_id = ObjectId(), ObjectId()
    _save(
        main_id,
        DashboardData(
            dashboard_id=main_id,
            title="Main",
            project_id=project_id,
            permissions=Permission(owners=[owner]),
        ),
        owner,
    )

    def tab(tab_id, owners):
        return DashboardData(
            dashboard_id=tab_id,
            title="Tab",
            project_id=project_id,
            is_main_tab=False,
            parent_dashboard_id=main_id,
            permissions=Permission(owners=owners),
        )

    tab_id = ObjectId()
    _save(tab_id, tab(tab_id, [stranger]), owner)
    doc = db["dashboards"].find_one({"dashboard_id": tab_id})
    assert _owner_ids(doc) == [str(owner.id)]

    other = ObjectId()
    with pytest.raises(HTTPException) as exc:
        _save(other, tab(other, [stranger]), stranger)
    assert exc.value.status_code == 403
    assert db["dashboards"].find_one({"dashboard_id": other}) is None
