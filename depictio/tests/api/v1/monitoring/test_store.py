"""Tests for the monitoring ledger's ingestion-run step writers.

``set_ingestion_step`` is the concurrent-safe writer (one positional update,
no read-modify-write) used when several workers report on different steps of
the same run. Its contract is narrower than ``upsert_ingestion_step``: the
step must have been seeded at run creation, so an unknown name is refused
rather than appended. Backed by mongomock, no live database.

mongomock 4.3 applies a positional ``steps.$`` assignment but drops the plain
sibling field set in the same ``$set`` (``current_step``); MongoDB applies
both. ``current_step`` is therefore only asserted where nothing should have
changed.
"""

import mongomock
import pytest

from depictio.api.v1.monitoring import store
from depictio.models.models.monitoring import IngestionRun, IngestionStep


@pytest.fixture()
def runs(monkeypatch):
    collection = mongomock.MongoClient()["depictio_test"]["ingestion_runs"]
    monkeypatch.setattr(store, "ingestion_runs_collection", collection)
    return collection


def _seed_run(run_id: str = "run-1", steps: tuple[str, ...] = ("counts", "annotations")) -> None:
    store.create_ingestion_run(
        IngestionRun(
            run_id=run_id,
            steps=[IngestionStep(name=name, status="pending") for name in steps],
        )
    )


def _steps(runs, run_id: str = "run-1") -> dict[str, dict]:
    doc = runs.find_one({"run_id": run_id})
    return {step["name"]: step for step in doc["steps"]}


def test_set_ingestion_step_replaces_only_the_named_step(runs):
    _seed_run()

    assert (
        store.set_ingestion_step(
            "run-1",
            step={"name": "counts", "status": "success", "detail": "3 entries"},
            current_step="annotations",
        )
        is True
    )

    steps = _steps(runs)
    assert steps["counts"] == {"name": "counts", "status": "success", "detail": "3 entries"}
    # The sibling step is untouched, and the order of the seeded list is kept.
    assert steps["annotations"]["status"] == "pending"
    assert [s["name"] for s in runs.find_one({"run_id": "run-1"})["steps"]] == [
        "counts",
        "annotations",
    ]


def test_set_ingestion_step_is_a_single_positional_update(runs):
    """No read-modify-write: one update_one with a positional filter, which is
    what lets concurrent workers report on different steps of one run."""
    _seed_run()
    calls: list[tuple[dict, dict]] = []
    original = runs.update_one

    def _spy(filter_doc, update_doc, **kwargs):
        calls.append((filter_doc, update_doc))
        return original(filter_doc, update_doc, **kwargs)

    runs.update_one = _spy  # type: ignore[method-assign]

    store.set_ingestion_step(
        "run-1", step={"name": "counts", "status": "success"}, current_step="annotations"
    )

    assert calls == [
        (
            {"run_id": "run-1", "steps.name": "counts"},
            {
                "$set": {
                    "steps.$": {"name": "counts", "status": "success"},
                    "current_step": "annotations",
                }
            },
        )
    ]


def test_set_ingestion_step_unknown_step_returns_false_and_never_appends(runs):
    _seed_run()

    assert (
        store.set_ingestion_step(
            "run-1", step={"name": "ghost", "status": "success"}, current_step="ghost"
        )
        is False
    )

    doc = runs.find_one({"run_id": "run-1"})
    assert [s["name"] for s in doc["steps"]] == ["counts", "annotations"]
    assert all(s["status"] == "pending" for s in doc["steps"])
    # A refused write changes nothing else on the run either.
    assert doc["current_step"] is None


def test_set_ingestion_step_unknown_run_returns_false_without_creating_it(runs):
    _seed_run()

    assert store.set_ingestion_step("nope", step={"name": "counts", "status": "success"}) is False

    assert runs.count_documents({}) == 1
    assert _steps(runs)["counts"]["status"] == "pending"


def test_upsert_ingestion_step_appends_what_set_refuses(runs):
    """The read-modify-write sibling is the one that grows the step list; the
    contrast pins down which writer a caller needs."""
    _seed_run()

    assert store.upsert_ingestion_step("run-1", step={"name": "ghost", "status": "running"}) is True
    assert store.upsert_ingestion_step("run-1", step={"name": "ghost", "status": "success"}) is True

    steps = _steps(runs)
    assert list(steps) == ["counts", "annotations", "ghost"]
    assert steps["ghost"]["status"] == "success"  # replaced in place, not duplicated
