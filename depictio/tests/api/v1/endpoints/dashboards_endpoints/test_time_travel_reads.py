"""What a pinned view reads besides its renders.

A version preview pins every tile to past data, but three other reads sat
beside the tiles and still answered with today's: a filter's option list, the
banner's claim about which collections travelled, and the sections a child tab
borrows from its siblings. Each looked right and was wrong, the failure this
feature cannot have:

* ``POST /filter_options/{id}``: a select offering values the pinned data does
  not hold, so picking one emptied every chart;
* ``POST /data_version_status/{id}``: "every value is from v3" over a
  collection added since, which reads live data;
* ``GET /cross_tab_components/{id}?version_id=``: today's persistent sections
  under the version's banner.
"""

from __future__ import annotations

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

API = "/depictio/api/v1/dashboards"

MAIN = ObjectId("6b0000000000000000000001")
CHILD = ObjectId("6b0000000000000000000002")
GONE_TAB = ObjectId("6b0000000000000000000003")
OTHER_FAMILY = ObjectId("6b0000000000000000000004")
PID = ObjectId("6b0000000000000000000005")
WF = ObjectId("6b0000000000000000000006")
DC = ObjectId("6b0000000000000000000007")
DC_MQC = ObjectId("6b0000000000000000000008")
DC_NEW = ObjectId("6b0000000000000000000009")
FOREIGN_DC = ObjectId("6b000000000000000000000a")


class _User:
    id = str(ObjectId())
    email = "viewer@example.com"
    is_admin = False
    is_anonymous = False


