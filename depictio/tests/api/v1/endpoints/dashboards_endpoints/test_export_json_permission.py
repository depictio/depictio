"""GET /dashboards/{id}/json is gated on viewer access to the dashboard's project.

It used to export any dashboard to any caller, anonymous included, given its id.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes

DASHBOARD_ID = ObjectId()
PROJECT_ID = ObjectId()


def _export(doc, allowed=True):
    dashboards = MagicMock()
    dashboards.find_one.return_value = doc
    projects = MagicMock()
    projects.find_one.return_value = {"_id": PROJECT_ID, "name": "demo"}
    check = MagicMock(return_value=allowed)
    with (
        patch.object(dash_routes, "dashboards_collection", dashboards),
        patch.object(dash_routes, "projects_collection", projects),
        patch.object(dash_routes, "check_project_permission", check),
        patch.object(dash_routes, "_extract_data_integrity_metadata", return_value={}),
    ):
        result = asyncio.run(dash_routes.export_dashboard_as_json(str(DASHBOARD_ID), MagicMock()))
    return result, check


def test_export_without_viewer_access_is_403():
    with pytest.raises(HTTPException) as exc:
        _export({"dashboard_id": DASHBOARD_ID, "project_id": PROJECT_ID}, allowed=False)
    assert exc.value.status_code == 403


def test_export_checks_viewer_level_on_the_dashboards_project():
    _, check = _export({"dashboard_id": DASHBOARD_ID, "project_id": PROJECT_ID})
    project_id, _, level = check.call_args.args
    assert (project_id, level) == (PROJECT_ID, "viewer")


def test_export_of_a_dashboard_without_project_is_403():
    with pytest.raises(HTTPException) as exc:
        _export({"dashboard_id": DASHBOARD_ID})
    assert exc.value.status_code == 403


def test_export_with_access_returns_the_dashboard():
    result, _ = _export({"dashboard_id": DASHBOARD_ID, "project_id": PROJECT_ID, "title": "T"})
    assert result["dashboard"]["title"] == "T"
    assert result["_export_source"]["project_tag"] == "demo"
