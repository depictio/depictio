"""``tab_group``: the sidebar category a child tab is listed under."""

from types import SimpleNamespace
from unittest.mock import patch

import mongomock
from bson import ObjectId

from depictio.models.models.dashboards import DashboardDataLite

CHILD_TAB_YAML = """
title: Alpha Diversity
is_main_tab: false
tab_order: 3
tab_icon: mdi:chart-bell-curve
tab_group: Analysis
components: []
"""


def test_absent_by_default_and_from_yaml():
    dash = DashboardDataLite(title="Alpha Diversity", components=[], is_main_tab=False)
    assert dash.tab_group is None
    assert "tab_group" not in dash.to_yaml()


def test_child_tab_yaml_parses_the_group():
    assert DashboardDataLite.from_yaml(CHILD_TAB_YAML).tab_group == "Analysis"


def test_group_survives_yaml_and_full_round_trips():
    dash = DashboardDataLite(title="Sequencing QC", components=[], tab_group="Quality")
    assert "tab_group: Quality" in dash.to_yaml()
    assert DashboardDataLite.from_yaml(dash.to_yaml()).tab_group == "Quality"
    full = dash.to_full()
    assert full["tab_group"] == "Quality"
    assert DashboardDataLite.from_full(full).tab_group == "Quality"


def test_empty_group_is_not_exported():
    # A group cleared in the editor can come back as "" from an older client;
    # exporting `tab_group: ''` would read as a group with no name.
    assert "tab_group" not in DashboardDataLite.from_full({"tab_group": ""}).to_yaml()


def test_multi_tab_import_stores_the_group_and_export_gives_it_back():
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _import_multi_tab_dashboard,
    )

    yaml_data = {
        "main_dashboard": {"title": "nf-core/ampliseq", "components": []},
        "tabs": [
            {"title": "Sampling Campaign", "tab_group": "Campaign", "components": []},
            {"title": "Alpha Diversity", "tab_group": "Analysis", "components": []},
            {"title": "Downloads", "components": []},
        ],
    }
    client = mongomock.MongoClient()
    db = client.test_db
    project_id = ObjectId()
    db.projects.insert_one({"_id": project_id, "workflows": []})
    user = SimpleNamespace(id=str(ObjectId()), email="author@example.org")

    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    with (
        patch(f"{routes_mod}.dashboards_collection", db.dashboards),
        patch(f"{routes_mod}.projects_collection", db.projects),
        patch(f"{routes_mod}.get_project_visibility", lambda _project_id: False),
    ):
        _import_multi_tab_dashboard(yaml_data, project_id, overwrite=False, current_user=user)

    tabs = {d["title"]: d for d in db.dashboards.find({"is_main_tab": False})}
    assert tabs["Sampling Campaign"]["tab_group"] == "Campaign"
    assert tabs["Alpha Diversity"]["tab_group"] == "Analysis"
    assert tabs["Downloads"]["tab_group"] is None

    assert "tab_group: Analysis" in DashboardDataLite.from_full(tabs["Alpha Diversity"]).to_yaml()
    assert "tab_group" not in DashboardDataLite.from_full(tabs["Downloads"]).to_yaml()
    client.close()
