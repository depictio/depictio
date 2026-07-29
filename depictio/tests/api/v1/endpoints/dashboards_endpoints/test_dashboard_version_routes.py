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

from datetime import datetime, timedelta

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


# ── regressions ─────────────────────────────────────────────────────────────
#
# Each of these reproduces something the timeline actually showed a user, and
# each failure mode was silent: the endpoint returned 200 every time.


def test_timeline_rows_report_what_a_version_holds(ctx) -> None:
    """Every row read "0 components", because the counts were never stored.

    ``component_count`` was a Python ``@property``, so it did not survive
    ``model_dump`` into Mongo — and the list endpoint projects ``tabs`` away,
    leaving nothing to count from on read. The timeline claimed every version
    was empty, which makes the whole surface untrustworthy: a user cannot pick
    a version to restore if none of them appear to contain anything.
    """
    main = _make_dashboard(ctx, components=[{"index": "a"}, {"index": "b"}])
    _make_dashboard(ctx, title="Tab 2", parent=main, tab_order=1, components=[{"index": "c"}])
    _capture(ctx, main, kind="explicit")

    row = ctx["client"].get(f"{API}/{main}/versions").json()["versions"][0]

    assert row["component_count"] == 3, "components across the whole family, not just the main tab"
    assert row["tab_count"] == 2


