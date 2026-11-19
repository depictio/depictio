"""Export jobs: bound to their requester, bounded per user, slots per deployment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from fastapi import HTTPException

from depictio.api.v1.services.notebook_export import jobs


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client.test_db
    with (
        patch.object(jobs, "jobs_collection", database.notebook_export_jobs),
        patch.object(jobs, "slots_collection", database.notebook_export_slots),
    ):
        yield database


def test_a_job_belongs_to_its_requester(db):
    jobs.record("j1", "alice", jobs.RENDER)
    assert jobs.owned("j1", "alice", jobs.RENDER) is not None
    assert jobs.owned("j1", "bob", jobs.RENDER) is None
    assert jobs.owned("j1", "alice", jobs.EXTRACT) is None
    assert jobs.owned("nope", "alice", jobs.RENDER) is None


def test_admission_counts_running_jobs_and_the_hour(db):
    def admit():
        jobs.admit("alice", jobs.RENDER, max_active=2, max_per_hour=3, window_s=600)

    for i in range(2):
        admit()
        jobs.record(f"j{i}", "alice", jobs.RENDER)
    with pytest.raises(HTTPException) as exc:
        admit()
    assert exc.value.status_code == 429
    jobs.finish("j0", "success")
    admit()
    jobs.record("j2", "alice", jobs.RENDER)
    jobs.finish("j1", "success")
    with pytest.raises(HTTPException) as exc:
        admit()  # three in the hour already
    assert exc.value.status_code == 429
    # Another user is not affected.
    jobs.admit("bob", jobs.RENDER, max_active=2, max_per_hour=3, window_s=600)


def test_a_crashed_job_stops_counting_once_its_window_is_over(db):
    jobs.record("old", "alice", jobs.RENDER)
    db.notebook_export_jobs.update_one(
        {"_id": "old"}, {"$set": {"created_at": datetime(2000, 1, 1)}}
    )
    jobs.admit("alice", jobs.RENDER, max_active=1, max_per_hour=5, window_s=600)


def test_slots_are_bounded_and_released(db):
    assert jobs.acquire_slot("report", "a", capacity=1, hold_s=60)
    assert not jobs.acquire_slot("report", "b", capacity=1, hold_s=60)
    # The holder asking again (a retried task) keeps its slot.
    assert jobs.acquire_slot("report", "a", capacity=1, hold_s=60)
    jobs.release_slot("report", "a")
    assert jobs.acquire_slot("report", "b", capacity=1, hold_s=60)


def test_a_lapsed_slot_is_taken_over(db):
    assert jobs.acquire_slot("report", "a", capacity=1, hold_s=60)
    db.notebook_export_slots.update_one(
        {"_id": "report:0"}, {"$set": {"until": datetime(2000, 1, 1)}}
    )
    assert jobs.acquire_slot("report", "b", capacity=1, hold_s=60)


def test_old_reports_are_pruned_at_most_hourly(db):
    now = datetime.now(timezone.utc)
    objects = [
        {"Key": "notebook_reports/u/j1/r.html", "LastModified": now - timedelta(days=30)},
        {"Key": "notebook_reports/u/j2/r.html", "LastModified": now},
    ]
    deleted: list[str] = []

    class _S3:
        def get_paginator(self, name):
            return SimpleNamespace(paginate=lambda **kw: [{"Contents": objects}])

        def delete_objects(self, Bucket, Delete):  # noqa: N803 - boto3's own names
            deleted.extend(o["Key"] for o in Delete["Objects"])

    with patch("depictio.api.v1.s3.s3_client", _S3()):
        assert jobs.prune_reports() == 1
        assert deleted == ["notebook_reports/u/j1/r.html"]
        assert jobs.prune_reports() == 0  # within the hour
