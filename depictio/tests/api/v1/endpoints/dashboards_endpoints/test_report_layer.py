"""The report layer (#1457): its routes, and what the export does with it.

Three surfaces of one feature:

**Routes.** ``GET/PUT /dashboards/report_layer/{id}`` are editor-only: a
viewer or an anonymous visitor is answered 404, the editor flag off makes the
feature not exist (404), a stale ``base_revision`` is a 409 with the stored
layer, and a published dashboard refuses the write like every other content
change. The write is versioned like a ``/save`` (baseline + capture), so a
restore brings a past layer back.

**The export's state.** With no state in the request, the export is drawn at
the layer's state — the filters the report was written for.

**The document.** The generator turns the layer into the report's shape: the
intro opens it, the conclusion closes the narrative, the appendix tabs follow,
and per-tile placement (exclusion, caption, page break, PDF visibility) is
the layer's, not the grid's. Every character the layer's prose carries goes
out inert, like every other author text.
"""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

BASE = datetime(2026, 3, 1, 12, 0, 0)


@pytest.fixture(autouse=True)
def _versions_do_not_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixtures are captured at a fixed BASE, while the routes capture at the
    real clock; past `retention_days` the prune would remove them all."""
    from depictio.api.v1.configs.config import settings

    monkeypatch.setattr(settings.dashboard_versions, "retention_days", 100 * 365)


class _User:
    def __init__(self, uid: str, email: str, is_admin: bool = False) -> None:
        self.id = uid
        self.email = email
        self.is_admin = is_admin
        self.is_anonymous = False


class _Anonymous:
    id = str(ObjectId())
    email = "anon@depictio.org"
    is_anonymous = True
    is_admin = False


CALLER = _User(str(ObjectId()), "caller@example.com")


def _tip(paragraph: str) -> dict:
    """One TipTap paragraph, as the editor stores it."""
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": paragraph}]}],
    }


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch):
    """A live app wired to in-memory Mongo, with permissions under test control."""
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.dashboards_endpoints import (
        core_functions,
        report_layer_routes,
        schema_integrity,
        version_store,
        versioning,
        versions_routes,
    )
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.projects_endpoints import publish_lock
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
    monkeypatch.setattr(dash_routes, "dashboards_collection", dashboards)
    monkeypatch.setattr(dash_routes, "projects_collection", db["projects"])
    monkeypatch.setattr(core_functions, "dashboards_collection", dashboards)
    monkeypatch.setattr(schema_integrity, "deltatables_collection", db["deltatables"])
    monkeypatch.setattr(schema_integrity, "projects_collection", db["projects"])
    # The report layer reads and writes through its own module-level handles.
    monkeypatch.setattr(report_layer_routes, "dashboards_collection", dashboards)
    # The publish lock reads the project through the real db module; hand it
    # the in-memory one (nothing is published unless a test says so).
    monkeypatch.setattr(
        publish_lock,
        "_db",
        lambda: SimpleNamespace(projects_collection=db["projects"]),
        raising=False,
    )
    # The feature exists in these tests; the flag-off test overrides this.
    monkeypatch.setattr(settings.notebook_export, "enabled", True)
    monkeypatch.setattr(settings.notebook_export, "report_editor", True)

    granted = {"level": "owner"}

    def fake_mutation(doc, user, level="editor"):
        order = {"none": -1, "viewer": 0, "editor": 1, "owner": 2}
        return order[level] <= order[granted["level"]]

    monkeypatch.setattr(report_layer_routes, "check_dashboard_mutation_permission", fake_mutation)
    # The restore route re-imports the check from the save routes at call
    # time, so the fake must land there too.
    monkeypatch.setattr(dash_routes, "check_dashboard_mutation_permission", fake_mutation)
    monkeypatch.setattr(
        versions_routes, "sync_tab_family_permissions", lambda *a, **k: 0, raising=False
    )
    # A restore queues a thumbnail like a save does; recorded, never dispatched.
    monkeypatch.setattr(dash_routes, "_queue_screenshot", lambda *a, **k: None, raising=False)

    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    app.dependency_overrides[get_user_or_anonymous] = lambda: CALLER

    return {
        "client": TestClient(app),
        "dashboards": dashboards,
        "versions": db["dashboard_versions"],
        "projects": db["projects"],
        "granted": granted,
        "versioning": versioning,
        "settings": settings,
    }


API = "/depictio/api/v1/dashboards/report_layer"


def _make_dashboard(ctx, *, notes=None, project_id=None, did=None):
    did = did or ObjectId()
    doc = {
        "_id": did,
        "dashboard_id": did,
        "project_id": project_id or ObjectId(),
        "title": "Main",
        "is_main_tab": True,
        "tab_order": 0,
        "stored_metadata": [{"index": "f1", "component_type": "figure", "dc_id": "dc1"}],
        "left_panel_layout_data": [],
        "right_panel_layout_data": [],
        "permissions": {"owners": [{"email": "owner@example.com"}]},
        "is_public": False,
    }
    if notes is not None:
        doc["notes_content"] = notes
    ctx["dashboards"].insert_one(doc)
    return did


def _put_layer(client, did, layer, *, base_revision=0):
    return client.put(f"{API}/{did}", json={"base_revision": base_revision, "layer": layer})


# ── the flag and the permission gates ───────────────────────────────────────


def test_both_routes_are_404_when_the_editor_flag_is_off(ctx, monkeypatch) -> None:
    did = _make_dashboard(ctx)
    monkeypatch.setattr(ctx["settings"].notebook_export, "report_editor", False)

    assert ctx["client"].get(f"{API}/{did}").status_code == 404
    assert _put_layer(ctx["client"], did, {"intro": None}).status_code == 404


def test_a_viewer_is_404_and_an_editor_gets_the_layer(ctx) -> None:
    did = _make_dashboard(ctx)

    ctx["granted"]["level"] = "viewer"
    assert ctx["client"].get(f"{API}/{did}").status_code == 404
    assert _put_layer(ctx["client"], did, {"intro": None}).status_code == 404

    ctx["granted"]["level"] = "editor"
    assert ctx["client"].get(f"{API}/{did}").status_code == 200


def test_an_anonymous_visitor_is_404(ctx, monkeypatch) -> None:
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

    did = _make_dashboard(ctx)
    ctx["client"].app.dependency_overrides[get_user_or_anonymous] = lambda: _Anonymous
    monkeypatch.setattr(type(ctx["settings"].auth), "is_single_user_mode", False)

    assert ctx["client"].get(f"{API}/{did}").status_code == 404


def test_an_unknown_dashboard_is_404(ctx) -> None:
    assert ctx["client"].get(f"{API}/{ObjectId()}").status_code == 404


# ── reading ─────────────────────────────────────────────────────────────────


def test_get_returns_an_empty_layer_when_nothing_is_stored(ctx) -> None:
    did = _make_dashboard(ctx)

    body = ctx["client"].get(f"{API}/{did}").json()

    assert body["revision"] == 0
    assert body["intro"] is None
    assert body["tiles"] == [] and body["tabs"] == []
    assert body["seeded_from_notes"] is False


def test_get_seeds_the_intro_from_the_guide_notes_without_writing(ctx) -> None:
    did = _make_dashboard(ctx, notes="First line.\n\nSecond line.")

    body = ctx["client"].get(f"{API}/{did}").json()

    assert body["seeded_from_notes"] is True
    paragraphs = body["intro"]["content"]
    assert [p["content"][0]["text"] for p in paragraphs] == ["First line.", "Second line."]
    # A seed is a draft: nothing is written anywhere.
    stored = ctx["dashboards"].find_one({"_id": did})
    assert not stored.get("report_layer")


def test_get_returns_the_stored_layer(ctx) -> None:
    did = _make_dashboard(ctx)
    _put_layer(ctx["client"], did, {"intro": _tip("Hello"), "cover": {"title": "The report"}})

    body = ctx["client"].get(f"{API}/{did}").json()

    assert body["cover"]["title"] == "The report"
    assert body["intro"]["content"][0]["content"][0]["text"] == "Hello"
    assert body["revision"] == 1
    assert body["seeded_from_notes"] is False


# ── writing: revisions, conflict, publish lock ──────────────────────────────


def test_put_stamps_revision_author_and_time(ctx) -> None:
    did = _make_dashboard(ctx)

    body = _put_layer(ctx["client"], did, {"intro": _tip("One")}).json()
    assert body["revision"] == 1
    assert body["updated_by"] == CALLER.id
    assert body["updated_at"]

    body = _put_layer(ctx["client"], did, {"intro": _tip("Two")}, base_revision=1).json()
    assert body["revision"] == 2


def test_a_stale_revision_is_refused_with_the_stored_layer(ctx) -> None:
    did = _make_dashboard(ctx)
    _put_layer(ctx["client"], did, {"intro": _tip("Theirs"), "cover": {"title": "Kept"}})

    response = _put_layer(ctx["client"], did, {"intro": _tip("Mine")}, base_revision=0)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["revision"] == 1
    assert detail["updated_by"] == CALLER.id
    assert detail["layer"]["cover"]["title"] == "Kept"
    # And the stored layer is untouched.
    body = ctx["client"].get(f"{API}/{did}").json()
    assert body["intro"]["content"][0]["content"][0]["text"] == "Theirs"


def test_the_first_write_does_not_conflict_with_revision_zero(ctx) -> None:
    """A dashboard with nothing stored is at revision 0: the editor's first
    PUT carries `base_revision=0` and must go through."""
    did = _make_dashboard(ctx)

    assert _put_layer(ctx["client"], did, {"intro": _tip("First")}).status_code == 200


def test_a_published_dashboard_refuses_the_write_with_409(ctx) -> None:
    project_id = ObjectId()
    ctx["projects"].insert_one({"_id": project_id})
    did = _make_dashboard(ctx, project_id=project_id)
    ctx["projects"].update_one(
        {"_id": project_id}, {"$set": {"published_lock": {"dashboard_ids": [str(did)]}}}
    )

    response = _put_layer(ctx["client"], did, {"intro": _tip("No")})

    assert response.status_code == 409
    assert ctx["client"].get(f"{API}/{did}").json()["revision"] == 0


# ── versioning: capture, restore, /save pops ────────────────────────────────


def test_a_layer_write_captures_a_version_and_a_restore_brings_it_back(ctx) -> None:
    did = _make_dashboard(ctx)
    baseline = ctx["versioning"].capture_dashboard_version(
        did, kind="explicit", author=CALLER, now=BASE
    )
    _put_layer(ctx["client"], did, {"intro": _tip("Version one")})
    assert ctx["versions"].count_documents({}) >= 2, (
        "the write seeded its own baseline and captured itself"
    )

    _put_layer(ctx["client"], did, {"intro": _tip("Version two")}, base_revision=1)

    response = ctx["client"].post(
        f"/depictio/api/v1/dashboards/versions/{baseline.version_id}/restore"
    )
    assert response.status_code == 200, response.text
    restored = ctx["dashboards"].find_one({"_id": did})
    assert not restored.get("report_layer"), (
        "the baseline predates the layer: the restore must not invent one"
    )


def test_a_restore_of_a_layered_version_brings_the_layer_back(ctx) -> None:
    did = _make_dashboard(ctx)
    _put_layer(ctx["client"], did, {"intro": _tip("Kept text")})
    # A version captured at the old BASE clock: its coalescing window is
    # closed, so the next write's autosave cannot fold into it.
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"title": "Renamed"}})
    record = ctx["versioning"].capture_dashboard_version(
        did, kind="explicit", author=CALLER, now=BASE
    )
    assert record is not None
    _put_layer(ctx["client"], did, {"intro": _tip("Overwritten")}, base_revision=1)

    response = ctx["client"].post(
        f"/depictio/api/v1/dashboards/versions/{record.version_id}/restore"
    )

    assert response.status_code == 200, response.text
    stored = ctx["dashboards"].find_one({"_id": did})
    assert stored["title"] == "Renamed"
    layer = stored["report_layer"]
    assert layer["intro"]["content"][0]["content"][0]["text"] == "Kept text"


def test_save_pops_the_layer_instead_of_overwriting_it(ctx) -> None:
    """/save never carries the layer: a save of a document the editor loaded
    must not undo a colleague's report text (or reset its revision)."""
    import asyncio
    from unittest.mock import patch

    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import versioning
    from depictio.models.models.dashboards import DashboardData
    from depictio.models.models.users import Permission, UserBase

    did = _make_dashboard(ctx)
    _put_layer(ctx["client"], did, {"intro": _tip("The author's text")})

    user = UserBase(id=ObjectId(CALLER.id), email=CALLER.email)
    user.is_anonymous = False
    project_id = ctx["dashboards"].find_one({"_id": did})["project_id"]
    data = DashboardData(
        dashboard_id=did,
        title="Renamed",
        project_id=project_id,
        report_layer={"intro": None},
        permissions=Permission(owners=[user]),
    )
    with (
        patch.object(dash_routes, "dashboards_collection", ctx["dashboards"]),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        patch.object(dash_routes, "check_project_permission", return_value=True),
        patch.object(dash_routes, "get_project_visibility", return_value=False),
        patch.object(versioning, "ensure_baseline_quietly", return_value=None),
        patch.object(versioning, "capture_quietly", return_value=None),
    ):
        asyncio.run(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=user))

    stored = ctx["dashboards"].find_one({"_id": did})
    assert stored["title"] == "Renamed", "the save itself went through"
    assert stored["report_layer"]["intro"]["content"][0]["content"][0]["text"] == (
        "The author's text"
    )