def test_coalescing_keeps_the_counts_in_step(ctx) -> None:
    """A folded save rewrites ``tabs``; the counts must follow it."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did)

    ctx["dashboards"].update_one(
        {"_id": did}, {"$set": {"stored_metadata": [{"index": "a"}, {"index": "b"}]}}
    )
    _capture(ctx, did, now=BASE + timedelta(seconds=30))

    row = ctx["client"].get(f"{API}/{did}/versions").json()["versions"][0]
    assert row["save_count"] == 2, "precondition: the second save folded into the first"
    assert row["component_count"] == 2


def test_restore_adds_exactly_one_version(ctx) -> None:
    """A restore appeared as two entries, not one.

    The pre-restore capture used ``kind="explicit"``, and an explicit capture
    bypassed the unchanged-content check — so restoring wrote a redundant
    snapshot of a state already at the top of the timeline, plus the restore
    point itself.
    """
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    target = _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": [{"index": "b"}]}})
    _capture(ctx, did, kind="auto", now=BASE + timedelta(hours=1))

    before = ctx["versions"].count_documents({})
    ctx["client"].post(f"{API}/versions/{target.version_id}/restore")
    after = ctx["versions"].count_documents({})

    assert after - before == 1


def test_restoring_the_live_state_is_a_no_op(ctx) -> None:
    """Restoring what is already on screen must not grow the timeline."""
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    before = ctx["versions"].count_documents({})
    response = ctx["client"].post(f"{API}/versions/{record.version_id}/restore")

    assert response.status_code == 200, response.text
    assert ctx["versions"].count_documents({}) == before


def test_restore_gives_components_back_their_object_ids(ctx) -> None:
    """A restored dashboard rendered no data, because its ids came back as text.

    Snapshots stringify ObjectIds so the payload is plain JSON and hashes
    deterministically. Writing that straight back left components carrying a
    string ``dc_id``, which no ``{"data_collection_id": ObjectId(...)}`` lookup
    on the read path matches — the dashboard returned intact but empty, which
    a user reads as "restore did nothing".
    """
    dc_id = ObjectId()
    did = _make_dashboard(ctx, components=[{"index": "a", "dc_id": dc_id}])
    record = _capture(ctx, did, kind="explicit")

    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": []}})
    ctx["client"].post(f"{API}/versions/{record.version_id}/restore")

    live = ctx["dashboards"].find_one({"_id": did})
    assert live["stored_metadata"][0]["dc_id"] == dc_id
    assert isinstance(live["stored_metadata"][0]["dc_id"], ObjectId)


def test_naming_an_unchanged_state_labels_it_instead_of_failing(ctx) -> None:
    """Naming the current state used to 409 whenever nothing had changed.

    Which is almost always: every save already records a version, so by the
    time the user opens the drawer the live state *is* the newest version.
    The button was therefore broken in its most common case.
    """
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    existing = _capture(ctx, did, kind="auto")

    response = ctx["client"].post(f"{API}/{did}/versions", json={"label": "Known good"})

    assert response.status_code == 200, response.text
    assert response.json()["version_id"] == existing.version_id
    assert ctx["versions"].count_documents({}) == 1, "naming must not duplicate the version"

    stored = ctx["versions"].find_one({"version_id": existing.version_id})
    assert stored["label"] == "Known good"
    assert stored["kind"] == "explicit"
    assert stored["coalesce_until"] == stored["created_at"], (
        "a named version must be sealed, or the next autosave rewrites what was named"
    )


def test_naming_a_changed_state_creates_a_version(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="auto")
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": [{"index": "b"}]}})

    response = ctx["client"].post(f"{API}/{did}/versions", json={"label": "After the change"})

    assert response.status_code == 200, response.text
    assert ctx["versions"].count_documents({}) == 2
    assert response.json()["label"] == "After the change"


def test_naming_requires_editor(ctx) -> None:
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="auto")
    ctx["granted"]["level"] = "viewer"

    response = ctx["client"].post(f"{API}/{did}/versions", json={"label": "nope"})

    assert response.status_code == 403


def test_version_detail_carries_what_the_preview_renders(ctx) -> None:
    """The viewer renders `?version=` from this payload, so it must be complete.

    ``GET /versions/{id}`` is the only endpoint that returns ``tabs`` — the
    list endpoint projects them away. The preview picks its tab out of this
    response and renders it through the live component tree, so a missing
    layout array is a blank dashboard rather than an error.
    """
    main = _make_dashboard(ctx, components=[{"index": "a"}])
    child = _make_dashboard(ctx, title="Tab 2", parent=main, tab_order=1)
    ctx["dashboards"].update_one(
        {"_id": main}, {"$set": {"right_panel_layout_data": [{"i": "a", "x": 0, "y": 0}]}}
    )
    record = _capture(ctx, main, kind="explicit")

    body = ctx["client"].get(f"{API}/versions/{record.version_id}").json()

    by_id = {t["dashboard_id"]: t for t in body["tabs"]}
    assert str(main) in by_id and str(child) in by_id, "the preview addresses tabs by id"

    tab = by_id[str(main)]
    assert tab["stored_metadata"] == [{"index": "a"}]
    assert tab["right_panel_layout_data"] == [{"i": "a", "x": 0, "y": 0}]
    assert "left_panel_layout_data" in tab
    assert tab["is_main_tab"] is True


def test_version_detail_never_leaks_access_control(ctx) -> None:
    """A snapshot the viewer renders must not carry permissions at all.

    Structural, not filtered: ``TabSnapshot`` has no such fields, so there is
    nothing for a preview — or a restore — to write back.
    """
    did = _make_dashboard(ctx, components=[{"index": "a"}])
    record = _capture(ctx, did, kind="explicit")

    tab = ctx["client"].get(f"{API}/versions/{record.version_id}").json()["tabs"][0]

    for field in ("permissions", "is_public", "project_id"):
        assert field not in tab, f"{field} must never travel inside a snapshot"


def test_legacy_records_still_report_their_counts(ctx) -> None:
    """Rows kept reading "0 components" even after the counts became stored.

    Storing them only fixes records written *since*. Every version already in
    a deployed ledger has neither field, and the list endpoint projects `tabs`
    away — so there was nothing left to derive them from and the timeline went
    on claiming every version was empty. `list_versions` backfills the family
    it is asked about, so an existing ledger heals on first view rather than
    needing a migration to have been run.
    """
    main = _make_dashboard(ctx, components=[{"index": "a"}, {"index": "b"}])
    _make_dashboard(ctx, title="Tab 2", parent=main, tab_order=1, components=[{"index": "c"}])
    record = _capture(ctx, main, kind="explicit")

    # Exactly what a record written by the previous code looks like.
    ctx["versions"].update_one(
        {"version_id": record.version_id},
        {"$unset": {"tab_count": "", "component_count": ""}},
    )

    row = ctx["client"].get(f"{API}/{main}/versions").json()["versions"][0]

    assert row["component_count"] == 3
    assert row["tab_count"] == 2

    stored = ctx["versions"].find_one({"version_id": record.version_id})
    assert stored["component_count"] == 3, "the repair must persist, not recompute every listing"


def test_backfill_leaves_current_records_alone(ctx) -> None:
    """The repair must not touch records that already carry counts."""
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store

    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="explicit")

    assert version_store.backfill_counts(str(did)) == 0


def test_snapshot_carries_the_exact_layout_a_preview_needs(ctx) -> None:
    """Preview did not reproduce the layout the user had.

    Two halves to that. The viewer merges the snapshot onto the *live*
    document rather than rendering it alone — a `TabSnapshot` deliberately has
    no `project_id`, so rendering it directly leaves nothing to resolve data
    collections against. This pins the other half: the snapshot must carry the
    layout arrays verbatim, geometry included, or there is nothing correct to
    merge.
    """
    layout = [
        {"i": "a", "x": 0, "y": 0, "w": 4, "h": 6},
        {"i": "b", "x": 4, "y": 0, "w": 4, "h": 3},
    ]
    did = _make_dashboard(ctx, components=[{"index": "a"}, {"index": "b"}])
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"right_panel_layout_data": layout}})
    record = _capture(ctx, did, kind="explicit")

    # The user rearranges everything afterwards.
    ctx["dashboards"].update_one(
        {"_id": did},
        {
            "$set": {
                "title": "Renamed later",
                "right_panel_layout_data": [{"i": "a", "x": 0, "y": 0, "w": 8, "h": 2}],
            }
        },
    )

    tab = ctx["client"].get(f"{API}/versions/{record.version_id}").json()["tabs"][0]

    assert tab["right_panel_layout_data"] == layout, "geometry must survive verbatim"
    assert tab["title"] != "Renamed later", "the snapshot must not track later edits"


def test_deleting_a_dashboard_deletes_its_history(ctx, monkeypatch) -> None:
    """A deleted dashboard's ledger was orphaned in Mongo forever.

    `delete_family` existed but nothing called it. Snapshots are the largest
    documents this deployment writes, and retention is scoped per family — so
    an orphaned ledger is never pruned and never reachable again, it only
    accumulates. The sequence counter goes too, or recreating a dashboard with
    the same id would resume numbering at the old maximum.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store
    from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

    monkeypatch.setattr(dash_routes, "dashboards_collection", ctx["dashboards"])
    ctx["client"].app.dependency_overrides[get_current_user] = lambda: CALLER

    did = _make_dashboard(ctx, components=[{"index": "a"}])
    _capture(ctx, did, kind="explicit")
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"stored_metadata": [{"index": "b"}]}})
    _capture(ctx, did, kind="explicit", now=BASE + timedelta(hours=1))
    assert ctx["versions"].count_documents({"family_id": str(did)}) == 2

    response = ctx["client"].delete(f"{API}/delete/{did}")

    assert response.status_code == 200, response.text
    assert ctx["versions"].count_documents({"family_id": str(did)}) == 0
    assert (
        version_store.dashboard_version_counters_collection.count_documents({"family_id": str(did)})
        == 0
    ), "the seq counter must go too, or a recreated dashboard resumes at the old max"


def test_deleting_a_child_tab_keeps_the_family_history(ctx, monkeypatch) -> None:
    """A child tab's versions belong to its parent's timeline.

    A version covers the whole family, so dropping the ledger when one tab is
    removed would discard the history of every other tab with it — including
    the record of the tab that was just deleted, which is exactly what someone
    would want to restore.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user

    monkeypatch.setattr(dash_routes, "dashboards_collection", ctx["dashboards"])
    ctx["client"].app.dependency_overrides[get_current_user] = lambda: CALLER

    main = _make_dashboard(ctx, components=[{"index": "a"}])
    child = _make_dashboard(ctx, title="Tab 2", parent=main, tab_order=1)
    _capture(ctx, main, kind="explicit")
    assert ctx["versions"].count_documents({"family_id": str(main)}) == 1

    ctx["client"].delete(f"{API}/delete/{child}")

    assert ctx["versions"].count_documents({"family_id": str(main)}) == 1
