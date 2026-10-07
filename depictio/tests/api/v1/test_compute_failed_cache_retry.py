"""A failed server-side computation must not be served from the cache forever.

``compute_results`` keeps one doc per payload. A ``failed`` doc used to be
returned on every later dispatch, so a tile replayed a stale error even after
its cause was fixed. Failed entries are now retried once they are older than a
short backoff; ``done`` and ``pending`` entries are still reused.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import mongomock
import pytest

from depictio.api.v1.endpoints.advanced_viz_endpoints import routes


@pytest.fixture
def cache():
    return mongomock.MongoClient().db["compute_results"]


def _ago(seconds: float) -> datetime:
    # pymongo hands back naive UTC datetimes: mimic that.
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).replace(tzinfo=None)


def test_done_and_pending_entries_are_reused(cache):
    cache.insert_one({"_id": "a", "status": "done", "result": {"x": 1}})
    cache.insert_one({"_id": "b", "status": "pending"})
    assert routes._find_reusable_cache_entry(cache, "a")["result"] == {"x": 1}
    assert routes._find_reusable_cache_entry(cache, "b")["status"] == "pending"
    assert routes._find_reusable_cache_entry(cache, "missing") is None


def test_old_failed_entry_is_a_miss_and_removed(cache):
    cache.insert_one({"_id": "k", "status": "failed", "error": "boom", "completed_at": _ago(3600)})
    assert routes._find_reusable_cache_entry(cache, "k") is None
    assert cache.find_one({"_id": "k"}) is None


def test_failed_entry_without_timestamp_is_retried(cache):
    cache.insert_one({"_id": "k", "status": "failed", "error": "boom"})
    assert routes._find_reusable_cache_entry(cache, "k") is None


def test_recent_failed_entry_is_kept_during_backoff(cache):
    cache.insert_one({"_id": "k", "status": "failed", "error": "boom", "completed_at": _ago(5)})
    doc = routes._find_reusable_cache_entry(cache, "k")
    assert doc is not None and doc["error"] == "boom"
    assert cache.find_one({"_id": "k"}) is not None


def test_dispatch_reenqueues_after_old_failure(monkeypatch):
    """End to end through the shared dispatch helper: the stale error is not
    served, a new task is enqueued and the doc goes back to pending."""
    db = mongomock.MongoClient().db
    monkeypatch.setattr("depictio.api.v1.db.db", db)
    user = SimpleNamespace(id="u1", is_admin=False)
    payload = {"wf_id": "w", "dc_id": "d"}
    key = routes._compute_cache_key({**payload, "method": "sankey"}, user.id)
    db["compute_results"].insert_one(
        {"_id": key, "status": "failed", "error": "old cause", "completed_at": _ago(600)}
    )

    calls: list = []

    class _Task:
        def apply_async(self, args):
            calls.append(args)
            return SimpleNamespace(id="task-1")

    out = routes._dispatch_compute(payload, "sankey", _Task(), user)

    assert out == {"job_id": key, "status": "pending", "from_cache": False}
    assert len(calls) == 1
    doc = db["compute_results"].find_one({"_id": key})
    assert doc["status"] == "pending" and "error" not in doc
    assert doc["celery_task_id"] == "task-1"