def test_a_restore_writes_the_layer_as_stored_and_the_dashboard_loads(ctx) -> None:
    """The layer's ObjectId-looking strings are values, not ids: a restore
    writes them back as the strings they are, and the document loads."""
    from depictio.models.models.dashboards import DashboardData

    did = _make_dashboard(ctx)
    # The fields a real dashboard always carries, so the restored document
    # differs from a healthy one only where the bugs bite.
    ctx["dashboards"].update_one(
        {"_id": did},
        {"$set": {"icon": "mdi:view-dashboard", "icon_color": "orange", "icon_variant": "filled"}},
    )
    _put_layer(
        ctx["client"],
        did,
        {
            "intro": _tip(f"Run {ObjectId()} finished early"),
            "cover": {"title": "The report"},
            "tiles": [{"tab_id": str(did), "component_id": "f1", "caption": "The tile"}],
            "tabs": [{"tab_id": str(did), "placement": "appendix"}],
            "state": {
                "filters": [
                    {
                        "index": "f-species",
                        "column_name": "species",
                        "interactive_component_type": "MultiSelect",
                        "value": ["Adelie"],
                        "metadata": {"dc_id": "dc1"},
                    }
                ],
                "context": {"dashboard_id": str(did)},
            },
        },
    )
    saved = ctx["dashboards"].find_one({"_id": did})["report_layer"]
    # The stored layer's author and tab ids are 24-hex strings.
    assert saved["updated_by"] == CALLER.id
    assert saved["tiles"][0]["tab_id"] == str(did)

    ctx["dashboards"].update_one({"_id": did}, {"$set": {"title": "Named"}})
    record = ctx["versioning"].capture_dashboard_version(
        did, kind="explicit", author=CALLER, now=BASE
    )
    assert record is not None
    _put_layer(ctx["client"], did, {"intro": _tip("Overwritten")}, base_revision=1)

    response = ctx["client"].post(
        f"/depictio/api/v1/dashboards/versions/{record.version_id}/restore"
    )
    assert response.status_code == 200, response.text

    restored_doc = ctx["dashboards"].find_one({"_id": did})
    # The GET path loads the restored document, ObjectIds and all.
    assert DashboardData.from_mongo(restored_doc) is not None
    restored = restored_doc["report_layer"]
    assert restored["updated_by"] == CALLER.id
    assert restored["tiles"][0]["tab_id"] == str(did)
    assert restored["state"]["context"]["dashboard_id"] == str(did)
    # The layer is what was saved, at a revision past every one read before
    # the restore (2 live, 1 in the version): max(2, 1) + 1.
    assert restored == dict(saved, revision=3)


