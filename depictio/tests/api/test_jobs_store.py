"""Tests for the job store's state machine, against a fake Mongo collection.

A fake rather than mongomock: the operations exercised here are ordinary
``update_one`` filters, and asserting on the *filters themselves* is the point
— the guarantees under test are "this write is conditional on X", which a real
database would hide behind its result rather than expose.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pymongo.errors import DuplicateKeyError

from depictio.models.models.jobs import TERMINAL_JOB_STATES, Job


class FakeResult:
    def __init__(self, matched: int = 1, modified: int = 1) -> None:
        self.matched_count = matched
        self.modified_count = modified


class FakeCollection:
    """Records every call; serves documents from an in-memory dict."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.updates: list[tuple[dict, dict, dict]] = []
        self.raise_duplicate_on_insert = False
        self.inserts: list[dict] = []

    def insert_one(self, doc):
        if self.raise_duplicate_on_insert:
            self.raise_duplicate_on_insert = False
            raise DuplicateKeyError("duplicate idempotency key")
        self.inserts.append(doc)
        self.docs[doc["job_id"]] = doc
        return FakeResult()

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        for key, cond in query.items():
            if isinstance(cond, dict) and "$nin" in cond:
                if doc.get(key) in cond["$nin"]:
                    return False
            elif doc.get(key) != cond:
                return False
        return True

    def find_one(self, query, projection=None, sort=None):
        if "job_id" in query:
            return self.docs.get(query["job_id"])
        candidates = [doc for doc in self.docs.values() if self._matches(doc, query)]
        if sort:
            key, direction = sort[0]
            candidates.sort(key=lambda d: d.get(key), reverse=direction < 0)
        return candidates[0] if candidates else None

    def update_one(self, query, update, array_filters=None, upsert=False):
        self.updates.append((query, update, {"array_filters": array_filters}))
        job_id = query.get("job_id")
        doc = self.docs.get(job_id) if job_id else None
        if doc is None:
            return FakeResult(matched=0, modified=0)
        # Honour the conditional filters the store relies on.
        for key, cond in query.items():
            if key == "job_id":
                continue
            if isinstance(cond, dict) and "$nin" in cond:
                if doc.get(key) in cond["$nin"]:
                    return FakeResult(matched=0, modified=0)
            elif doc.get(key) != cond:
                return FakeResult(matched=0, modified=0)
        doc.update(update.get("$set", {}))
        return FakeResult()

    def create_index(self, *args, **kwargs):
        return "index"


@pytest.fixture
def store(monkeypatch):
    from depictio.api.v1.jobs import store as jobs_store

    fake = FakeCollection()
    monkeypatch.setattr(jobs_store, "jobs_collection", fake)
    jobs_store._fake = fake  # convenience handle for assertions
    return jobs_store


def _job(**kwargs) -> Job:
    defaults = dict(job_id="j1", kind="deltatable.upsert", user_id="u1")
    defaults.update(kwargs)
    return Job(**defaults)


class TestCreateJob:
    def test_inserts_and_reports_created(self, store):
        job, created = store.create_job(_job())

        assert created is True
        assert job.expires_at is not None
        assert store._fake.inserts[0]["job_id"] == "j1"

    def test_duplicate_key_attaches_to_existing_job(self, store):
        existing = _job(job_id="already-running", idempotency_key="k1").model_dump()
        store._fake.docs["already-running"] = existing
        store._fake.raise_duplicate_on_insert = True

        job, created = store.create_job(_job(job_id="new", idempotency_key="k1"))

        # The whole point: a retry must reuse the in-flight job rather than
        # enqueue a second full table read.
        assert created is False
        assert job.job_id == "already-running"

    def test_failed_jobs_get_the_longer_retention(self, store, monkeypatch):
        from depictio.api.v1.configs.config import settings

        monkeypatch.setattr(settings.jobs, "retention_hours", 1)
        monkeypatch.setattr(settings.jobs, "failed_retention_hours", 100)

        success_expiry = store._expiry("success")
        failed_expiry = store._expiry("failed")

        assert failed_expiry > success_expiry + timedelta(hours=90)


