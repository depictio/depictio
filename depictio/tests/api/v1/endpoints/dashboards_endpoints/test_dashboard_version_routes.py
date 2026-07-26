"""HTTP behaviour of the dashboard version routes.

Two classes of invariant here, and both have bitten this codebase's
neighbours before:

**Routing.** ``routes.py`` declares ``GET /dashboards/{dashboard_id}/yaml``
and ``/json``. A greedy path parameter there would happily match
``/dashboards/versions/<uuid>``, silently turning a version fetch into a YAML
export of a nonexistent dashboard. These tests issue real requests rather than
trusting registration order.

**Permission gates.** ``POST /dashboards/save`` has a branch that upserts with
no permission check at all. Nothing here may inherit that shape, so every
route is exercised against a caller who lacks the required level.
"""

from __future__ import annotations

from datetime import datetime

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE = datetime(2026, 3, 1, 12, 0, 0)


class _User:
    def __init__(self, uid: str, email: str, is_admin: bool = False) -> None:
        self.id = uid
        self.email = email
        self.is_admin = is_admin
        self.is_anonymous = False


CALLER = _User(str(ObjectId()), "caller@example.com")


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch):
    """A live app wired to in-memory Mongo, with permissions under test control."""
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
        "versions": db["dashboard_versions"],
        "granted": granted,
        "versioning": versioning,
    }


API = "/depictio/api/v1/dashboards"


def _make_dashboard(ctx, *, title="Main", components=None, parent=None, tab_order=0, did=None):
    did = did or ObjectId()
    ctx["dashboards"].insert_one(
        {
            "_id": did,
            "dashboard_id": did,
            "project_id": ObjectId(),
            "title": title,
            "is_main_tab": parent is None,
            "parent_dashboard_id": parent,
            "tab_order": tab_order,
            "stored_metadata": components or [],
            "left_panel_layout_data": [],
            "right_panel_layout_data": [],
            "permissions": {"owners": [{"email": "owner@example.com"}]},
            "is_public": False,
        }
    )
    return did


def _capture(ctx, did, **kwargs):
    kwargs.setdefault("author", CALLER)
    kwargs.setdefault("now", BASE)
    return ctx["versioning"].capture_dashboard_version(did, **kwargs)


# ── routing ─────────────────────────────────────────────────────────────────


def test_version_path_is_not_shadowed_by_the_yaml_catch_all(ctx) -> None:
    """`/dashboards/versions/{id}` must not be eaten by `/{dashboard_id}/yaml`."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    response = ctx["client"].get(f"{API}/versions/{record.version_id}")

    assert response.status_code == 200, response.text
    assert response.json()["version_id"] == record.version_id


def test_list_endpoint_resolves(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="explicit")

    response = ctx["client"].get(f"{API}/{did}/versions")

    assert response.status_code == 200, response.text
    assert len(response.json()["versions"]) == 1


def test_list_omits_the_snapshot_payload(ctx) -> None:
    """`tabs` is ~95% of a record; the timeline must not ship it."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="explicit")

    row = ctx["client"].get(f"{API}/{did}/versions").json()["versions"][0]

    assert "tabs" not in row


