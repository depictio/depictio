"""Component figure extraction and embed endpoints."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import embed as emb
from depictio.api.v1.services.embed.extract import embed_url, encode_state, parse_extracted
from depictio.models.models.analysis_state import AnalysisState, ComponentEmbedRequest

DASHBOARD_ID = str(ObjectId())
PROJECT_ID = ObjectId()


@pytest.fixture
def patched_env():
    client = mongomock.MongoClient()
    db = client.test_db
    db.dashboards.insert_one(
        {
            "dashboard_id": DASHBOARD_ID,
            "project_id": PROJECT_ID,
            "stored_metadata": [
                {"index": "fig-1", "component_type": "figure", "title": "Bill shape"},
                {
                    "index": "viz-1",
                    "component_type": "advanced_viz",
                    "viz_kind": "volcano",
                    "title": "Volcano",
                },
                {"index": "tbl-1", "component_type": "table", "title": "Rows"},
                {
                    "index": "rec-1",
                    "component_type": "advanced_viz",
                    "viz_kind": "record_card",
                    "title": "Sample record",
                },
            ],
        }
    )
    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    jobs_mod = "depictio.api.v1.services.notebook_export.jobs"
    emb._results.clear()
    with (
        patch(f"{jobs_mod}.jobs_collection", db.notebook_export_jobs),
        patch(f"{jobs_mod}.slots_collection", db.notebook_export_slots),
        patch(f"{routes_mod}.dashboards_collection", db.dashboards),
        patch(f"{routes_mod}.check_project_permission", lambda *a, **k: True),
    ):
        yield
        client.close()


def _state():
    return AnalysisState.model_validate(
        {
            "filters": [
                {
                    "index": "f",
                    "value": ["a"],
                    "column_name": "c",
                    "interactive_component_type": "MultiSelect",
                }
            ],
            "context": {"dashboard_id": DASHBOARD_ID},
        }
    )


class _Reader:
    id = ObjectId()


class _Other:
    id = ObjectId()


READER = _Reader()


def _figure(component, user=READER):
    return emb.component_figure(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        component_id=component,
        request=ComponentEmbedRequest(state=_state(), theme="dark"),
        current_user=user,  # type: ignore[arg-type]
        access_token=None,
    )


def _sent(task) -> dict:
    """The payload the last ``apply_async`` call queued."""
    return task.apply_async.call_args.kwargs["args"][0]


def test_non_plotly_component_is_unsupported(patched_env):
    resp = _figure("tbl-1")
    assert resp.status == "unsupported" and "table" in (resp.reason or "")


def test_a_kind_drawn_without_plotly_is_snapshotted(patched_env):
    """The browser pass is told to take a PNG once the renderer is drawn, rather
    than wait 90 s for a Plotly div the renderer never draws."""
    with patch("depictio.api.v1.celery_tasks.extract_component_figure_task") as task:
        resp = _figure("rec-1")
        assert resp.status == "pending"
        assert _sent(task)["expect"] == "image"
        _figure("viz-1")
        assert _sent(task)["expect"] == "plotly"


def test_a_snapshot_job_hands_back_its_image(patched_env):
    with patch("depictio.api.v1.celery_tasks.extract_component_figure_task"):
        job_id = _figure("rec-1").job_id
    done = SimpleNamespace(
        state="SUCCESS",
        result={"status": "ready", "image": "data:image/png;base64,AAAA", "source": "snapshot"},
    )
    with patch("celery.result.AsyncResult", return_value=done):
        resp = emb.component_figure_job(job_id=job_id, current_user=READER)  # type: ignore[arg-type]
    assert resp.status == "ready" and resp.figure is None
    assert resp.image == "data:image/png;base64,AAAA" and resp.source == "snapshot"


def test_the_cache_tells_colour_by_apart(patched_env):
    base = AnalysisState.model_validate({"context": {"dashboard_id": DASHBOARD_ID}})
    grouped = AnalysisState.model_validate(
        {
            "context": {"dashboard_id": DASHBOARD_ID},
            "color_by": {"kind": "column", "column_name": "x"},
        }
    )
    plain = emb._cache_key(DASHBOARD_ID, "viz-1", base.model_dump(mode="json"), "light")
    other = emb._cache_key(DASHBOARD_ID, "viz-1", grouped.model_dump(mode="json"), "light")
    assert plain != other


def test_parse_extracted_carries_the_renderer_reason():
    out = parse_extracted(json.dumps({"status": "error", "figure": None, "reason": "no rows"}))
    assert out["status"] == "error" and "no rows" in out["reason"]


def test_dispatch_then_poll_then_cache(patched_env):
    with patch("depictio.api.v1.celery_tasks.extract_component_figure_task") as task:
        first = _figure("viz-1")
        sent = _sent(task)
        assert task.apply_async.call_args.kwargs["task_id"] == first.job_id
    assert first.status == "pending" and first.job_id
    assert sent["dashboard_id"] == DASHBOARD_ID and sent["component_id"] == "viz-1"
    assert sent["theme"] == "dark" and sent["state"]["filters"][0]["value"] == ["a"]
    # Run as the reader who asked, never as the admin.
    assert sent["user_id"] == str(READER.id) and sent["job_id"] == first.job_id

    figure = {"data": [{"type": "scatter", "x": [1], "y": [2]}], "layout": {}}
    pending = SimpleNamespace(state="STARTED", result=None)
    done = SimpleNamespace(
        state="SUCCESS", result={"status": "ready", "figure": figure, "source": "extracted"}
    )
    with patch("celery.result.AsyncResult", lambda job_id, app=None: pending):
        assert emb.component_figure_job(first.job_id, current_user=READER).status == "pending"  # type: ignore[arg-type]
    with patch("celery.result.AsyncResult", lambda job_id, app=None: done):
        got = emb.component_figure_job(first.job_id, current_user=READER)  # type: ignore[arg-type]
    assert got.status == "ready" and got.figure == figure and got.source == "extracted"
    # The same request now hits the cache and dispatches nothing.
    with patch(
        "depictio.api.v1.celery_tasks.extract_component_figure_task.apply_async",
        side_effect=AssertionError,
    ):
        again = _figure("viz-1")
    assert again.status == "ready" and again.figure == figure


def test_failed_job_reports_error(patched_env):
    """A sentence of ours: the exception's text is the worker's."""
    with patch("depictio.api.v1.celery_tasks.extract_component_figure_task"):
        job_id = _figure("viz-1").job_id
    failed = SimpleNamespace(state="FAILURE", result=RuntimeError("/srv/chromium died"))
    with patch("celery.result.AsyncResult", lambda job_id, app=None: failed):
        got = emb.component_figure_job(job_id, current_user=READER)  # type: ignore[arg-type]
    assert got.status == "error" and "/srv" not in (got.reason or "")


def test_a_job_is_only_its_requester_s(patched_env):
    with patch("depictio.api.v1.celery_tasks.extract_component_figure_task"):
        job_id = _figure("viz-1").job_id
    for user, job in ((_Other(), job_id), (READER, "never-queued")):
        with pytest.raises(HTTPException) as exc:
            emb.component_figure_job(job, current_user=user)  # type: ignore[arg-type]
        assert exc.value.status_code == 404


def test_extractions_are_limited_per_user(patched_env):
    with (
        patch("depictio.api.v1.celery_tasks.extract_component_figure_task"),
        patch.object(emb.settings.notebook_export, "extract_max_active_per_user", 2),
    ):
        _figure("viz-1")
        _figure("rec-1")
        with pytest.raises(HTTPException) as exc:
            _figure("fig-1")
        assert exc.value.status_code == 429
        # Someone else is not held up by this reader.
        assert _figure("fig-1", user=_Other()).status == "pending"


def test_a_pinned_state_never_takes_the_server_builder(patched_env):
    """The builders read current data; under pins the renderer draws the tile."""
    state = AnalysisState.model_validate(
        {**_state().model_dump(mode="json"), "pins": {"as_of_version": "v1"}}
    )

    async def build(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("server builder used for a pinned tile")

    with (
        patch("depictio.api.v1.services.export.plotly_export.build_plotly_export", build),
        patch("depictio.api.v1.celery_tasks.extract_component_figure_task"),
    ):
        resp = emb.component_figure(
            dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
            component_id="viz-1",
            request=ComponentEmbedRequest(state=state, theme="light"),
            current_user=READER,  # type: ignore[arg-type]
            access_token=None,
        )
    assert resp.status == "pending"


def test_unknown_component_and_permission(patched_env):
    with pytest.raises(HTTPException) as exc:
        _figure("nope")
    assert exc.value.status_code == 404
    with patch(
        "depictio.api.v1.endpoints.dashboards_endpoints.routes.check_project_permission",
        lambda *a, **k: False,
    ):
        with pytest.raises(HTTPException) as exc:
            _figure("fig-1")
    assert exc.value.status_code == 403


def test_embed_html_frames_the_viewer_route(patched_env):
    resp = emb.component_embed(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        component_id="fig-1",
        request=ComponentEmbedRequest(state=_state(), theme="light"),
        current_user=READER,  # type: ignore[arg-type]
    )
    doc = resp.body.decode()
    assert resp.media_type.startswith("text/html")
    assert f"/embed/{DASHBOARD_ID}/fig-1?no-walkthrough=1#state=" in doc
    assert "&amp;theme=light" in doc and "<title>Bill shape</title>" in doc


def test_feature_flag_off(patched_env):
    with patch.object(emb.settings.notebook_export, "enabled", False):
        with pytest.raises(HTTPException) as exc:
            _figure("fig-1")
    assert exc.value.status_code == 404


# --- extraction helpers (pure) ------------------------------------------------


def test_state_encoding_round_trips_through_the_page_decoder():
    state = {"filters": [{"index": "é", "value": [1, 2]}], "context": {"dashboard_id": "d"}}
    encoded = encode_state(state)
    assert "=" not in encoded and "+" not in encoded and "/" not in encoded
    import base64

    padded = encoded + "=" * (-len(encoded) % 4)
    assert json.loads(base64.urlsafe_b64decode(padded)) == state
    url = embed_url("https://viewer.test/", "d1", "c 1", state, "dark")
    assert url.startswith("https://viewer.test/embed/d1/c%201?no-walkthrough=1#state=")
    assert url.endswith("&theme=dark")


def test_parse_extracted_normalises_figures():
    raw = json.dumps(
        {
            "status": "ready",
            "figure": {
                "data": [{"type": "bar", "x": ["a"], "y": [1.5]}],
                "layout": {"title": {"text": "t"}},
            },
        }
    )
    out = parse_extracted(raw)
    assert out["status"] == "ready" and out["source"] == "extracted"
    assert out["figure"]["data"][0]["type"] == "bar"
    assert (
        parse_extracted(json.dumps({"status": "unsupported", "figure": None}))["status"]
        == "unsupported"
    )
    assert parse_extracted(json.dumps({"status": "error", "figure": None}))["status"] == "error"


def test_parse_extracted_survives_8digit_hex_alpha_without_losing_the_trace_type():
    # A trace read straight off a live Sankey graph div (SankeyRenderer.tsx
    # colours each link via hexWithAlpha, an 8-digit #RRGGBBAA) used to blow
    # up go.Figure()'s validation; the except handler then returned the SAME
    # dict go.Figure() had already started mutating — it pops a trace's
    # ``type`` off before validating the rest, so the fallback figure came
    # back with no ``type`` at all (real bug: rendered as a blank scatter).
    raw = json.dumps(
        {
            "status": "ready",
            "figure": {
                "data": [
                    {
                        "type": "sankey",
                        "node": {"label": ["a", "b"], "color": ["#339af0", "#51cf66"]},
                        "link": {
                            "source": [0],
                            "target": [1],
                            "value": [1],
                            "color": ["#339af033"],
                        },
                    }
                ],
                "layout": {},
            },
        }
    )
    out = parse_extracted(raw)
    assert out["status"] == "ready"
    trace = out["figure"]["data"][0]
    assert trace["type"] == "sankey"
    assert trace["link"]["color"] == ["rgba(51, 154, 240, 0.200)"]
    assert trace["node"]["color"] == ["#339af0", "#51cf66"]  # a plain 6-digit hex is untouched


class _FakeTile:
    async def screenshot(self, **kwargs):
        return b"\x89PNG-tile"


class _FakePage:
    """The embed page as the extraction sees it: a status, maybe a Plotly div."""

    def __init__(self, status: str, figure: dict | None, settles: bool = True):
        self.status, self.figure, self.settles = status, figure, settles
        self.locator = lambda selector: SimpleNamespace(first=_FakeTile())

    async def goto(self, *a, **k):
        return None

    async def wait_for_function(self, js, arg=None, timeout=None):
        if not self.settles:
            raise TimeoutError("not settled")

    async def wait_for_load_state(self, *a, **k):
        return None

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, js):
        from depictio.api.v1.services.embed import extract

        if js == extract._STATUS_JS:
            return self.status
        return json.dumps(
            {"status": "ready" if self.figure else "unsupported", "figure": self.figure}
        )


def _run_extract(page: _FakePage, expect: str):
    import asyncio

    from depictio.api.v1.services.embed import extract

    class _Ctx:
        async def new_page(self):
            return page

    class _Browser:
        async def new_context(self, **k):
            return _Ctx()

        async def close(self):
            return None

    class _PW:
        chromium = SimpleNamespace(launch=None)

        async def __aenter__(self):
            async def launch(**k):
                return _Browser()

            self.chromium = SimpleNamespace(launch=launch)
            return self

        async def __aexit__(self, *a):
            return None

    async def _noop(*a, **k):
        return {}

    with (
        patch("playwright.async_api.async_playwright", lambda: _PW()),
        patch("depictio.api.v1.services.screenshot_helpers.apply_init_script", _noop),
    ):
        return asyncio.run(
            extract.extract_component_figure(
                DASHBOARD_ID, "c", {}, timeout_s=1, expect=expect, token_payload={}
            )
        )


def test_extraction_snapshots_a_renderer_that_is_not_plotly():
    out = _run_extract(_FakePage("ready", None), "image")
    assert out["status"] == "ready" and out["source"] == "snapshot"
    assert out["image"].startswith("data:image/png;base64,")


def test_extraction_reads_the_plotly_figure_when_there_is_one():
    fig = {"data": [{"type": "scatter", "x": [1], "y": [2]}], "layout": {}}
    out = _run_extract(_FakePage("ready", fig), "plotly")
    assert out["status"] == "ready" and out["figure"]["data"][0]["type"] == "scatter"


def test_a_drawn_tile_without_a_plotly_div_still_gets_its_snapshot():
    """Expected Plotly, but the renderer drew something else: a picture, not an error."""
    out = _run_extract(_FakePage("ready", None, settles=False), "plotly")
    assert out["source"] == "snapshot"


def test_a_tile_that_never_draws_is_an_error_with_the_timeout():
    out = _run_extract(_FakePage("loading", None, settles=False), "plotly")
    assert out["status"] == "error" and "did not render" in out["reason"]


def test_a_kind_with_a_server_builder_skips_the_browser(patched_env):
    """volcano has a Python builder: the figure comes from it, no extraction job."""
    spec = {"data": [{"type": "scattergl", "x": [1], "y": [2]}], "layout": {"title": "v"}}

    async def build(**kwargs):
        assert kwargs["component"]["viz_kind"] == "volcano"
        assert kwargs["filters"][0]["value"] == ["a"]
        return {**spec, "config": {}, "meta": {}}

    with (
        patch("depictio.api.v1.services.export.plotly_export.build_plotly_export", build),
        patch("depictio.api.v1.celery_tasks.extract_component_figure_task") as task,
    ):
        resp = _figure("viz-1")
    assert resp.status == "ready" and resp.source == "server"
    assert resp.figure == spec
    task.apply_async.assert_not_called()


def test_a_tile_coloured_by_groups_goes_to_the_renderer(patched_env):
    """The builders take no colour-by; the embed page applies it."""
    state = AnalysisState.model_validate(
        {**_state().model_dump(mode="json"), "color_by": {"kind": "groups"}}
    )

    async def build(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("server builder used for a grouped tile")

    with (
        patch("depictio.api.v1.services.export.plotly_export.build_plotly_export", build),
        patch("depictio.api.v1.celery_tasks.extract_component_figure_task"),
    ):
        resp = emb.component_figure(
            dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
            component_id="viz-1",
            request=ComponentEmbedRequest(state=state, theme="light"),
            current_user=READER,  # type: ignore[arg-type]
            access_token=None,
        )
    assert resp.status == "pending"


def test_export_tasks_have_their_own_queues():
    from depictio.api.celery_app import celery_app
    from depictio.api.v1.configs.config import settings

    routes = celery_app.conf.task_routes
    assert routes["depictio.embed.extract_figure"]["queue"] == settings.celery.export_queue
    assert routes["render_notebook_report"]["queue"] == settings.celery.report_queue
    assert settings.celery.export_queue != "celery" != settings.celery.report_queue


def test_the_local_worker_consumes_the_export_queues():
    from depictio.api.v1.configs.config import settings
    from depictio.cli.cli.local_stack import LOCAL_WORKER_QUEUES

    assert {"celery", settings.celery.export_queue, settings.celery.report_queue} <= set(
        LOCAL_WORKER_QUEUES
    )
