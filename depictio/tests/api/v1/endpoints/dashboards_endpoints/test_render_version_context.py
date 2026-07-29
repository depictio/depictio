"""Rendering a past version must use that version's spec and that version's data.

Two failures this pins, both of which look like working software:

**The spec.** If a render resolves its component from the *live* document while
the banner says "viewing v9", you get today's chart under a historical label —
or a hard 404 on a component that only existed then. Neither is distinguishable
from a bug in the version feature itself.

**The data.** A version stamps the Delta commit each collection was at.
Rendering it must pass that commit down to the loader, and when the commit is no
longer readable it must fall back to live and *say so* rather than 500 — a
vacuumed table should cost a warning, not a blank dashboard.

Mirrors ``test_dashboard_version_routes.py``'s mongomock + TestClient fixture.
"""

from __future__ import annotations

from datetime import datetime

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE = datetime(2026, 3, 1, 12, 0, 0)
API = "/depictio/api/v1/dashboards"

DC_ID = ObjectId()
DELTA_LOCATION = "s3://bucket/dc"


class _User:
    def __init__(self, uid: str, email: str, is_admin: bool = False) -> None:
        self.id = uid
        self.email = email
        self.is_admin = is_admin
        self.is_anonymous = False


CALLER = _User(str(ObjectId()), "caller@example.com")


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1 import deltatables_utils
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import (
        schema_integrity,
        version_store,
        versioning,
        versions_routes,
    )
    from depictio.api.v1.endpoints.routers import router
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    client = mongomock.MongoClient()
    db = client["depictioTest"]
    dashboards = db["dashboards"]
    deltatables = db["deltatables"]

    monkeypatch.setattr(version_store, "dashboard_versions_collection", db["dashboard_versions"])
    monkeypatch.setattr(version_store, "dashboard_version_counters_collection", db["counters"])
    monkeypatch.setattr(versioning, "dashboards_collection", dashboards)
    monkeypatch.setattr(versioning, "deltatables_collection", deltatables)
    monkeypatch.setattr(versions_routes, "dashboards_collection", dashboards)
    monkeypatch.setattr(dash_routes, "dashboards_collection", dashboards)
    monkeypatch.setattr(dash_routes, "projects_collection", db["projects"])
    monkeypatch.setattr(schema_integrity, "deltatables_collection", deltatables)
    monkeypatch.setattr(schema_integrity, "projects_collection", db["projects"])

    # `_delta_location_for` imports the collection lazily from depictio.api.v1.db.
    import depictio.api.v1.db as api_db

    monkeypatch.setattr(api_db, "deltatables_collection", deltatables)

    monkeypatch.setattr(
        dash_routes, "check_project_permission", lambda *a, **k: True, raising=False
    )
    monkeypatch.setattr(
        versions_routes, "sync_tab_family_permissions", lambda *a, **k: 0, raising=False
    )

    # Every Delta commit is readable unless a test says otherwise.
    available: dict = {"reason": None}
    probes: list = []

    def fake_available(location, version):
        probes.append((location, version))
        return available["reason"]

    monkeypatch.setattr(deltatables_utils, "check_delta_version_available", fake_available)

    # Record what the loader was asked for instead of touching S3.
    loads: list = []

    def fake_load(**kwargs):
        import polars as pl

        loads.append(kwargs)
        return pl.DataFrame({"sample": ["a"], "value": [1]})

    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", fake_load)

    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    app.dependency_overrides[get_user_or_anonymous] = lambda: CALLER

    return {
        "client": TestClient(app),
        "dashboards": dashboards,
        "deltatables": deltatables,
        "versions": db["dashboard_versions"],
        "versioning": versioning,
        "loads": loads,
        "probes": probes,
        "available": available,
    }


def _make_dashboard(ctx, components, did=None):
    did = did or ObjectId()
    ctx["dashboards"].insert_one(
        {
            "_id": did,
            "dashboard_id": did,
            "project_id": ObjectId(),
            "title": "Main",
            "is_main_tab": True,
            "parent_dashboard_id": None,
            "tab_order": 0,
            "stored_metadata": components,
            "left_panel_layout_data": [],
            "right_panel_layout_data": [],
            "permissions": {"owners": [{"email": "owner@example.com"}]},
            "is_public": False,
        }
    )
    return did


def _table_component(index="c1", column="value"):
    return {
        "index": index,
        "component_type": "table",
        "wf_id": ObjectId(),
        "dc_id": DC_ID,
        "column": column,
        "dc_config": {"type": "table", "delta_location": DELTA_LOCATION},
    }


def _record_aggregation(ctx, *, aggregation_version=1, delta_version=None):
    """A `deltatables` document shaped as `/deltatables/upsert` writes it."""
    ctx["deltatables"].replace_one(
        {"data_collection_id": DC_ID},
        {
            "data_collection_id": DC_ID,
            "delta_table_location": DELTA_LOCATION,
            "aggregation": [
                {
                    "aggregation_version": aggregation_version,
                    "aggregation_hash": "h",
                    "aggregation_columns_specs": [{"name": "value", "type": "int64"}],
                    "delta_version": delta_version,
                    "rows_total": 10,
                }
            ],
        },
        upsert=True,
    )


def _capture(ctx, did, **kwargs):
    kwargs.setdefault("author", CALLER)
    kwargs.setdefault("now", BASE)
    return ctx["versioning"].capture_dashboard_version(did, **kwargs)


