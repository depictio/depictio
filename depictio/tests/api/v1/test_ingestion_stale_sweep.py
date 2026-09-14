"""Stale ``running`` ingestion runs are swept to ``abandoned`` on the admin read path.

A CLI that is killed (SIGKILL, lost node, lost network) never closes its record,
so without the sweep the admin Ingestion pane shows it "running" forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import mongomock
import pytest

from depictio.api.v1.monitoring import store
from depictio.models.models.monitoring import IngestionRun

NOW = datetime(2026, 9, 14, 12, 0, 0)


@pytest.fixture
def runs():
    collection = mongomock.MongoClient().db.ingestion_runs
    with (
        patch.object(store, "ingestion_runs_collection", collection),
        patch.object(store, "settings") as settings,
    ):
        settings.monitoring.ingestion_stale_after_hours = 24
        yield collection


def _insert(collection, run_id, *, started_hours_ago, updated_hours_ago=None, status="running"):
    doc = {
        "run_id": run_id,
        "status": status,
        "current_step": "scan",
        "error": None,
        "finished_at": None,
        "started_at": NOW - timedelta(hours=started_hours_ago),
    }
    if updated_hours_ago is not None:
        doc["updated_at"] = NOW - timedelta(hours=updated_hours_ago)
    collection.insert_one(doc)


def _doc(collection, run_id):
    return collection.find_one({"run_id": run_id}, {"_id": 0})


class TestMarkStaleIngestionRuns:
    def test_a_run_silent_past_the_threshold_is_abandoned(self, runs):
        _insert(runs, "stale", started_hours_ago=30, updated_hours_ago=25)

        assert store.mark_stale_ingestion_runs(now=NOW) == 1

        doc = _doc(runs, "stale")
        assert doc["status"] == "abandoned"
        assert doc["current_step"] is None
        assert "24 h" in doc["error"]
        # Nobody knows when the process died, so no finish time is invented.
        assert doc["finished_at"] is None

    def test_a_long_run_with_a_recent_write_stays_running(self, runs):
        _insert(runs, "long", started_hours_ago=30, updated_hours_ago=1)

        assert store.mark_stale_ingestion_runs(now=NOW) == 0
        assert _doc(runs, "long")["status"] == "running"

    def test_records_from_before_updated_at_fall_back_to_started_at(self, runs):
        _insert(runs, "legacy-stale", started_hours_ago=30)
        _insert(runs, "legacy-fresh", started_hours_ago=2)

        assert store.mark_stale_ingestion_runs(now=NOW) == 1
        assert _doc(runs, "legacy-stale")["status"] == "abandoned"
        assert _doc(runs, "legacy-fresh")["status"] == "running"

    @pytest.mark.parametrize("status", ["success", "partial", "failed", "interrupted"])
    def test_closed_runs_are_never_touched(self, runs, status):
        _insert(runs, "done", started_hours_ago=100, updated_hours_ago=99, status=status)

        assert store.mark_stale_ingestion_runs(now=NOW) == 0
        assert _doc(runs, "done")["status"] == status

    def test_a_zero_threshold_disables_the_sweep(self, runs):
        store.settings.monitoring.ingestion_stale_after_hours = 0
        _insert(runs, "stale", started_hours_ago=1000)

        assert store.mark_stale_ingestion_runs(now=NOW) == 0
        assert _doc(runs, "stale")["status"] == "running"

    def test_a_late_finish_still_wins_over_abandoned(self, runs):
        _insert(runs, "slow", started_hours_ago=30, updated_hours_ago=25)
        store.mark_stale_ingestion_runs(now=NOW)

        assert store.finish_ingestion_run("slow", status="success", error=None)
        doc = _doc(runs, "slow")
        assert doc["status"] == "success"
        assert doc["finished_at"] is not None


class TestUpdatedAtStamping:
    def test_opening_a_run_stamps_updated_at(self, runs):
        store.create_ingestion_run(IngestionRun(run_id="new"))
        assert isinstance(_doc(runs, "new")["updated_at"], datetime)

    def test_a_step_update_refreshes_updated_at(self, runs):
        _insert(runs, "live", started_hours_ago=30, updated_hours_ago=25)

        assert store.upsert_ingestion_step(
            "live", step={"name": "scan", "status": "running"}, current_step="scan"
        )
        # Written now, so a sweep at the real current time leaves it running.
        assert store.mark_stale_ingestion_runs() == 0
        assert _doc(runs, "live")["status"] == "running"
