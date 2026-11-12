"""MultiQC data time travel: a version's data is the set of reports it held.

A MultiQC collection has one report per run, each with its own content-addressed
parquet. A dashboard version therefore stamps the report ids (``manifest``), a
past view reads only those reports, and ``report_sets`` lets a caller name a set
of its own (a reader's last-visit baseline). The failure to rule out is the
quiet one: a view labelled "as of v3" that draws every report the collection
holds today.
"""

from __future__ import annotations

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.services.multiqc.dc_lookup import report_set_digest

API = "/depictio/api/v1/dashboards"

MAIN = ObjectId("6c0000000000000000000001")
PID = ObjectId("6c0000000000000000000002")
WF = ObjectId("6c0000000000000000000003")
DC_MQC = ObjectId("6c0000000000000000000004")
OTHER_DC = ObjectId("6c0000000000000000000005")

R1 = ObjectId("6c00000000000000000000a1")
R2 = ObjectId("6c00000000000000000000a2")
R3 = ObjectId("6c00000000000000000000a3")
FOREIGN = ObjectId("6c00000000000000000000b1")

LOC = {R1: "s3://b/dc/aaa/multiqc.parquet", R2: "s3://b/dc/bbb/multiqc.parquet"}
LOC[R3] = "s3://b/dc/ccc/multiqc.parquet"


class _User:
    id = str(ObjectId())
    email = "viewer@example.com"
    is_admin = False
    is_anonymous = False


class _Cache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data
        return True

    def set_nx(self, key, data, ttl=None):
        return self.store.setdefault(key, data) is data


def _reports(db):
    db["multiqc"].insert_many(
        [
            {
                "_id": R1,
                "data_collection_id": str(DC_MQC),
                "s3_location": LOC[R1],
                "metadata": {"samples": ["s1", "s2"]},
            },
            {
                "_id": R2,
                "data_collection_id": str(DC_MQC),
                "s3_location": LOC[R2],
                "metadata": {"samples": ["s2", "s3"]},
            },
            {
                "_id": R3,
                "data_collection_id": str(DC_MQC),
                "s3_location": LOC[R3],
                "metadata": {"samples": ["s4"]},
            },
            {
                "_id": FOREIGN,
                "data_collection_id": str(OTHER_DC),
                "s3_location": "s3://b/other/zzz/multiqc.parquet",
                "metadata": {"samples": ["x"]},
            },
        ]
    )


# ── the stamp ──────────────────────────────────────────────────────────────