def test_from_mongo_loads_a_layer_whose_values_are_objectids(ctx) -> None:
    """A restore before the layer was kept as stored wrote ObjectIds into the
    stored layer; those dashboards must load again, values back to strings."""
    from depictio.models.models.dashboards import DashboardData

    did = _make_dashboard(ctx)
    broken_text = ObjectId()
    ctx["dashboards"].update_one(
        {"_id": did},
        {
            "$set": {
                "report_layer": {
                    "revision": 1,
                    "updated_by": ObjectId(CALLER.id),
                    "intro": {
                        "type": "doc",
                        "content": [{"type": "text", "text": broken_text}],
                    },
                    "tiles": [{"tab_id": ObjectId(str(did)), "component_id": "f1"}],
                }
            }
        },
    )

    dashboard = DashboardData.from_mongo(ctx["dashboards"].find_one({"_id": did}))

    assert dashboard.report_layer is not None
    assert dashboard.report_layer.updated_by == CALLER.id
    assert dashboard.report_layer.tiles[0].tab_id == str(did)
    assert dashboard.report_layer.intro["content"][0]["text"] == str(broken_text)


def test_a_write_landing_between_the_read_and_the_write_gets_409(ctx, monkeypatch) -> None:
    """Two writers holding the same revision: the one whose write lands
    mid-flight must not overwrite the other's text."""
    from depictio.api.v1.endpoints.dashboards_endpoints import report_layer_routes

    did = _make_dashboard(ctx)
    fired: list[ObjectId] = []

    def ensure_then_write(family_id, current_user):
        """Seed the baseline, and with it land the other editor's write: the
        only call between this request's read and its write."""
        if fired:
            return None
        fired.append(family_id)
        ctx["dashboards"].update_one(
            {"dashboard_id": ObjectId(str(family_id))},
            {
                "$set": {
                    "report_layer": {
                        "revision": 1,
                        "updated_by": CALLER.id,
                        "intro": _tip("The other editor's text"),
                    }
                }
            },
        )
        return None

    monkeypatch.setattr(report_layer_routes, "_ensure_baseline_quietly", ensure_then_write)

    response = _put_layer(ctx["client"], did, {"intro": _tip("This editor's text")})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["revision"] == 1
    assert detail["updated_by"] == CALLER.id
    assert detail["layer"]["intro"]["content"][0]["content"][0]["text"] == (
        "The other editor's text"
    )
    stored = ctx["dashboards"].find_one({"_id": did})["report_layer"]
    assert stored["intro"]["content"][0]["content"][0]["text"] == "The other editor's text"


