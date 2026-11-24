"""The report editor's backend (#1457): the outline and the exact preview.

**The outline** (``GET /dashboards/notebook_export/{id}/outline``) is an
editor route: the report editor's flag and the dashboard-editing rule answer
404 to everyone else. It lists the whole report an editor can compose — every
tile in the generator's order, also the ones the layer left out, whose real
``in_report`` comes back — and the cover's defaults ignoring the layer's
cover, so the editor's fields reset to what an export would print.

**The preview** (``POST /dashboards/notebook_export/{id}/preview``) is the
render route's own path for the editor: the same job (``pdf`` off, the
runtime embedded when it may be, the same quotas and the same
author-code gate), into a per user+dashboard workdir. It is built from a
**neutral layer** — every tile in, default placement, no caption overrides,
no intro or conclusion — and carries no export minute, so the preview cache
key depends only on the dashboard, the state and the data: a text edit
changes nothing and the finished job of the same document answers instead of
queuing again — unless ``force``, which also re-executes the cached cells
(``--cache-refresh``). Its document is rendered with ``embed-resources:
false``, so the report is served by capability URL
(``GET .../notebook_export/preview_files/<token>/<path>``, the job's token is
the secret) with the patch script injected into ``report.html``.

**The workdir**: ``render._render`` keeps its temporary-directory behaviour
unless given a workdir; with jupyter-cache importable it asks Quarto to cache
the executed cells there, so a text-only edit of the report does not
re-execute every tile.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as nbx
from depictio.api.v1.endpoints.dashboards_endpoints import report_layer_routes
from depictio.models.models.analysis_state import NotebookExportRequest
from depictio.models.models.report_layer import ReportPreviewRequest

DASHBOARD_ID = str(ObjectId())
PROJECT_ID = ObjectId()
DC1 = str(ObjectId())
USER_ID = str(ObjectId())
FIXED_NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)

BASE_DF = pl.DataFrame({"habitat": ["Groundwater", "Riverwater"], "temp": [4.0, 12.0]})


def _component(index, **extra):
    return {
        "index": index,
        "component_type": "figure",
        "dc_id": DC1,
        "wf_id": str(ObjectId()),
        "dc_config": {"delta_location": f"memory://{DC1}", "type": "table"},
        **extra,
    }


def _dashboard_doc() -> dict:
    return {
        "dashboard_id": ObjectId(DASHBOARD_ID),
        "project_id": PROJECT_ID,
        "title": "Wells & Rivers",
        "subtitle": "Where the samples came from",
        "is_main_tab": True,
        "tab_order": 0,
        "grid_sections": [
            {
                "name": "Overview",
                "icon": "mdi:chart-box",
                "color": "teal",
                "description": "What the cohort looks like.",
            }
        ],
        "stored_metadata": [
            _component(
                "fig-1",
                title="Temperature by habitat",
                caption="The tiles' own caption.",
                mode="ui",
                visu_type="bar",
                dict_kwargs={"x": "habitat", "y": "temp"},
                section="Overview",
            ),
            _component(
                "fig-2",
                title="Custom",
                mode="code",
                visu_type="scatter",
                code_content="fig = px.scatter(df.to_pandas(), x='habitat', y='temp')",
                section="Overview",
            ),
        ],
    }


def _project_doc() -> dict:
    return {
        "_id": PROJECT_ID,
        "name": "Wells",
        "permissions": {"owners": [{"username": "tweber", "email": "t@depictio.org"}]},
        "workflows": [
            {
                "workflow_tag": "sampling",
                "data_collections": [{"_id": ObjectId(DC1), "data_collection_tag": "samples"}],
            }
        ],
    }


def _fake_load(workflow_id, data_collection_id, metadata=None, init_data=None, **kwargs):
    return BASE_DF


class _RenderUser:
    id = USER_ID
    email = "t.weber@example.org"
    is_anonymous = False


@pytest.fixture()
def ctx():
    """A live app's modules over in-memory Mongo: the routes' collections, the
    job bookkeeping, the Delta load and the editor rule, like the two export
    test files. The dashboard carries a report layer that leaves ``fig-2`` out
    of the report and sets a cover."""
    client = mongomock.MongoClient()
    db = client.test_db
    doc = _dashboard_doc()
    doc["report_layer"] = {
        "revision": 1,
        "cover": {"title": "Custom cover", "authors": ["Layer Author"]},
        "tiles": [
            {"tab_id": DASHBOARD_ID, "component_id": "fig-2", "in_report": False},
            {"tab_id": DASHBOARD_ID, "component_id": "fig-1", "page_break_before": True},
        ],
    }
    db.dashboards.insert_one(doc)
    db.projects.insert_one(_project_doc())
    # The preview's data identity reads each collection's latest commit from
    # the same Mongo-only place the reader marks do.
    db.deltatables.insert_one(
        {
            "data_collection_id": ObjectId(DC1),
            "aggregation": [{"delta_version": 3, "aggregation_version": 2}],
        }
    )

    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    jobs_mod = "depictio.api.v1.services.notebook_export.jobs"
    changes_mod = "depictio.api.v1.services.changes.baseline"
    granted = {"level": "owner"}

    def fake_mutation(doc_, user, level="editor"):
        order = {"none": -1, "viewer": 0, "editor": 1, "owner": 2}
        return order[level] <= order[granted["level"]]

    with (
        patch(f"{jobs_mod}.jobs_collection", db.notebook_export_jobs),
        patch(f"{jobs_mod}.slots_collection", db.notebook_export_slots),
        patch(f"{routes_mod}.dashboards_collection", db.dashboards),
        patch(f"{routes_mod}.projects_collection", db.projects),
        patch(f"{routes_mod}.check_project_permission", lambda *a, **k: True),
        patch(f"{routes_mod}._resolve_link_filters_cached", lambda **kw: list(kw["filters"])),
        patch(f"{changes_mod}.deltatables_collection", db.deltatables),
        patch(f"{changes_mod}.multiqc_collection", db.multiqc),
        patch(f"{changes_mod}.projects_collection", db.projects),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", _fake_load),
        # The report's icons come from the Iconify API when missing from the
        # bundled set: offline, the export carries on without them (the
        # resolver's own failure path), so no test may fetch them for real.
        patch("depictio.api.v1.services.icons._fetch_icon_svg", lambda icon_id: None),
        patch.object(nbx, "_dtypes_for", lambda *a, **k: None),
        patch.object(report_layer_routes, "dashboards_collection", db.dashboards),
        patch.object(report_layer_routes, "check_dashboard_mutation_permission", fake_mutation),
        patch.object(nbx.settings.notebook_export, "report_editor", True),
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        # Whether the runtime is embedded depends on a built `dist-static` and
        # the static export switch, neither of which a preview test is about.
        patch.object(nbx, "_embed_runtime", lambda *a, **k: False),
        # Two builds of the same report a minute apart differ by the export
        # minute in their provenance: freeze the clock so an unchanged report
        # hashes to the same preview key.
        patch.object(
            nbx,
            "datetime",
            SimpleNamespace(now=lambda tz=None: FIXED_NOW),
        ),
    ):
        yield {"granted": granted, "dashboards": db.dashboards, "deltatables": db.deltatables}
    client.close()


def _outline(dashboard_id=None, user=None):
    return nbx.notebook_export_outline(
        # As the router's PyObjectId would: an ObjectId, which is also what
        # the stored docs carry.
        dashboard_id=dashboard_id or ObjectId(DASHBOARD_ID),  # type: ignore[arg-type]
        current_user=user or _RenderUser(),  # type: ignore[arg-type]
        access_token=None,
    )


def _preview(force: bool = False, user=None):
    return nbx.notebook_export_preview(
        dashboard_id=ObjectId(DASHBOARD_ID),  # type: ignore[arg-type]
        request=ReportPreviewRequest(force=force),
        current_user=user or _RenderUser(),  # type: ignore[arg-type]
        access_token=None,
    )


def _staging(staged: dict, queued: dict):
    return (
        patch.object(nbx.settings.notebook_export, "render_enabled", True),
        patch(
            "depictio.api.v1.services.notebook_export.store.put",
            lambda key, body, content_type: staged.__setitem__(key, body),
        ),
        patch(
            "depictio.api.celery_app.render_notebook_report.apply_async",
            lambda **kw: queued.update(kw),
        ),
    )


class _Ready:
    """A Celery result for a job that finished with a report."""

    state = "SUCCESS"
    result = {"user_id": USER_ID, "key": "k", "filename": "wells-rivers.html", "size": 10}

    def successful(self):
        return True

    def failed(self):
        return False


# ── the outline: who may call it ─────────────────────────────────────────────


def test_the_outline_is_404_with_the_editor_flag_off(ctx) -> None:
    with patch.object(nbx.settings.notebook_export, "report_editor", False):
        with pytest.raises(HTTPException) as exc:
            _outline()
    assert exc.value.status_code == 404


def test_the_outline_is_404_for_a_viewer_and_an_unknown_dashboard(ctx) -> None:
    ctx["granted"]["level"] = "viewer"
    with pytest.raises(HTTPException) as exc:
        _outline()
    assert exc.value.status_code == 404

    ctx["granted"]["level"] = "owner"
    with pytest.raises(HTTPException) as exc:
        _outline(dashboard_id=str(ObjectId()))
    assert exc.value.status_code == 404


def test_a_preview_is_404_for_a_viewer(ctx) -> None:
    ctx["granted"]["level"] = "viewer"
    with pytest.raises(HTTPException) as exc:
        _preview()
    assert exc.value.status_code == 404


# ── the outline: what it lists ───────────────────────────────────────────────


def test_the_outline_lists_an_excluded_tile_with_its_real_settings(ctx) -> None:
    outline = _outline()

    assert [t.tab_id for t in outline.tabs] == [DASHBOARD_ID]
    tab = outline.tabs[0]
    # The generator's own order, section first, and the excluded tile still
    # listed — the layer only keeps it out of the report itself.
    assert [e.kind for e in tab.entries] == ["section", "component", "component"]
    section, fig1, fig2 = tab.entries
    assert section.title == "Overview" and section.level is not None
    # The section's own look, so the editor draws its header as the dashboard does.
    assert (section.icon, section.color, section.description) == (
        "mdi:chart-box",
        "teal",
        "What the cohort looks like.",
    )

    assert (fig1.component_id, fig2.component_id) == ("fig-1", "fig-2")
    assert fig1.in_report is True
    assert fig2.in_report is False, "the layer leaves it out; the outline says so"
    # The layer's other settings come back, and the caption is the tile's own
    # (the layer sets none here, and the export's caption stays the tile's).
    assert fig1.page_break_before is True
    assert fig1.caption == "The tiles' own caption."
    assert fig1.component_type == "figure"
    assert fig2.orientation == "auto" and fig2.order is None
    # Each tile names the section it sits under, so the editor can group them.
    assert fig1.section == fig2.section == "Overview"


def test_cover_defaults_are_the_dashboard_and_project_ones(ctx) -> None:
    outline = _outline()

    assert outline.revision == 1
    assert outline.dashboard_id == DASHBOARD_ID
    assert outline.cover_defaults.title == "Wells & Rivers"
    assert outline.cover_defaults.subtitle == "Wells"
    assert outline.cover_defaults.authors == ["tweber"]
    assert outline.cover_defaults.date == FIXED_NOW.strftime("%Y-%m-%d")


def test_the_outline_says_whether_a_preview_can_run(ctx) -> None:
    from depictio.api.v1.services.notebook_export import render as render_service

    with (
        patch.object(render_service, "quarto_binary", lambda: "quarto"),
        patch.dict(sys.modules, {"ipykernel": types.ModuleType("ipykernel")}),
        patch.dict(sys.modules, {"nbclient": types.ModuleType("nbclient")}),
    ):
        outline = _outline()
    assert outline.preview_available is True
    assert outline.preview_unavailable_reason is None

    with patch.object(render_service, "quarto_binary", lambda: None):
        outline = _outline()
    assert outline.preview_available is False
    assert outline.preview_unavailable_reason is not None
    assert "quarto.org" in outline.preview_unavailable_reason
    assert "depictio[render]" in outline.preview_unavailable_reason


# ── the preview: the job, and its cache ──────────────────────────────────────


def test_a_preview_queues_the_render_job(ctx) -> None:
    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c:
        status = _preview()

    assert status.status == "queued" and status.filename.endswith(".html")
    kwargs = queued["kwargs"]  # type: ignore[index]
    assert kwargs["pdf"] is False
    assert kwargs["preview"] is True
    # One workdir per user, dashboard and data identity: the digest moves when
    # the data does, so Quarto's cell cache cannot serve outputs of other data.
    assert kwargs["preview_cache"].startswith(f"{USER_ID}/{DASHBOARD_ID}/")
    assert kwargs["preview_force"] is False
    assert kwargs["combined"] is None
    # The notebook is staged under the caller's prefix, as a render's is.
    key = next(iter(staged))
    assert key.startswith(f"notebook_reports/{USER_ID}/{status.job_id}/")
    assert key.endswith(".qmd")
    # The record carries the cache key the next identical preview matches on.
    from depictio.api.v1.services.notebook_export import jobs

    record = jobs.get(status.job_id)
    assert record is not None
    assert record["user_id"] == USER_ID
    assert record["dashboard_id"] == DASHBOARD_ID
    assert record["preview_key"]


def test_an_identical_preview_returns_the_ready_job_without_queuing(ctx) -> None:
    from depictio.api.v1.services.notebook_export import jobs

    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c:
        first = _preview()
    assert first.status == "queued"
    jobs.finish(first.job_id, "success")

    staged2: dict[str, bytes] = {}
    queued2: dict[str, object] = {}
    a, b, c = _staging(staged2, queued2)
    with a, b, c, patch("celery.result.AsyncResult", lambda *args, **kw: _Ready()):
        second = _preview()

    assert second.job_id == first.job_id
    assert second.status == "ready"
    assert second.filename == "wells-rivers.html"
    assert queued2 == {}, "no second job was queued for an unchanged report"
    assert staged2 == {}, "and no notebook was staged again"


def test_force_queues_a_new_preview(ctx) -> None:
    from depictio.api.v1.services.notebook_export import jobs

    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c:
        first = _preview()
    jobs.finish(first.job_id, "success")

    queued2: dict[str, object] = {}
    a, b, c = _staging(staged, queued2)
    with a, b, c, patch("celery.result.AsyncResult", lambda *args, **kw: _Ready()):
        forced = _preview(force=True)

    assert forced.job_id != first.job_id
    assert forced.status == "queued"
    assert queued2["kwargs"]["preview_force"] is True  # type: ignore[index]


# ── the preview: the data identity in the key and the workdir ────────────────


def test_a_changed_data_identity_serves_a_fresh_preview(ctx) -> None:
    """The same document after a re-ingest is NOT the same preview: another
    data identity gets another cache key, another job and another workdir, and
    the same identity still reuses the finished job."""
    from depictio.api.v1.services.notebook_export import jobs

    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c, patch.object(nbx, "_report_data_identity", lambda plan: "identity-A"):
        first = _preview()
    jobs.finish(first.job_id, "success")

    staged2: dict[str, bytes] = {}
    queued2: dict[str, object] = {}
    a, b, c = _staging(staged2, queued2)
    with (
        a,
        b,
        c,
        patch.object(nbx, "_report_data_identity", lambda plan: "identity-B"),
        patch("celery.result.AsyncResult", lambda *args, **kw: _Ready()),
    ):
        second = _preview()

    assert second.status == "queued", "the finished job of the old data is not served"
    assert second.job_id != first.job_id
    assert next(iter(staged2.values())) == next(iter(staged.values())), "the document is the same"
    assert jobs.get(first.job_id)["preview_key"] != jobs.get(second.job_id)["preview_key"]  # type: ignore[index]
    assert queued2["kwargs"]["preview_cache"] != queued["kwargs"]["preview_cache"]  # type: ignore[index]
    assert str(queued2["kwargs"]["preview_cache"]).startswith(f"{USER_ID}/{DASHBOARD_ID}/")  # type: ignore[index]

    # The finished job of THIS identity answers the next identical request.
    jobs.finish(second.job_id, "success")
    queued3: dict[str, object] = {}
    a, b, c = _staging(staged2, queued3)
    with (
        a,
        b,
        c,
        patch.object(nbx, "_report_data_identity", lambda plan: "identity-B"),
        patch("celery.result.AsyncResult", lambda *args, **kw: _Ready()),
    ):
        third = _preview()
    assert third.job_id == second.job_id and third.status == "ready"


def test_a_reingest_moves_the_preview_key_and_the_workdir(ctx) -> None:
    """The current Delta commit is part of the identity: a collection whose
    latest commit moved gets a fresh preview, a collection that did not move
    does not (the qmd itself is unchanged either way)."""
    from depictio.api.v1.services.notebook_export import jobs

    staged, queued, first = _staged_preview_qmd()
    jobs.finish(first.job_id, "success")
    first_key = jobs.get(first.job_id)["preview_key"]  # type: ignore[index]
    first_workdir = queued["kwargs"]["preview_cache"]  # type: ignore[index]

    ctx["deltatables"].update_one(
        {"data_collection_id": ObjectId(DC1)},
        {"$set": {"aggregation": [{"delta_version": 4, "aggregation_version": 3}]}},
    )

    staged2, queued2, second = _staged_preview_qmd()

    assert second.status == "queued" and second.job_id != first.job_id
    assert next(iter(staged2.values())) == next(iter(staged.values())), "same document, new data"
    assert jobs.get(second.job_id)["preview_key"] != first_key  # type: ignore[index]
    assert queued2["kwargs"]["preview_cache"] != first_workdir  # type: ignore[index]


# ── the layer's stale pins: the editor stays open, live data answers ─────────


def _layer_with_stale_pins(ctx, state):
    layer = ctx["dashboards"].find_one({"dashboard_id": ObjectId(DASHBOARD_ID)})["report_layer"]
    layer["state"] = state
    ctx["dashboards"].update_one(
        {"dashboard_id": ObjectId(DASHBOARD_ID)}, {"$set": {"report_layer": layer}}
    )


_STALE_PIN_STORE = "depictio.api.v1.endpoints.dashboards_endpoints.data_versions.version_store"


def test_a_layer_pin_that_no_longer_exists_no_longer_blocks_the_editor(ctx) -> None:
    """Retention deleted the version the layer's state pins: the outline and
    the preflight still answer, and the export falls back to live data."""
    _layer_with_stale_pins(
        ctx,
        {
            "filters": [],
            "context": {"dashboard_id": DASHBOARD_ID},
            "pins": {"as_of_version": "gone", "definition_version": "gone"},
        },
    )
    with (
        patch(f"{_STALE_PIN_STORE}.get_version", lambda vid: None),
        patch(f"{_STALE_PIN_STORE}.get_version_tab", lambda vid, tab: None),
        # The combined file's owner check reads the live database: not this test's.
        patch.object(nbx, "_combined_refusal", lambda *a, **k: None),
    ):
        outline = _outline()
        preflight = nbx.notebook_export_preflight(
            dashboard_id=ObjectId(DASHBOARD_ID),  # type: ignore[arg-type]
            request=NotebookExportRequest(),
            current_user=_RenderUser(),  # type: ignore[arg-type]
            access_token=None,
        )
        source = nbx.notebook_export(
            dashboard_id=ObjectId(DASHBOARD_ID),  # type: ignore[arg-type]
            request=NotebookExportRequest(),
            current_user=_RenderUser(),  # type: ignore[arg-type]
            access_token=None,
        ).body.decode()

    assert [e.kind for e in outline.tabs[0].entries] == ["section", "component", "component"]
    assert not any("pinned" in w for w in preflight.warnings), "the export reads live data"
    assert "version=" not in source.split("client.data(")[1][:60], "no commit pin in the document"


def test_a_layer_pin_sent_in_the_request_body_is_still_a_400(ctx) -> None:
    from depictio.models.models.analysis_state import AnalysisState

    _layer_with_stale_pins(
        ctx,
        {
            "filters": [],
            "context": {"dashboard_id": DASHBOARD_ID},
            "pins": {"as_of_version": "gone"},
        },
    )
    state = AnalysisState.model_validate(
        {"context": {"dashboard_id": DASHBOARD_ID}, "pins": {"as_of_version": "gone"}}
    )
    with (
        patch(f"{_STALE_PIN_STORE}.get_version", lambda vid: None),
        pytest.raises(HTTPException) as exc,
    ):
        nbx.notebook_export_preflight(
            dashboard_id=ObjectId(DASHBOARD_ID),  # type: ignore[arg-type]
            request=NotebookExportRequest(state=state),
            current_user=_RenderUser(),  # type: ignore[arg-type]
            access_token=None,
        )
    assert exc.value.status_code == 400
    assert "no longer exists" in str(exc.value.detail)


# ── the preview: a neutral build, the same key after a text edit ─────────────


def _staged_preview_qmd():
    """Queue one preview over the staging patches; its staged qmd and kwargs."""
    staged: dict[str, bytes] = {}
    queued: dict[str, object] = {}
    a, b, c = _staging(staged, queued)
    with a, b, c:
        status = _preview()
    return staged, queued, status


def test_a_preview_builds_a_neutral_document_and_a_download_does_not(ctx) -> None:
    """The preview's document is built from a neutral layer (every tile in,
    the default cover, no intro) and carries no export minute, so an edit of
    the layer's text cannot change it; a downloaded report honours the layer
    and keeps the minute."""
    staged, _queued, _status = _staged_preview_qmd()
    qmd = next(iter(staged.values())).decode()

    assert "embed-resources: false" in qmd, "the preview's files are served, not inlined"
    assert "12:00" not in qmd, "no export minute in a preview's provenance"
    assert "Custom cover" not in qmd, "the layer's cover does not reach a preview"

    export = nbx.notebook_export(
        dashboard_id=ObjectId(DASHBOARD_ID),  # type: ignore[arg-type]
        request=NotebookExportRequest(),
        current_user=_RenderUser(),  # type: ignore[arg-type]
        access_token=None,
    )
    export_qmd = export.body.decode()
    assert "embed-resources: true" in export_qmd, "a download stays self-contained"
    assert "12:00" in export_qmd
    assert "Custom cover" in export_qmd, "the layer's cover is the download's"


def test_the_preview_key_ignores_intro_and_caption_edits(ctx) -> None:
    """Only the dashboard, the state and the data move the key: editing the
    layer's intro text or a tile's caption override does not."""
    from depictio.api.v1.services.notebook_export import jobs

    staged, queued, first = _staged_preview_qmd()
    first_key = jobs.get(first.job_id)["preview_key"]  # type: ignore[index]

    layer = ctx["dashboards"].find_one({"dashboard_id": ObjectId(DASHBOARD_ID)})["report_layer"]
    layer["intro"] = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "A hand-written intro."}]}
        ],
    }
    layer["conclusion"] = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "The end."}]}],
    }
    layer["tiles"][0]["caption"] = "A caption override."
    layer["tiles"][1]["in_report"] = True
    ctx["dashboards"].update_one(
        {"dashboard_id": ObjectId(DASHBOARD_ID)}, {"$set": {"report_layer": layer}}
    )

    staged2, _queued2, second = _staged_preview_qmd()

    assert staged2 and next(iter(staged2.values())) == next(iter(staged.values()))
    assert jobs.get(second.job_id)["preview_key"] == first_key  # type: ignore[index]
    assert queued and queued["kwargs"]["preview_cache"]  # type: ignore[index]


def test_a_ready_preview_status_carries_the_capability_url(ctx) -> None:
    from depictio.api.v1.services.notebook_export import jobs

    _staged, _queued, status = _staged_preview_qmd()
    jobs.finish(status.job_id, "success")

    class _ReadyPreview(_Ready):
        result = {
            "user_id": USER_ID,
            "filename": "wells-rivers.html",
            "size": 10,
            "preview_url": "/depictio/api/v1/dashboards/notebook_export/preview_files/t/report.html",
        }

    with patch("celery.result.AsyncResult", lambda *args, **kw: _ReadyPreview()):
        got = nbx.notebook_export_render_status(job_id=status.job_id, current_user=_RenderUser())
    assert got.status == "ready" and got.preview_url is not None
    assert got.preview_url.startswith("/depictio/api/v1/dashboards/notebook_export/preview_files/")
    assert got.preview_url.endswith("/report.html")


def test_the_outline_exposes_the_tab_s_icon_and_accent(ctx) -> None:
    """The tab's icon and the accent the report tints its heading with: the
    sidebar precedence, resolved to hex the same way the generator does."""
    from depictio.notebook.theme import palette_hex

    ctx["dashboards"].update_one(
        {"dashboard_id": ObjectId(DASHBOARD_ID)},
        {"$set": {"icon": "mdi:flask", "icon_color": "teal"}},
    )

    tab = _outline().tabs[0]
    assert tab.icon == "mdi:flask"
    assert tab.color == palette_hex("teal", "")
    assert tab.color and tab.color.startswith("#")

    # No colour anywhere: the accent stays unset rather than picked.
    ctx["dashboards"].update_one(
        {"dashboard_id": ObjectId(DASHBOARD_ID)},
        {"$unset": {"icon": "", "icon_color": ""}},
    )
    tab = _outline().tabs[0]
    assert tab.icon == "mdi:view-dashboard"  # a main tab's fallback icon
    assert tab.color is None or tab.color.startswith("#")


# ── the worker's render: the persistent workdir and its cache ────────────────


def _fake_quarto(monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
    """A quarto run that writes its report next to its source and logs that it
    executed the notebook — the two things ``_render`` checks."""

    class _Proc:
        returncode = 0
        pid = 99999  # nothing of ours: the group kill finds no process

        def __init__(self, cwd) -> None:
            self._cwd = cwd

        def communicate(self, timeout=None):
            (self._cwd / "report.html").write_text("<html>report</html>")
            return "Executing 'report.qmd'", ""

        def wait(self, timeout=None):
            return 0

    def popen(cmd, **kwargs):
        calls.append(list(cmd))
        return _Proc(Path(kwargs["cwd"]))

    from depictio.api.v1.services.notebook_export import render as render_service

    monkeypatch.setattr(render_service.subprocess, "Popen", popen)
    monkeypatch.setattr(render_service, "quarto_binary", lambda: "quarto")


def _renderable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "ipykernel", types.ModuleType("ipykernel"))
    monkeypatch.setitem(sys.modules, "nbclient", types.ModuleType("nbclient"))


def test_render_in_a_workdir_caches_and_keeps_the_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from depictio.api.v1.services.notebook_export import render as render_service

    _renderable(monkeypatch)
    calls: list[list[str]] = []
    _fake_quarto(monkeypatch, calls)
    monkeypatch.setattr("importlib.import_module", lambda name: types.ModuleType(name))
    workdir = tmp_path / "preview" / "deep"

    html = render_service.render_quarto_html(
        b"# Hi",
        stem="report",
        api_url="http://api",
        api_token=None,
        timeout_s=10,
        workdir=str(workdir),
        cache=True,
    )

    assert html == b"<html>report</html>"
    cmd = calls[0]
    assert "--cache" in cmd and "--cache-refresh" not in cmd
    # The workdir is created (parents included) and survives the render: the
    # cache in it is the next preview's starting point.
    assert (workdir / "report.qmd").exists()
    assert (workdir / "report.html").exists()


def test_render_with_force_refreshes_the_cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from depictio.api.v1.services.notebook_export import render as render_service

    _renderable(monkeypatch)
    calls: list[list[str]] = []
    _fake_quarto(monkeypatch, calls)
    monkeypatch.setattr("importlib.import_module", lambda name: types.ModuleType(name))

    render_service.render_quarto_html(
        b"# Hi",
        stem="report",
        api_url="http://api",
        api_token=None,
        timeout_s=10,
        workdir=str(tmp_path / "wd"),
        cache=True,
        force=True,
    )

    cmd = calls[0]
    assert "--cache-refresh" in cmd and "--cache" not in cmd


def test_render_without_jupyter_cache_adds_no_cache_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from depictio.api.v1.services.notebook_export import render as render_service

    _renderable(monkeypatch)
    calls: list[list[str]] = []
    _fake_quarto(monkeypatch, calls)

    def _no_jupyter_cache(name):
        raise ImportError(f"no module named {name!r}")

    monkeypatch.setattr("importlib.import_module", _no_jupyter_cache)

    render_service.render_quarto_html(
        b"# Hi",
        stem="report",
        api_url="http://api",
        api_token=None,
        timeout_s=10,
        workdir=str(tmp_path / "wd"),
        cache=True,
    )

    assert "--cache" not in calls[0], "the flag is unknown to Quarto without jupyter-cache"


def test_render_without_a_workdir_stays_in_a_temporary_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The plain render path is unchanged: no cache flags, nothing left behind."""
    from depictio.api.v1.services.notebook_export import render as render_service

    _renderable(monkeypatch)
    calls: list[list[str]] = []
    _fake_quarto(monkeypatch, calls)

    render_service.render_quarto_html(
        b"# Hi",
        stem="report",
        api_url="http://api",
        api_token=None,
        timeout_s=10,
    )

    assert "--cache" not in calls[0] and "--cache-refresh" not in calls[0]


