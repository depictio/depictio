"""Tests for the offload decision and the Celery configuration it depends on.

The Celery assertions are regression guards for three specific traps documented
in ``celery_app.py``; each one, if reintroduced, fails silently in production
rather than loudly in CI.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.deltatables_endpoints.routes import _should_offload


@pytest.fixture
def offload_enabled(monkeypatch):
    monkeypatch.setattr(settings.ingestion, "async_deltatable_upsert", True)
    monkeypatch.setattr(settings.jobs, "enabled", True)


class TestShouldOffload:
    def test_requires_the_client_to_ask(self, offload_enabled):
        assert _should_offload(False, is_multiqc=False) is False

    def test_offloads_when_asked_and_enabled(self, offload_enabled):
        assert _should_offload(True, is_multiqc=False) is True

    def test_multiqc_always_runs_inline(self, offload_enabled):
        # MultiQC is parquet, not Delta: there is no table read to defer, so
        # offloading would buy a broker round-trip and nothing else.
        assert _should_offload(True, is_multiqc=True) is False

    def test_disabled_ingestion_flag_keeps_it_synchronous(self, monkeypatch):
        monkeypatch.setattr(settings.ingestion, "async_deltatable_upsert", False)
        monkeypatch.setattr(settings.jobs, "enabled", True)

        assert _should_offload(True, is_multiqc=False) is False

    def test_jobs_disabled_keeps_it_synchronous(self, monkeypatch):
        # Without the job store there is nowhere to record the work, so a
        # job_id would point at nothing. Falling back is the only safe answer.
        monkeypatch.setattr(settings.ingestion, "async_deltatable_upsert", True)
        monkeypatch.setattr(settings.jobs, "enabled", False)

        assert _should_offload(True, is_multiqc=False) is False

    def test_default_configuration_never_offloads(self):
        # Both flags ship off; an upgraded deployment must behave exactly as
        # before until someone opts in.
        assert settings.ingestion.async_deltatable_upsert is False
        assert settings.jobs.enabled is False


class TestCeleryConfiguration:
    def test_results_use_their_own_redis_db(self):
        from depictio.api.celery_app import celery_app

        # Broker DB 1, results DB 2. Sharing one DB put queues and result keys
        # in the same keyspace.
        assert celery_app.conf.result_backend == settings.celery.result_backend_url
        assert celery_app.conf.result_backend != celery_app.conf.broker_url

    def test_default_queue_stays_celery(self):
        from depictio.api.celery_app import celery_app

        # CeleryConfig.default_queue says "dashboard_tasks" but was never
        # applied. Applying it would route every task to a queue the shipped
        # worker command does not consume — i.e. everything silently stops.
        assert celery_app.conf.task_default_queue == "celery"
        assert settings.celery.default_queue == "dashboard_tasks"

    def test_result_expiry_is_not_shortened_below_celery_default(self):
        from depictio.api.celery_app import celery_app

        # Celery reports PENDING for both unknown and expired task ids, so
        # shortening this makes long-idle pollers hang forever.
        assert celery_app.conf.result_expires >= 86400

    def test_ingestion_task_is_routed_to_its_own_queue(self):
        from depictio.api.celery_app import celery_app

        routes = celery_app.conf.task_routes or {}
        assert routes["depictio.deltatable.finalize_upsert"] == {
            "queue": settings.celery.ingestion_queue
        }

    def test_worker_tuning_is_not_forced_globally(self):
        from depictio.api.celery_app import celery_app

        # These must stay unset so the interactive worker keeps its own sizing;
        # the ingestion worker passes them as CLI flags instead.
        conf = celery_app.conf
        assert "worker_concurrency" not in conf.changes
        assert "worker_prefetch_multiplier" not in conf.changes
        assert "worker_max_tasks_per_child" not in conf.changes

    def test_finalize_task_is_registered(self):
        import depictio.api.v1.ingestion_tasks  # noqa: F401
        from depictio.api.celery_app import celery_app

        assert "depictio.deltatable.finalize_upsert" in celery_app.tasks

    def test_finalize_task_is_late_acking(self):
        import depictio.api.v1.ingestion_tasks  # noqa: F401
        from depictio.api.celery_app import celery_app

        task = celery_app.tasks["depictio.deltatable.finalize_upsert"]
        # Safe only because the task patches one identified aggregation entry
        # instead of appending. If someone changes it to append, this pairing
        # becomes a corruption bug on redelivery.
        assert task.acks_late is True
        assert task.reject_on_worker_lost is True


class TestAggregationStatus:
    def test_defaults_to_complete_for_historical_documents(self):
        from depictio.models.models.deltatables import Aggregation
        from depictio.models.models.users import UserBase

        agg = Aggregation(
            aggregation_by=UserBase(id="507f1f77bcf86cd799439011", email="a@b.c"),
            aggregation_hash="h",
        )

        # Everything the synchronous path ever wrote was complete on arrival.
        assert agg.aggregation_status == "complete"

    def test_upsert_payload_defaults_to_synchronous(self):
        from depictio.models.models.deltatables import UpsertDeltaTableAggregated

        payload = UpsertDeltaTableAggregated(
            data_collection_id="507f1f77bcf86cd799439011",
            delta_table_location="s3://bucket/dc",
        )

        assert payload.async_mode is False

    def test_unknown_fields_are_ignored_for_forward_compatibility(self):
        from depictio.models.models.deltatables import UpsertDeltaTableAggregated

        # A newer CLI sending a field this server does not know must not 422 —
        # that is what makes "no job_id means done" a safe contract.
        payload = UpsertDeltaTableAggregated(
            data_collection_id="507f1f77bcf86cd799439011",
            delta_table_location="s3://bucket/dc",
            some_future_field="whatever",
        )

        assert payload.async_mode is False


class TestCapabilities:
    def test_async_upsert_is_advertised_only_when_both_flags_are_on(self, monkeypatch):
        # Guards the "runtime state, not build state" promise in the endpoint
        # docstring: advertising a capability the server will refuse to use
        # makes the probe worse than useless.
        monkeypatch.setattr(settings.jobs, "enabled", True)
        monkeypatch.setattr(settings.ingestion, "async_deltatable_upsert", False)
        assert _should_offload(True, is_multiqc=False) is False

        monkeypatch.setattr(settings.ingestion, "async_deltatable_upsert", True)
        assert _should_offload(True, is_multiqc=False) is True

    def test_limits_are_the_ones_the_request_models_enforce(self):
        """The delete limit used to be read from a setting nothing enforced.

        Raising the setting made the server advertise batches its own request
        models then rejected.
        """
        import asyncio
        from types import SimpleNamespace

        from pydantic import ValidationError

        from depictio.api.v1.endpoints.files_endpoints.routes import (
            MAX_FILES_PER_BATCH,
            MAX_IDS_PER_DELETE_BATCH,
            DeleteFilesBatchRequest,
        )
        from depictio.api.v1.endpoints.runs_endpoints.routes import DeleteRunsBatchRequest
        from depictio.api.v1.endpoints.utils_endpoints.routes import capabilities

        body = asyncio.run(capabilities(current_user=SimpleNamespace(id="u")))

        assert body["limits"] == {
            "max_files_per_batch": MAX_FILES_PER_BATCH,
            "max_ids_per_delete_batch": MAX_IDS_PER_DELETE_BATCH,
        }
        ids = [str(i) for i in range(MAX_IDS_PER_DELETE_BATCH)]
        DeleteFilesBatchRequest(file_ids=ids)
        DeleteRunsBatchRequest(run_ids=ids)
        with pytest.raises(ValidationError):
            DeleteFilesBatchRequest(file_ids=[*ids, "one-more"])
        with pytest.raises(ValidationError):
            DeleteRunsBatchRequest(run_ids=[*ids, "one-more"])

    def test_unused_tuning_settings_are_gone(self):
        # Each of these was configurable and read by nothing; the task
        # decorators hardcode their time limits and the compose file sizes
        # the ingestion worker.
        for section, name in [
            ("celery", "ingestion_worker_concurrency"),
            ("celery", "ingestion_task_soft_time_limit"),
            ("celery", "ingestion_task_time_limit"),
            ("ingestion", "max_files_per_batch"),
            ("ingestion", "max_ids_per_delete_batch"),
            ("ingestion", "delta_history_timeout_seconds"),
            ("monitoring", "cli_log_shipping"),
        ]:
            assert name not in type(getattr(settings, section)).model_fields, name


class _BrokerDown:
    """Stands in for a Celery task whose broker cannot be reached."""

    def apply_async(self, *args, **kwargs):
        from kombu.exceptions import OperationalError

        raise OperationalError("broker down")


class _ArrayFilterShim:
    """mongomock lacks ``array_filters``; applies the one shape finalization uses."""

    def __init__(self, collection) -> None:
        self._collection = collection

    def __getattr__(self, name):
        return getattr(self._collection, name)

    def update_one(self, query, update, array_filters=None, **kwargs):
        if not array_filters:
            return self._collection.update_one(query, update, **kwargs)
        (condition,) = array_filters
        doc = self._collection.find_one(query)
        for aggregation in doc["aggregation"]:
            if aggregation.get("aggregation_version") == condition["a.aggregation_version"]:
                for key, value in update["$set"].items():
                    aggregation[key.removeprefix("aggregation.$[a].")] = value
        return self._collection.update_one(
            {"_id": doc["_id"]}, {"$set": {"aggregation": doc["aggregation"]}}
        )


class TestBrokerDown:
    """An offloaded upsert with no reachable broker falls back to finishing inline.

    ``_dispatch_finalize`` created the job and then let ``apply_async`` raise,
    so its documented ``None`` never came back: the synchronous fallback was
    dead code, the upsert answered 500, and the job sat ``pending`` with no task
    behind it while the aggregation stayed ``pending`` for good.
    """

    @pytest.fixture
    def env(self, monkeypatch, offload_enabled):
        import mongomock
        from bson import ObjectId

        from depictio.api.v1 import ingestion_tasks
        from depictio.api.v1.endpoints.deltatables_endpoints import routes
        from depictio.api.v1.jobs import store as jobs_store

        db = mongomock.MongoClient().db
        monkeypatch.setattr(jobs_store, "jobs_collection", db.jobs)
        monkeypatch.setattr(routes, "projects_collection", db.projects)
        monkeypatch.setattr(routes, "deltatables_collection", _ArrayFilterShim(db.deltatables))
        monkeypatch.setattr(routes, "users_collection", db.users)
        monkeypatch.setattr(ingestion_tasks, "finalize_deltatable_upsert", _BrokerDown())
        # The expensive halves read a Delta table; their outputs are all this
        # path needs.
        monkeypatch.setattr(routes, "_upsert_hash", lambda *_a, **_k: "hash")
        monkeypatch.setattr(
            routes,
            "_compute_upsert_artifacts",
            lambda *_a, **_k: ("hash", [{"name": "x", "type": "int64", "specs": {}}]),
        )

        async def _no_broadcast(_dc_id):
            return None

        monkeypatch.setattr(routes, "_broadcast_dc_update", _no_broadcast)

        user_id, dc_id = ObjectId(), ObjectId()
        db.users.insert_one(
            {"_id": user_id, "email": "owner@example.com", "password": "$2b$12$hash"}
        )
        db.projects.insert_one(
            {
                "_id": ObjectId(),
                "permissions": {"owners": [{"_id": user_id}]},
                "workflows": [{"data_collections": [{"_id": dc_id, "config": {"type": "table"}}]}],
            }
        )
        return {"db": db, "routes": routes, "user_id": user_id, "dc_id": dc_id}

    def test_dispatch_returns_none_and_fails_the_job(self, env):
        job_id = env["routes"]._dispatch_finalize(
            dc_id=str(env["dc_id"]),
            delta_table_location="s3://bucket/dc",
            version=1,
            user_id=str(env["user_id"]),
            project_id=None,
            ingestion_run_id="run1",
        )

        assert job_id is None
        jobs = list(env["db"].jobs.find({}))
        assert len(jobs) == 1
        assert jobs[0]["status"] == "failed"
        assert "queue" in jobs[0]["error"]

    def test_the_upsert_succeeds_through_the_synchronous_fallback(self, env):
        import asyncio
        from types import SimpleNamespace

        from depictio.models.models.deltatables import UpsertDeltaTableAggregated

        payload = UpsertDeltaTableAggregated(
            data_collection_id=str(env["dc_id"]),
            delta_table_location="s3://bucket/dc",
            update=True,
            async_mode=True,
        )
        user = SimpleNamespace(id=env["user_id"], is_admin=False)

        response = asyncio.run(env["routes"].upsert_deltatable(payload, current_user=user))

        assert response["result"] == "success"
        assert "job_id" not in response
        stored = env["db"].deltatables.find_one({"data_collection_id": env["dc_id"]})
        latest = stored["aggregation"][-1]
        assert latest["aggregation_status"] == "complete"
        assert latest["aggregation_columns_specs"][0]["name"] == "x"
        # No job left pending with nothing behind it.
        assert env["db"].jobs.count_documents({"status": {"$nin": ["failed"]}}) == 0


def test_a_job_cancelled_while_queued_is_not_run(monkeypatch):
    """Revoked ids live in worker memory only, so a revoke can miss.

    The worker that picks the task up anyway must find the job cancelled and
    stop, not flip it back to running and do the work.
    """
    from unittest.mock import MagicMock

    from depictio.api.v1 import ingestion_tasks
    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.jobs import store as jobs_store

    monkeypatch.setattr(jobs_store, "mark_job_running", MagicMock(return_value=False))
    finish = MagicMock()
    monkeypatch.setattr(jobs_store, "finish_job", finish)
    lookup = MagicMock()
    monkeypatch.setattr(projects_collection, "find_one", lookup)

    outcome = ingestion_tasks.finalize_deltatable_upsert.run(
        {
            "job_id": "j",
            "data_collection_id": "507f1f77bcf86cd799439011",
            "delta_table_location": "s3://bucket/dc",
            "aggregation_version": 2,
            "ingestion_run_id": None,
        }
    )

    assert outcome["skipped"] == "job already terminal"
    lookup.assert_not_called()
    finish.assert_not_called()