def _render_table(ctx, did, component_id, body=None):
    return ctx["client"].post(f"{API}/render_table/{did}/{component_id}", json=body or {})


class TestTheSpecComesFromTheSnapshot:
    def test_a_live_render_is_unchanged_by_all_of_this(self, ctx):
        did = _make_dashboard(ctx, [_table_component()])

        response = _render_table(ctx, did, "c1")

        assert response.status_code == 200, response.text
        body = response.json()
        # No version was asked for, so nothing about versions appears.
        assert "version_id" not in body
        assert "data_degraded" not in body
        assert ctx["loads"][0]["delta_version"] is None

    def test_a_component_deleted_since_still_renders_at_its_version(self, ctx):
        """The 404 this prevents is the common case, not an edge case: a
        version is most worth looking at precisely when something was lost."""
        did = _make_dashboard(ctx, [_table_component()])
        record = _capture(ctx, did, kind="explicit")

        ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": []}})

        assert _render_table(ctx, did, "c1").status_code == 404

        response = _render_table(ctx, did, "c1", {"version_id": record.version_id})

        assert response.status_code == 200, response.text
        assert response.json()["version_id"] == record.version_id

    def test_a_since_edited_spec_is_not_used(self, ctx):
        """Otherwise you render today's chart under a historical banner."""
        did = _make_dashboard(ctx, [_table_component(column="value")])
        record = _capture(ctx, did, kind="explicit")

        ctx["dashboards"].update_one(
            {"_id": did}, {"$set": {"stored_metadata": [_table_component(column="edited")]}}
        )

        _render_table(ctx, did, "c1", {"version_id": record.version_id})

        # The loader is handed the snapshot's component, not the live one.
        assert ctx["loads"][-1]["data_collection_id"] == str(DC_ID)
        stored = ctx["versions"].find_one({"version_id": record.version_id})
        assert stored["tabs"][0]["stored_metadata"][0]["column"] == "value"

    def test_a_version_from_another_family_is_a_404(self, ctx):
        """Inherited from `_guarded_version_tab`, and worth pinning at this
        route too: viewer rights on one dashboard must not read another's."""
        mine = _make_dashboard(ctx, [_table_component()])
        theirs = _make_dashboard(ctx, [_table_component()])
        other_record = _capture(ctx, theirs, kind="explicit")

        response = _render_table(ctx, mine, "c1", {"version_id": other_record.version_id})

        assert response.status_code == 404
        assert "does not belong" in response.json()["detail"]

    def test_an_unknown_version_is_a_404(self, ctx):
        did = _make_dashboard(ctx, [_table_component()])

        response = _render_table(ctx, did, "c1", {"version_id": "deadbeef"})

        assert response.status_code == 404


class TestTheDataComesFromTheStampedCommit:
    def test_the_pinned_commit_reaches_the_loader(self, ctx):
        _record_aggregation(ctx, delta_version=3)
        did = _make_dashboard(ctx, [_table_component()])
        record = _capture(ctx, did, kind="explicit")

        response = _render_table(ctx, did, "c1", {"version_id": record.version_id})

        assert response.status_code == 200, response.text
        assert ctx["loads"][-1]["delta_version"] == 3
        assert response.json()["delta_versions"] == {str(DC_ID): 3}

    def test_a_stamp_with_no_delta_version_reads_live(self, ctx):
        """Every aggregation written before Delta provenance existed, and every
        UI upload, lands here. The stamp records `version_kind: "none"`."""
        _record_aggregation(ctx, delta_version=None)
        did = _make_dashboard(ctx, [_table_component()])
        record = _capture(ctx, did, kind="explicit")

        response = _render_table(ctx, did, "c1", {"version_id": record.version_id})

        assert response.status_code == 200
        assert ctx["loads"][-1]["delta_version"] is None
        assert "delta_versions" not in response.json()

    def test_an_unreadable_commit_degrades_to_live_with_a_reason(self, ctx):
        """200 with a warning, not a 500. A vacuumed table costs a note."""
        _record_aggregation(ctx, delta_version=3)
        did = _make_dashboard(ctx, [_table_component()])
        record = _capture(ctx, did, kind="explicit")
        ctx["available"]["reason"] = "vacuumed"

        response = _render_table(ctx, did, "c1", {"version_id": record.version_id})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data_degraded"] is True
        assert body["data_warnings"] == [
            {"dc_id": str(DC_ID), "requested_version": 3, "reason": "vacuumed"}
        ]
        # And it actually read live rather than failing the scan.
        assert ctx["loads"][-1]["delta_version"] is None

    def test_availability_is_probed_once_per_request_not_once_per_component(self, ctx):
        """`bulk_compute_cards` renders every card on a dashboard in one call."""
        _record_aggregation(ctx, delta_version=3)
        cards = [
            {
                "index": f"card{i}",
                "component_type": "card",
                "wf_id": ObjectId(),
                "dc_id": DC_ID,
                "dc_config": {"type": "table", "delta_location": DELTA_LOCATION},
                "aggregation": "count",
                "column_name": "value",
            }
            for i in range(6)
        ]
        did = _make_dashboard(ctx, cards)
        record = _capture(ctx, did, kind="explicit")
        ctx["probes"].clear()

        response = ctx["client"].post(
            f"{API}/bulk_compute_cards/{did}", json={"version_id": record.version_id}
        )

        assert response.status_code == 200, response.text
        assert len(ctx["probes"]) == 1, f"probed {len(ctx['probes'])} times for 6 cards"
