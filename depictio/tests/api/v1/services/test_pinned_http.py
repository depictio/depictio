"""DNS rebinding: the outbound guards dial the address they validated.

``outbound_http`` (push targets) and ``remote_fetch`` (user URLs) check a
host's addresses before a request, then connect through
``services.pinned_http``, which resolves again, applies the same rule and
connects to that exact IP. These tests fake DNS with ``socket.getaddrinfo``
and run a local TCP server on 127.0.0.1 that counts the connections it
accepts, to prove a rebound name never reaches it.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpcore
import httpx
import pytest

from depictio.api.v1 import remote_fetch
from depictio.api.v1.configs.config import settings
from depictio.api.v1.remote_fetch import (
    RemoteFetchFailed,
    RemoteURLRejected,
    bounded_download,
    open_validated_stream,
    remote_policy,
)
from depictio.api.v1.services import outbound_http, pinned_http
from depictio.api.v1.services.outbound_http import RemoteError, ResolvedTarget, TargetClient
from depictio.api.v1.services.pinned_http import AddressRejected, PinnedBackend, pinned_transport

PUBLIC_IP = "93.184.216.34"
KEY = "k" * 40

_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
_GATEWAY_ENV_VARS = (
    "DEPICTIO_REMOTE_ALLOW_HTTP",
    "DEPICTIO_REMOTE_URL_ALLOWLIST",
    "DEPICTIO_REMOTE_URL_DENYLIST",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _PROXY_ENV_VARS + _GATEWAY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings.migration, "ui_target_host_allowlist", [])


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        body = b'{"instance_label": "local"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _CountingServer(ThreadingHTTPServer):
    accepted = 0

    def verify_request(self, request, client_address):  # called once per TCP accept
        self.accepted += 1
        return True


@pytest.fixture
def local_server():
    """A loopback HTTP server; yields (port, server) with ``server.accepted``."""
    server = _CountingServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _answer(address, port=0):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, port))]


def _fake_dns(monkeypatch, host, answers):
    """Make ``host`` resolve to ``answers[i]`` on call i (the last one repeats).

    Other names (the IP literals ``socket.create_connection`` resolves) go to
    the real resolver.
    """
    real = socket.getaddrinfo
    calls = []

    def fake(name, port, *args, **kwargs):
        if name != host:
            return real(name, port, *args, **kwargs)
        calls.append(name)
        return _answer(answers[min(len(calls), len(answers)) - 1], port or 0)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return calls


def _backend_of(client: httpx.Client):
    return client._transport._pool._network_backend


@pytest.fixture
def recording_connect(monkeypatch):
    """Replace ``SyncBackend.connect_tcp`` (what ``PinnedBackend`` calls via super()).

    Records the address dialled and the TLS server name, and never touches the
    network: the fake stream aborts the request at the TLS handshake.
    """
    recorded = SimpleNamespace(hosts=[], server_hostnames=[])

    class _Stream(httpcore.NetworkStream):
        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            recorded.server_hostnames.append(server_hostname)
            raise httpcore.ConnectError("stop here")

        def close(self):
            pass

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        recorded.hosts.append(host)
        return _Stream()

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect_tcp)
    return recorded


# ---------------------------------------------------------------------------
# The transport wiring itself (fails loudly if an httpx/httpcore upgrade
# stops honouring the swapped network backend).
# ---------------------------------------------------------------------------


class TestPinnedTransportWiring:
    def test_pool_uses_the_pinned_backend(self):
        transport = pinned_transport(lambda ip: None)
        assert isinstance(transport._pool, httpcore.ConnectionPool)
        assert isinstance(transport._pool._network_backend, PinnedBackend)

    def test_backend_is_actually_used_for_requests(self, local_server):
        port, server = local_server
        seen = []

        def validator(ip):
            seen.append(ip)
            return None

        with httpx.Client(transport=pinned_transport(validator)) as client:
            response = client.get(f"http://127.0.0.1:{port}/")
        assert response.status_code == 200
        assert seen == [ipaddress.ip_address("127.0.0.1")]

    def test_refusal_never_opens_a_connection(self, local_server):
        port, server = local_server
        with httpx.Client(transport=pinned_transport(lambda ip: "test refusal")) as client:
            with pytest.raises(AddressRejected, match="test refusal"):
                client.get(f"http://127.0.0.1:{port}/")
        assert server.accepted == 0

    def test_mixed_answer_is_refused(self, monkeypatch, recording_connect):
        real = socket.getaddrinfo
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda name, port, *a, **k: (
                _answer(PUBLIC_IP, port) + _answer("10.0.0.1", port)
                if name == "mixed.example"
                else real(name, port, *a, **k)
            ),
        )
        backend = PinnedBackend(lambda ip: "private" if ip.is_private else None)
        with pytest.raises(AddressRejected, match="private"):
            backend.connect_tcp("mixed.example", 443)
        assert recording_connect.hosts == []

    def test_proxy_applies_follows_env(self, monkeypatch):
        assert pinned_http.proxy_applies("https://a.example/") is False
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
        monkeypatch.setenv("NO_PROXY", "direct.example")
        assert pinned_http.proxy_applies("https://a.example/") is True
        assert pinned_http.proxy_applies("https://direct.example/") is False
        assert pinned_http.proxy_applies("http://a.example/") is False  # no HTTP_PROXY


# ---------------------------------------------------------------------------
# outbound_http (push targets)
# ---------------------------------------------------------------------------


def _target(url, trusted=False):
    return ResolvedTarget(id="t1", name="t", url=url, pairing_key=KEY, trusted=trusted)


@pytest.fixture
def direct(monkeypatch):
    """No proxy, whatever the machine's system settings say."""
    monkeypatch.setattr(outbound_http, "proxy_applies", lambda url: False)
    monkeypatch.setattr(remote_fetch, "proxy_applies", lambda url: False)