def test_after_a_restore_a_put_with_the_pre_restore_base_revision_is_409(ctx) -> None:
    """A restore must not lower the stored revision: an editor still holding
    the pre-restore revision cannot overwrite the restored layer."""
    did = _make_dashboard(ctx)
    _put_layer(ctx["client"], did, {"intro": _tip("Version one")})
    ctx["dashboards"].update_one({"_id": did}, {"$set": {"title": "Named"}})
    record = ctx["versioning"].capture_dashboard_version(
        did, kind="explicit", author=CALLER, now=BASE
    )
    assert record is not None
    _put_layer(ctx["client"], did, {"intro": _tip("Version two")}, base_revision=1)

    response = ctx["client"].post(
        f"/depictio/api/v1/dashboards/versions/{record.version_id}/restore"
    )
    assert response.status_code == 200, response.text

    stale = _put_layer(ctx["client"], did, {"intro": _tip("Stale")}, base_revision=2)
    assert stale.status_code == 409
    assert stale.json()["detail"]["revision"] == 3
    stored = ctx["dashboards"].find_one({"_id": did})["report_layer"]
    assert stored["revision"] == 3
    assert stored["intro"]["content"][0]["content"][0]["text"] == "Version one"


def test_an_absent_layer_and_an_explicit_none_hash_the_same(ctx) -> None:
    """Adding the field must not make existing dashboards look edited."""
    versioning = ctx["versioning"]
    did = _make_dashboard(ctx)
    tabs = versioning.build_tab_snapshots(versioning.load_family_docs(did))
    hash_absent = versioning.compute_content_hash(tabs)

    ctx["dashboards"].update_one({"_id": did}, {"$set": {"report_layer": None}})
    tabs = versioning.build_tab_snapshots(versioning.load_family_docs(did))

    assert versioning.compute_content_hash(tabs) == hash_absent


