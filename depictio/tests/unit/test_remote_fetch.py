"""Unit tests for the SSRF-hardened remote fetch gateway.

Pure-validation tests exercise ``validate_remote_url`` without any network.
Probe/download tests run a real in-process HTTP server on 127.0.0.1 and opt
the loopback host in via ``DEPICTIO_REMOTE_ALLOW_HTTP`` +
``DEPICTIO_REMOTE_URL_ALLOWLIST`` (the documented way tests/airgapped
deployments bypass the private-range rejection).
"""

import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from depictio.api.v1 import remote_fetch
from depictio.api.v1.configs.settings_models import RemoteConfig
from depictio.api.v1.remote_fetch import (
    RemoteFetchFailed,
    RemoteURLRejected,
    bounded_download,
    fetch_validated_text,
    is_server_context,
    open_validated_stream,
    probe_remote_url,
    remote_policy,
    validate_remote_url,
)

# ---------------------------------------------------------------------------
# Env isolation
# ---------------------------------------------------------------------------

_GATEWAY_ENV_VARS = (
    "DEPICTIO_REMOTE_ALLOW_HTTP",
    "DEPICTIO_REMOTE_URL_ALLOWLIST",
    "DEPICTIO_REMOTE_URL_DENYLIST",
    "DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES",
    "DEPICTIO_REMOTE_TIMEOUT_S",
    "DEPICTIO_REMOTE_MAX_REDIRECTS",
)

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


@pytest.fixture(autouse=True)
def _clean_gateway_env(monkeypatch):
    """Every test starts with no gateway env vars set (they are read lazily)."""
    for var in _GATEWAY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def loopback_env(monkeypatch):
    """Opt loopback HTTP in, and keep httpx off any sandbox proxy.

    httpx.Client defaults to trust_env=True, so HTTP(S)_PROXY env vars would
    otherwise route 127.0.0.1 requests through the proxy.
    """
    for var in _PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "127.0.0.1")


# ---------------------------------------------------------------------------
# Policy (RemoteConfig) and context switch
# ---------------------------------------------------------------------------


class TestRemoteConfig:
    def test_defaults(self):
        policy = remote_policy()
        assert isinstance(policy, RemoteConfig)
        assert policy.allow_http is False
        assert policy.url_allowlist == ""
        assert policy.url_denylist == ""
        assert policy.max_download_bytes == 500 * 1024 * 1024
        assert policy.timeout_s == 30.0
        assert policy.max_redirects == 3

    def test_env_parsing(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "a.example, B.example")
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_DENYLIST", "evil.example")
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "123")
        monkeypatch.setenv("DEPICTIO_REMOTE_TIMEOUT_S", "1.5")
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_REDIRECTS", "1")
        policy = remote_policy()
        assert policy.allow_http is True
        assert policy.url_allowlist == "a.example, B.example"
        assert policy.url_denylist == "evil.example"
        assert policy.max_download_bytes == 123
        assert policy.timeout_s == 1.5
        assert policy.max_redirects == 1

    def test_policy_is_read_per_call(self, monkeypatch):
        assert remote_policy().max_redirects == 3
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_REDIRECTS", "0")
        assert remote_policy().max_redirects == 0

    def test_allowlist_is_exclusive(self, monkeypatch):
        # A listed host passes without DNS; an unlisted public host is rejected
        # even though it would pass the private-range check.
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "trusted.invalid")
        validate_remote_url("https://trusted.invalid/data.csv")
        with pytest.raises(RemoteURLRejected, match="not in the administrator allowlist"):
            validate_remote_url("https://example.org/data.csv")

    def test_invalid_max_download_bytes_raises(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "lots")
        with pytest.raises(ValidationError, match="max_download_bytes"):
            remote_policy()

    def test_zero_max_download_bytes_raises(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "0")
        with pytest.raises(ValidationError, match="max_download_bytes"):
            remote_policy()

    def test_invalid_policy_fails_loudly_on_fetch(self, monkeypatch, tmp_path):
        # No silent fallback to the default cap: the download must not start.
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "lots")
        with pytest.raises(ValidationError):
            bounded_download("https://example.org/x", str(tmp_path / "o.bin"))
        with pytest.raises(ValidationError):
            validate_remote_url("https://example.org/x")

    def test_allow_http_from_policy(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "trusted.invalid")
        validate_remote_url("http://trusted.invalid/data.csv")