# ── the worker task's preview workdir ────────────────────────────────────────


def test_the_preview_workdir_is_per_user_and_dashboard(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``preview_cache`` (``"<user>/<dashboard>"``) sits under the configured
    root; without one, under the system temporary directory."""
    from depictio.api import celery_app

    monkeypatch.setattr(
        celery_app.settings.notebook_export, "preview_cache_dir", str(tmp_path / "cache")
    )
    assert celery_app._preview_workdir(f"{USER_ID}/{DASHBOARD_ID}") == str(
        tmp_path / "cache" / USER_ID / DASHBOARD_ID
    )

    monkeypatch.setattr(celery_app.settings.notebook_export, "preview_cache_dir", None)
    assert celery_app._preview_workdir(f"{USER_ID}/{DASHBOARD_ID}").endswith(
        f"depictio-preview/{USER_ID}/{DASHBOARD_ID}"
    )


# ── the preview files route: the capability URL the editor's iframe opens ────


_REPORT_HTML = (
    b"<html><head><title>x</title></head><body><p>report</p>"
    b'<script src="report_files/site_libs/quarto.js"></script></body></html>'
)

#: A token as the worker mints one: ``secrets.token_urlsafe(32)`` is 43 chars
#: of the URL-safe alphabet, so a shape check may not refuse the real thing.
_REPORT_TOKEN = "t" * 43


def _served(token: str, path: str):
    """One preview file request, over an object store that has a single
    report — under ``_REPORT_TOKEN``'s prefix and nowhere else."""
    from depictio.api.v1.services.notebook_export import store

    objects = {
        store.preview_key(_REPORT_TOKEN, "report.html"): _REPORT_HTML,
        store.preview_key(_REPORT_TOKEN, "report_files/site_libs/quarto.js"): b"console.log(1)",
    }
    with patch.object(store, "get", lambda key: objects[key]):
        return nbx.notebook_export_preview_files(token=token, path=path)


def test_the_preview_files_are_404_with_the_editor_flag_off(ctx) -> None:
    with patch.object(nbx.settings.notebook_export, "report_editor", False):
        with pytest.raises(HTTPException) as exc:
            _served(_REPORT_TOKEN, "report.html")
    assert exc.value.status_code == 404


def test_an_unknown_token_or_path_is_404(ctx) -> None:
    # A token that is shaped like one but was never minted: nothing under it.
    with pytest.raises(HTTPException) as exc:
        _served("u" * 43, "report.html")
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        _served(_REPORT_TOKEN, "report_files/site_libs/no-such.js")
    assert exc.value.status_code == 404

    # A token that is not even shaped like one: no such file, not a probe.
    with pytest.raises(HTTPException) as exc:
        _served("../../etc/passwd", "report.html")
    assert exc.value.status_code == 404


def test_a_path_may_not_escape_the_token_s_prefix(ctx) -> None:
    for path in (
        "../secret.html",
        "report_files/../../secret.html",
        "..%2Fsecret.html",
        "/etc/passwd",
        "report_files\\..\\..\\secret.html",
        ".",
        "",
    ):
        with pytest.raises(HTTPException) as exc:
            _served(_REPORT_TOKEN, path)
        assert exc.value.status_code == 404, path


def test_the_report_is_served_sandboxed_with_the_patch_injected(ctx) -> None:
    """The app's own policy would refuse the report outright (``default-src
    'self'`` and no inline scripts); the preview's policy allows those, only
    in an opaque origin, and the patch script is injected into the report
    alone."""
    response = _served(_REPORT_TOKEN, "report.html")
    csp = response.headers["Content-Security-Policy"]
    directives = {d.split()[0]: d.split()[1:] for d in csp.split("; ")}
    assert directives["sandbox"][0] == "allow-scripts"
    assert "allow-same-origin" not in directives["sandbox"]
    assert "'self'" in directives["script-src"] and "'unsafe-inline'" in directives["script-src"]
    assert directives["default-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'self'"]
    assert directives["base-uri"] == ["'self'"]
    assert directives["form-action"] == ["'none'"]
    body = response.body.decode()
    assert f'<script src="{nbx.PREVIEW_PATCH_SCRIPT}"></script><' in body
    assert body.count("</body>") == 1

    other = _served(_REPORT_TOKEN, "report_files/site_libs/quarto.js")
    assert nbx.PREVIEW_PATCH_SCRIPT not in other.body.decode(), "only report.html is patched"


def test_the_report_gets_a_storage_shim_before_any_script(ctx) -> None:
    """The opaque origin makes ``window.localStorage`` throw, and Quarto's own
    scripts read it unguarded: an in-memory stand-in is set first, at the top
    of ``<head>``, so they run instead of throwing on every page."""
    body = _served(_REPORT_TOKEN, "report.html").body.decode()
    shim = body.find(nbx.PREVIEW_STORAGE_SHIM)
    assert shim != -1
    assert body.count(nbx.PREVIEW_STORAGE_SHIM) == 1
    first_script = body.find("<script", shim + len(nbx.PREVIEW_STORAGE_SHIM))
    assert shim < body.find("</head>")
    assert first_script == -1 or shim < first_script


def test_the_patch_script_is_served_from_the_assets(ctx) -> None:
    from depictio.api.v1.services.notebook_export import resources

    response = _served(_REPORT_TOKEN, nbx.PREVIEW_PATCH_SCRIPT)
    assert response.headers["Content-Type"].startswith("text/javascript")
    assert response.body.decode() == resources.asset("preview_patch.js")


def test_preview_files_answer_cors_so_quarto_s_module_scripts_load(ctx) -> None:
    """The sandboxed frame's origin is opaque, and quarto.js is an ES module:
    fetched in CORS mode, it only runs with an allow-origin header."""
    headers = nbx._preview_headers(immutable=True)
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "max-age" in headers["Cache-Control"]
    assert nbx._preview_headers()["Cache-Control"] == "no-store"


def test_a_text_tile_is_named_by_its_heading_or_first_words():
    """The editor names a title-less text tile from its body, never by its id."""
    from depictio.api.v1.endpoints.dashboards_endpoints.notebook_export import _text_label

    assert _text_label("### The run\n- ![](icon:mdi:dna) **Pipeline** x") == "The run"
    assert (
        _text_label("![](icon:mdi:flask) **Samples** {{n}} in the [sheet](section:S)")
        == "Samples in the sheet"
    )
    assert _text_label("one two three four five six seven eight nine") == (
        "one two three four five six seven eight …"
    )
    assert _text_label(None) == ""
