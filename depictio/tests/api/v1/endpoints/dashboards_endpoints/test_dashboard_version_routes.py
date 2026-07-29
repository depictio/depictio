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

    monkeypatch.setattr(version_store, "dashboard_versions_collection", db["dashboard_versions"])
    monkeypatch.setattr(version_store, "dashboard_version_counters_collection", db["counters"])
    monkeypatch.setattr(versioning, "dashboards_collection", dashboards)
    monkeypatch.setattr(versioning, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(versions_routes, "dashboards_collection", dashboards)
    # `GET /dashboards/get/{id}` lives in routes.py and holds its own handles;
    # without these it reaches for the real Mongo and hangs on connect.
    monkeypatch.setattr(dash_routes, "dashboards_collection", dashboards)
    monkeypatch.setattr(dash_routes, "projects_collection", db["projects"])
    monkeypatch.setattr(schema_integrity, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(schema_integrity, "projects_collection", db["projects"])

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
        "deltatables": db["deltatables"],
        "projects": db["projects"],
    }


API = "/depictio/api/v1/dashboards"


def _make_dashboard(ctx, *, title="Main", components=None, parent=None, tab_order=0, did=None):
    did = did or ObjectId()
    # Real components always carry a `dc_config` with the collection's type —
    # it is what tells the capture path which versioning family applies, and
    # therefore whether a schema is worth recording. Mirror that here so the
    # fixtures exercise the same path production does.
    for component in components or []:
        if component.get("dc_id") and "dc_config" not in component:
            component["dc_config"] = {"type": "table"}
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


# ── Previewing a past version through the normal load path ──────────────────


def _get(ctx, did, version_id=None):
    qs = f"?version_id={version_id}" if version_id else ""
    return ctx["client"].get(f"{API}/get/{did}{qs}")


def test_preview_returns_snapshot_content(ctx) -> None:
    did = _make_dashboard(ctx, title="Original", components=[{"index": "old"}])
    record = _capture(ctx, did, kind="explicit")

    ctx["dashboards"].update_one(
        {"_id": did}, {"$set": {"title": "Renamed", "stored_metadata": [{"index": "new"}]}}
    )

    body = _get(ctx, did, record.version_id).json()

    assert body["stored_metadata"] == [{"index": "old"}]
    assert body["title"] == "Original"


def test_preview_never_returns_snapshot_permissions(ctx) -> None:
    """The invariant that matters: a preview must not widen access.

    The restore path already pins this; this is the same guarantee on the read
    path, where a stale snapshot would otherwise be handed straight to a client
    that decides what to render from it.
    """
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

    body = _get(ctx, did, record.version_id).json()

    assert body["permissions"]["owners"][0]["email"] == "new-owner@example.com"
    assert body["is_public"] is True


def test_preview_carries_banner_metadata(ctx) -> None:
    """One request, not two — the banner should not need a second round trip."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["client"].post(f"{API}/versions/{record.version_id}/pin", json={"label": "Known good"})

    preview = _get(ctx, did, record.version_id).json()["preview"]

    assert preview["version_id"] == record.version_id
    assert preview["label"] == "Known good"
    assert preview["pinned"] is True
    assert preview["seq"] == record.seq


def test_live_get_has_no_preview_block(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="explicit")

    assert "preview" not in _get(ctx, did).json()


def test_preview_rejects_a_version_from_another_dashboard(ctx) -> None:
    """Otherwise viewer rights on A would read B's snapshot via a guessed id."""
    mine = _make_dashboard(ctx, title="Mine", components=[{"index": "a"}])
    theirs = _make_dashboard(ctx, title="Theirs", components=[{"index": "secret"}])
    other_version = _capture(ctx, theirs, kind="explicit")

    response = _get(ctx, mine, other_version.version_id)

    assert response.status_code == 404


def test_preview_of_unknown_version_is_404(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])

    assert _get(ctx, did, "deadbeef").status_code == 404