@pytest.fixture()
def stamp_store(monkeypatch):
    from depictio.api.v1 import db as db_module
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning

    db = mongomock.MongoClient()["mqc_stamps"]
    _reports(db)
    db["projects"].insert_one(
        {
            "_id": PID,
            "workflows": [
                {
                    "_id": WF,
                    "data_collections": [
                        {"_id": DC_MQC, "data_collection_tag": "qc", "config": {"type": "multiqc"}}
                    ],
                }
            ],
        }
    )
    monkeypatch.setattr(db_module, "multiqc_collection", db["multiqc"])
    monkeypatch.setattr(versioning, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(versioning, "projects_collection", db["projects"])
    monkeypatch.setattr(versioning, "dashboards_collection", db["dashboards"])
    return db


def _stamp(dc_id=DC_MQC):
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import build_dc_stamps
    from depictio.models.models.dashboard_versions import TabSnapshot

    tab = TabSnapshot(
        dashboard_id=str(MAIN),
        is_main_tab=True,
        tab_order=0,
        title="Main",
        stored_metadata=[
            {
                "index": "qc",
                "component_type": "multiqc",
                "dc_id": str(dc_id),
                "dc_config": {"type": "multiqc"},
            }
        ],
    )
    (stamp,) = build_dc_stamps([tab])
    return stamp


def test_a_multiqc_stamp_records_the_report_set(stamp_store):
    stamp = _stamp()

    assert stamp.version_kind == "manifest"
    assert stamp.reason is None
    assert stamp.report_ids == sorted([str(R1), str(R2), str(R3)]), "only this DC's reports"
    assert stamp.s3_locations == [LOC[R1], LOC[R2], LOC[R3]]
    assert stamp.sample_count == 4, "unique samples across reports"
    assert stamp.manifest_digest == report_set_digest([str(R1), str(R2), str(R3)])
    assert stamp.as_of is not None
    assert stamp.unversioned_parts == ["report_overwrites"]


def test_a_multiqc_collection_without_reports_stays_unstamped(stamp_store):
    stamp_store["multiqc"].delete_many({"data_collection_id": str(DC_MQC)})

    stamp = _stamp()

    assert stamp.version_kind == "none"
    assert stamp.reason == "no_multiqc_reports"
    assert stamp.report_ids == []


def test_old_stamps_without_report_ids_still_validate():
    from depictio.models.models.dashboard_versions import DataCollectionStamp

    stamp = DataCollectionStamp.model_validate(
        {"dc_id": "x", "version_kind": "none", "reason": "manifest_versioning_not_enabled"}
    )

    assert stamp.report_ids == []


def test_stamps_do_not_enter_the_content_hash():
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import compute_content_hash
    from depictio.models.models.dashboard_versions import TabSnapshot

    assert "report_ids" not in TabSnapshot.model_fields
    assert "data_collections" not in TabSnapshot.model_fields
    tab = TabSnapshot(dashboard_id=str(MAIN), is_main_tab=True, tab_order=0, title="Main")
    assert compute_content_hash([tab]) == compute_content_hash([tab])


# ── the lookup ─────────────────────────────────────────────────────────────


def test_pinned_locations_drop_missing_and_foreign_reports(stamp_store):
    from depictio.api.v1.services.multiqc.dc_lookup import fetch_s3_locations_for_reports

    got = fetch_s3_locations_for_reports(
        str(DC_MQC), [str(R2), str(FOREIGN), "not-an-id", str(ObjectId())]
    )

    assert got == [LOC[R2]], "another DC's report and unknown ids are dropped"


# ── the renders ────────────────────────────────────────────────────────────

COMPONENT = {
    "index": "qc",
    "component_type": "multiqc",
    "dc_id": str(DC_MQC),
    "selected_module": "fastqc",
    "selected_plot": "fastqc_sequence_counts",
    "selected_dataset": None,
}


@pytest.fixture()
def env(monkeypatch):
    from depictio.api import cache as cache_module
    from depictio.api.v1 import db as db_module
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store
    from depictio.api.v1.endpoints.routers import router
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    db = mongomock.MongoClient()["mqc_renders"]
    _reports(db)
    db["dashboards"].insert_one(
        {
            "_id": MAIN,
            "dashboard_id": MAIN,
            "project_id": PID,
            "is_main_tab": True,
            "parent_dashboard_id": None,
            "title": "Main",
            "tab_order": 0,
            "stored_metadata": [COMPONENT],
        }
    )
    monkeypatch.setattr(dash_routes, "check_project_permission", lambda *a, **k: True)
    monkeypatch.setattr(dash_routes, "dashboards_collection", db["dashboards"])
    monkeypatch.setattr(db_module, "multiqc_collection", db["multiqc"])
    monkeypatch.setattr(db_module, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(version_store, "dashboard_versions_collection", db["dashboard_versions"])
    cache = _Cache()
    monkeypatch.setattr(cache_module, "get_cache", lambda: cache)

    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    app.dependency_overrides[get_user_or_anonymous] = lambda: _User()
    return {
        "client": TestClient(app),
        "cache": cache,
        "versions": db["dashboard_versions"],
        "dash_routes": dash_routes,
        "monkeypatch": monkeypatch,
    }


def _version(env, report_ids):
    version_id = str(ObjectId())
    env["versions"].insert_one(
        {
            "version_id": version_id,
            "family_id": str(MAIN),
            "seq": 1,
            "tabs": [],
            "data_collections": [
                {
                    "dc_id": str(DC_MQC),
                    "dc_type": "multiqc",
                    "version_kind": "manifest",
                    "report_ids": [str(r) for r in report_ids],
                }
            ],
        }
    )
    return version_id


def _figure_keys(locations, filter_sig):
    from depictio.api.v1.services.multiqc.figures import generate_figure_cache_key

    return generate_figure_cache_key(
        locations,
        "fastqc",
        "fastqc_sequence_counts",
        None,
        "light",
        filter_sig=filter_sig,
        dc_id=str(DC_MQC),
    )


def _warm_bare(env, locations):
    bare = _figure_keys(locations, None)
    env["cache"].store[bare] = {"data": [{"y": [1]}], "layout": {}}


def test_a_pinned_render_reads_only_the_pinned_reports(env):
    _warm_bare(env, [LOC[R1], LOC[R2]])
    version = _version(env, [R1, R2])

    response = env["client"].post(
        f"{API}/render_multiqc/{MAIN}/qc", json={"as_of_version": version}
    )

    assert response.status_code == 200, response.text
    assert response.json()["figure"]["data"] == [{"y": [1]}], "served from the subset's bare key"
    digest = report_set_digest([str(R1), str(R2)])
    salted = _figure_keys([LOC[R1], LOC[R2]], f"v=0||pin={digest}")
    assert salted in env["cache"].store, "the pinned read is cached under its own, pin-salted key"
    live_style = _figure_keys([LOC[R1], LOC[R2]], "v=0|")
    assert live_style not in env["cache"].store, "never the live entry"


def test_report_sets_in_the_body_pin_without_a_version(env):
    _warm_bare(env, [LOC[R3]])

    response = env["client"].post(
        f"{API}/render_multiqc/{MAIN}/qc", json={"report_sets": {str(DC_MQC): [str(R3)]}}
    )

    assert response.status_code == 200, response.text
    assert _figure_keys([LOC[R3]], f"v=0||pin={report_set_digest([str(R3)])}") in env["cache"].store


def test_a_pin_to_vanished_reports_is_a_400(env):
    version = _version(env, [ObjectId()])

    response = env["client"].post(
        f"{API}/render_multiqc/{MAIN}/qc", json={"as_of_version": version}
    )

    assert response.status_code == 400
    assert "exist any more" in response.json()["detail"]


def test_a_pin_naming_another_collections_report_is_a_400(env):
    response = env["client"].post(
        f"{API}/render_multiqc/{MAIN}/qc", json={"report_sets": {str(DC_MQC): [str(FOREIGN)]}}
    )

    assert response.status_code == 400


def test_a_stale_version_is_still_a_400(env):
    response = env["client"].post(f"{API}/render_multiqc/{MAIN}/qc", json={"as_of_version": "gone"})

    assert response.status_code == 400
    assert "no longer exists" in response.json()["detail"]


def test_a_cold_pinned_subset_builds_in_the_background(env, monkeypatch):
    from depictio.api.v1.services import multiqc_prerender_store

    monkeypatch.setattr(multiqc_prerender_store, "read_figure", lambda *a, **k: None)
    started = []
    monkeypatch.setattr(
        env["dash_routes"], "_start_pinned_multiqc_build", lambda *a, **k: started.append(a)
    )

    response = env["client"].post(
        f"{API}/render_multiqc/{MAIN}/qc", json={"report_sets": {str(DC_MQC): [str(R1)]}}
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "preparing"
    (args,) = started
    assert args[3] == [LOC[R1]], "the build gets the pinned locations, not the collection's"


def test_general_stats_reads_only_the_pinned_reports(env, monkeypatch):
    from depictio.api.v1.services.multiqc import figures, general_stats_payload

    seen = []
    monkeypatch.setattr(figures, "_get_local_path_for_s3", lambda p, **k: p)

    def fake_payload(*, parquet_path, **kwargs):
        seen.append(list(parquet_path))
        return {"is_paired_end": False, "all_samples": [], "modes": {}}

    monkeypatch.setattr(general_stats_payload, "build_general_stats_payload", fake_payload)
    url = f"{API}/render_multiqc_general_stats/{MAIN}/qc"

    live = env["client"].post(url, json={})
    pinned = env["client"].post(url, json={"report_sets": {str(DC_MQC): [str(R1), str(R2)]}})
    pinned_again = env["client"].post(url, json={"report_sets": {str(DC_MQC): [str(R1), str(R2)]}})

    assert live.status_code == pinned.status_code == pinned_again.status_code == 200
    assert seen == [[LOC[R1], LOC[R2], LOC[R3]], [LOC[R1], LOC[R2]]], (
        "live reads all three, the pin two, and the repeat is a cache hit"
    )