def test_a_layer_write_changes_the_hash(ctx) -> None:
    """The layer is content: a family that gains one is a new version."""
    versioning = ctx["versioning"]
    did = _make_dashboard(ctx)
    tabs = versioning.build_tab_snapshots(versioning.load_family_docs(did))
    hash_before = versioning.compute_content_hash(tabs)

    ctx["dashboards"].update_one(
        {"_id": did}, {"$set": {"report_layer": {"intro": _tip("Prose"), "revision": 1}}}
    )
    tabs = versioning.build_tab_snapshots(versioning.load_family_docs(did))

    assert versioning.compute_content_hash(tabs) != hash_before


def test_the_layer_write_is_classified_as_guarded() -> None:
    """The publish-lock census must know the write reaches the lock guard."""
    from depictio.tests.api.v1.test_publish_lock_routes import EXEMPT, GUARDED

    assert ("dashboards_endpoints.report_layer_routes", "put_report_layer") in GUARDED
    assert ("dashboards_endpoints.report_layer_routes", "put_report_layer") not in EXEMPT


# ── the export's state ──────────────────────────────────────────────────────


def test_the_export_draws_the_layer_state_when_the_request_has_none(ctx) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export
    from depictio.models.models.analysis_state import AnalysisState, NotebookExportRequest

    did = _make_dashboard(ctx)
    ctx["dashboards"].update_one(
        {"_id": did},
        {
            "$set": {
                "report_layer": {
                    "state": {
                        "filters": [
                            {
                                "index": "f-species",
                                "column_name": "species",
                                "interactive_component_type": "MultiSelect",
                                "value": ["Adelie"],
                                "metadata": {"dc_id": "dc1"},
                            }
                        ],
                        "context": {"dashboard_id": str(did)},
                    },
                    "revision": 1,
                }
            }
        },
    )

    state = notebook_export._resolved_request_state(did, NotebookExportRequest(state=None))
    assert state is not None
    assert state.filters[0].value == ["Adelie"]

    # A request that carries a state keeps it, layer or not.
    own = AnalysisState.model_validate({"context": {"dashboard_id": str(did)}})
    resolved = notebook_export._resolved_request_state(did, NotebookExportRequest(state=own))
    assert resolved.filters == []


