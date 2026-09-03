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
    DashboardDataContext,
    DataContext,
    FilterSummary,
    JoinSummary,
)
from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
from depictio.api.v1.endpoints.ai_endpoints.sandbox import InlineSandbox
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
    # `init_data_for_dc` resolves the delta location from Mongo and is passed
    # as an *argument* to the loader, so it runs even when the loader itself
    # is faked. Without this the suite needs a live Mongo.
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.context.init_data_for_dc",
        lambda dc_id: {str(dc_id): {"delta_location": "s3://fake", "dc_type": "table"}},
    )
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.filter_resolver.init_data_for_dc",
        lambda dc_id: {str(dc_id): {"delta_location": "s3://fake", "dc_type": "table"}},
    )
    # Run analyze code in-process: spawning a real child would need a live
    # delta table. `test_sandbox.py` covers the process itself.
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes._sandbox_factory",
        lambda specs: InlineSandbox(
            frames={specs[0].tag: pl.DataFrame({"depth": list(range(1, 101))})},
            default_tag=specs[0].tag,
        ),
    )
    # Keep report persistence out of Mongo; the saved snapshots stay
    # inspectable for assertions.
    saved_reports: list = []
    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.analyses.save",
        lambda r: saved_reports.append(r.model_copy(deep=True)),
    )
    return SimpleNamespace(saved_reports=saved_reports)


def _fake_usage_completion(monkeypatch, payloads):
    """Patch completion_with_usage with a queue of envelope payloads."""
    queue = iter(payloads)

    def fake(messages, **kw):
        return llm_client.Completion(
            content=json.dumps(next(queue)),
            usage=llm_client.CompletionUsage(100, 50, 150),
            cached=False,
        )

    monkeypatch.setattr(llm_client, "completion_with_usage", fake)


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


