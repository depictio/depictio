"""Tests for the CLI-side job polling client.

The clock and the HTTP transport are both injected, so these run instantly and
deterministically — no sleeping, no server.
"""

from __future__ import annotations

import httpx
import pytest

from depictio.cli.cli.utils.jobs import (
    DEFAULT_MAX_INTERVAL,
    JobOutcome,
    JobPollError,
    maybe_wait_for_job,
    poll_job,
)


class FakeSleep:
    """Records how long the poller would have slept."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _client(responses: list[dict], status: int = 200) -> httpx.Client:
    """Client returning each payload in turn, repeating the last one forever."""
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def patched_client(monkeypatch):
    """Route the module's shared client through a caller-supplied transport."""

    def install(client: httpx.Client) -> None:
        monkeypatch.setattr("depictio.cli.cli.utils.jobs.get_http_client", lambda: client)

    return install


class TestPollJob:
    def test_returns_immediately_on_terminal_state(self, patched_client):
        patched_client(_client([{"status": "success", "result": {"rows": 10}}]))
        sleep = FakeSleep()

        outcome = poll_job("j1", api_base_url="http://api", token="t", sleep=sleep)

        assert outcome.ok
        assert outcome.result == {"rows": 10}
        # A job that is already done must not cost a sleep.
        assert sleep.calls == []

    def test_polls_until_terminal(self, patched_client):
        patched_client(
            _client(
                [
                    {"status": "pending"},
                    {"status": "running", "step": "hash_rows"},
                    {"status": "success", "result": {"columns": 4}},
                ]
            )
        )
        sleep = FakeSleep()

        outcome = poll_job("j1", api_base_url="http://api", token="t", sleep=sleep)

        assert outcome.ok
        assert outcome.result == {"columns": 4}
        assert len(sleep.calls) == 2

    def test_failed_job_is_not_ok_and_carries_error(self, patched_client):
        patched_client(_client([{"status": "failed", "error": "table vanished"}]))

        outcome = poll_job("j1", api_base_url="http://api", token="t", sleep=FakeSleep())

        assert not outcome.ok
        assert outcome.status == "failed"
        assert outcome.error == "table vanished"

    def test_cancelled_is_terminal(self, patched_client):
        patched_client(_client([{"status": "cancelled"}]))

        outcome = poll_job("j1", api_base_url="http://api", token="t", sleep=FakeSleep())

        assert outcome.status == "cancelled"
        assert not outcome.ok

    def test_honours_server_poll_hint(self, patched_client):
        patched_client(
            _client(
                [
                    {"status": "running", "poll_after_seconds": 7},
                    {"status": "success"},
                ]
            )
        )
        sleep = FakeSleep()

        poll_job("j1", api_base_url="http://api", token="t", sleep=sleep)

        assert sleep.calls == [7.0]

    def test_server_hint_is_capped_at_max_interval(self, patched_client):
        patched_client(
            _client([{"status": "running", "poll_after_seconds": 9999}, {"status": "success"}])
        )
        sleep = FakeSleep()

        poll_job("j1", api_base_url="http://api", token="t", sleep=sleep)

        assert sleep.calls == [DEFAULT_MAX_INTERVAL]

    def test_backs_off_geometrically_without_a_hint(self, patched_client):
        patched_client(
            _client(
                [
                    {"status": "running"},
                    {"status": "running"},
                    {"status": "running"},
                    {"status": "success"},
                ]
            )
        )
        sleep = FakeSleep()

        poll_job("j1", api_base_url="http://api", token="t", poll_interval=1.0, sleep=sleep)

        assert sleep.calls == [1.5, 2.25, 3.375]

    def test_404_raises_rather_than_hanging(self, patched_client):
        patched_client(_client([{"detail": "Job not found"}], status=404))

        with pytest.raises(JobPollError, match="unknown to the server"):
            poll_job("j1", api_base_url="http://api", token="t", sleep=FakeSleep())

    def test_overall_timeout_is_enforced_when_requested(self, patched_client, monkeypatch):
        patched_client(_client([{"status": "running"}]))
        # Advance the clock by a minute on every sleep so the deadline is
        # crossed without the test actually waiting.
        ticks = iter(range(0, 100_000, 60))
        monkeypatch.setattr(
            "depictio.cli.cli.utils.jobs.time.monotonic", lambda: float(next(ticks))
        )

        with pytest.raises(JobPollError, match="did not finish within"):
            poll_job(
                "j1",
                api_base_url="http://api",
                token="t",
                overall_timeout=120,
                sleep=FakeSleep(),
            )

    def test_on_update_exception_does_not_abort_polling(self, patched_client):
        patched_client(_client([{"status": "running"}, {"status": "success"}]))

        def boom(_payload):
            raise RuntimeError("telemetry is broken")

        outcome = poll_job(
            "j1", api_base_url="http://api", token="t", on_update=boom, sleep=FakeSleep()
        )

        assert outcome.ok

    def test_on_update_receives_progress_payloads(self, patched_client):
        patched_client(
            _client(
                [
                    {"status": "running", "step": "read_delta"},
                    {"status": "success"},
                ]
            )
        )
        seen: list[dict] = []

        poll_job(
            "j1",
            api_base_url="http://api",
            token="t",
            on_update=seen.append,
            sleep=FakeSleep(),
        )

        assert [s["step"] for s in seen] == ["read_delta"]


class TestMaybeWaitForJob:
    def test_no_job_id_means_work_is_already_done(self, patched_client):
        # The whole backward-compatibility contract: an older server answers
        # without a job_id because it did the work inline.
        assert (
            maybe_wait_for_job({"result": "success"}, api_base_url="http://api", token="t") is None
        )

    def test_job_id_triggers_polling(self, patched_client):
        patched_client(_client([{"status": "success", "result": {"ok": True}}]))

        outcome = maybe_wait_for_job(
            {"result": "success", "job_id": "j9"}, api_base_url="http://api", token="t"
        )

        assert isinstance(outcome, JobOutcome)
        assert outcome.ok
