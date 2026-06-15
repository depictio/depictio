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

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            IngestionRun(run_id="r1", bogus=1)


class TestAppLogRecord:
    def test_defaults(self):
        rec = AppLogRecord(message="hello")
        assert rec.level == "INFO"
        assert rec.source == "api"
        assert rec.message == "hello"


def test_admin_channel_constant():
    # The frontend hook hardcodes the same sentinel; keep them in sync.
    assert ADMIN_MONITORING_CHANNEL == "__admin_monitoring__"
