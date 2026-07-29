"""Restoring a single component from a stored version.

The narrow edit, as distinct from a full restore: one component's config comes
back and *nothing else moves*. Every test here is about that boundary, because
the failure mode is silent — a restore that also reverts a neighbour, or moves
the grid, looks like it worked until someone notices their other work is gone.
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


class _User:
    def __init__(self, uid: str, email: str, is_admin: bool = False) -> None:
        self.id = uid
        self.email = email
        self.is_admin = is_admin
        self.is_anonymous = False


CALLER = _User(str(ObjectId()), "caller@example.com")


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import (
        version_store,
        versioning,
        versions_routes,
    )
    from depictio.api.v1.endpoints.routers import router
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    client = mongomock.MongoClient()
    db = client["depictioTest"]
    dashboards = db["dashboards"]

    monkeypatch.setattr(version_store, "dashboard_versions_collection", db["dashboard_versions"])
    monkeypatch.setattr(version_store, "dashboard_version_counters_collection", db["counters"])
    monkeypatch.setattr(versioning, "dashboards_collection", dashboards)
    monkeypatch.setattr(versioning, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(versions_routes, "dashboards_collection", dashboards)

    granted = {"level": "owner"}

    def fake_permission(project_id, user, required_permission="viewer"):
        order = {"none": -1, "viewer": 0, "editor": 1, "owner": 2}
        return order[required_permission] <= order[granted["level"]]

    monkeypatch.setattr(dash_routes, "check_project_permission", fake_permission)
    monkeypatch.setattr(
        versions_routes, "sync_tab_family_permissions", lambda *a, **k: 0, raising=False
    )

    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    app.dependency_overrides[get_user_or_anonymous] = lambda: CALLER

    return {
        "client": TestClient(app),
        "dashboards": dashboards,
        "granted": granted,
        "versioning": versioning,
    }


def _make_dashboard(ctx, *, components=None, layout=None, did=None):
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
            "stored_metadata": components or [],
            "left_panel_layout_data": [],
            "right_panel_layout_data": layout or [],
            "permissions": {"owners": [{"email": "owner@example.com"}]},
            "is_public": False,
        }
    )
    return did


def _capture(ctx, did, **kwargs):
    kwargs.setdefault("author", CALLER)
    kwargs.setdefault("now", BASE)
    return ctx["versioning"].capture_dashboard_version(did, **kwargs)


def _components(ctx, did):
    return ctx["dashboards"].find_one({"dashboard_id": did})["stored_metadata"]


def _by_index(components, index):
    return next(c for c in components if str(c.get("index")) == index)


def _restore(ctx, version_id, index, **body):
    return ctx["client"].post(
        f"{API}/versions/{version_id}/restore_component",
        json={"component_index": index, **body},
    )


# ── the narrow edit ─────────────────────────────────────────────────────────


def test_restores_only_the_named_component(ctx) -> None:
    """The whole point: neighbours keep whatever they hold now."""
    did = _make_dashboard(
        ctx,
        components=[
            {"index": "a", "title": "A v1"},
            {"index": "b", "title": "B v1"},
        ],
    )
    record = _capture(ctx, did, kind="explicit")

    ctx["dashboards"].update_one(
        {"dashboard_id": did},
        {
            "$set": {
                "stored_metadata": [
                    {"index": "a", "title": "A v2"},
                    {"index": "b", "title": "B v2"},
                ]
            }
        },
    )

    response = _restore(ctx, record.version_id, "a")
    assert response.status_code == 200, response.text

    components = _components(ctx, did)
    assert _by_index(components, "a")["title"] == "A v1"
    # If this is "B v1" the endpoint restored the whole snapshot and the
    # narrow edit is a lie.
    assert _by_index(components, "b")["title"] == "B v2"


def test_restore_preserves_component_order(ctx) -> None:
    """In-place replacement, not remove-and-append.

    Order is not purely cosmetic: layouts without an explicit grid entry fall
    back to document order, so reordering silently moves things.
    """
    did = _make_dashboard(
        ctx,
        components=[{"index": "a"}, {"index": "b"}, {"index": "c"}],
    )
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did},
        {"$set": {"stored_metadata": [{"index": "a"}, {"index": "b", "t": 2}, {"index": "c"}]}},
    )

    _restore(ctx, record.version_id, "b")

    assert [str(c["index"]) for c in _components(ctx, did)] == ["a", "b", "c"]


def test_restores_a_deleted_component(ctx) -> None:
    """Recovering something someone removed is the highest-value case."""
    did = _make_dashboard(
        ctx, components=[{"index": "a", "title": "A"}, {"index": "gone", "title": "Deleted"}]
    )
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did}, {"$set": {"stored_metadata": [{"index": "a", "title": "A"}]}}
    )

    response = _restore(ctx, record.version_id, "gone")

    assert response.status_code == 200, response.text
    assert response.json()["readded"] is True
    assert _by_index(_components(ctx, did), "gone")["title"] == "Deleted"


def test_missing_component_is_a_404_not_a_silent_noop(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    response = _restore(ctx, record.version_id, "never-existed")

    assert response.status_code == 404


# ── layout ──────────────────────────────────────────────────────────────────


def test_layout_is_left_alone_by_default(ctx) -> None:
    """ "Give me back what this chart showed" must not also move it."""
    did = _make_dashboard(
        ctx,
        components=[{"index": "a", "title": "A v1"}],
        layout=[{"i": "a", "x": 0, "y": 0, "w": 4, "h": 2}],
    )
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did},
        {
            "$set": {
                "stored_metadata": [{"index": "a", "title": "A v2"}],
                "right_panel_layout_data": [{"i": "a", "x": 6, "y": 3, "w": 2, "h": 1}],
            }
        },
    )

    _restore(ctx, record.version_id, "a")

    layout = ctx["dashboards"].find_one({"dashboard_id": did})["right_panel_layout_data"]
    assert layout == [{"i": "a", "x": 6, "y": 3, "w": 2, "h": 1}]


def test_layout_is_restored_when_asked(ctx) -> None:
    did = _make_dashboard(
        ctx,
        components=[{"index": "a", "title": "A v1"}],
        layout=[{"i": "a", "x": 0, "y": 0, "w": 4, "h": 2}],
    )
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did},
        {"$set": {"right_panel_layout_data": [{"i": "a", "x": 6, "y": 3, "w": 2, "h": 1}]}},
    )

    _restore(ctx, record.version_id, "a", restore_layout=True)

    layout = ctx["dashboards"].find_one({"dashboard_id": did})["right_panel_layout_data"]
    assert layout == [{"i": "a", "x": 0, "y": 0, "w": 4, "h": 2}]


def test_restoring_layout_does_not_move_neighbours(ctx) -> None:
    """Only the named component's grid entry is rewritten."""
    did = _make_dashboard(
        ctx,
        components=[{"index": "a"}, {"index": "b"}],
        layout=[
            {"i": "a", "x": 0, "y": 0, "w": 4, "h": 2},
            {"i": "b", "x": 4, "y": 0, "w": 4, "h": 2},
        ],
    )
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did},
        {
            "$set": {
                "right_panel_layout_data": [
                    {"i": "a", "x": 9, "y": 9, "w": 1, "h": 1},
                    {"i": "b", "x": 0, "y": 5, "w": 8, "h": 3},
                ]
            }
        },
    )

    _restore(ctx, record.version_id, "a", restore_layout=True)

    layout = ctx["dashboards"].find_one({"dashboard_id": did})["right_panel_layout_data"]
    entries = {e["i"]: e for e in layout}
    assert entries["a"] == {"i": "a", "x": 0, "y": 0, "w": 4, "h": 2}
    # b keeps the position it was moved to since the snapshot.
    assert entries["b"] == {"i": "b", "x": 0, "y": 5, "w": 8, "h": 3}


