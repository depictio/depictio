"""Section summaries: trimming caps, hash stability, cache behavior.

The Mongo collection is replaced with mongomock; the LLM with a canned
response; the dashboard permission gate with a no-op.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.ai_endpoints import llm_client
from depictio.api.v1.endpoints.ai_endpoints import summaries as summaries_mod
from depictio.api.v1.endpoints.ai_endpoints.context import DashboardContext
from depictio.api.v1.endpoints.ai_endpoints.routes import ai_endpoint_router
from depictio.api.v1.endpoints.ai_endpoints.schemas import SummaryComponent
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous

FAKE_USER = SimpleNamespace(id="0" * 24, email="t@example.com", is_admin=False)
DASH_ID = "d1" * 12


class TestTrimDigest:
    def test_long_list_keeps_head_and_tail(self):
        digest = list(range(1000))
        trimmed = summaries_mod.trim_digest(digest, max_list=10, max_str=100)
        assert len(trimmed) == 11  # 10 kept + 1 marker
        assert trimmed[0] == 0
        assert trimmed[-1] == 999
        assert any(isinstance(x, str) and "trimmed" in x for x in trimmed)

    def test_long_string_is_capped(self):
        trimmed = summaries_mod.trim_digest("x" * 1000, max_str=50)
        assert len(trimmed) < 120
        assert "trimmed" in trimmed

    def test_nested_structures(self):
        digest = {"data": [{"y": list(range(500))}]}
        trimmed = summaries_mod.trim_digest(digest, max_list=10)
        assert len(trimmed["data"][0]["y"]) == 11

    def test_component_hard_cap(self):
        c = SummaryComponent(id="a", type="figure", digest={"blob": ["v" * 300] * 200})
        trimmed = summaries_mod.trim_component(c)
        assert len(json.dumps(trimmed.digest, default=str)) < summaries_mod.MAX_DIGEST_CHARS + 200


class TestContextHash:
    def _components(self):
        return [
            SummaryComponent(id="a", type="card", title="N", digest=42),
            SummaryComponent(id="b", type="figure", digest={"data": [1, 2]}),
        ]

    def test_stable_across_component_order(self):
        comps = self._components()
        h1 = summaries_mod.compute_context_hash("s", [], comps)
        h2 = summaries_mod.compute_context_hash("s", [], list(reversed(comps)))
        assert h1 == h2

    def test_stable_across_filter_order(self):
        f1 = [{"a": 1}, {"b": 2}]
        f2 = [{"b": 2}, {"a": 1}]
        comps = self._components()
        assert summaries_mod.compute_context_hash(
            None, f1, comps
        ) == summaries_mod.compute_context_hash(None, f2, comps)

    def test_changes_when_digest_changes(self):
        comps = self._components()
        h1 = summaries_mod.compute_context_hash("s", [], comps)
        comps[0] = comps[0].model_copy(update={"digest": 43})
        assert summaries_mod.compute_context_hash("s", [], comps) != h1

    def test_changes_when_section_changes(self):
        comps = self._components()
        assert summaries_mod.compute_context_hash(
            "a", [], comps
        ) != summaries_mod.compute_context_hash("b", [], comps)


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoint_router, prefix="/ai")
    app.dependency_overrides[get_user_or_anonymous] = lambda: FAKE_USER

    async def fake_dashboard(dashboard_id, user):
        return DashboardContext(dashboard_id=dashboard_id, figures=[], filters=[]), None

    monkeypatch.setattr(
        "depictio.api.v1.endpoints.ai_endpoints.routes.build_dashboard_context",
        fake_dashboard,
    )
    fake_collection = mongomock.MongoClient().db.ai_summaries
    monkeypatch.setattr(summaries_mod, "_collection", lambda: fake_collection)
    return TestClient(app)


BODY = {
    "dashboard_id": DASH_ID,
    "section": "QC",
    "filters": [],
    "components": [{"id": "a", "type": "card", "title": "Samples", "digest": 42}],
}


class TestSummarizeEndpoint:
    def test_generate_then_cache_hit(self, client, monkeypatch):
        calls = {"n": 0}

        def fake_completion(messages, **kw):
            calls["n"] += 1
            return "All 42 samples pass QC."

        monkeypatch.setattr(llm_client, "completion", fake_completion)

        r1 = client.post("/ai/summarize-section", json=BODY)
        assert r1.status_code == 200
        assert r1.json()["cached"] is False
        assert r1.json()["summary_md"] == "All 42 samples pass QC."

        r2 = client.post("/ai/summarize-section", json=BODY)
        assert r2.status_code == 200
        assert r2.json()["cached"] is True
        assert calls["n"] == 1  # second call served from cache

        # Same context ⇒ same hash, so the client can match it.
        assert r1.json()["context_hash"] == r2.json()["context_hash"]

    def test_force_regenerates(self, client, monkeypatch):
        calls = {"n": 0}

        def fake_completion(messages, **kw):
            calls["n"] += 1
            return f"summary v{calls['n']}"

        monkeypatch.setattr(llm_client, "completion", fake_completion)
        client.post("/ai/summarize-section", json=BODY)
        r = client.post("/ai/summarize-section", json={**BODY, "force": True})
        assert r.json()["summary_md"] == "summary v2"
        assert calls["n"] == 2

    def test_changed_digest_regenerates(self, client, monkeypatch):
        monkeypatch.setattr(llm_client, "completion", lambda m, **kw: "s")
        r1 = client.post("/ai/summarize-section", json=BODY)
        changed = {
            **BODY,
            "components": [{"id": "a", "type": "card", "title": "Samples", "digest": 43}],
        }
        r2 = client.post("/ai/summarize-section", json=changed)
        assert r1.json()["context_hash"] != r2.json()["context_hash"]
        assert r2.json()["cached"] is False

    def test_empty_components_is_422(self, client, monkeypatch):
        monkeypatch.setattr(llm_client, "completion", lambda m, **kw: "s")
        r = client.post("/ai/summarize-section", json={**BODY, "components": []})
        assert r.status_code == 422

    def test_get_summaries_lists_latest_per_section(self, client, monkeypatch):
        monkeypatch.setattr(llm_client, "completion", lambda m, **kw: "s1")
        client.post("/ai/summarize-section", json=BODY)
        client.post("/ai/summarize-section", json={**BODY, "section": "Coverage"})
        # Regenerate QC with new data — replaces, not appends.
        client.post(
            "/ai/summarize-section",
            json={
                **BODY,
                "components": [{"id": "a", "type": "card", "title": "Samples", "digest": 99}],
            },
        )

        r = client.get(f"/ai/summaries/{DASH_ID}")
        assert r.status_code == 200
        entries = r.json()["summaries"]
        assert sorted(e["section"] for e in entries) == ["Coverage", "QC"]
