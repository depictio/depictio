"""Unit tests for the SSRF-hardened remote fetch gateway.

Pure-validation tests exercise ``validate_remote_url`` without any network.
Probe/download tests run a real in-process HTTP server on 127.0.0.1 and opt
the loopback host in via ``DEPICTIO_REMOTE_ALLOW_HTTP`` +
``DEPICTIO_REMOTE_URL_ALLOWLIST`` (the documented way tests/airgapped
deployments bypass the private-range rejection).
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from depictio.api.v1.remote_fetch import (
    MAX_REDIRECTS,
    RemoteURLRejected,
    bounded_download,
    probe_remote_url,
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
            self.send_response(302)
            self.send_header("Location", "/data.bin")
            self.end_headers()
        elif self.path == "/redirect-evil":
            self.send_response(302)
            self.send_header("Location", "https://10.0.0.1/secret")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
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
        # connect; the raised message must stay generic (no internal details).
        with pytest.raises(RemoteURLRejected, match="Could not reach"):
            probe_remote_url("http://127.0.0.1:1/x", timeout_s=2)


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
        assert MAX_REDIRECTS == 3

    def test_http_error_status_sanitized(self, loopback_env, http_server, tmp_path):
        with pytest.raises(RemoteURLRejected, match="Could not download"):
            bounded_download(f"{http_server}/missing", str(tmp_path / "o.bin"), timeout_s=5)