def test_a_component_with_no_grid_entry_is_left_alone(ctx) -> None:
    """No stored position means nothing to restore, not a crash.

    Components can exist without an explicit layout entry — the grid falls
    back to document order — so `restore_layout` has to tolerate its absence.
    """
    did = _make_dashboard(ctx, components=[{"index": "a", "title": "A v1"}], layout=[])
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did}, {"$set": {"stored_metadata": [{"index": "a", "title": "A v2"}]}}
    )

    response = _restore(ctx, record.version_id, "a", restore_layout=True)

    assert response.status_code == 200, response.text
    assert _by_index(_components(ctx, did), "a")["title"] == "A v1"


# ── undo + guards ───────────────────────────────────────────────────────────


def test_the_pre_restore_state_is_captured(ctx) -> None:
    """A component restore must be as undoable as a full one."""
    did = _make_dashboard(ctx, components=[{"index": "a", "title": "A v1"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did}, {"$set": {"stored_metadata": [{"index": "a", "title": "A v2"}]}}
    )

    _restore(ctx, record.version_id, "a")

    versions = ctx["client"].get(f"{API}/{did}/versions").json()["versions"]
    titles = []
    for summary in versions:
        detail = ctx["client"].get(f"{API}/versions/{summary['version_id']}").json()
        for tab in detail["tabs"]:
            for component in tab["stored_metadata"]:
                titles.append(component.get("title"))
    # "A v2" is only recoverable if it was captured before being overwritten.
    assert "A v2" in titles


def test_editor_permission_is_required(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a", "title": "A v1"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did}, {"$set": {"stored_metadata": [{"index": "a", "title": "A v2"}]}}
    )
    ctx["granted"]["level"] = "viewer"

    response = _restore(ctx, record.version_id, "a")

    assert response.status_code in (403, 404)
    assert _by_index(_components(ctx, did), "a")["title"] == "A v2"


def test_dc_id_is_rehydrated_to_an_objectid(ctx) -> None:
    """Snapshots flatten ObjectIds to strings.

    Writing one back verbatim leaves a component whose `dc_id` no lookup can
    match: it returns structurally intact and renders nothing, which reads as
    "restore did nothing".
    """
    dc_id = ObjectId()
    did = _make_dashboard(ctx, components=[{"index": "a", "dc_id": dc_id, "title": "A v1"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one(
        {"dashboard_id": did}, {"$set": {"stored_metadata": [{"index": "a", "title": "A v2"}]}}
    )

    _restore(ctx, record.version_id, "a")

    restored = _by_index(_components(ctx, did), "a")
    assert isinstance(restored["dc_id"], ObjectId)
    assert restored["dc_id"] == dc_id