def test_an_export_without_a_layer_state_uses_the_dashboard_defaults(ctx) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export
    from depictio.models.models.analysis_state import NotebookExportRequest

    did = _make_dashboard(ctx)

    state = notebook_export._resolved_request_state(did, NotebookExportRequest(state=None))

    assert str(state.context.dashboard_id) == str(did)
    assert state.filters == []


# ── the document ────────────────────────────────────────────────────────────

DC_ID = "646b0f3c1e4a2d7f8e5b8ca1"


def _gen_tab():
    return {
        "dashboard_id": "tab1",
        "title": "Overview",
        "is_main_tab": True,
        "tab_order": 0,
        "stored_metadata": [
            {"index": "f1", "component_type": "figure", "title": "Bill", "dc_id": DC_ID},
            {"index": "f2", "component_type": "figure", "title": "Mass", "dc_id": DC_ID},
        ],
        "right_panel_layout_data": [
            {"i": "f1", "x": 0, "y": 0, "w": 12, "h": 4},
            {"i": "f2", "x": 0, "y": 4, "w": 12, "h": 4},
        ],
        "left_panel_layout_data": [],
    }


def _gen_plan(tabs, *, layer=None, pdf=False):
    from depictio.api.v1.services.notebook_export.generator import DCPlan, ExportPlan
    from depictio.models.models.analysis_state import AnalysisState

    return ExportPlan(
        tabs=tabs,
        project={
            "name": "Palmer Penguins",
            "permissions": {"owners": [{"username": "tweber", "email": "t@depictio.org"}]},
        },
        state=AnalysisState.model_validate({"context": {"dashboard_id": "tab1"}}),
        stages=[],
        title="Penguins",
        report_layer=layer,
        dcs=[DCPlan(dc_id=DC_ID, tag="penguins", dtypes={"x": pl.Float64})],
        pdf=pdf,
    )


