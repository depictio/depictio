"""``POST /resolve_groups``: the guards and the hand-off to the link translation.

The translation itself (``resolve_group_defs_for_dc``) is covered with the
figure groups; what is checked here is what the endpoint adds: a required
``dc_id``, a data collection that must belong to the dashboard's project, and
the rewritten groups returned with one verdict per input group.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes

GROUP = {
    "name": "Group 1",
    "column_name": "guide",
    "values": ["ACG"],
    "color": "#ff0000",
    "dc_id": "dc-guide",
}


def _call(body: dict):
    return asyncio.run(
        routes.resolve_groups_endpoint("0" * 24, body, current_user=object(), access_token="t")
    )


@pytest.fixture
def project(monkeypatch):
    monkeypatch.setattr(routes, "_viewable_dashboard", lambda *_a: {"project_id": "p1"})
    monkeypatch.setattr(routes, "_project_collections", lambda _pid: {"dc-lib": {}, "dc-guide": {}})


def test_dc_id_is_required(project):
    with pytest.raises(HTTPException) as err:
        _call({"groups": [GROUP]})
    assert err.value.status_code == 400


def test_a_collection_of_another_project_is_a_404(project):
    with pytest.raises(HTTPException) as err:
        _call({"dc_id": "dc-elsewhere", "groups": [GROUP]})
    assert err.value.status_code == 404


def test_returns_the_rewritten_groups_and_one_verdict_each(project, monkeypatch):
    seen = {}

    def fake(group_defs, dc_id, project_id, token, component_type, target_columns=None):
        seen.update(dc_id=dc_id, project_id=project_id, component_type=component_type)
        return [{**group_defs[0], "column_name": "sample", "values": ["s1"]}], [
            {"status": "translated"}
        ]

    monkeypatch.setattr(routes, "_resolve_group_defs", fake)
    out = _call({"dc_id": "dc-lib", "groups": [GROUP]})
    assert out["groups"][0]["column_name"] == "sample"
    assert out["groups"][0]["values"] == ["s1"]
    assert out["status"] == [{"status": "translated"}]
    assert seen == {"dc_id": "dc-lib", "project_id": "p1", "component_type": "advanced_viz"}


def test_no_groups_resolves_to_nothing(project):
    assert _call({"dc_id": "dc-lib", "groups": []}) == {"groups": [], "status": []}
