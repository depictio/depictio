"""Endpoint tests for /ai/suggest-figures and /ai/component-from-prompt.

No network, no Mongo, no LLM: `build_data_context` and
`llm_client.completion` are monkeypatched; auth is overridden with a
stub user. The router is mounted on a throwaway app so the tests are
independent of the DEPICTIO_AI_ENABLED gate.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.ai_endpoints import llm_client
from depictio.api.v1.endpoints.ai_endpoints.context import ColumnSummary, DataContext
from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

FAKE_USER = SimpleNamespace(id="0" * 24, email="t@example.com", is_admin=False)


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoint_router, prefix="/ai")
    app.dependency_overrides[get_user_or_anonymous] = lambda: FAKE_USER
    return TestClient(app)


@pytest.fixture()
def data_ctx() -> DataContext:
    return DataContext(
        data_collection_id="6" * 24,
        workflow_id="7" * 24,
        project_name="Iris",
        project_description=None,
        dc_name="iris_table",
        dc_description=None,
        columns=[
            ColumnSummary(name="sepal_length", dtype="Float64", null_pct=0.0, nunique=35),
            ColumnSummary(name="variety", dtype="String", null_pct=0.0, nunique=3),
        ],
        sample_rows=[{"sepal_length": 5.1, "variety": "Setosa"}],
        row_count=150,
        workflow_tag="wf",
        data_collection_tag="dc",
    )


@pytest.fixture()
def patch_context(monkeypatch, data_ctx):
    async def fake_build_data_context(dc_id, user, **kwargs):
        return data_ctx

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_data_context",
        fake_build_data_context,
    )


def _patch_completion(monkeypatch, responses: list[str]):
    """completion() pops canned responses in order (repeats the last one)."""
    queue = list(responses)

    def fake_completion(messages, **kwargs):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(llm_client, "completion", fake_completion)


class TestSuggestFigures:
    def test_happy_path_drops_invalid_items(self, client, patch_context, monkeypatch):
        _patch_completion(
            monkeypatch,
            [
                '{"suggestions": ['
                '{"visu_type": "scatter", "dict_kwargs": {"x": "sepal_length", "y": "sepal_length"},'
                ' "title": "S", "explanation": "E"},'
                '{"visu_type": "scatter", "dict_kwargs": {}, "title": "bad", "explanation": "no kwargs"}'
                "]}"
            ],
        )
        r = client.post(
            "/ai/suggest-figures",
            json={"data_collection_id": "6" * 24, "n": 2},
        )
        assert r.status_code == 200
        suggestions = r.json()["suggestions"]
        assert len(suggestions) == 1
        # Server-side synthesized Plotly Express code for display.
        assert suggestions[0]["code"].startswith("fig = px.scatter(")

    def test_invalid_json_is_502(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, ["not json at all"])
        r = client.post(
            "/ai/suggest-figures",
            json={"data_collection_id": "6" * 24, "n": 2},
        )
        assert r.status_code == 502

    def test_all_invalid_suggestions_is_502(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, ['{"suggestions": [{"visu_type": "scatter"}]}'])
        r = client.post(
            "/ai/suggest-figures",
            json={"data_collection_id": "6" * 24, "n": 2},
        )
        assert r.status_code == 502


VALID_CARD_YAML = (
    "component_type: card\n"
    "workflow_tag: wf\n"
    "data_collection_tag: dc\n"
    "aggregation: count\n"
    "column_name: variety\n"
    "column_type: object\n"
    "title: Sample count\n"
)


class TestComponentFromPrompt:
    def test_first_try_valid(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, [VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count of samples",
                "component_type": "card",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["component_type"] == "card"
        assert payload["validation_attempts"] == 1
        assert payload["parsed"]["aggregation"] == "count"
        assert payload["explanation"] == "Sample count"

    def test_retry_then_valid(self, client, patch_context, monkeypatch):
        invalid = "component_type: card\nworkflow_tag: wf\ndata_collection_tag: dc\n"
        _patch_completion(monkeypatch, [invalid, VALID_CARD_YAML])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count of samples",
                "component_type": "card",
            },
        )
        assert r.status_code == 200
        assert r.json()["validation_attempts"] == 2

    def test_exhausted_retries_is_422(self, client, patch_context, monkeypatch):
        _patch_completion(monkeypatch, ["component_type: gizmo\n"])
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "??",
                "component_type": "card",
            },
        )
        assert r.status_code == 422

    def test_llm_error_is_502(self, client, patch_context, monkeypatch):
        def boom(messages, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(llm_client, "completion", boom)
        r = client.post(
            "/ai/component-from-prompt",
            json={
                "data_collection_id": "6" * 24,
                "prompt": "count",
                "component_type": "card",
            },
        )
        assert r.status_code == 502