def test_current_version_is_identified(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    body = ctx["client"].get(f"{API}/{did}/versions").json()

    assert body["current_version_id"] == record.version_id


def test_current_version_is_none_after_an_edit(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": [{"index": "b"}]}})

    body = ctx["client"].get(f"{API}/{did}/versions").json()

    assert body["current_version_id"] is None, "live state differs from every stored version"


# ── permission gates ────────────────────────────────────────────────────────


def test_listing_requires_viewer(ctx) -> None:
    """Even the timeline is project data — it leaks titles and author emails."""
    did = _make_dashboard(ctx)
    _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "none"

    response = ctx["client"].get(f"{API}/{did}/versions")

    assert response.status_code == 403


def test_reading_one_version_requires_viewer(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "none"

    response = ctx["client"].get(f"{API}/versions/{record.version_id}")

    assert response.status_code == 403


def test_pin_requires_editor(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "viewer"

    response = ctx["client"].post(f"{API}/versions/{record.version_id}/pin", json={})

    assert response.status_code == 403


def test_restore_requires_editor(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "viewer"

    response = ctx["client"].post(f"{API}/versions/{record.version_id}/restore")

    assert response.status_code == 403


def test_delete_requires_owner_not_merely_editor(ctx) -> None:
    """Erasing history is the one action a restore cannot undo."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "editor"

    response = ctx["client"].delete(f"{API}/versions/{record.version_id}")

    assert response.status_code == 403


def test_version_of_another_family_is_still_guarded(ctx) -> None:
    """A guessed version_id must not bypass the family's permission check."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "viewer"

    response = ctx["client"].patch(f"{API}/versions/{record.version_id}", json={"label": "sneaky"})

    assert response.status_code == 403


# ── pin / rename / delete ───────────────────────────────────────────────────


def test_pin_sets_label_and_seals(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    response = ctx["client"].post(
        f"{API}/versions/{record.version_id}/pin", json={"label": "Known good"}
    )

    assert response.status_code == 200, response.text
    stored = ctx["versions"].find_one({"version_id": record.version_id})
    assert stored["pinned"] is True
    assert stored["label"] == "Known good"
    assert stored["coalesce_until"] == stored["created_at"], (
        "pinning must seal the window so the next autosave cannot rewrite this state"
    )


def test_unpin_restores_eligibility(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["client"].post(f"{API}/versions/{record.version_id}/pin", json={"label": "x"})

    ctx["client"].delete(f"{API}/versions/{record.version_id}/pin")

    assert ctx["versions"].find_one({"version_id": record.version_id})["pinned"] is False


def test_rename_sets_label(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    ctx["client"].patch(f"{API}/versions/{record.version_id}", json={"label": "Renamed"})

    assert ctx["versions"].find_one({"version_id": record.version_id})["label"] == "Renamed"


def test_delete_refuses_a_pinned_version_without_force(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    first = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": [{"index": "b"}]}})
    _capture(ctx, did, kind="explicit", now=datetime(2026, 3, 2))
    ctx["client"].post(f"{API}/versions/{first.version_id}/pin", json={"label": "keep"})

    response = ctx["client"].delete(f"{API}/versions/{first.version_id}")

    assert response.status_code == 409
    assert ctx["versions"].count_documents({"version_id": first.version_id}) == 1


def test_delete_refuses_the_only_version(ctx) -> None:
    """Leaving a dashboard with no history at all is never what was meant."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    response = ctx["client"].delete(f"{API}/versions/{record.version_id}")

    assert response.status_code == 409


# ── restore ─────────────────────────────────────────────────────────────────


def test_restore_puts_content_back(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "keep-me"}])
    record = _capture(ctx, did, kind="explicit")

    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": []}})
    response = ctx["client"].post(f"{API}/versions/{record.version_id}/restore")

    assert response.status_code == 200, response.text
    live = ctx["dashboards"].find_one({"_id": did})
    assert live["stored_metadata"] == [{"index": "keep-me"}]


def test_restore_is_itself_undoable(ctx) -> None:
    """The state being replaced is captured before anything is written."""
    did = _make_dashboard(ctx, components=[{"index": "original"}])
    first = _capture(ctx, did, kind="explicit")

    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": [{"index": "newer"}]}})
    ctx["client"].post(f"{API}/versions/{first.version_id}/restore")

    hashes = [v["tabs"][0]["stored_metadata"] for v in ctx["versions"].find({})]
    assert [{"index": "newer"}] in hashes, (
        "the pre-restore state must be recoverable, or restore itself destroys work"
    )


def test_restore_never_touches_permissions(ctx) -> None:
    """A stale snapshot must not resurrect a revoked access grant."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    ctx["dashboards"].update_one(
        {"_id": did},
        {
            "$set": {
                "permissions": {"owners": [{"email": "new-owner@example.com"}]},
                "is_public": True,
            }
        },
    )
    ctx["client"].post(f"{API}/versions/{record.version_id}/restore")

    live = ctx["dashboards"].find_one({"_id": did})
    assert live["permissions"]["owners"][0]["email"] == "new-owner@example.com"
    assert live["is_public"] is True


def test_restore_recreates_a_deleted_tab(ctx) -> None:
    main = _make_dashboard(ctx, title="Main")
    child = _make_dashboard(ctx, title="Tab 2", parent=main, tab_order=1)
    record = _capture(ctx, main, kind="explicit")

    ctx["dashboards"].delete_one({"_id": child})
    response = ctx["client"].post(f"{API}/versions/{record.version_id}/restore")

    assert response.json()["tabs_created"] == 1
    assert ctx["dashboards"].count_documents({"parent_dashboard_id": main}) == 1


def test_restore_removes_a_tab_added_later(ctx) -> None:
    main = _make_dashboard(ctx, title="Main")
    record = _capture(ctx, main, kind="explicit")

    _make_dashboard(ctx, title="Tab added later", parent=main, tab_order=1)
    response = ctx["client"].post(f"{API}/versions/{record.version_id}/restore")

    assert response.json()["tabs_deleted"] == 1
    assert ctx["dashboards"].count_documents({"parent_dashboard_id": main}) == 0


def test_restore_records_a_restore_point(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": [{"index": "b"}]}})

    body = ctx["client"].post(f"{API}/versions/{record.version_id}/restore").json()

    restored = ctx["versions"].find_one({"version_id": body["new_version_id"]})
    assert restored["kind"] == "restore"
    assert restored["parent_version_id"] == record.version_id


def test_restore_of_unknown_version_is_404(ctx) -> None:
    assert ctx["client"].post(f"{API}/versions/deadbeef/restore").status_code == 404