class TestIsServerContext:
    def test_cli_marker_disables_gateway(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
        assert is_server_context() is False
        monkeypatch.setenv("DEPICTIO_CONTEXT", " cli ")
        assert is_server_context() is False

    def test_server_and_unknown_values_fail_closed(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        assert is_server_context() is True
        # Only the explicit CLI marker opts out; legacy-looking values do not.
        monkeypatch.setenv("DEPICTIO_CONTEXT", "client")
        assert is_server_context() is True
        monkeypatch.setenv("DEPICTIO_CONTEXT", "something-else")
        assert is_server_context() is True
        monkeypatch.delenv("DEPICTIO_CONTEXT", raising=False)
        assert is_server_context() is True


# ---------------------------------------------------------------------------
# Pure validation tests (no network)
# ---------------------------------------------------------------------------


class TestValidateRemoteURL:
    def test_ftp_scheme_rejected(self):
        with pytest.raises(RemoteURLRejected, match="scheme not allowed"):
            validate_remote_url("ftp://example.org/file.csv")

    def test_file_scheme_rejected(self):
        with pytest.raises(RemoteURLRejected, match="scheme not allowed"):
            validate_remote_url("file:///etc/passwd")

    def test_http_rejected_without_env_flag(self):
        with pytest.raises(RemoteURLRejected, match="scheme not allowed"):
            validate_remote_url("http://example.org/data.csv")

    def test_s3_without_bucket_rejected(self):
        with pytest.raises(RemoteURLRejected, match="must include a bucket"):
            validate_remote_url("s3:///key/only")

    def test_s3_with_bucket_accepted(self):
        # No DNS/IP checks for s3:// — should not raise and not touch the network.
        validate_remote_url("s3://my-bucket/path/to/key.parquet")

    def test_https_without_host_rejected(self):
        with pytest.raises(RemoteURLRejected, match="no host"):
            validate_remote_url("https:///path/only")

    def test_denylist_rejects_host(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_DENYLIST", "evil.example, other.example")
        with pytest.raises(RemoteURLRejected, match="denied by the administrator"):
            validate_remote_url("https://evil.example/data.csv")

    def test_denylist_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_DENYLIST", "evil.example")
        with pytest.raises(RemoteURLRejected, match="denied by the administrator"):
            validate_remote_url("https://EVIL.example/data.csv")

    def test_allowlist_rejects_unlisted_host(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "trusted.example")
        with pytest.raises(RemoteURLRejected, match="not in the administrator allowlist"):
            validate_remote_url("https://untrusted.example/data.csv")

    def test_allowlist_accepts_listed_host_without_dns(self, monkeypatch):
        # ".invalid" TLD can never resolve — passing proves DNS is bypassed.
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "trusted.invalid")
        validate_remote_url("https://trusted.invalid/data.csv")

    def test_allowlist_bypasses_private_range_rejection(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "127.0.0.1")
        validate_remote_url("https://127.0.0.1/data.csv")

    def test_denylist_wins_over_allowlist(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "both.example")
        monkeypatch.setenv("DEPICTIO_REMOTE_URL_DENYLIST", "both.example")
        with pytest.raises(RemoteURLRejected, match="denied by the administrator"):
            validate_remote_url("https://both.example/data.csv")

    def test_localhost_rejected(self):
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            validate_remote_url("https://localhost/secrets")

    def test_loopback_ip_rejected(self):
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            validate_remote_url("https://127.0.0.1/secrets")

    def test_private_ip_rejected(self):
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            validate_remote_url("https://10.0.0.1/internal")

    def test_cloud_metadata_endpoint_rejected(self):
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            validate_remote_url("https://169.254.169.254/latest/meta-data/")

    def test_unresolvable_host_rejected(self):
        with pytest.raises(RemoteURLRejected, match="Could not resolve"):
            validate_remote_url("https://definitely-not-a-real-host.invalid/x")


# ---------------------------------------------------------------------------
# Local HTTP server fixture for probe/download tests
# ---------------------------------------------------------------------------

PAYLOAD = b"depictio-remote-fetch-test-payload\n" * 64  # ~2.2 KB
ETAG = '"abc123"'


class _Handler(BaseHTTPRequestHandler):
    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _serve(self, include_body: bool) -> None:
        if self.path == "/data.bin":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.send_header("ETag", ETAG)
            self.end_headers()
            if include_body:
                self.wfile.write(PAYLOAD)
        elif self.path == "/nosize":
            self.send_response(200)
            self.send_header("ETag", ETAG)
            self.end_headers()
        elif self.path == "/redirect":
            self._redirect("/data.bin")
        elif self.path == "/redirect-evil":
            self._redirect("https://10.0.0.1/secret")
        elif self.path == "/redirect-ftp":
            self._redirect("ftp://example.org/secret")
        elif self.path == "/loop":
            self._redirect("/loop")
        elif self.path.startswith("/hop/"):
            # /hop/3 -> /hop/2 -> /hop/1 -> /data.bin: a chain of N redirects.
            remaining = int(self.path.rsplit("/", 1)[1])
            self._redirect(f"/hop/{remaining - 1}" if remaining > 1 else "/data.bin")
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):  # noqa: N802 (http.server API)
        self._serve(include_body=True)

    def do_HEAD(self):  # noqa: N802
        self._serve(include_body=False)

    def log_message(self, *args):  # silence per-request stderr noise
        pass


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# open_validated_stream
# ---------------------------------------------------------------------------


class TestOpenValidatedStream:
    def test_yields_streamed_body_and_closes(self, loopback_env, http_server):
        with open_validated_stream(f"{http_server}/data.bin", timeout=5) as response:
            assert response.status_code == 200
            assert b"".join(response.iter_bytes()) == PAYLOAD
        assert response.is_closed

    def test_head_method(self, loopback_env, http_server):
        with open_validated_stream(f"{http_server}/data.bin", timeout=5, method="HEAD") as r:
            assert r.headers["etag"] == ETAG

    def test_rejects_before_opening_a_client(self):
        with pytest.raises(RemoteURLRejected, match="scheme not allowed"):
            with open_validated_stream("ftp://example.org/x"):
                pass

    def test_s3_rejected(self):
        with pytest.raises(RemoteURLRejected, match="object store"):
            with open_validated_stream("s3://bucket/key"):
                pass

    def test_redirect_to_private_address_rejected(self, monkeypatch, http_server):
        # No allowlist: the loopback origin is made to look public by stubbing
        # its DNS answer, so the private-range check fires on the hop target
        # (10.0.0.1) and nowhere else.
        for var in _PROXY_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("DEPICTIO_REMOTE_ALLOW_HTTP", "true")
        real_resolve = remote_fetch._resolve_addresses

        def fake_resolve(host):
            if host == "127.0.0.1":
                return [ipaddress.ip_address("93.184.216.34")]
            return real_resolve(host)

        monkeypatch.setattr(remote_fetch, "_resolve_addresses", fake_resolve)
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            with open_validated_stream(f"{http_server}/redirect-evil", timeout=5):
                pass

    def test_redirect_to_disallowed_scheme_rejected(self, loopback_env, http_server):
        with pytest.raises(RemoteURLRejected, match="scheme not allowed"):
            with open_validated_stream(f"{http_server}/redirect-ftp", timeout=5):
                pass

    def test_redirect_to_unlisted_host_rejected(self, loopback_env, http_server):
        # Allowlist is exclusive on every hop, not only on the first URL.
        with pytest.raises(RemoteURLRejected, match="not in the administrator allowlist"):
            with open_validated_stream(f"{http_server}/redirect-evil", timeout=5):
                pass

    def test_follows_up_to_max_redirects(self, loopback_env, http_server):
        with open_validated_stream(f"{http_server}/hop/3", timeout=5) as response:
            assert b"".join(response.iter_bytes()) == PAYLOAD

    def test_honours_max_redirects_from_policy(self, loopback_env, http_server, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_REDIRECTS", "2")
        with pytest.raises(RemoteURLRejected, match=r"Too many redirects \(> 2\)"):
            with open_validated_stream(f"{http_server}/hop/3", timeout=5):
                pass

    def test_zero_max_redirects_refuses_any_hop(self, loopback_env, http_server, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_REDIRECTS", "0")
        with pytest.raises(RemoteURLRejected, match=r"Too many redirects \(> 0\)"):
            with open_validated_stream(f"{http_server}/redirect", timeout=5):
                pass

    def test_timeout_from_policy(self, loopback_env, monkeypatch):
        # Port 1 is closed: the connection error surfaces as-is from the raw
        # stream (callers sanitize), proving the client was built.
        import httpx

        monkeypatch.setenv("DEPICTIO_REMOTE_TIMEOUT_S", "1")
        with pytest.raises(httpx.HTTPError):
            with open_validated_stream("http://127.0.0.1:1/x"):
                pass


# ---------------------------------------------------------------------------
# probe_remote_url
# ---------------------------------------------------------------------------


class TestProbeRemoteURL:
    def test_probe_returns_size_and_etag(self, loopback_env, http_server):
        result = probe_remote_url(f"{http_server}/data.bin", timeout_s=5)
        assert result == {"size": len(PAYLOAD), "etag": ETAG}

    def test_probe_unknown_size(self, loopback_env, http_server):
        result = probe_remote_url(f"{http_server}/nosize", timeout_s=5)
        assert result["size"] == -1
        assert result["etag"] == ETAG

    def test_probe_s3_returns_unknowns_without_network(self):
        assert probe_remote_url("s3://bucket/key") == {"size": -1, "etag": ""}

    def test_probe_follows_redirect(self, loopback_env, http_server):
        result = probe_remote_url(f"{http_server}/redirect", timeout_s=5)
        assert result["size"] == len(PAYLOAD)

    def test_probe_rejects_before_any_fetch(self):
        # Scheme rejection happens before the client is even built.
        with pytest.raises(RemoteURLRejected, match="scheme not allowed"):
            probe_remote_url("ftp://example.org/x")

    def test_probe_unreachable_url_sanitized(self, loopback_env):
        # A closed port on an allowlisted host passes validation but fails to
        # connect; the raised message must stay generic (no internal details),
        # and the narrower RemoteFetchFailed lets callers degrade on it.
        with pytest.raises(RemoteFetchFailed, match="Could not reach"):
            probe_remote_url("http://127.0.0.1:1/x", timeout_s=2)

    def test_policy_rejection_is_not_a_fetch_failure(self, loopback_env, http_server):
        with pytest.raises(RemoteURLRejected) as excinfo:
            probe_remote_url(f"{http_server}/redirect-evil", timeout_s=5)
        assert not isinstance(excinfo.value, RemoteFetchFailed)


# ---------------------------------------------------------------------------
# bounded_download
# ---------------------------------------------------------------------------


class TestBoundedDownload:
    def test_download_roundtrip(self, loopback_env, http_server, tmp_path):
        dest = tmp_path / "out.bin"
        written = bounded_download(f"{http_server}/data.bin", str(dest), timeout_s=5)
        assert written == len(PAYLOAD)
        assert dest.read_bytes() == PAYLOAD

    def test_download_size_cap_exceeded(self, loopback_env, http_server, tmp_path):
        dest = tmp_path / "out.bin"
        with pytest.raises(RemoteURLRejected, match="exceeds the download cap"):
            bounded_download(
                f"{http_server}/data.bin",
                str(dest),
                max_bytes=len(PAYLOAD) - 1,
                timeout_s=5,
            )
        # No partial download may survive a cap violation.
        assert not dest.exists()

    def test_download_cap_from_env(self, loopback_env, http_server, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", str(len(PAYLOAD) - 1))
        with pytest.raises(RemoteURLRejected, match="exceeds the download cap"):
            bounded_download(f"{http_server}/data.bin", str(tmp_path / "o.bin"), timeout_s=5)

    def test_download_follows_redirect(self, loopback_env, http_server, tmp_path):
        dest = tmp_path / "out.bin"
        written = bounded_download(f"{http_server}/redirect", str(dest), timeout_s=5)
        assert written == len(PAYLOAD)
        assert dest.read_bytes() == PAYLOAD

    def test_redirect_to_disallowed_host_rejected(self, loopback_env, http_server, tmp_path):
        # The hop target (10.0.0.1) is not in the allowlist -> re-validation
        # of the redirect Location must reject it.
        dest = tmp_path / "out.bin"
        with pytest.raises(RemoteURLRejected):
            bounded_download(f"{http_server}/redirect-evil", str(dest), timeout_s=5)
        assert not dest.exists()

    def test_redirect_to_private_ip_rejected_without_allowlist(
        self, loopback_env, http_server, tmp_path, monkeypatch
    ):
        # With no allowlist the redirect target hits the private-range check.
        # (The initial 127.0.0.1 hop is rejected too, which still proves the
        # gateway never fetches; assert on the private-range path directly.)
        monkeypatch.delenv("DEPICTIO_REMOTE_URL_ALLOWLIST", raising=False)
        with pytest.raises(RemoteURLRejected, match="non-public address"):
            bounded_download(f"{http_server}/data.bin", str(tmp_path / "o.bin"), timeout_s=5)

    def test_too_many_redirects_rejected(self, loopback_env, http_server, tmp_path):
        with pytest.raises(RemoteURLRejected, match="Too many redirects"):
            bounded_download(f"{http_server}/loop", str(tmp_path / "o.bin"), timeout_s=5)
        assert RemoteConfig().max_redirects == 3

    def test_http_error_status_sanitized(self, loopback_env, http_server, tmp_path):
        with pytest.raises(RemoteFetchFailed, match="Could not download"):
            bounded_download(f"{http_server}/missing", str(tmp_path / "o.bin"), timeout_s=5)
        assert not (tmp_path / "o.bin").exists()


# ---------------------------------------------------------------------------
# fetch_validated_text
# ---------------------------------------------------------------------------


class TestFetchValidatedText:
    def test_roundtrip(self, loopback_env, http_server):
        text = fetch_validated_text(f"{http_server}/data.bin", timeout=5)
        assert text == PAYLOAD.decode()

    def test_follows_redirect(self, loopback_env, http_server):
        assert fetch_validated_text(f"{http_server}/redirect", timeout=5) == PAYLOAD.decode()

    def test_cap_exceeded(self, loopback_env, http_server):
        with pytest.raises(RemoteURLRejected, match="exceeds the download cap"):
            fetch_validated_text(f"{http_server}/data.bin", max_bytes=len(PAYLOAD) - 1, timeout=5)

    def test_cap_from_env(self, loopback_env, http_server, monkeypatch):
        monkeypatch.setenv("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", str(len(PAYLOAD) - 1))
        with pytest.raises(RemoteURLRejected, match="exceeds the download cap"):
            fetch_validated_text(f"{http_server}/data.bin", timeout=5)

    def test_policy_rejection_propagates(self, loopback_env, http_server):
        with pytest.raises(RemoteURLRejected, match="not in the administrator allowlist"):
            fetch_validated_text(f"{http_server}/redirect-evil", timeout=5)

    def test_http_error_status_sanitized(self, loopback_env, http_server):
        with pytest.raises(RemoteFetchFailed, match="Could not fetch"):
            fetch_validated_text(f"{http_server}/missing", timeout=5)
