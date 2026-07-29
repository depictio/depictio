"""Tests for the CLI's HTTP retry policy.

The interesting cases are all about *not* retrying. A blind retry of
/deltatables/upsert appends a duplicate Aggregation and bumps the version a
second time, which silently invalidates the API's dataframe caches — a failure
that surfaces long after the request that caused it.
"""

import httpx
import pytest

from depictio.cli.cli.utils.http_retry import RETRYABLE_STATUS, request_with_retry

URL = "http://api.test/depictio/api/v1/thing"


class Recorder:
    """Counts attempts and the delays the policy asked for."""

    def __init__(self):
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)

    @property
    def sleeps(self) -> int:
        return len(self.delays)


def client_returning(*outcomes) -> httpx.Client:
    """A client whose successive calls yield the given statuses or exceptions."""
    remaining = list(outcomes)

    def handler(request: httpx.Request) -> httpx.Response:
        outcome = remaining.pop(0) if remaining else 200
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, tuple):
            status, headers = outcome
            return httpx.Response(status, headers=headers)
        return httpx.Response(outcome)

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestRetryableStatuses:
    def test_retries_then_succeeds(self):
        sleeper = Recorder()
        response = request_with_retry(
            "GET",
            URL,
            timeout=1.0,
            client=client_returning(503, 503, 200),
            sleep=sleeper,
        )
        assert response.status_code == 200
        assert sleeper.sleeps == 2

    def test_returns_the_last_response_when_attempts_run_out(self):
        sleeper = Recorder()
        response = request_with_retry(
            "GET",
            URL,
            timeout=1.0,
            retries=2,
            client=client_returning(503, 503, 503),
            sleep=sleeper,
        )
        # Callers keep their existing status-code handling rather than having to
        # catch a new exception type.
        assert response.status_code == 503
        assert sleeper.sleeps == 2

    @pytest.mark.parametrize("status", sorted(RETRYABLE_STATUS))
    def test_every_declared_status_is_retried(self, status):
        sleeper = Recorder()
        response = request_with_retry(
            "GET", URL, timeout=1.0, client=client_returning(status, 200), sleep=sleeper
        )
        assert response.status_code == 200
        assert sleeper.sleeps == 1

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413, 422])
    def test_client_errors_are_not_retried(self, status):
        sleeper = Recorder()
        response = request_with_retry(
            "GET", URL, timeout=1.0, client=client_returning(status, 200), sleep=sleeper
        )
        # Retrying a malformed or unauthorised request just burns time.
        assert response.status_code == status
        assert sleeper.sleeps == 0

    def test_success_does_not_sleep(self):
        sleeper = Recorder()
        request_with_retry("GET", URL, timeout=1.0, client=client_returning(200), sleep=sleeper)
        assert sleeper.sleeps == 0

    def test_retries_zero_disables_retrying(self):
        sleeper = Recorder()
        response = request_with_retry(
            "GET", URL, timeout=1.0, retries=0, client=client_returning(503, 200), sleep=sleeper
        )
        assert response.status_code == 503
        assert sleeper.sleeps == 0


class TestIdempotency:
    def test_read_timeout_is_retried_when_idempotent(self):
        sleeper = Recorder()
        response = request_with_retry(
            "POST",
            URL,
            timeout=1.0,
            idempotent=True,
            client=client_returning(httpx.ReadTimeout("slow"), 200),
            sleep=sleeper,
        )
        assert response.status_code == 200
        assert sleeper.sleeps == 1

    def test_read_timeout_is_not_retried_when_not_idempotent(self):
        sleeper = Recorder()
        # The server may already have appended the Aggregation; replaying would
        # create a second one plus a phantom version bump.
        with pytest.raises(httpx.ReadTimeout):
            request_with_retry(
                "POST",
                URL,
                timeout=1.0,
                idempotent=False,
                client=client_returning(httpx.ReadTimeout("slow"), 200),
                sleep=sleeper,
            )
        assert sleeper.sleeps == 0

    def test_server_error_is_not_retried_when_not_idempotent(self):
        sleeper = Recorder()
        response = request_with_retry(
            "POST",
            URL,
            timeout=1.0,
            idempotent=False,
            client=client_returning(500, 200),
            sleep=sleeper,
        )
        assert response.status_code == 500
        assert sleeper.sleeps == 0

    def test_connect_error_is_retried_even_when_not_idempotent(self):
        sleeper = Recorder()
        # A connection that was never established cannot have applied anything,
        # so replaying it is safe regardless of the endpoint's semantics.
        response = request_with_retry(
            "POST",
            URL,
            timeout=1.0,
            idempotent=False,
            client=client_returning(httpx.ConnectError("refused"), 200),
            sleep=sleeper,
        )
        assert response.status_code == 200
        assert sleeper.sleeps == 1

    def test_connect_error_propagates_after_the_last_attempt(self):
        sleeper = Recorder()
        with pytest.raises(httpx.ConnectError):
            request_with_retry(
                "GET",
                URL,
                timeout=1.0,
                retries=1,
                client=client_returning(
                    httpx.ConnectError("refused"), httpx.ConnectError("refused")
                ),
                sleep=sleeper,
            )
        assert sleeper.sleeps == 1


class TestBackoff:
    def test_delays_grow_exponentially(self):
        sleeper = Recorder()
        request_with_retry(
            "GET",
            URL,
            timeout=1.0,
            retries=3,
            backoff_base=1.0,
            jitter=0.0,
            client=client_returning(503, 503, 503, 200),
            sleep=sleeper,
        )
        assert sleeper.delays == [1.0, 2.0, 4.0]

    def test_delays_are_capped(self):
        sleeper = Recorder()
        request_with_retry(
            "GET",
            URL,
            timeout=1.0,
            retries=3,
            backoff_base=10.0,
            backoff_max=15.0,
            jitter=0.0,
            client=client_returning(503, 503, 503, 200),
            sleep=sleeper,
        )
        assert sleeper.delays == [10.0, 15.0, 15.0]

    def test_jitter_keeps_delays_in_band(self):
        sleeper = Recorder()
        request_with_retry(
            "GET",
            URL,
            timeout=1.0,
            retries=3,
            backoff_base=1.0,
            jitter=0.2,
            client=client_returning(503, 503, 503, 200),
            sleep=sleeper,
        )
        for delay, base in zip(sleeper.delays, [1.0, 2.0, 4.0]):
            assert base * 0.8 <= delay <= base * 1.2

    def test_retry_after_header_wins_over_backoff(self):
        sleeper = Recorder()
        request_with_retry(
            "GET",
            URL,
            timeout=1.0,
            backoff_base=1.0,
            jitter=0.0,
            client=client_returning((429, {"Retry-After": "7"}), 200),
            sleep=sleeper,
        )
        # A server that says how long to wait knows better than our curve.
        assert sleeper.delays == [7.0]

    def test_unparseable_retry_after_falls_back_to_backoff(self):
        sleeper = Recorder()
        request_with_retry(
            "GET",
            URL,
            timeout=1.0,
            backoff_base=1.0,
            jitter=0.0,
            client=client_returning((429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), 200),
            sleep=sleeper,
        )
        assert sleeper.delays == [1.0]
