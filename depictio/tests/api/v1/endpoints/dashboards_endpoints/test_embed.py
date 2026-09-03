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
            ],
        }
    )
    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    emb._results.clear()
    emb._jobs.clear()
    with (
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


def _figure(component):
    return emb.component_figure(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        component_id=component,
        request=ComponentEmbedRequest(state=_state(), theme="dark"),
        current_user=object(),
        access_token=None,
    )


def test_non_plotly_component_is_unsupported(patched_env):
    resp = _figure("tbl-1")
    assert resp.status == "unsupported" and "table" in (resp.reason or "")


def test_dispatch_then_poll_then_cache(patched_env):
    sent = {}

    def fake_delay(payload):
        sent.update(payload)
        return SimpleNamespace(id="job-1")

    with patch("depictio.api.v1.celery_tasks.extract_component_figure_task.delay", fake_delay):
        first = _figure("viz-1")
    assert first.status == "pending" and first.job_id == "job-1"
    assert sent["dashboard_id"] == DASHBOARD_ID and sent["component_id"] == "viz-1"
    assert sent["theme"] == "dark" and sent["state"]["filters"][0]["value"] == ["a"]

    figure = {"data": [{"type": "scatter", "x": [1], "y": [2]}], "layout": {}}
    pending = SimpleNamespace(state="STARTED", result=None)
    done = SimpleNamespace(
        state="SUCCESS", result={"status": "ready", "figure": figure, "source": "extracted"}
    )
    with patch("celery.result.AsyncResult", lambda job_id, app=None: pending):
        assert emb.component_figure_job("job-1", current_user=object()).status == "pending"
    with patch("celery.result.AsyncResult", lambda job_id, app=None: done):
        got = emb.component_figure_job("job-1", current_user=object())
    assert got.status == "ready" and got.figure == figure and got.source == "extracted"
    # The same request now hits the cache and dispatches nothing.
    with patch(
        "depictio.api.v1.celery_tasks.extract_component_figure_task.delay",
        side_effect=AssertionError,
    ):
        again = _figure("viz-1")
    assert again.status == "ready" and again.figure == figure


def test_failed_job_reports_error(patched_env):
    failed = SimpleNamespace(state="FAILURE", result=RuntimeError("chromium died"))
    with patch("celery.result.AsyncResult", lambda job_id, app=None: failed):
        got = emb.component_figure_job("job-x", current_user=object())
    assert got.status == "error" and "chromium" in (got.reason or "")


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
        current_user=object(),
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
