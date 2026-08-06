"""Endpoint tests for /ai/resolve-filters and the /ai/analyze SSE stream.

Contexts and the LLM are monkeypatched (no Mongo, no Delta, no network).
The SSE body is parsed with a minimal event-stream reader to assert on the
event sequence the React client consumes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.ai_endpoints import llm_client
from depictio.api.v1.endpoints.ai_endpoints.context import (
    ColumnSummary,
    DashboardContext,
    DataContext,
    FilterSummary,
)
from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

FAKE_USER = SimpleNamespace(id="0" * 24, email="t@example.com", is_admin=False)
DC_ID = "6" * 24
WF_ID = "7" * 24
DASH_ID = "d1" * 12


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoint_router, prefix="/ai")
    app.dependency_overrides[get_user_or_anonymous] = lambda: FAKE_USER
    return TestClient(app)


@pytest.fixture()
def patch_contexts(monkeypatch):
    data_ctx = DataContext(
        data_collection_id=DC_ID,
        workflow_id=WF_ID,
        project_name="P",
        project_description=None,
        dc_name="dc",
        dc_description=None,
        columns=[ColumnSummary(name="depth", dtype="Int64", null_pct=0.0, nunique=100)],
        sample_rows=[{"depth": 12}],
        row_count=100,
        workflow_tag="wf",
        data_collection_tag="dc",
    )
    dashboard_ctx = DashboardContext(
        dashboard_id=DASH_ID,
        figures=[],
        filters=[
            FilterSummary(
                component_id="widget-depth",
                component_type="RangeSlider",
                column="depth",
                value=None,
            )
        ],
    )

    async def fake_dashboard(dashboard_id, user):
        return dashboard_ctx, DC_ID

    async def fake_data(dc_id, user, **kwargs):
        return data_ctx

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_dashboard_context",
        fake_dashboard,
    )
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_data_context",
        fake_data,
    )
    # Threshold resolution + analyze executor both re-load the delta table.
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.filter_resolver.load_deltatable_lite",
        lambda **kwargs: pl.DataFrame({"depth": list(range(1, 101))}),
    )


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        etype = lines[0].removeprefix("event: ").strip()
        data_line = next((ln for ln in lines[1:] if ln.startswith("data: ")), "data: {}")
        events.append((etype, json.loads(data_line.removeprefix("data: "))))
    return events


class TestResolveFilters:
    def test_hybrid_resolution(self, client, patch_contexts, monkeypatch):
        monkeypatch.setattr(
            llm_client,
            "completion",
            lambda messages, **kw: json.dumps(
                {
                    "explanation": "depth range + top 3%",
                    "proposals": [
                        {"kind": "set_widget", "component_id": "widget-depth", "value": [30, 100]},
                        {
                            "kind": "threshold",
                            "threshold": {"column": "depth", "q": 0.97, "op": ">="},
                        },
                        {"kind": "set_widget", "component_id": "ghost", "value": 1},
                    ],
                }
            ),
        )
        r = client.post(
            "/ai/resolve-filters",
            json={"dashboard_id": DASH_ID, "prompt": "top 3% depth", "filters": []},
        )
        assert r.status_code == 200
        payload = r.json()
        kinds = [a["kind"] for a in payload["applied"]]
        assert kinds == ["set_widget", "filter_expr"]
        assert payload["applied"][1]["filter_expr"] == "col('depth') >= 97.0"
        assert len(payload["warnings"]) == 1  # the ghost widget
        assert payload["explanation"] == "depth range + top 3%"

    def test_invalid_llm_json_is_502(self, client, patch_contexts, monkeypatch):
        monkeypatch.setattr(llm_client, "completion", lambda m, **kw: "nope")
        r = client.post(
            "/ai/resolve-filters",
            json={"dashboard_id": DASH_ID, "prompt": "x"},
        )
        assert r.status_code == 502


class TestAnalyzeStream:
    def test_two_round_react_loop(self, client, patch_contexts, monkeypatch):
        responses = iter(
            [
                json.dumps(
                    {
                        "thought": "compute median depth",
                        "code": "df.select(pl.col('depth').median())",
                        "answer": "",
                        "actions": {},
                    }
                ),
                json.dumps(
                    {
                        "thought": "done",
                        "code": "",
                        "answer": "Median depth is 50.",
                        "actions": {
                            "filter_proposals": [
                                {"kind": "filter_expr", "filter_expr": "col('depth') >= 50"}
                            ]
                        },
                    }
                ),
            ]
        )
        monkeypatch.setattr(llm_client, "completion", lambda m, **kw: next(responses))
        # _load_df_for_analyze imports from deltatables_utils at call time.
        monkeypatch.setattr(
            "depictio.api.v1.deltatables_utils.load_deltatable_lite",
            lambda **kwargs: pl.DataFrame({"depth": list(range(1, 101))}),
        )

        r = client.post(
            "/ai/analyze",
            json={"dashboard_id": DASH_ID, "prompt": "median depth then filter"},
        )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        types = [t for t, _ in events]
        assert types[-1] == "done"
        assert "answer" in types and "actions" in types and "result" in types
        # The executed step is streamed with its output.
        step_events = [d for t, d in events if t == "step" and d.get("status") == "success"]
        assert step_events, f"no successful step event in {types}"
        actions = next(d for t, d in events if t == "actions")
        assert actions["resolved_filters"][0]["filter_expr"] == "col('depth') >= 50"
        answer = next(d for t, d in events if t == "answer")
        assert answer["answer"] == "Median depth is 50."

    def test_llm_error_streams_error_event(self, client, patch_contexts, monkeypatch):
        def boom(messages, **kw):
            raise RuntimeError("provider down")

        monkeypatch.setattr(llm_client, "completion", boom)
        r = client.post(
            "/ai/analyze",
            json={"dashboard_id": DASH_ID, "prompt": "x"},
        )
        assert r.status_code == 200  # stream starts before the failure
        events = _parse_sse(r.text)
        types = [t for t, _ in events]
        assert "error" in types
        assert types[-1] == "done"
