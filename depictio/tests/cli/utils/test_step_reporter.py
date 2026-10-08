"""Tests for live step reporting.

The send function is injected, so these exercise the real threading without a
server. Each test joins the worker via ``close()`` before asserting, which is
the same bounded flush the CLI performs.
"""

from __future__ import annotations

import threading

from depictio.cli.cli.utils.step_reporter import StepReporter


class Recorder:
    """Captures what the reporter would have sent."""

    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[str, dict, str | None]] = []
        self.ok = ok
        self._lock = threading.Lock()

    def __call__(self, run_id: str, step: dict, current: str | None) -> bool:
        with self._lock:
            self.calls.append((run_id, dict(step), current))
        return self.ok


class TestDisabled:
    def test_records_locally_without_a_run_id(self):
        # Phases that run before the monitoring record exists must still end up
        # in the ledger sent at finish.
        reporter = StepReporter(send=Recorder(), run_id=None, enabled=True)
        reporter.record("server_check", "success", "reachable")

        assert [s["name"] for s in reporter.steps] == ["server_check"]

    def test_sends_nothing_when_disabled(self):
        recorder = Recorder()
        reporter = StepReporter(send=recorder, run_id="r1", enabled=False)
        reporter.record("scan", "success")
        reporter.close()

        assert recorder.calls == []


class TestLiveReporting:
    def test_start_then_finish_updates_one_step(self):
        recorder = Recorder()
        reporter = StepReporter(send=recorder, run_id="r1", enabled=True)

        reporter.start("scan", "walking")
        reporter.finish("scan", "success", "done")
        reporter.close()

        # One step locally, two pushes — the point of the feature is that the
        # UI sees "running" before it sees the outcome.
        assert [s["name"] for s in reporter.steps] == ["scan"]
        assert reporter.steps[0]["status"] == "success"
        assert [c[1]["status"] for c in recorder.calls] == ["running", "success"]

    def test_current_step_is_set_while_running_and_cleared_after(self):
        recorder = Recorder()
        reporter = StepReporter(send=recorder, run_id="r1", enabled=True)

        reporter.start("process")
        reporter.finish("process", "success")
        reporter.close()

        assert [c[2] for c in recorder.calls] == ["process", None]

    def test_duration_is_stamped_on_finish(self):
        reporter = StepReporter(send=Recorder(), run_id="r1", enabled=True)
        reporter.start("scan")
        reporter.finish("scan", "success")
        reporter.close()

        assert reporter.steps[0]["duration_ms"] >= 0

    def test_no_duration_when_the_step_was_never_started(self):
        reporter = StepReporter(send=Recorder(), run_id="r1", enabled=True)
        reporter.record("skipped_phase", "skipped")
        reporter.close()

        assert "duration_ms" not in reporter.steps[0]

    def test_steps_keep_first_seen_order_and_carry_an_index(self):
        reporter = StepReporter(send=Recorder(), run_id="r1", enabled=True)
        for name in ("a", "b", "c"):
            reporter.record(name, "success")
        reporter.close()

        assert [s["name"] for s in reporter.steps] == ["a", "b", "c"]
        assert [s["index"] for s in reporter.steps] == [0, 1, 2]

    def test_extra_fields_are_carried_through(self):
        recorder = Recorder()
        reporter = StepReporter(send=recorder, run_id="r1", enabled=True)
        reporter.finish("scan", "success", counters={"files_new": 3})
        reporter.close()

        assert reporter.steps[0]["counters"] == {"files_new": 3}
        assert recorder.calls[0][1]["counters"] == {"files_new": 3}


class TestFailureHandling:
    def test_gives_up_permanently_when_the_server_refuses(self):
        recorder = Recorder(ok=False)
        reporter = StepReporter(send=recorder, run_id="r1", enabled=True)

        for index in range(10):
            reporter.record(f"step{index}", "success")
        reporter.close()

        # One attempt, then latched off — retrying an unsupported endpoint for
        # the rest of the run is pure waste.
        assert len(recorder.calls) == 1
        # The local ledger is unaffected: finish still reports every step.
        assert len(reporter.steps) == 10

    def test_a_raising_send_never_escapes(self):
        def boom(*_args):
            raise RuntimeError("network is on fire")

        reporter = StepReporter(send=boom, run_id="r1", enabled=True)
        reporter.record("scan", "success")
        reporter.close()

        # Recording must never be able to break an ingestion.
        assert reporter.steps[0]["status"] == "success"

    def test_close_is_safe_to_call_twice(self):
        reporter = StepReporter(send=Recorder(), run_id="r1", enabled=True)
        reporter.record("scan", "success")
        reporter.close()
        reporter.close()


class TestReplay:
    def test_adopts_earlier_steps_and_pushes_them(self):
        recorder = Recorder()
        early = StepReporter(send=Recorder(), run_id=None, enabled=False)
        early.record("server_check", "success")
        early.record("s3_check", "success")

        live = StepReporter(send=recorder, run_id="r1", enabled=True)
        live.replay(early.steps)
        live.close()

        assert [s["name"] for s in live.steps] == ["server_check", "s3_check"]
        assert {c[1]["name"] for c in recorder.calls} == {"server_check", "s3_check"}

    def test_replay_does_not_clobber_a_newer_record(self):
        live = StepReporter(send=Recorder(), run_id="r1", enabled=True)
        live.record("scan", "success", "fresh")
        live.replay([{"name": "scan", "status": "running", "detail": "stale"}])
        live.close()

        assert live.steps[0]["status"] == "success"
        assert live.steps[0]["detail"] == "fresh"
