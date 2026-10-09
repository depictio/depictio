"""Which kind of version the real save route asks for.

Calls ``save_dashboard`` itself against mongomock and records the capture
call, so the decision is tested where it is made rather than re-implemented.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.api.v1.endpoints.dashboards_endpoints import versioning
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission, UserBase


@pytest.fixture
def captures():
    database = mongomock.MongoClient()["depictio_test"]
    calls: list[dict] = []
    with (
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        patch.object(dash_routes, "check_project_permission", return_value=True),
        patch.object(dash_routes, "get_project_visibility", return_value=False),
        patch.object(versioning, "ensure_baseline_quietly", return_value=None),
        patch.object(
            versioning,
            "capture_quietly",
            side_effect=lambda dashboard_id, **kwargs: calls.append(kwargs),
        ),
    ):
        yield calls


@pytest.fixture
def user():
    u = UserBase(id=ObjectId(), email="owner@example.com")
    u.is_anonymous = False
    return u


def _save(dashboard_id, project_id, user, *, title="Dashboard", force_screenshot=False):
    data = DashboardData(
        dashboard_id=dashboard_id,
        title=title,
        project_id=project_id,
        permissions=Permission(owners=[user]),
    )
    return asyncio.run(
        dash_routes.save_dashboard(
            dashboard_id=dashboard_id,
            data=data,
            current_user=user,
            force_screenshot=force_screenshot,
        )
    )


def test_creating_a_dashboard_is_an_explicit_version(captures, user) -> None:
    """As an autosave, the creator's first edits would fold into and erase it."""
    _save(ObjectId(), ObjectId(), user)

    assert captures[-1]["kind"] == "explicit"
    assert captures[-1]["seal"] is False


def test_an_autosave_of_an_existing_dashboard_is_auto(captures, user) -> None:
    dashboard_id, project_id = ObjectId(), ObjectId()
    _save(dashboard_id, project_id, user)

    _save(dashboard_id, project_id, user, title="Renamed")

    assert captures[-1]["kind"] == "auto"
    assert captures[-1]["seal"] is False


def test_a_save_click_is_explicit_and_seals(captures, user) -> None:
    dashboard_id, project_id = ObjectId(), ObjectId()
    _save(dashboard_id, project_id, user)

    _save(dashboard_id, project_id, user, force_screenshot=True)

    assert captures[-1]["kind"] == "explicit"
    assert captures[-1]["seal"] is True


def test_a_save_seeds_the_baseline_from_the_state_it_replaces(user) -> None:
    """Seeded before the write, or the baseline would hold the saved state."""
    dashboards = mongomock.MongoClient()["depictio_test"]["dashboards"]
    seen: list[str | None] = []

    def baseline(dashboard_id, **_kwargs):
        doc = dashboards.find_one({"dashboard_id": dashboard_id})
        seen.append(doc["title"] if doc else None)

    with (
        patch.object(dash_routes, "dashboards_collection", dashboards),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        patch.object(dash_routes, "check_project_permission", return_value=True),
        patch.object(dash_routes, "get_project_visibility", return_value=False),
        patch.object(versioning, "ensure_baseline_quietly", side_effect=baseline),
        patch.object(versioning, "capture_quietly", return_value=None),
    ):
        dashboard_id, project_id = ObjectId(), ObjectId()
        _save(dashboard_id, project_id, user, title="Before")
        _save(dashboard_id, project_id, user, title="After")

    # A creation has no earlier state to keep, so only the second save seeds.
    assert seen == ["Before"]
