"""``/ai/agent-runs*`` and ``/ai/agent-profiles``: flags, SSE sequence, ownership, cancel."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1 import db
from depictio.api.v1.agents.router import RouteContext
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints import agent_runs_routes as routes
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.tests.api.v1.agents._fakes import FakeLLM, FakeToolbox, default_tools
from depictio.tests.api.v1.agents.test_team import team_script

AI = "/depictio/api/v1/ai"


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def world():
    me = SimpleNamespace(id=ObjectId())
    state = SimpleNamespace(user=me, llm=None, toolbox=FakeToolbox(tools=default_tools()))
    coll = mongomock.MongoClient()["depictio_test"]["ai_agent_runs"]

    app = FastAPI()
    app.include_router(routes.agent_runs_router, prefix=AI)
    app.dependency_overrides[get_current_user] = lambda: state.user
    app.dependency_overrides[routes.get_llm_factory] = lambda: lambda key: state.llm
    app.dependency_overrides[routes.get_toolbox] = lambda: state.toolbox
    app.dependency_overrides[routes.get_route_context_builder] = lambda: (
        lambda user, dashboard_id: RouteContext(
            dashboard_id=dashboard_id,
            columns={"bill_length_mm", "species"},
            component_indexes={"c1", "c2"},
        )
    )
    with (
        patch.object(db, "ai_agent_runs_collection", coll),
        patch.object(settings.ai, "enabled", True),
        patch.object(settings.ai, "agents_enabled", True),
    ):
        state.client = TestClient(app)
        state.app = app
        state.coll = coll
        yield state


def test_flag_off_is_404(world):
    with patch.object(settings.ai, "agents_enabled", False):
        assert world.client.get(f"{AI}/agent-profiles").status_code == 404
        assert world.client.get(f"{AI}/agent-runs").status_code == 404
        body = {"dashboard_id": "d1", "question": "q"}
        assert world.client.post(f"{AI}/agent-runs", json=body).status_code == 404
        assert world.client.post(f"{AI}/agent-runs/route", json=body).status_code == 404
        assert world.client.post(f"{AI}/agent-runs/x/cancel").status_code == 404


def test_profiles_listing(world):
    listed = world.client.get(f"{AI}/agent-profiles").json()
    by_id = {(p["id"], p["kind"]): p for p in listed}
    assert ("analyst", "role") in by_id and ("microbiome", "topic") in by_id
    assert set(by_id[("microbiome", "topic")]) == {
        "id",
        "kind",
        "name",
        "version",
        "description",
        "applies_to_summary",
    }


def test_route_dry_run(world):
    body = {"dashboard_id": "d1", "question": "Which species differ?"}
    out = world.client.post(f"{AI}/agent-runs/route", json=body).json()
    assert out["routing"]["method"] == "rules"
    assert out["team"][0] == {
        "agent_id": "analyst/general@1",
        "role": "analyst",
        "topic": "general",
        "reason": "no specialist topic matched this dashboard's structure",
    }
    bad = world.client.post(f"{AI}/agent-runs/route", json={**body, "team": ["nope/x"]})
    assert bad.status_code == 422
    dup = ["analyst/general", "skeptic/general", "skeptic/variants"]
    bad = world.client.post(f"{AI}/agent-runs/route", json={**body, "team": dup})
    assert bad.status_code == 422 and "at most one skeptic" in bad.json()["detail"]


def test_route_dry_run_never_calls_the_llm(world):
    # Three topics tie for two places: the dry run breaks the tie by the rules.
    world.llm = FakeLLM([])
    builder = lambda user, dashboard_id: RouteContext(  # noqa: E731
        dashboard_id=dashboard_id, catalog_modules={"qiime2", "multiqc", "ivar"}
    )
    world.app.dependency_overrides[routes.get_route_context_builder] = lambda: builder
    body = {"dashboard_id": "d1", "question": "What stands out?"}
    out = world.client.post(f"{AI}/agent-runs/route", json=body).json()
    assert out["routing"]["method"] == "rules"
    assert [m["topic"] for m in out["team"] if m["role"] == "analyst"] == [
        "microbiome",
        "qc_multiqc",
    ]
    assert not world.llm.calls


def test_run_without_llm_key_is_refused(world):
    body = {"dashboard_id": "d1", "question": "q"}
    assert world.client.post(f"{AI}/agent-runs", json=body).status_code == 400


def test_run_streams_the_contract_events_and_is_stored(world):
    world.llm = FakeLLM(team_script())
    body = {"dashboard_id": "d1", "question": "Which species differ?", "budget_usd": 5}
    response = world.client.post(f"{AI}/agent-runs", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [e for e, _ in events]
    assert names[0] == "run_started" and names[-2:] == ["run_finished", "done"]
    for expected in (
        "agent_started",
        "tool_call",
        "tool_result",
        "finding",
        "verdict",
        "thread_created",
        "report_created",
        "budget",
        "agent_finished",
    ):
        assert expected in names, expected
    started = events[0][1]
    # The request may lower the cost ceiling, never raise it.
    assert started["budget"]["limit_usd"] == settings.ai.agents_max_cost_usd
    run_id = started["run_id"]
    assert events[-2][1]["run_id"] == run_id and events[-2][1]["status"] == "complete"

    detail = world.client.get(f"{AI}/agent-runs/{run_id}").json()
    assert detail["run_id"] == run_id and detail["status"] == "complete"
    assert {"agents", "verdicts", "threads", "budget", "outputs", "routing", "team"} <= set(detail)
    analyst = detail["agents"][0]
    assert analyst["tool_calls"][0]["tool"] == "query_data"
    assert analyst["findings"][0]["verdict"] == "confirmed"
    assert detail["outputs"]["report_id"] == "r1"

    listed = world.client.get(f"{AI}/agent-runs", params={"dashboard_id": "d1"}).json()
    assert [r["run_id"] for r in listed] == [run_id]
    assert {"run_id", "question", "status", "created_at", "finished_at"} <= set(listed[0])

    # Someone else's run does not exist for them.
    world.user = SimpleNamespace(id=ObjectId())
    assert world.client.get(f"{AI}/agent-runs/{run_id}").status_code == 404
    assert world.client.get(f"{AI}/agent-runs").json() == []


def test_cancel_flags_a_running_run(world):
    world.coll.insert_one(
        {
            "id": "r-live",
            "user_id": str(world.user.id),
            "status": "running",
            "cancel_requested": False,
        }
    )
    # Minimal stored run: the route reads it through the model.
    world.coll.update_one(
        {"id": "r-live"},
        {
            "$set": {
                "dashboard_id": "d1",
                "question": "q",
                "model": "m",
                "budget": {"limit_usd": 1, "max_tool_calls": 10, "max_tokens": 1000},
            }
        },
    )
    # No process here runs it (a leftover of a restart): marked cancelled at once.
    out = world.client.post(f"{AI}/agent-runs/r-live/cancel").json()
    assert out == {"run_id": "r-live", "cancelled": True, "status": "cancelled"}
    stored = world.coll.find_one({"id": "r-live"})
    assert stored["cancel_requested"] is True and stored["status"] == "cancelled"
    # A run no longer running is not reported cancelled again.
    again = world.client.post(f"{AI}/agent-runs/r-live/cancel").json()
    assert again["cancelled"] is False
    assert world.client.post(f"{AI}/agent-runs/unknown/cancel").status_code == 404


def test_startup_sweep_fails_runs_left_running(world):
    from depictio.api.v1.agents import runs

    world.coll.insert_many(
        [
            {"id": "orphan", "status": "running", "warnings": []},
            {"id": "done", "status": "complete", "warnings": []},
        ]
    )
    assert runs.sweep_orphans() == 1
    orphan = world.coll.find_one({"id": "orphan"})
    assert orphan["status"] == "failed" and orphan["finished_at"]
    assert orphan["warnings"] == [runs.ORPHAN_WARNING]
    assert world.coll.find_one({"id": "done"})["status"] == "complete"
