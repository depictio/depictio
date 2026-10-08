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
