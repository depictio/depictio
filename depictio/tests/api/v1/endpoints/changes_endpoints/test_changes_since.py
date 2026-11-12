"""What changed since a reader's last visit (#1397).

The three cases the issue's acceptance names, plus the guarantees around
them: a first visit shows nothing, a reader's own changes are not news, the
mark never records a dashboard version, and a read-only "before this run"
view never moves the mark.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

API = "/depictio/api/v1/changes"
T0 = datetime(2026, 11, 1, 12, 0, 0)


class _User:
    def __init__(self, email: str, *, anonymous: bool = False) -> None:
        self.id = str(ObjectId())
        self.email = email
        self.is_admin = False
        self.is_anonymous = anonymous
        self.is_temporary = False


READER = _User("reader@example.com")
EDITOR = _User("editor@example.com")
ANON = _User("anon@example.com", anonymous=True)


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch):
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.changes_endpoints import routes as changes_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
    from depictio.api.v1.endpoints.dashboards_endpoints import (
        version_store,
        versioning,
        versions_routes,
    )
    from depictio.api.v1.endpoints.routers import router
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
    from depictio.api.v1.services.changes import baseline, diff, store

    monkeypatch.setattr(settings.dashboard_versions, "changes_since_enabled", True)
    monkeypatch.setattr(settings.dashboard_versions, "changes_since_mark_mode", "sticky")

    db = mongomock.MongoClient()["depictioTest"]
    handles = {
        "dashboards_collection": db["dashboards"],
        "dashboard_versions_collection": db["dashboard_versions"],
        "deltatables_collection": db["deltatables"],
        "multiqc_collection": db["multiqc"],
        "projects_collection": db["projects"],
        "comment_threads_collection": db["comment_threads"],
        "ingestion_runs_collection": db["ingestion_runs"],
        "runs_collection": db["runs"],
        "reader_marks_collection": db["reader_marks"],
    }
    for module in (
        baseline,
        diff,
        store,
        changes_routes,
        versioning,
        versions_routes,
        version_store,
    ):
        for name, coll in handles.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, coll)

    monkeypatch.setattr(dash_routes, "check_project_permission", lambda *a, **k: True)

    project_id = ObjectId()
    dc_table, dc_mqc = ObjectId(), ObjectId()
    wf_id = ObjectId()
    db["projects"].insert_one(
        {
            "_id": project_id,
            "name": "rnaseq",
            "workflows": [
                {
                    "_id": wf_id,
                    "workflow_tag": "nf-core/rnaseq",
                    "data_collections": [
                        {
                            "_id": dc_table,
                            "data_collection_tag": "samples",
                            "config": {"type": "table"},
                        },
                        {
                            "_id": dc_mqc,
                            "data_collection_tag": "multiqc_data",
                            "config": {"type": "multiqc"},
                        },
                    ],
                }
            ],
        }
    )
    family = ObjectId()
    components = [
        {"index": "fig-1", "component_type": "figure", "title": "Reads", "dc_id": str(dc_table)},
        {"index": "mqc-1", "component_type": "multiqc", "title": "FastQC", "dc_id": str(dc_mqc)},
        {"index": "txt-1", "component_type": "text", "title": "Notes"},
    ]
    db["dashboards"].insert_one(
        {
            "dashboard_id": family,
            "is_main_tab": True,
            "title": "Overview",
            "project_id": project_id,
            "stored_metadata": components,
        }
    )
    db["deltatables"].insert_one(
        {
            "data_collection_id": dc_table,
            "aggregation": [
                {
                    "aggregation_version": 1,
                    "delta_version": 0,
                    "rows_total": 10,
                    "rows_added": 10,
                    "run_tags": ["run_a", "run_b"],
                    "aggregation_by": {"email": EDITOR.email},
                    "aggregation_time": T0,
                }
            ],
        }
    )
    db["multiqc"].insert_many(
        [
            {
                "data_collection_id": str(dc_mqc),
                "run_tag": tag,
                "processed_at": T0,
                "metadata": {"samples": [f"SRR{n}_1", f"SRR{n}_2"]},
            }
            for n, tag in ((1, "run_a"), (2, "run_b"))
        ]
    )
    db["dashboard_versions"].insert_one(_version(family, project_id, 1, EDITOR, components))

    caller = {"user": READER}
    app = FastAPI()
    app.include_router(router, prefix="/depictio/api/v1")
    app.dependency_overrides[get_user_or_anonymous] = lambda: caller["user"]

    return {
        "client": TestClient(app),
        "db": db,
        "family": str(family),
        "project": str(project_id),
        "dc_table": dc_table,
        "dc_mqc": str(dc_mqc),
        "components": components,
        "caller": caller,
        "settings": settings,
    }


def _version(family, project_id, seq, author, components, **extra):
    return {
        "version_id": f"v{seq}-{ObjectId()}",
        "family_id": str(family),
        "project_id": str(project_id),
        "seq": seq,
        "kind": "auto",
        "author_id": author.id,
        "author_email": author.email,
        "created_at": T0 + timedelta(minutes=seq),
        "updated_at": T0 + timedelta(minutes=seq),
        "content_hash": f"h{seq}",
        "tabs": [{"dashboard_id": str(family), "title": "Overview", "stored_metadata": components}],
        **extra,
    }


def _changes(ctx, user=READER, body=None):
    ctx["caller"]["user"] = user
    res = ctx["client"].post(f"{API}/dashboard/{ctx['family']}", json=body or {})
    assert res.status_code == 200, res.text
    return res.json()


def _visit(ctx, user=READER):
    ctx["caller"]["user"] = user
    res = ctx["client"].put(f"{API}/dashboard/{ctx['family']}/visit")
    assert res.status_code == 200, res.text
    return res.json()


def _edit_component(ctx, author, title):
    components = [dict(c) for c in ctx["components"]]
    components[0]["title"] = title
    ctx["db"]["dashboards"].update_one(
        {"dashboard_id": ObjectId(ctx["family"])}, {"$set": {"stored_metadata": components}}
    )
    seq = ctx["db"]["dashboard_versions"].count_documents({}) + 1
    ctx["db"]["dashboard_versions"].insert_one(
        _version(ctx["family"], ctx["project"], seq, author, components)
    )


def _ingest_run_c(ctx, by=EDITOR):
    ctx["db"]["ingestion_runs"].insert_one(
        {
            "run_id": "ing-c",
            "user_id": by.id,
            "email": by.email,
            "project_id": ctx["project"],
            "status": "success",
            "run_tags": ["run_c"],
            "started_at": T0 + timedelta(hours=1),
        }
    )
    ctx["db"]["multiqc"].insert_one(
        {
            "data_collection_id": ctx["dc_mqc"],
            "run_tag": "run_c",
            "ingestion_run_id": "ing-c",
            "processed_at": T0 + timedelta(hours=1),
            "metadata": {"samples": ["SRR3_1", "SRR3_2"]},
        }
    )


# ── flag ────────────────────────────────────────────────────────────────────


def test_routes_are_hidden_while_the_flag_is_off(ctx):
    ctx["settings"].dashboard_versions.changes_since_enabled = False
    res = ctx["client"].post(f"{API}/dashboard/{ctx['family']}", json={})
    assert res.status_code == 404


# ── acceptance: first visit ─────────────────────────────────────────────────


def test_a_first_visit_shows_no_marks_and_records_no_version(ctx):
    first = _changes(ctx)
    assert first["first_visit"] is True
    assert first["data"] == first["dashboard"] == first["comments"] == []
    assert first["changed_components"] == {}

    versions_before = ctx["db"]["dashboard_versions"].count_documents({})
    assert _visit(ctx) == {"persisted": True, "moved": True}
    assert ctx["db"]["reader_marks"].count_documents({}) == 1
    assert ctx["db"]["dashboard_versions"].count_documents({}) == versions_before

    again = _changes(ctx)
    assert again["first_visit"] is False
    assert again["data"] == again["dashboard"] == []


# ── acceptance: a new run ───────────────────────────────────────────────────


def test_a_new_run_is_listed_and_its_components_marked(ctx):
    _visit(ctx)
    _ingest_run_c(ctx)

    result = _changes(ctx)
    [mqc] = result["data"]
    assert mqc["data_collection_tag"] == "multiqc_data"
    assert mqc["new_run_tags"] == ["run_c"]
    assert mqc["new_samples"] == ["SRR3_1", "SRR3_2"]
    assert mqc["reports_added"] == 1
    assert mqc["by"] == [EDITOR.email]
    assert result["changed_components"] == {f"{ctx['family']}:mqc-1": ["data"]}


def test_a_delta_refresh_reports_new_run_tags_and_rows(ctx):
    _visit(ctx)
    ctx["db"]["deltatables"].update_one(
        {"data_collection_id": ctx["dc_table"]},
        {
            "$push": {
                "aggregation": {
                    "aggregation_version": 2,
                    "delta_version": 1,
                    "rows_total": 15,
                    "rows_added": 5,
                    "run_tags": ["run_c"],
                    "aggregation_by": {"email": EDITOR.email},
                }
            }
        },
    )
    [table] = _changes(ctx)["data"]
    assert table["new_run_tags"] == ["run_c"]
    assert (table["rows_before"], table["rows_after"], table["rows_added"]) == (10, 15, 5)
    assert (table["delta_from"], table["delta_to"]) == (0, 1)


def test_the_reader_s_own_ingestion_is_not_news(ctx):
    _visit(ctx)
    _ingest_run_c(ctx, by=READER)
    result = _changes(ctx)
    assert result["data"] == []
    assert result["changed_components"] == {}


# ── acceptance: a component edited by someone else ──────────────────────────


def test_another_user_s_edit_is_marked_with_its_author(ctx):
    _visit(ctx)
    _edit_component(ctx, EDITOR, "Reads per sample")

    result = _changes(ctx)
    [change] = result["dashboard"]
    assert change["kind"] == "component_edited"
    assert change["component_index"] == "fig-1"
    assert change["authors"] == [EDITOR.email]
    assert change["seq"] == 2
    assert result["changed_components"] == {f"{ctx['family']}:fig-1": ["definition"]}


def test_the_editor_does_not_see_their_own_edit(ctx):
    _visit(ctx, EDITOR)
    _edit_component(ctx, EDITOR, "Reads per sample")
    result = _changes(ctx, EDITOR)
    assert result["dashboard"] == []
    assert result["changed_components"] == {}


def test_moving_a_tile_is_not_a_change(ctx):
    _visit(ctx)
    components = [dict(c) for c in ctx["components"]]
    components[0]["layout"] = {"x": 4, "y": 2}
    ctx["db"]["dashboards"].update_one(
        {"dashboard_id": ObjectId(ctx["family"])}, {"$set": {"stored_metadata": components}}
    )
    assert _changes(ctx)["dashboard"] == []


# ── marking as seen ─────────────────────────────────────────────────────────


def test_marks_stay_until_marked_as_seen_in_sticky_mode(ctx):
    _visit(ctx)
    _edit_component(ctx, EDITOR, "Reads per sample")
    assert _visit(ctx)["moved"] is False  # sticky: a later visit does not clear them
    assert _changes(ctx)["changed_components"]

    key = f"{ctx['family']}:fig-1"
    res = ctx["client"].put(f"{API}/dashboard/{ctx['family']}/seen", json={"component_keys": [key]})
    assert res.json() == {"persisted": True}
    assert _changes(ctx)["changed_components"] == {}

    # Changed again after the dismissal: marked again.
    _edit_component(ctx, EDITOR, "Reads per sample (v3)")
    assert key in _changes(ctx)["changed_components"]

    ctx["client"].put(f"{API}/dashboard/{ctx['family']}/seen", json={})
    after = _changes(ctx)
    assert after["dashboard"] == [] and after["changed_components"] == {}


def test_previous_visit_mode_moves_the_mark_on_each_visit(ctx):
    _visit(ctx)
    ctx["client"].put(f"{API}/prefs", json={"mark_mode": "previous_visit"})
    _edit_component(ctx, EDITOR, "Reads per sample")
    assert _changes(ctx)["dashboard"]  # shown for this visit
    assert _visit(ctx)["moved"] is True
    assert _changes(ctx)["dashboard"] == []


# ── anonymous readers keep their mark in the browser ────────────────────────


def test_an_anonymous_reader_gets_and_sends_its_baseline(ctx):
    first = _changes(ctx, ANON)
    assert first["first_visit"] is True and first["server_held"] is False
    assert _visit(ctx, ANON) == {"persisted": False}
    assert ctx["db"]["reader_marks"].count_documents({}) == 0

    _edit_component(ctx, EDITOR, "Reads per sample")
    result = _changes(ctx, ANON, {"baseline": first["current_baseline"]})
    assert [c["component_index"] for c in result["dashboard"]] == ["fig-1"]


# ── read-only views ─────────────────────────────────────────────────────────


def test_before_run_shows_that_run_and_never_moves_the_mark(ctx):
    _visit(ctx)
    _ingest_run_c(ctx)
    ctx["client"].put(f"{API}/dashboard/{ctx['family']}/seen", json={})
    assert _changes(ctx)["data"] == []

    view = _changes(ctx, body={"before_run": "ing-c"})
    [mqc] = view["data"]
    assert mqc["new_run_tags"] == ["run_c"]
    assert _changes(ctx)["data"] == []  # the mark did not move


# ── comments ────────────────────────────────────────────────────────────────


def test_new_comments_by_others_are_listed(ctx):
    _visit(ctx)
    later = datetime.now() + timedelta(minutes=5)
    for author in (EDITOR, READER):
        ctx["db"]["comment_threads"].insert_one(
            {
                "project_id": ctx["project"],
                "parent_dashboard_id": ctx["family"],
                "anchor": {"dashboard_id": ctx["family"], "component_index": "fig-1"},
                "status": "open",
                "created_at": later,
                "comments": [
                    {
                        "author": {"user_id": author.id, "email": author.email},
                        "body": "Look",
                        "created_at": later,
                    }
                ],
            }
        )
    [comment] = _changes(ctx)["comments"]
    assert comment["author"] == EDITOR.email and comment["kind"] == "thread"


# ── project ─────────────────────────────────────────────────────────────────


def test_project_marks_list_new_runs(ctx):
    ctx["db"]["runs"].insert_one({"workflow_id": _wf(ctx), "run_tag": "run_a"})
    ctx["client"].put(f"{API}/project/{ctx['project']}/visit")
    ctx["db"]["runs"].insert_one({"workflow_id": _wf(ctx), "run_tag": "run_c"})
    _ingest_run_c(ctx)
    res = ctx["client"].post(f"{API}/project/{ctx['project']}", json={}).json()
    assert [r["run_tag"] for r in res["new_runs"]] == ["run_c"]
    assert [d["data_collection_tag"] for d in res["data"]] == ["multiqc_data"]


def _wf(ctx):
    return ctx["db"]["projects"].find_one()["workflows"][0]["_id"]


def test_an_append_that_recreates_every_report_only_reports_the_new_samples(ctx):
    """Appending to a MultiQC collection re-processes every report: new ids,
    same content-addressed keys. Only the appended samples are news."""
    reports = ctx["db"]["multiqc"]
    for i, report in enumerate(reports.find({"data_collection_id": ctx["dc_mqc"]})):
        reports.update_one({"_id": report["_id"]}, {"$set": {"s3_location": f"s3://b/{i}.parquet"}})
    _visit(ctx)

    old = list(reports.find({"data_collection_id": ctx["dc_mqc"]}))
    reports.delete_many({"data_collection_id": ctx["dc_mqc"]})
    for report in old:
        report.pop("_id")
        report["processed_at"] = T0 + timedelta(hours=2)
        reports.insert_one(report)
    reports.insert_one(
        {
            "data_collection_id": ctx["dc_mqc"],
            "s3_location": "s3://b/new.parquet",
            "processed_at": T0 + timedelta(hours=2),
            "metadata": {"samples": ["SRR3_1"]},
        }
    )
    [mqc] = _changes(ctx)["data"]
    assert (mqc["reports_added"], mqc["reports_refreshed"], mqc["reports_removed"]) == (1, 0, 0)
    assert mqc["new_samples"] == ["SRR3_1"]
