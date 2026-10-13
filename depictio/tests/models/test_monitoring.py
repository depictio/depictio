"""Tests for the monitoring ledger models and pure helpers.

DB-backed behaviour (store upserts, endpoint admin-gating) needs a live MongoDB
and is exercised by the API integration tests; these cover the pure logic.
"""

import pytest
from pydantic import ValidationError

from depictio.models.models.monitoring import (
    ADMIN_MONITORING_CHANNEL,
    AppLogRecord,
    IngestionRun,
    IngestionStep,
    TaskEvent,
    derive_task_kind,
)


class TestDeriveTaskKind:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("generate_dashboard_screenshot_dual", "screenshot"),
            ("depictio.multiqc.build_preview", "multiqc"),
            ("prewarm_multiqc_dashboard", "multiqc"),
            ("depictio.advanced_viz.compute_embedding", "advanced_viz"),
            ("compute_complex_heatmap", "advanced_viz"),
            ("depictio.deltatables.preview", "deltatable"),
            ("depictio.figure.build_preview", "figure"),
            ("health_check", "other"),
            ("", "other"),
            (None, "other"),
        ],
    )
    def test_mapping(self, name, expected):
        assert derive_task_kind(name) == expected


class TestTaskEvent:
    def test_defaults(self):
        ev = TaskEvent(task_id="abc")
        assert ev.task_id == "abc"
        assert ev.status == "pending"
        assert ev.kind == "other"
        assert ev.logs == []
        assert ev.created_at is not None

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            TaskEvent(task_id="abc", bogus="nope")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            TaskEvent(task_id="abc", status="exploded")


class TestIngestionRun:
    def test_defaults_and_steps(self):
        run = IngestionRun(
            run_id="r1",
            steps=[IngestionStep(name="sync", status="success")],
        )
        assert run.status == "running"
        assert run.command == "run"
        assert run.steps[0].name == "sync"
        assert run.finished_at is None
        assert run.updated_at is None

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            IngestionRun(run_id="r1", bogus=1)

    @pytest.mark.parametrize("status", ["interrupted", "abandoned"])
    def test_statuses_for_runs_that_never_finished(self, status):
        assert IngestionRun(run_id="r1", status=status).status == status

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            IngestionRun(run_id="r1", status="exploded")


class TestAppLogRecord:
    def test_defaults(self):
        rec = AppLogRecord(message="hello")
        assert rec.level == "INFO"
        assert rec.source == "api"
        assert rec.message == "hello"


def test_admin_channel_constant():
    # The frontend hook hardcodes the same sentinel; keep them in sync.
    assert ADMIN_MONITORING_CHANNEL == "__admin_monitoring__"


@pytest.fixture
def far_from_utc(monkeypatch: pytest.MonkeyPatch):
    """Run with a local clock 14 hours ahead of UTC."""
    import time

    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_agent_and_job_default_times_are_naive_utc(far_from_utc):
    """BSON dates are UTC: a TTL index and the viewer both read them that way.

    A local default put a watcher's ``expires_at`` 14 hours late here, and
    evicted it about a minute after each heartbeat west of UTC.
    """
    from datetime import datetime, timezone

    from depictio.models.models.jobs import Job
    from depictio.models.models.monitoring import CliAgent

    before = datetime.now(timezone.utc).replace(tzinfo=None)
    agent = CliAgent(agent_id="a1")
    job = Job(job_id="j1", kind="project.ingest")

    for value in (agent.started_at, agent.heartbeat_at, agent.expires_at, job.submitted_at):
        assert value.tzinfo is None
        assert abs((value - before).total_seconds()) < 60


def test_log_records_have_no_cli_source():
    """Nothing ships CLI log lines, so the ledger does not pretend to accept them."""
    with pytest.raises(ValidationError):
        AppLogRecord(message="hello", source="cli")
    with pytest.raises(ValidationError):
        AppLogRecord(message="hello", run_id="r1")
