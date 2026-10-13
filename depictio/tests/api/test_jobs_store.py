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


class TestTerminalStatesStick:
    """A cancelled job stays cancelled whatever the task does afterwards.

    A cancel reaches a prefork worker as SIGUSR1, which billiard raises inside
    the task as ``SoftTimeLimitExceeded``, so its failure handler calls
    ``finish_job("failed")`` straight after; on a threads or solo pool the task
    simply runs on and reports success. Revoked ids also live in worker memory
    only, so a job cancelled while queued can still be picked up.
    """

    def test_finish_job_does_not_overwrite_a_cancelled_job(self, store):
        store.create_job(_job())
        store.mark_job_running("j1")
        assert store.cancel_job("j1") is True

        assert store.finish_job("j1", status="success", result={"rows": 10}) is False

        doc = store._fake.docs["j1"]
        assert doc["status"] == "cancelled"
        assert doc.get("result") is None

    def test_the_failure_handler_after_a_cancel_does_not_win_either(self, store):
        store.create_job(_job())
        store.mark_job_running("j1")
        store.cancel_job("j1")

        store.finish_job("j1", status="failed", error="SoftTimeLimitExceeded()")

        assert store._fake.docs["j1"]["status"] == "cancelled"
        assert store._fake.docs["j1"].get("error") is None

    def test_a_cancelled_job_is_not_brought_back_to_running(self, store):
        store.create_job(_job())
        store.cancel_job("j1")

        assert store.mark_job_running("j1", step="read_delta") is False

        doc = store._fake.docs["j1"]
        assert doc["status"] == "cancelled"
        assert doc.get("started_at") is None

    def test_mark_running_reports_success_on_a_live_job(self, store):
        store.create_job(_job())

        assert store.mark_job_running("j1") is True
        assert store._fake.docs["j1"]["status"] == "running"

    def test_finish_job_reports_success_on_a_live_job(self, store):
        store.create_job(_job())

        assert store.finish_job("j1", status="success") is True


class TestIdempotencyIndex:
    """Against mongomock, which enforces unique, sparse and partial indexes.

    The sparse index this replaces collided every keyless job of one user and
    kind on null: the second browser-triggered ingestion of any project then
    failed with a 500 for the whole retention window.
    """

    @pytest.fixture
    def collection(self, monkeypatch):
        import mongomock

        from depictio.api.v1.jobs import store as jobs_store

        jobs = mongomock.MongoClient().db.jobs
        monkeypatch.setattr(jobs_store, "jobs_collection", jobs)
        return jobs

    def test_the_index_is_partial_on_a_string_key(self, collection):
        from depictio.api.v1.jobs import store as jobs_store

        jobs_store.ensure_jobs_storage()

        spec = collection.index_information()[jobs_store.IDEMPOTENCY_INDEX_NAME]
        assert spec["unique"] is True
        assert spec["partialFilterExpression"] == {"idempotency_key": {"$type": "string"}}
        assert not spec.get("sparse")

    def test_two_keyless_jobs_of_one_user_and_kind_are_both_created(self, collection):
        from depictio.api.v1.jobs import store as jobs_store

        jobs_store.ensure_jobs_storage()

        first, first_created = jobs_store.create_job(_job(job_id="a", kind="project.ingest"))
        second, second_created = jobs_store.create_job(_job(job_id="b", kind="project.ingest"))

        assert first_created and second_created
        assert {first.job_id, second.job_id} == {"a", "b"}
        assert collection.count_documents({"user_id": "u1", "kind": "project.ingest"}) == 2

    def test_a_keyed_resubmission_still_attaches_to_the_first_job(self, collection):
        from depictio.api.v1.jobs import store as jobs_store

        jobs_store.ensure_jobs_storage()
        jobs_store.create_job(_job(job_id="first", idempotency_key="k"))

        job, created = jobs_store.create_job(_job(job_id="retry", idempotency_key="k"))

        assert created is False
        assert job.job_id == "first"

    def test_an_existing_sparse_index_is_replaced(self, collection):
        """Recreating an index under the same name with other options raises.

        Swallowed by ``ensure_jobs_storage``, so a deployment that already held
        the sparse index would have kept it, and its collisions, for good.
        """
        from depictio.api.v1.jobs import store as jobs_store

        collection.create_index(
            jobs_store.IDEMPOTENCY_INDEX_KEYS,
            unique=True,
            sparse=True,
            name=jobs_store.IDEMPOTENCY_INDEX_NAME,
        )

        jobs_store.ensure_jobs_storage()

        spec = collection.index_information()[jobs_store.IDEMPOTENCY_INDEX_NAME]
        assert "partialFilterExpression" in spec
        assert not spec.get("sparse")
        jobs_store.create_job(_job(job_id="a"))
        _, created = jobs_store.create_job(_job(job_id="b"))
        assert created is True

    def test_ensuring_twice_keeps_the_index(self, collection):
        from depictio.api.v1.jobs import store as jobs_store

        jobs_store.ensure_jobs_storage()
        jobs_store.ensure_jobs_storage()

        assert jobs_store.IDEMPOTENCY_INDEX_NAME in collection.index_information()


@pytest.fixture
def far_from_utc(monkeypatch: pytest.MonkeyPatch):
    """Run with a local clock 14 hours ahead of UTC."""
    import time

    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class TestNaiveUtc:
    """Job times are naive UTC, like every BSON date.

    The TTL index on ``expires_at`` is evaluated in UTC, so a local clock kept
    jobs for 14 extra hours east of UTC and evicted them early west of it.
    """

    def test_job_times_are_utc_under_a_far_from_utc_clock(self, store, far_from_utc):
        from datetime import timezone

        from depictio.api.v1.configs.config import settings

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        job, _ = store.create_job(_job())
        store.mark_job_running("j1")
        store.finish_job("j1", status="success")

        doc = store._fake.docs["j1"]
        assert abs((job.submitted_at - before).total_seconds()) < 60
        assert abs((doc["started_at"] - before).total_seconds()) < 60
        assert abs((doc["finished_at"] - before).total_seconds()) < 60
        retention = timedelta(hours=settings.jobs.retention_hours)
        assert abs((doc["expires_at"] - (before + retention)).total_seconds()) < 60

    def test_cancel_time_is_utc(self, store, far_from_utc):
        from datetime import timezone

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        store.create_job(_job())
        store.cancel_job("j1")

        assert abs((store._fake.docs["j1"]["finished_at"] - before).total_seconds()) < 60