class TestAnalyzeMode:
    """`mode` is exclusive: read-only means no actions reach the client."""

    def _run(self, client, mode, monkeypatch, payload):
        # The mutate loop uses `completion`; the read-only loop uses
        # `completion_with_usage`. Patch both so the dispatch is opaque here.
        monkeypatch.setattr(llm_client, "completion", lambda m, **kw: json.dumps(payload))
        _fake_usage_completion(monkeypatch, [payload] * 3)
        body = {"dashboard_id": DASH_ID, "prompt": "what is going on"}
        if mode is not None:
            body["mode"] = mode
        r = client.post("/ai/analyze", json=body)
        assert r.status_code == 200
        return _parse_sse(r.text)

    def test_analyze_mode_discards_actions(self, client, patch_contexts, monkeypatch):
        # The model ignores its instructions and proposes a filter anyway.
        events = self._run(
            client,
            "analyze",
            monkeypatch,
            {
                "mode": "analyze",
                "thought": "done",
                "code": "",
                "answer": "Median depth is 50.",
                "actions": {
                    "filter_proposals": [
                        {"kind": "filter_expr", "filter_expr": "col('depth') >= 50"}
                    ]
                },
            },
        )
        types = [t for t, _ in events]
        assert "actions" not in types, types
        result = next(d for t, d in events if t == "result")
        assert result["mode"] == "analyze"
        assert result["actions"]["filter_proposals"] == []
        assert result["resolved_filters"] == []
        # Discarding is recorded rather than silent.
        assert any("read-only" in w for w in result["warnings"])
        assert types[-1] == "done"

    def test_mutate_mode_is_the_default_and_still_applies(
        self, client, patch_contexts, monkeypatch
    ):
        events = self._run(
            client,
            None,
            monkeypatch,
            {
                "thought": "done",
                "code": "",
                "answer": "Filtering.",
                "actions": {
                    "filter_proposals": [
                        {"kind": "filter_expr", "filter_expr": "col('depth') >= 50"}
                    ]
                },
            },
        )
        types = [t for t, _ in events]
        assert "actions" in types
        result = next(d for t, d in events if t == "result")
        assert result["mode"] == "mutate"
        assert result["resolved_filters"][0]["filter_expr"] == "col('depth') >= 50"

    def test_malformed_actions_are_surfaced_not_swallowed(
        self, client, patch_contexts, monkeypatch
    ):
        events = self._run(
            client,
            "mutate",
            monkeypatch,
            {
                "thought": "done",
                "code": "",
                "answer": "Filtering.",
                "actions": {"filter_proposals": [{"kind": "not-a-kind"}]},
            },
        )
        result = next(d for t, d in events if t == "result")
        assert result["actions"]["filter_proposals"] == []
        assert any("malformed" in w for w in result["warnings"])

    def test_resolve_failure_still_terminates_the_stream(self, client, patch_contexts, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("resolver exploded")

        monkeypatch.setattr("depictio.api.v1.endpoints.ai_endpoints.routes.resolve_proposals", boom)
        events = self._run(
            client,
            "mutate",
            monkeypatch,
            {
                "thought": "done",
                "code": "",
                "answer": "Filtering.",
                "actions": {
                    "filter_proposals": [
                        {"kind": "filter_expr", "filter_expr": "col('depth') >= 50"}
                    ]
                },
            },
        )
        types = [t for t, _ in events]
        assert types[-1] == "done", types
        result = next(d for t, d in events if t == "result")
        assert any("resolver exploded" in w for w in result["warnings"])


class TestMultiDCAnalyze:
    """Read-only analysis sees every DC the dashboard uses, and the
    sandbox is fed exactly what the prompt advertises."""

    def test_cross_dc_join_end_to_end(self, client, patch_contexts, monkeypatch):
        meta_ctx = DataContext(
            data_collection_id="8" * 24,
            workflow_id=WF_ID,
            project_name="P",
            project_description=None,
            dc_name="meta",
            dc_description=None,
            columns=[ColumnSummary(name="sample", dtype="String", null_pct=0.0, nunique=2)],
            sample_rows=[],
            row_count=2,
            workflow_tag="wf",
            data_collection_tag="meta",
        )
        obs_ctx = DataContext(
            data_collection_id=DC_ID,
            workflow_id=WF_ID,
            project_name="P",
            project_description=None,
            dc_name="obs",
            dc_description=None,
            columns=[ColumnSummary(name="sample", dtype="String", null_pct=0.0, nunique=4)],
            sample_rows=[],
            row_count=4,
            workflow_tag="wf",
            data_collection_tag="obs",
        )
        multi = DashboardDataContext(
            dashboard_id=DASH_ID,
            collections=[obs_ctx, meta_ctx],
            joins=[JoinSummary(left_dc="obs", right_dc="meta", on_columns=["sample"])],
        )

        async def fake_multi(dashboard_ctx, user):
            return multi, []

        monkeypatch.setattr(
            "depictio.api.v1.endpoints.ai_endpoints.routes.build_dashboard_data_context",
            fake_multi,
        )

        captured_specs: list = []

        def factory(specs):
            captured_specs.extend(specs)
            return InlineSandbox(
                frames={
                    "obs": pl.DataFrame({"sample": ["a", "b", "c", "d"]}),
                    "meta": pl.DataFrame({"sample": ["a", "b"], "site": ["x", "y"]}),
                },
                default_tag="obs",
            )

        monkeypatch.setattr(
            "depictio.api.v1.endpoints.ai_endpoints.routes._sandbox_factory", factory
        )

        _fake_usage_completion(
            monkeypatch,
            [
                {
                    "mode": "analyze",
                    "plan": "Join observations to metadata and count matches.",
                    "thought": "join the two collections",
                    "code": "dc['obs'].join(dc['meta'], on='sample', how='inner').height",
                    "answer": "",
                },
                {
                    "mode": "analyze",
                    "thought": "done",
                    "code": "",
                    "answer": "2 samples have metadata.",
                    "findings": [
                        {
                            "claim": "2 of 4 samples have matching metadata",
                            "evidence_step_ids": [0],
                            "confidence": "high",
                        }
                    ],
                },
            ],
        )

        r = client.post(
            "/ai/analyze",
            json={
                "dashboard_id": DASH_ID,
                "prompt": "how many samples have metadata?",
                "mode": "analyze",
            },
        )
        assert r.status_code == 200
        events = _parse_sse(r.text)

        # One spec per advertised collection, filters only on the default.
        assert [s.tag for s in captured_specs] == ["obs", "meta"]
        assert captured_specs[1].filters is None

        step_events = [d for t, d in events if t == "step" and d.get("status") == "success"]
        assert step_events, [t for t, _ in events]
        assert step_events[0]["output"] == "2"
        result = next(d for t, d in events if t == "result")
        assert result["answer"] == "2 samples have metadata."
        assert result["mode"] == "analyze"

        # The report artifact: plan + budget stream, evidence-checked
        # findings, cardinalities on the executed step.
        types = [t for t, _ in events]
        assert "plan" in types and "budget" in types
        report = next(d for t, d in events if t == "report")
        assert report["status"] == "complete"
        assert report["findings"] == [
            {
                "claim": "2 of 4 samples have matching metadata",
                "evidence_step_ids": [0],
                "confidence": "high",
            }
        ]
        assert report["steps"][0]["rows_in"] == 4
        assert report["steps"][0]["rows_out"] is None  # scalar result
        assert report["budget_spent"]["steps"] == 1
        assert report["budget_spent"]["tokens"] > 0


class TestAnalysisBudget:
    """Three bounds, first one hit ends the loop — with one grace call so
    the model concludes from its evidence instead of being cut off."""

    CODE_PAYLOAD = {
        "mode": "analyze",
        "thought": "keep digging",
        "code": "df.height",
        "answer": "",
    }
    FINAL_PAYLOAD = {
        "mode": "analyze",
        "thought": "out of budget",
        "code": "",
        "answer": "Concluding from what ran.",
        "findings": [{"claim": "100 rows", "evidence_step_ids": [0], "confidence": "medium"}],
    }

    def _post(self, client):
        r = client.post(
            "/ai/analyze",
            json={"dashboard_id": DASH_ID, "prompt": "dig", "mode": "analyze"},
        )
        assert r.status_code == 200
        return _parse_sse(r.text)

    def test_step_bound_stops_the_loop(self, client, patch_contexts, monkeypatch):
        from depictio.api.v1.configs.config import settings

        monkeypatch.setattr(settings.ai, "analyze_max_steps", 2)
        # The model would code forever; the third call is the grace call.
        _fake_usage_completion(
            monkeypatch, [self.CODE_PAYLOAD, self.CODE_PAYLOAD, self.FINAL_PAYLOAD]
        )
        events = self._post(client)

        executed = [d for t, d in events if t == "step" and d.get("status") == "success"]
        assert len(executed) == 2
        report = next(d for t, d in events if t == "report")
        assert report["status"] == "complete"
        assert report["narrative_md"] == "Concluding from what ran."
        assert report["findings"][0]["claim"] == "100 rows"

    def test_token_bound_stops_the_loop(self, client, patch_contexts, monkeypatch):
        from depictio.api.v1.configs.config import settings

        # Each fake call reports 150 total tokens; cap at 100 → conclude
        # after the first executed step.
        monkeypatch.setattr(settings.ai, "analyze_max_tokens_total", 100)
        _fake_usage_completion(monkeypatch, [self.CODE_PAYLOAD, self.FINAL_PAYLOAD])
        events = self._post(client)

        executed = [d for t, d in events if t == "step" and d.get("status") == "success"]
        assert len(executed) == 1
        assert next(d for t, d in events if t == "report")["status"] == "complete"

    def test_budget_events_carry_the_countdown(self, client, patch_contexts, monkeypatch):
        _fake_usage_completion(monkeypatch, [self.CODE_PAYLOAD, self.FINAL_PAYLOAD])
        events = self._post(client)
        budgets = [d for t, d in events if t == "budget"]
        assert budgets, [t for t, _ in events]
        assert {"steps_used", "tokens_used", "seconds", "max_steps"} <= set(budgets[0])
        # Token accounting accumulates across turns.
        assert budgets[-1]["tokens_used"] >= budgets[0]["tokens_used"]

    def test_model_that_never_concludes_is_ended_with_a_warning(
        self, client, patch_contexts, monkeypatch
    ):
        from depictio.api.v1.configs.config import settings

        monkeypatch.setattr(settings.ai, "analyze_max_steps", 2)
        _fake_usage_completion(monkeypatch, [self.CODE_PAYLOAD] * 4)
        events = self._post(client)
        report = next(d for t, d in events if t == "report")
        assert report["status"] == "complete"
        assert any("budget" in w for w in report["warnings"])
        assert [t for t, _ in events][-1] == "done"


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
