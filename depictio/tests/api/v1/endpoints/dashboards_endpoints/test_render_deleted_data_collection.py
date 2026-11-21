"""A render of a component whose data collection was deleted answers 410.

Deleting a data collection (directly, or by deleting the join that produced it)
leaves the dashboards reading it untouched. The render routes used to fail deep
in the Delta loader and answer an opaque 500; they now answer 410 with a
``data_collection_deleted`` code and a sentence the tile can show.
"""

from __future__ import annotations

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

API = "/depictio/api/v1/dashboards"

DID = ObjectId("6a0000000000000000000011")
PID = ObjectId("6a0000000000000000000012")
WF = ObjectId("6a0000000000000000000013")
DC = ObjectId("6a0000000000000000000014")
DC_GONE = ObjectId("6a0000000000000000000015")

EXPECTED_DETAIL = {
    "code": "data_collection_deleted",
    "message": "The data collection this component reads was deleted.",
}


class _Admin:
    def __init__(self):
        self.id = ObjectId()
        self.email = "admin@example.com"
        self.is_admin = True
        self.is_anonymous = False


def _component(kind: str, dc_id: ObjectId, dc_config: dict, **fields) -> dict:
    return {
        "index": f"{kind}-{dc_id}",
        "component_type": kind,
        "wf_id": WF,
        "dc_id": dc_id,
        "dc_config": dc_config,
        **fields,
    }


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from depictio.api import cache as cache_module
    from depictio.api.v1 import db as db_module
    from depictio.api.v1 import deltatables_utils
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions, version_store
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.routers import router
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    table = str(tmp_path / "delta")
    pl.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}).write_delta(table)
    dc_config = {"delta_location": table, "type": "table", "size_bytes": 0}

    db = mongomock.MongoClient()["deleted_dc"]
    # DC_GONE is read by components below but is no longer in the project.
    db["projects"].insert_one(
        {
            "_id": PID,
            "name": "demo",
            "permissions": {"owners": [], "editors": [], "viewers": []},
            "workflows": [
                {
                    "_id": WF,
                    "workflow_tag": "wf",
                    "data_collections": [
                        {"_id": DC, "data_collection_tag": "dc", "config": {"type": "table"}}
                    ],
                }
            ],
        }
    )
    db["deltatables"].insert_one({"data_collection_id": DC, "delta_table_location": table})
    components = []
    for dc_id in (DC, DC_GONE):
        components += [
            _component(
                "figure",
                dc_id,
                dc_config,
                mode="ui",
                visu_type="scatter",
                dict_kwargs={"x": "x", "y": "y"},
            ),
            _component("table", dc_id, dc_config),
            _component("map", dc_id, dc_config),
            _component("image", dc_id, dc_config, image_column="x"),
            _component("card", dc_id, dc_config, column_name="x", aggregation="sum"),
        ]
    db["dashboards"].insert_one(
        {
            "_id": DID,
            "dashboard_id": DID,
            "project_id": PID,
            "is_main_tab": True,
            "title": "demo",
            "stored_metadata": components,
        }
    )

    monkeypatch.setattr(dash_routes, "dashboards_collection", db["dashboards"])
    monkeypatch.setattr(dash_routes, "projects_collection", db["projects"])
    monkeypatch.setattr(core_functions, "dashboards_collection", db["dashboards"])
    monkeypatch.setattr(db_module, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(version_store, "dashboard_versions_collection", db["dashboard_versions"])
    monkeypatch.setattr(deltatables_utils, "polars_s3_config", {})
    monkeypatch.setattr(deltatables_utils, "_get_aggregation_version", lambda _dc: "1")

    class _Cache:
        def get(self, key):
            return None

        def set(self, *a, **k):
            return True

        def exists(self, key):
            return False

        def delete_pattern(self, pattern):
            return 0

    monkeypatch.setattr(cache_module, "get_cache", lambda: _Cache())
    monkeypatch.setattr(dash_routes, "should_offload_render", lambda **_k: False)
    deltatables_utils.clear_memory_cache()

    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    app.dependency_overrides[get_user_or_anonymous] = lambda: _Admin()
    return TestClient(app)


def _post(client, route: str, kind: str, dc_id: ObjectId):
    return client.post(f"{API}/{route}/{DID}/{kind}-{dc_id}", json={"filters": []})


ROUTES = [
    ("render_figure", "figure"),
    ("render_table", "table"),
    ("render_map", "map"),
    ("render_image_paths", "image"),
]


@pytest.mark.parametrize(("route", "kind"), ROUTES)
def test_deleted_collection_answers_410_with_code(env, route, kind):
    response = _post(env, route, kind, DC_GONE)

    assert response.status_code == 410
    assert response.json()["detail"] == EXPECTED_DETAIL


@pytest.mark.parametrize(("route", "kind"), ROUTES)
def test_existing_collection_is_not_refused(env, route, kind):
    """Whatever else a render does, a live collection is never a 410."""
    response = _post(env, route, kind, DC)

    assert response.status_code != 410


def test_existing_collection_figure_still_renders(env):
    response = _post(env, "render_figure", "figure", DC)

    assert response.status_code == 200
    assert response.json()["figure"]["data"]


def test_helper_ignores_a_malformed_id():
    """A non-ObjectId id is left to the render's own handling, not turned into a 410."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _require_live_data_collection,
    )

    _require_live_data_collection("not-an-id", "also-not-an-id")


def test_a_card_on_a_deleted_collection_says_why_it_has_no_value(env):
    response = env.post(f"{API}/bulk_compute_cards/{DID}", json={"filters": []})

    assert response.status_code == 200
    body = response.json()
    assert body["values"][f"card-{DC_GONE}"] is None
    assert body["secondary_values"][f"card-{DC_GONE}"] == {
        "__unavailable__": EXPECTED_DETAIL["message"]
    }
    # The card on the live collection is computed as before.
    assert body["values"][f"card-{DC}"] == 6
    assert "__unavailable__" not in (body["secondary_values"].get(f"card-{DC}") or {})


def test_a_dashboard_whose_only_card_reads_a_deleted_collection(env):
    response = env.post(
        f"{API}/bulk_compute_cards/{DID}",
        json={"filters": [], "component_ids": [f"card-{DC_GONE}"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["values"] == {f"card-{DC_GONE}": None}
    assert body["secondary_values"][f"card-{DC_GONE}"]["__unavailable__"]