def test_preview_requires_viewer(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "none"

    assert _get(ctx, did, record.version_id).status_code == 403


def test_preview_of_a_tab_that_did_not_exist_yet(ctx) -> None:
    """A deep link to a tab added after the version must not render blank."""
    main = _make_dashboard(ctx, title="Main")
    record = _capture(ctx, main, kind="explicit")
    later = _make_dashboard(ctx, title="Added later", parent=main, tab_order=1)

    assert _get(ctx, later, record.version_id).status_code == 404


# ── Compatibility report ────────────────────────────────────────────────────


def _register_dc(ctx, dc_id, columns, *, exists=True):
    """Give a data collection a current schema (and optionally a project)."""
    ctx["deltatables"].insert_one(
        {
            "data_collection_id": dc_id,
            "aggregation": [
                {
                    "aggregation_version": 1,
                    "aggregation_columns_specs": [{"name": n, "type": t} for n, t in columns],
                    "rows_total": 10,
                    "delta_version": 3,
                }
            ],
        }
    )
    if exists:
        ctx["projects"].insert_one({"workflows": [{"data_collections": [{"_id": dc_id}]}]})


def _compat(ctx, version_id):
    return ctx["client"].get(f"{API}/versions/{version_id}/compatibility")


def test_compatibility_is_clean_when_nothing_changed(ctx) -> None:
    dc_id = ObjectId()
    _register_dc(ctx, dc_id, [("body_mass_g", "float64")])
    did = _make_dashboard(
        ctx, components=[{"index": "card-1", "dc_id": dc_id, "column_name": "body_mass_g"}]
    )
    record = _capture(ctx, did, kind="explicit")

    body = _compat(ctx, record.version_id).json()

    assert body["severity"] == "ok", body


def test_compatibility_names_the_missing_column_and_components(ctx) -> None:
    """The whole point: a hash pair cannot tell you which boxes break."""
    dc_id = ObjectId()
    _register_dc(ctx, dc_id, [("body_mass_g", "float64")])
    did = _make_dashboard(
        ctx,
        components=[
            {"index": "card-1", "dc_id": dc_id, "column_name": "body_mass_g"},
            {"index": "card-2", "dc_id": dc_id, "column_name": "body_mass_g"},
            {"index": "text-1", "dc_id": None},
        ],
    )
    record = _capture(ctx, did, kind="explicit")

    # The column goes away underneath the version.
    ctx["deltatables"].update_one(
        {"data_collection_id": dc_id},
        {
            "$set": {
                "aggregation.0.aggregation_columns_specs": [{"name": "species", "type": "object"}]
            }
        },
    )

    body = _compat(ctx, record.version_id).json()
    check = next(c for c in body["checks"] if c["dc_id"] == str(dc_id))

    assert body["severity"] == "error"
    assert "body_mass_g" in check["columns_removed"]
    assert sorted(check["affected_components"]) == ["card-1", "card-2"]


def test_compatibility_flags_a_retyped_column_as_warning(ctx) -> None:
    dc_id = ObjectId()
    _register_dc(ctx, dc_id, [("n", "int64")])
    did = _make_dashboard(ctx, components=[{"index": "c", "dc_id": dc_id, "column_name": "n"}])
    record = _capture(ctx, did, kind="explicit")

    ctx["deltatables"].update_one(
        {"data_collection_id": dc_id},
        {"$set": {"aggregation.0.aggregation_columns_specs": [{"name": "n", "type": "object"}]}},
    )

    body = _compat(ctx, record.version_id).json()
    check = next(c for c in body["checks"] if c["dc_id"] == str(dc_id))

    assert body["severity"] == "warning"
    assert check["columns_retyped"] == [{"name": "n", "from": "int64", "to": "object"}]


def test_compatibility_reports_a_deleted_data_collection(ctx) -> None:
    dc_id = ObjectId()
    _register_dc(ctx, dc_id, [("a", "int64")], exists=False)
    did = _make_dashboard(ctx, components=[{"index": "c", "dc_id": dc_id, "column_name": "a"}])
    record = _capture(ctx, did, kind="explicit")

    body = _compat(ctx, record.version_id).json()
    check = next(c for c in body["checks"] if c["dc_id"] == str(dc_id))

    assert body["severity"] == "error"
    assert check["found"] is False
    assert check["affected_components"] == ["c"]


def test_compatibility_ignores_a_removed_column_nothing_uses(ctx) -> None:
    """Drift that breaks nothing must not read as an error."""
    dc_id = ObjectId()
    _register_dc(ctx, dc_id, [("used", "int64"), ("spare", "int64")])
    did = _make_dashboard(ctx, components=[{"index": "c", "dc_id": dc_id, "column_name": "used"}])
    record = _capture(ctx, did, kind="explicit")

    ctx["deltatables"].update_one(
        {"data_collection_id": dc_id},
        {"$set": {"aggregation.0.aggregation_columns_specs": [{"name": "used", "type": "int64"}]}},
    )

    body = _compat(ctx, record.version_id).json()

    assert body["severity"] == "info", body
    assert body["renderable"] is True


def test_compatibility_requires_viewer(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")
    ctx["granted"]["level"] = "none"

    assert _compat(ctx, record.version_id).status_code == 403


def test_compatibility_covers_map_columns(ctx) -> None:
    """A map alone references seven columns; a card-only check would miss it."""
    dc_id = ObjectId()
    _register_dc(ctx, dc_id, [("lat", "float64"), ("lon", "float64")])
    did = _make_dashboard(
        ctx,
        components=[{"index": "map-1", "dc_id": dc_id, "lat_column": "lat", "lon_column": "lon"}],
    )
    record = _capture(ctx, did, kind="explicit")

    ctx["deltatables"].update_one(
        {"data_collection_id": dc_id},
        {"$set": {"aggregation.0.aggregation_columns_specs": [{"name": "lat", "type": "float64"}]}},
    )

    check = next(
        c for c in _compat(ctx, record.version_id).json()["checks"] if c["dc_id"] == str(dc_id)
    )

    assert check["affected_components"] == ["map-1"]