class _DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data
        return True


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from depictio.api import cache as cache_module
    from depictio.api.v1 import db as db_module
    from depictio.api.v1 import deltatables_utils
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store
    from depictio.api.v1.endpoints.deltatables_endpoints import routes as dt_routes
    from depictio.api.v1.endpoints.routers import router
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    # Two commits: v0 holds varieties a and b, v1 adds c and a far larger x.
    table = str(tmp_path / "delta")
    pl.DataFrame({"variety": ["a", "b"], "x": [1, 2]}).write_delta(table)
    pl.DataFrame({"variety": ["a", "b", "c"], "x": [1, 2, 30]}).write_delta(table, mode="overwrite")

    db = mongomock.MongoClient()["time_travel_reads"]
    db["projects"].insert_one(
        {
            "_id": PID,
            "workflows": [
                {
                    "_id": WF,
                    "workflow_tag": "wf",
                    "data_collections": [
                        {"_id": DC, "data_collection_tag": "iris", "config": {"type": "table"}},
                        {"_id": DC_MQC, "data_collection_tag": "qc", "config": {"type": "multiqc"}},
                        {"_id": DC_NEW, "data_collection_tag": "new", "config": {"type": "table"}},
                    ],
                }
            ],
        }
    )
    db["deltatables"].insert_one(
        {
            "data_collection_id": DC,
            "delta_table_location": table,
            "aggregation": [
                {
                    "aggregation_columns_specs": [
                        {"name": "x", "type": "int64", "specs": {"min": 1, "max": 30, "unique": 3}}
                    ]
                }
            ],
        }
    )
    db["dashboards"].insert_many(
        [
            {
                "_id": MAIN,
                "dashboard_id": MAIN,
                "project_id": PID,
                "is_main_tab": True,
                "parent_dashboard_id": None,
                "title": "Main",
                "tab_order": 0,
                "stored_metadata": [
                    {"index": "card", "component_type": "card", "dc_id": DC},
                    {"index": "qc", "component_type": "multiqc", "dc_id": DC_MQC},
                ],
            },
            {
                "_id": CHILD,
                "dashboard_id": CHILD,
                "project_id": PID,
                "is_main_tab": False,
                "parent_dashboard_id": MAIN,
                "title": "Child",
                "tab_order": 1,
                # Added after the version below was taken.
                "stored_metadata": [{"index": "new", "component_type": "table", "dc_id": DC_NEW}],
                "grid_sections": [{"name": "Today", "persistent": True}],
            },
        ]
    )

    granted = {"ok": True}
    monkeypatch.setattr(dash_routes, "check_project_permission", lambda *a, **k: granted["ok"])
    monkeypatch.setattr(dash_routes, "dashboards_collection", db["dashboards"])
    monkeypatch.setattr(dash_routes, "projects_collection", db["projects"])
    monkeypatch.setattr(db_module, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(dt_routes, "projects_collection", db["projects"])
    monkeypatch.setattr(dt_routes, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(dt_routes, "polars_s3_config", {})
    monkeypatch.setattr(version_store, "dashboard_versions_collection", db["dashboard_versions"])
    monkeypatch.setattr(deltatables_utils, "polars_s3_config", {})
    monkeypatch.setattr(deltatables_utils, "_get_aggregation_version", lambda _dc: "1")
    cache = _DictCache()
    monkeypatch.setattr(cache_module, "get_cache", lambda: cache)
    deltatables_utils.clear_memory_cache()

    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    app.dependency_overrides[get_user_or_anonymous] = lambda: _User()
    return {
        "client": TestClient(app),
        "versions": db["dashboard_versions"],
        "dashboards": db["dashboards"],
        "cache": cache,
        "granted": granted,
    }


def _version(env, *, family=MAIN, stamps=(), tabs=()) -> str:
    version_id = str(ObjectId())
    env["versions"].insert_one(
        {
            "version_id": version_id,
            "family_id": str(family),
            "seq": 1,
            "data_collections": list(stamps),
            "tabs": list(tabs),
        }
    )
    return version_id


def _delta(dc, n):
    return {"dc_id": str(dc), "version_kind": "delta", "delta_version": n}


# ── filter options ─────────────────────────────────────────────────────────


def _options(env, dashboard=MAIN, **body):
    return env["client"].post(f"{API}/filter_options/{dashboard}", json=body)


def test_unique_options_follow_the_pin(env):
    live = _options(env, dc_id=str(DC), column="variety", kind="unique")
    pinned = _options(
        env, dc_id=str(DC), column="variety", kind="unique", data_versions={str(DC): 0}
    )

    assert live.status_code == 200, live.text
    assert live.json()["values"] == ["a", "b", "c"]
    assert pinned.status_code == 200, pinned.text
    assert pinned.json() == {"column": "variety", "values": ["a", "b"]}


def test_unique_options_as_of_a_version(env):
    version = _version(env, stamps=[_delta(DC, 0)])

    response = _options(env, dc_id=str(DC), column="variety", kind="unique", as_of_version=version)

    assert response.json()["values"] == ["a", "b"]


def test_range_follows_the_pin(env):
    live = _options(env, dc_id=str(DC), column="x", kind="range")
    pinned = _options(env, dc_id=str(DC), column="x", kind="range", data_versions={str(DC): 0})

    assert live.json() == {"min": 1, "max": 30, "dtype": "int64", "unique": 3}
    assert pinned.status_code == 200, pinned.text
    assert pinned.json() == {"min": 1, "max": 2, "dtype": "int64", "unique": 2}


def test_pinned_options_are_cached_apart_from_live(env):
    """Salted with the pin: a historical list is never served as the live one."""
    _options(env, dc_id=str(DC), column="variety", kind="unique", data_versions={str(DC): 0})
    live = _options(env, dc_id=str(DC), column="variety", kind="unique")

    assert live.json()["values"] == ["a", "b", "c"]
    pinned_keys = [k for k in env["cache"].store if k.startswith("filter_options_")]
    assert pinned_keys and all(k.endswith("_dv0") for k in pinned_keys)


def test_a_collection_of_another_project_is_404(env):
    response = _options(env, dc_id=str(FOREIGN_DC), column="variety", kind="unique")

    assert response.status_code == 404


def test_a_pin_on_a_collection_without_history_is_400(env):
    response = _options(
        env, dc_id=str(DC_MQC), column="sample", kind="unique", data_versions={str(DC_MQC): 0}
    )

    assert response.status_code == 400
    assert "no commit log" in response.json()["detail"]


def test_a_stale_version_is_400_with_the_detail_the_editor_matches(env):
    response = _options(env, dc_id=str(DC), column="variety", kind="unique", as_of_version="gone")

    assert response.status_code == 400
    assert response.json()["detail"] == "Version gone no longer exists."


@pytest.mark.parametrize(
    "body",
    [
        {"column": "variety", "kind": "unique"},
        {"dc_id": str(DC), "kind": "unique"},
        {"dc_id": str(DC), "column": "variety", "kind": "values"},
        {"dc_id": str(DC), "column": "variety", "kind": "unique", "data_versions": {str(DC): -1}},
    ],
)
def test_a_malformed_request_is_400(env, body):
    assert _options(env, **body).status_code == 400


def test_options_need_viewer_access(env):
    env["granted"]["ok"] = False

    assert _options(env, dc_id=str(DC), column="variety", kind="unique").status_code == 403


# ── what each collection shows ─────────────────────────────────────────────


def _status(env, dashboard=MAIN, body=None):
    return env["client"].post(f"{API}/data_version_status/{dashboard}", json=body)


def test_status_names_every_collection_of_the_family(env):
    version = _version(
        env,
        stamps=[
            _delta(DC, 0),
            {
                "dc_id": str(DC_MQC),
                "version_kind": "none",
                "reason": "manifest_versioning_not_enabled",
            },
        ],
    )

    # Asked from the child tab: the answer covers the whole family.
    response = _status(env, CHILD, {"as_of_version": version})

    assert response.status_code == 200, response.text
    got = {entry["dc_id"]: entry for entry in response.json()["collections"]}
    assert list(got) == [str(DC), str(DC_MQC), str(DC_NEW)]
    assert got[str(DC)] == {
        "dc_id": str(DC),
        "workflow_tag": "wf",
        "data_collection_tag": "iris",
        "dc_type": "table",
        "status": "pinned",
        "delta_version": 0,
        "reason": None,
    }
    assert (got[str(DC_MQC)]["status"], got[str(DC_MQC)]["reason"]) == (
        "not_versioned",
        "manifest_versioning_not_enabled",
    )
    assert (got[str(DC_NEW)]["status"], got[str(DC_NEW)]["reason"]) == ("live", "not_in_version")


def test_status_without_time_travel_is_live(env):
    response = _status(env)

    statuses = [(e["status"], e["reason"]) for e in response.json()["collections"]]
    assert statuses == [
        ("live", None),
        ("not_versioned", "manifest_versioning_not_enabled"),
        ("live", None),
    ]


def test_status_of_a_collection_kept_live(env):
    version = _version(env, stamps=[_delta(DC, 0)])

    response = _status(env, body={"as_of_version": version, "data_versions": {str(DC): None}})

    first = response.json()["collections"][0]
    assert (first["status"], first["reason"]) == ("live", "kept_live")


def test_status_refuses_what_a_render_refuses(env):
    foreign = _version(env, family=OTHER_FAMILY, stamps=[_delta(DC, 0)])

    assert _status(env, body={"as_of_version": "gone"}).json()["detail"] == (
        "Version gone no longer exists."
    )
    assert _status(env, body={"as_of_version": foreign}).status_code == 400
    assert _status(env, body={"data_versions": {str(DC): True}}).status_code == 400


# ── cross-tab content as a version held it ─────────────────────────────────


def _cross_tab(env, dashboard=CHILD, version_id=None):
    params = {"version_id": version_id} if version_id else None
    return env["client"].get(f"{API}/cross_tab_components/{dashboard}", params=params)


def _snapshot_tab(tab_id, title, order, section):
    return {
        "dashboard_id": str(tab_id),
        "title": title,
        "tab_order": order,
        "stored_metadata": [
            {"index": f"{title}-fig", "component_type": "figure", "section": section}
        ],
        "grid_sections": [{"name": section, "persistent": True}],
        "right_panel_layout_data": [{"i": f"box-{title}-fig", "x": 0, "y": 0, "w": 4, "h": 3}],
    }


def test_cross_tab_sections_come_from_the_version(env):
    version = _version(
        env,
        tabs=[
            _snapshot_tab(MAIN, "Main", 0, "Then"),
            _snapshot_tab(CHILD, "Child", 1, "Then"),
            _snapshot_tab(GONE_TAB, "Gone", 2, "Then"),
        ],
    )

    live = _cross_tab(env).json()
    past = _cross_tab(env, version_id=version)

    assert [s["spec"]["name"] for s in live["persistent_sections"]] == ["Today"]
    assert past.status_code == 200, past.text
    body = past.json()
    assert [(s["owner_dashboard_id"], s["spec"]["name"]) for s in body["persistent_sections"]] == [
        (str(MAIN), "Then"),
        (str(CHILD), "Then"),
    ]
    assert body["persistent_sections"][0]["components"][0]["metadata"]["index"] == "Main-fig"
    assert body["version_id"] == version
    assert body["omitted_tab_ids"] == [str(GONE_TAB)]
    assert "version_id" not in live


def test_cross_tab_of_another_familys_version_is_404(env):
    version = _version(env, family=OTHER_FAMILY, tabs=[_snapshot_tab(MAIN, "Main", 0, "Then")])

    assert _cross_tab(env, version_id=version).status_code == 404
    assert _cross_tab(env, version_id="gone").status_code == 404