class TestOutboundHttp:
    def test_rebinding_refused_at_connect(self, monkeypatch, local_server, direct):
        port, server = local_server
        calls = _fake_dns(monkeypatch, "rebind.example", [PUBLIC_IP, "127.0.0.1"])
        with TargetClient(_target(f"https://rebind.example:{port}")) as client:
            with pytest.raises(RemoteError) as exc_info:
                client.info()
        assert exc_info.value.status_code == 400
        assert (
            exc_info.value.detail == "Target host 'rebind.example' resolves to a loopback address"
        )
        assert len(calls) == 2  # the pre-check, then the connect
        assert server.accepted == 0

    def test_public_answer_dials_the_validated_ip(self, monkeypatch, recording_connect, direct):
        _fake_dns(monkeypatch, "pin.example", [PUBLIC_IP])
        with TargetClient(_target("https://pin.example")) as client:
            with pytest.raises(RemoteError) as exc_info:
                client.info()
        assert exc_info.value.status_code == 502  # the recorder aborts the TLS handshake
        assert recording_connect.hosts == [PUBLIC_IP]
        assert recording_connect.server_hostnames == ["pin.example"]  # SNI keeps the name

    def test_proxied_target_keeps_the_plain_client(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
        assert outbound_http._pinned_transport(_target("https://far.example")) is None
        with TargetClient(_target("https://far.example")) as client:
            assert not isinstance(_backend_of(client._client), PinnedBackend)
            assert client._client._mounts  # httpx's env proxy is still in place

    def test_direct_target_is_pinned(self, direct):
        with TargetClient(_target("https://far.example")) as client:
            assert isinstance(_backend_of(client._client), PinnedBackend)

    def test_trusted_target_unchanged(self, local_server, direct):
        port, server = local_server
        with TargetClient(_target(f"http://127.0.0.1:{port}", trusted=True)) as client:
            assert not isinstance(_backend_of(client._client), PinnedBackend)
            assert client.info() == {"instance_label": "local"}
        assert server.accepted == 1

    def test_allowlisted_host_unchanged(self, monkeypatch, local_server, direct):
        port, server = local_server
        monkeypatch.setattr(settings.migration, "ui_target_host_allowlist", ["127.0.0.1"])
        with TargetClient(_target(f"http://127.0.0.1:{port}")) as client:
            assert not isinstance(_backend_of(client._client), PinnedBackend)
            assert client.info() == {"instance_label": "local"}

    def test_explicit_transport_is_kept(self, direct):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        with TargetClient(_target("https://far.example"), transport=transport) as client:
            assert client._client._transport is transport


# ---------------------------------------------------------------------------
# remote_fetch (user-supplied URLs)
# ---------------------------------------------------------------------------


class TestRemoteFetch:
    def test_rebinding_refused_at_connect(self, monkeypatch, local_server, direct):
        port, server = local_server
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        calls = _fake_dns(monkeypatch, "rebind.example", [PUBLIC_IP, "127.0.0.1"])
        with pytest.raises(RemoteURLRejected) as exc_info:
            with open_validated_stream(f"http://rebind.example:{port}/data", timeout=5):
                pass
        assert str(exc_info.value) == (
            "Host 'rebind.example' resolves to a non-public address and was rejected."
        )
        assert len(calls) == 2
        assert server.accepted == 0

    def test_rebinding_is_a_policy_refusal_for_downloads(
        self, monkeypatch, local_server, direct, tmp_path
    ):
        port, server = local_server
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        _fake_dns(monkeypatch, "rebind.example", [PUBLIC_IP, "127.0.0.1"])
        with pytest.raises(RemoteURLRejected) as exc_info:
            bounded_download(f"http://rebind.example:{port}/data", str(tmp_path / "out"))
        assert not isinstance(exc_info.value, RemoteFetchFailed)
        assert server.accepted == 0

    def test_public_answer_dials_the_validated_ip(self, monkeypatch, recording_connect, direct):
        _fake_dns(monkeypatch, "pin.example", [PUBLIC_IP])
        with pytest.raises(httpx.ConnectError):
            with open_validated_stream("https://pin.example/data.csv", timeout=5):
                pass
        assert recording_connect.hosts == [PUBLIC_IP]
        assert recording_connect.server_hostnames == ["pin.example"]

    def test_proxied_url_keeps_the_plain_client(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
        monkeypatch.setenv("NO_PROXY", "direct.example")
        policy = remote_policy()
        with remote_fetch._gateway_client("https://far.example/x", 5, policy) as client:
            assert not isinstance(_backend_of(client), PinnedBackend)
            assert client._mounts
        with remote_fetch._gateway_client("https://direct.example/x", 5, policy) as client:
            assert isinstance(_backend_of(client), PinnedBackend)

    def test_allowlisted_policy_unchanged(self, monkeypatch, local_server, direct):
        port, server = local_server
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "127.0.0.1")
        policy = remote_policy()
        with remote_fetch._gateway_client(f"http://127.0.0.1:{port}/", 5, policy) as client:
            assert not isinstance(_backend_of(client), PinnedBackend)
        with open_validated_stream(f"http://127.0.0.1:{port}/", timeout=5) as response:
            assert response.status_code == 200
        assert server.accepted == 1

    def test_redirect_hop_still_checked_before_connect(self, monkeypatch, direct):
        # The per-hop pre-check stays: a redirect to 10.0.0.1 is refused by
        # ``validate_remote_url`` before any client is opened for that hop.
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        monkeypatch.setattr(
            remote_fetch,
            "_resolve_addresses",
            lambda host: [ipaddress.ip_address(PUBLIC_IP if host == "a.example" else host)],
        )
        opened = []

        def gateway_client(url, timeout_s, policy):
            opened.append(url)
            return httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(302, headers={"location": "http://10.0.0.1/"})
                )
            )

        monkeypatch.setattr(remote_fetch, "_gateway_client", gateway_client)
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            with open_validated_stream("http://a.example/start", timeout=5):
                pass
        assert opened == ["http://a.example/start"]