_CHUNK_RE = re.compile(r"^(`{3,})\{python\}\n(.*?)\n\1$", re.S | re.M)

LIVE_MARKERS = (
    re.compile(r"\{\{+\s*[<%]"),  # a chunk or shortcode beginning
    re.compile(r"`[ \t]*\{(?!=)"),  # an inline-code opening
    re.compile(r"~{3,}[ \t]*\{"),  # a tilde fence with a language
)


def _markdown_only(src: str) -> str:
    """The document's markdown, its own python chunks removed — the part
    author prose must not poison."""
    return _CHUNK_RE.sub("", src)


def test_the_intro_opens_and_the_conclusion_closes_the_report() -> None:
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    plan = _gen_plan(
        [_gen_tab()],
        layer={"intro": _tip("This report opens."), "conclusion": _tip("This report closes.")},
    )
    src = NotebookBuilder(plan).build()

    intro_at = src.index("This report opens.")
    conclusion_at = src.index("This report closes.")
    assert intro_at < src.index("**Bill**."), "the intro comes before the results"
    assert conclusion_at > src.rindex("**Bill**."), "the conclusion comes after every tile"


def test_tiles_follow_the_layer_order_exclusion_and_caption() -> None:
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    layer = {
        "tiles": [
            {"tab_id": "tab1", "component_id": "f2", "in_report": False},
            {"tab_id": "tab1", "component_id": "f1", "caption": "The layer's own caption."},
        ],
    }
    src = NotebookBuilder(_gen_plan([_gen_tab()], layer=layer)).build()

    assert "**Mass**" not in src, "a tile the layer leaves out is not in the report"
    assert "The layer's own caption." in src


def test_a_poisoned_intro_comes_out_inert() -> None:
    """Chunk openers, shortcodes and fences typed into the layer's prose must
    not survive as markup."""
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    poison = "Hello {{< env HOME >}} and ```{python} and ~~~{r} end"
    plan = _gen_plan([_gen_tab()], layer={"intro": _tip(poison)})
    src = NotebookBuilder(plan).build()

    markdown = _markdown_only(src)
    for marker in LIVE_MARKERS:
        assert not marker.search(markdown), f"the intro's poison survived as {marker.pattern}"
    assert "Hello" in src and "end" in src, "the prose itself is kept"