class TestStateTransitions:
    def test_mark_running_sets_started_at_only_once(self, store):
        store.create_job(_job())
        store.mark_job_running("j1", step="read_delta")

        # Second update is guarded on started_at being None, so a redelivered
        # task cannot reset the clock.
        guard = store._fake.updates[-1][0]
        assert guard == {"job_id": "j1", "started_at": None}

    def test_progress_is_ignored_once_terminal(self, store):
        store.create_job(_job())
        store.finish_job("j1", status="success", result={"rows": 1})

        store.update_job_progress("j1", step="late-ping")

        assert store._fake.docs["j1"]["status"] == "success"
        assert store._fake.docs["j1"].get("step") != "late-ping"

    def test_progress_with_no_fields_is_a_noop(self, store):
        store.create_job(_job())
        before = len(store._fake.updates)

        store.update_job_progress("j1")

        assert len(store._fake.updates) == before

    def test_finish_job_stores_result(self, store):
        store.create_job(_job())
        store.finish_job("j1", status="success", result={"rows": 42})

        doc = store._fake.docs["j1"]
        assert doc["status"] == "success"
        assert doc["result"] == {"rows": 42}
        assert doc["result_truncated"] is False

    def test_oversized_result_is_dropped_not_stored(self, store, monkeypatch):
        from depictio.api.v1.configs.config import settings

        monkeypatch.setattr(settings.jobs, "max_result_bytes", 50)
        store.create_job(_job())

        store.finish_job("j1", status="success", result={"blob": "x" * 500})

        doc = store._fake.docs["j1"]
        # Success is still success — the work happened. Only the payload is gone.
        assert doc["status"] == "success"
        assert doc["result"] is None
        assert doc["result_truncated"] is True

    def test_error_is_truncated_to_a_sane_length(self, store):
        store.create_job(_job())
        store.finish_job("j1", status="failed", error="e" * 10_000)

        assert len(store._fake.docs["j1"]["error"]) == 4000

    def test_cancel_only_applies_to_non_terminal_jobs(self, store):
        store.create_job(_job())
        assert store.cancel_job("j1") is True

        # Already cancelled — the $nin guard must reject the second attempt.
        assert store.cancel_job("j1") is False

    def test_cancel_unknown_job_returns_false(self, store):
        assert store.cancel_job("nope") is False


class TestIdempotencyKey:
    def test_is_stable_for_the_same_inputs(self, store):
        a = store.build_idempotency_key("run1", "dc1", "s3://t", "deltatable.upsert")
        b = store.build_idempotency_key("run1", "dc1", "s3://t", "deltatable.upsert")
        assert a == b

    def test_differs_when_any_part_differs(self, store):
        base = store.build_idempotency_key("run1", "dc1", "s3://t", "k")
        assert base != store.build_idempotency_key("run2", "dc1", "s3://t", "k")
        assert base != store.build_idempotency_key("run1", "dc2", "s3://t", "k")
        assert base != store.build_idempotency_key("run1", "dc1", "s3://other", "k")


class TestToStatus:
    def test_projects_task_id_for_admin_pivot(self, store):
        doc = _job(celery_task_id="celery-123").model_dump()

        status = store.to_status(doc, poll_after_seconds=2.5)

        assert status.task_id == "celery-123"
        assert status.poll_after_seconds == 2.5

    def test_omits_ownership_fields(self, store):
        doc = _job(idempotency_key="secret-key").model_dump()

        status = store.to_status(doc)

        assert not hasattr(status, "idempotency_key")
        assert not hasattr(status, "user_id")

    def test_terminal_property_matches_the_shared_set(self, store):
        for state in TERMINAL_JOB_STATES:
            doc = _job(status=state).model_dump()
            assert store.to_status(doc).terminal is True

        assert store.to_status(_job(status="running").model_dump()).terminal is False


class TestExpiry:
    def test_create_job_does_not_overwrite_an_explicit_expiry(self, store):
        chosen = datetime.now() + timedelta(days=30)

        job, _ = store.create_job(_job(expires_at=chosen))

        assert job.expires_at == chosen


class TestFindActiveJob:
    """The one-ingestion-per-project lock.

    Expressed as a status query rather than an idempotency key on purpose: a
    key stays valid for the document's whole retention window, so keying a
    project ingestion on its project id would make the second ingestion of the
    day silently return the morning's finished job and start nothing.
    """

    def _store(self, store, **kwargs):
        kwargs.setdefault("kind", "project.ingest")
        kwargs.setdefault("project_id", "p1")
        job = _job(**kwargs)
        store._fake.docs[job.job_id] = job.model_dump()
        return job

    def test_finds_a_running_job(self, store):
        self._store(store, job_id="running", status="running")

        found = store.find_active_job(kind="project.ingest", project_id="p1")

        assert found is not None and found["job_id"] == "running"

    def test_finds_a_pending_job(self, store):
        self._store(store, job_id="queued", status="pending")

        assert store.find_active_job(kind="project.ingest", project_id="p1") is not None

    @pytest.mark.parametrize("state", sorted(TERMINAL_JOB_STATES))
    def test_ignores_terminal_jobs(self, store, state):
        # The regression this pins: a finished ingestion must not block the
        # next one.
        self._store(store, job_id=f"done-{state}", status=state)

        assert store.find_active_job(kind="project.ingest", project_id="p1") is None

    def test_ignores_another_project(self, store):
        self._store(store, job_id="other", status="running", project_id="p2")

        assert store.find_active_job(kind="project.ingest", project_id="p1") is None

    def test_ignores_another_kind(self, store):
        # A DC upsert also carries project_id; it must not look like an
        # in-flight project ingestion.
        self._store(store, job_id="upsert", kind="deltatable.upsert", status="running")

        assert store.find_active_job(kind="project.ingest", project_id="p1") is None
