"""A single-user server says in its log when it is reached through the network."""

import asyncio

import pytest

from depictio.api.v1 import single_user_exposure as sue


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost:5080",
        "127.0.0.1:5080",
        "127.0.0.2",
        "[::1]:5080",
        "::1",
        "app.localhost:5080",
        "depictio-backend:8058",  # compose service name
        "",
    ],
)
def test_local_hosts(host):
    assert sue.host_is_local(host)


@pytest.mark.parametrize(
    "host",
    ["192.168.1.20:5080", "10.0.0.5", "mylaptop.lab.example.org", "[fe80::1]:5080", "8.8.8.8"],
)
def test_network_hosts(host):
    assert not sue.host_is_local(host)


def _run(mw, host: str | None, forwarded: str | None = None):
    headers = []
    if host is not None:
        headers.append((b"host", host.encode()))
    if forwarded is not None:
        headers.append((b"x-forwarded-host", forwarded.encode()))
    asyncio.run(mw({"type": "http", "headers": headers}, None, None))


@pytest.fixture
def app_calls():
    calls = []

    async def app(scope, receive, send):
        calls.append(scope)

    return app, calls


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(sue.logger, "error", lambda msg, *a, **k: seen.append(msg))
    return seen


def test_warns_once_per_network_host_and_always_serves(app_calls, warnings):
    app, calls = app_calls
    mw = sue.SingleUserExposureWarning(app)
    _run(mw, "localhost:5080")
    _run(mw, "192.168.1.20:5080")
    _run(mw, "192.168.1.20:5080")
    _run(mw, "localhost:5080", forwarded="mylaptop.lab.example.org")
    assert len(calls) == 4  # never blocks
    assert len(warnings) == 2
    assert "192.168.1.20:5080" in warnings[0]
    assert "mylaptop.lab.example.org" in warnings[1]


def test_reported_hosts_are_bounded(app_calls, warnings):
    app, _ = app_calls
    mw = sue.SingleUserExposureWarning(app)
    for i in range(100):
        _run(mw, f"10.0.0.{i}")
    assert len(warnings) == sue._MAX_REPORTED_HOSTS


def test_lifespan_scope_passes_through(app_calls, warnings):
    app, calls = app_calls
    mw = sue.SingleUserExposureWarning(app)
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert len(calls) == 1 and not warnings