def test_a_page_break_reaches_the_document() -> None:
    from depictio.api.v1.services.notebook_export.generator import PAGE_BREAK_MD, NotebookBuilder

    layer = {"tiles": [{"tab_id": "tab1", "component_id": "f1", "page_break_before": True}]}
    src = NotebookBuilder(_gen_plan([_gen_tab()], layer=layer)).build()

    assert "`#pagebreak()`{=typst}" in src, "the page break reaches the PDF"
    assert PAGE_BREAK_MD in src


def test_a_tile_kept_out_of_the_pdf_is_html_only() -> None:
    from depictio.api.v1.services.notebook_export.generator import HTML_ONLY_OPEN, NotebookBuilder

    plain = NotebookBuilder(_gen_plan([_gen_tab()], pdf=True)).build()
    layer = {"tiles": [{"tab_id": "tab1", "component_id": "f2", "in_pdf": False}]}
    layered = NotebookBuilder(_gen_plan([_gen_tab()], layer=layer, pdf=True)).build()

    assert layered.count(HTML_ONLY_OPEN) == plain.count(HTML_ONLY_OPEN) + 1, (
        "the tile is wrapped so only the HTML shows it"
    )


def test_appendix_tabs_follow_the_conclusion() -> None:
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    tab2 = {
        "dashboard_id": "tab2",
        "title": "Extra",
        "is_main_tab": False,
        "tab_order": 1,
        "stored_metadata": [
            {"index": "f3", "component_type": "figure", "title": "Deep", "dc_id": DC_ID}
        ],
        "right_panel_layout_data": [{"i": "f3", "x": 0, "y": 0, "w": 12, "h": 4}],
        "left_panel_layout_data": [],
    }
    plan = _gen_plan(
        [_gen_tab(), tab2],
        layer={
            "conclusion": _tip("The end."),
            "tabs": [{"tab_id": "tab2", "placement": "appendix"}],
        },
        pdf=True,
    )
    src = NotebookBuilder(plan).build()

    assert src.index("The end.") < src.index("Appendices"), (
        "the conclusion closes the narrative before the appendix parts"
    )
    assert src.index("Appendices") < src.index("**Deep**"), (
        "the appendix tab's tiles follow the heading"
    )


def test_the_cover_fills_the_title_block_with_the_defaults() -> None:
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    plan = _gen_plan([_gen_tab()], layer={"revision": 1})
    yaml_front = NotebookBuilder(plan).front_matter().to_yaml()

    assert "title: Penguins" in yaml_front
    assert "subtitle: Palmer Penguins" in yaml_front
    assert "tweber" in yaml_front, "the project's owners are the default authors"


def test_the_cover_fields_override_the_defaults() -> None:
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    plan = _gen_plan(
        [_gen_tab()],
        layer={
            "cover": {
                "title": "Penguin report",
                "subtitle": "2026 season",
                "authors": ["A. Author"],
                "date": "2026-11-23",
            },
        },
    )
    yaml_front = NotebookBuilder(plan).front_matter().to_yaml()

    assert "title: Penguin report" in yaml_front
    assert "subtitle: 2026 season" in yaml_front
    assert "A. Author" in yaml_front
    assert "2026-11-23" in yaml_front


def test_a_layer_that_does_not_validate_falls_back_with_a_warning() -> None:
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    plan = _gen_plan([_gen_tab()], layer={"tiles": [{"component_id": "f1"}]})

    src = NotebookBuilder(plan).build()

    assert "Penguins" in src, "the export still builds"
    assert any("report layer" in w for w in plan.warnings), "and says why the layer is out"


def test_a_tile_orientation_is_set_in_that_tile_cell_only() -> None:
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder

    layer = {"tiles": [{"tab_id": "tab1", "component_id": "f2", "orientation": "landscape"}]}
    src = NotebookBuilder(_gen_plan([_gen_tab()], layer=layer, pdf=True)).build()

    assert src.count("set_page_orientation('landscape')") == 1, "only the overridden tile asks"
    plain = NotebookBuilder(_gen_plan([_gen_tab()], pdf=True)).build()
    assert "set_page_orientation(" not in plain.replace("set_page_orientation,", "")
