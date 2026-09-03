"""GenerationRun persistence: upsert by id, newest-first listing, json-mode dumps.

Mirrors test_analyses.py: the collection is a mongomock stand-in patched
through the lazy `_collection()` resolver, so nothing here touches
`depictio.api.v1.db`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import mongomock
import pytest

from depictio.api.v1.endpoints.ai_endpoints import generations
from depictio.api.v1.endpoints.ai_endpoints.schemas import BudgetSpent


@pytest.fixture()
def collection(monkeypatch):
    coll = mongomock.MongoClient().db.ai_generations
    monkeypatch.setattr(generations, "_collection", lambda: coll)
    return coll


class TestNewRun:
    def test_starts_running_with_empty_artifacts(self):
        run = generations.new_run("proj-1", "overview of the cohort", "test-model")
        assert run.status == "running"
        assert run.project_id == "proj-1"
        assert run.prompt == "overview of the cohort"
        assert run.model == "test-model"
        assert run.dashboard_id is None
        assert run.plan is None
        assert run.components == []
        assert run.yaml == ""
        assert run.warnings == []
        assert run.budget_spent == BudgetSpent()
        assert len(run.id) == 32

    def test_created_at_is_naive_utc_iso(self):
        run = generations.new_run("p", "", "m")
        parsed = datetime.fromisoformat(run.created_at)
        assert parsed.tzinfo is None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((now - parsed).total_seconds()) < 60

    def test_ids_are_unique(self):
        ids = {generations.new_run("p", "", "m").id for _ in range(5)}
        assert len(ids) == 5


class TestPersistence:
    def test_round_trip(self, collection):
        run = generations.new_run("proj-1", "iris overview", "test-model")
        run.plan = {"title": "Iris overview", "components": [{"tag": "species_filter"}]}
        run.components.append(
            {
                "tag": "species_filter",
                "section": "Cohort",
                "component_type": "interactive",
                "status": "ok",
                "attempts": 1,
                "error": None,
            }
        )
        run.budget_spent = BudgetSpent(steps=3, tokens=1200, seconds=4.5)
        run.dashboard_id = "d" * 24
        run.yaml = "title: Iris overview\n"
        run.warnings.append("1 component dropped")
        run.status = "complete"
        generations.save(run)

        loaded = generations.get(run.id)
        assert loaded is not None
        assert loaded.project_id == "proj-1"
        assert loaded.dashboard_id == "d" * 24
        assert loaded.plan == run.plan
        assert loaded.components[0]["tag"] == "species_filter"
        assert loaded.budget_spent == BudgetSpent(steps=3, tokens=1200, seconds=4.5)
        assert loaded.yaml == "title: Iris overview\n"
        assert loaded.warnings == ["1 component dropped"]
        assert loaded.status == "complete"
        assert loaded.created_at == run.created_at

    def test_save_is_upsert_not_append(self, collection):
        run = generations.new_run("proj-1", "q", "m")
        generations.save(run)  # running
        run.status = "failed"
        generations.save(run)  # final
        assert collection.count_documents({}) == 1
        loaded = generations.get(run.id)
        assert loaded is not None and loaded.status == "failed"

    def test_saved_document_is_json_mode(self, collection):
        run = generations.new_run("proj-1", "q", "m")
        run.budget_spent = BudgetSpent(steps=1, tokens=10, seconds=0.5)
        generations.save(run)
        doc = collection.find_one({"id": run.id})
        assert doc is not None
        assert doc["budget_spent"] == {"steps": 1, "tokens": 10, "seconds": 0.5}
        assert doc["created_at"] == run.created_at
        assert doc["status"] == "running"

    def test_list_for_project_newest_first_and_scoped(self, collection):
        for i in range(3):
            run = generations.new_run("proj-1", f"q{i}", "m")
            run.created_at = f"2026-09-0{i + 1}T00:00:00"
            generations.save(run)
        generations.save(generations.new_run("other-project", "q", "m"))

        out = generations.list_for_project("proj-1")
        assert [r.prompt for r in out] == ["q2", "q1", "q0"]

    def test_list_for_project_respects_limit(self, collection):
        for i in range(4):
            run = generations.new_run("proj-1", f"q{i}", "m")
            run.created_at = f"2026-09-0{i + 1}T00:00:00"
            generations.save(run)
        assert [r.prompt for r in generations.list_for_project("proj-1", limit=2)] == ["q3", "q2"]

    def test_get_unknown_id(self, collection):
        assert generations.get("nope") is None
