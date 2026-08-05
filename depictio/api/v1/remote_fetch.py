"""SSRF-hardened gateway for all server-side reads of user-supplied URLs.

Every remote fetch triggered by user input (``create_from_url``, manifest
ingestion, Celery tasks) must go through this module — never call httpx on a
user-supplied URL directly. See docs/design/rfc-remote-data-manifests.md §5.2.

What it enforces:
- scheme allowlist (https, s3; http only behind ``DEPICTIO_REMOTE_ALLOW_HTTP``);
- DNS resolution + rejection of private / loopback / link-local / reserved
  ranges (including the cloud metadata endpoint 169.254.169.254);
- re-validation on every redirect hop, with a hop cap;
- bounded, streamed downloads (size cap + timeout);
- optional admin allow/deny lists via ``DEPICTIO_REMOTE_URL_ALLOWLIST`` /
  ``DEPICTIO_REMOTE_URL_DENYLIST`` (comma-separated host names; an allowlisted
  host bypasses the private-range rejection, which is how airgapped/internal
  deployments — and tests against 127.0.0.1 — opt in).

Known residual risk (documented in the RFC): DNS rebinding between the check
and the fetch. Hardened deployments should run allowlist-only.
"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

import httpx

# The models logger keeps this module import-light: pulling the API logging
# stack would trigger full Settings validation, which unit tests (and the CLI
# process) must not require.
from depictio.models.logging import logger
from depictio.models.models.manifest import is_remote_url

MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500MB


class RemoteURLRejected(ValueError):
    """Raised when a URL fails the gateway's safety checks.

    The message is safe to surface to API clients (no internal details).
    """


def _env_hosts(var: str) -> set[str]:
    raw = os.environ.get(var, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _max_download_bytes() -> int:
    raw = os.environ.get("DEPICTIO_REMOTE_MAX_DOWNLOAD_BYTES", "")
    try:
        return int(raw) if raw else DEFAULT_MAX_DOWNLOAD_BYTES
    except ValueError:
        return DEFAULT_MAX_DOWNLOAD_BYTES


def _resolve_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise RemoteURLRejected(f"Could not resolve host '{host}'.")
    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not addresses:
        raise RemoteURLRejected(f"Could not resolve host '{host}'.")
    return addresses


def validate_remote_url(url: str) -> None:
    """Validate a user-supplied URL before any fetch. Raises ``RemoteURLRejected``.

    ``s3://`` URLs skip the DNS/IP checks — they are read through the object
    store client with the instance's configured credentials, not fetched over
    arbitrary HTTP.
    """
    if not is_remote_url(url):
        raise RemoteURLRejected(
            "URL scheme not allowed. Use s3:// or https:// "
            "(http:// only when DEPICTIO_REMOTE_ALLOW_HTTP is set)."
        )

    parsed = urlparse(url)
    if parsed.scheme == "s3":
        if not parsed.netloc:
            raise RemoteURLRejected("s3:// URL must include a bucket.")
        return

    host = (parsed.hostname or "").lower()
    if not host:
        raise RemoteURLRejected("URL has no host.")

    denylist = _env_hosts("DEPICTIO_REMOTE_URL_DENYLIST")
    if host in denylist:
        raise RemoteURLRejected(f"Host '{host}' is denied by the administrator.")

    allowlist = _env_hosts("DEPICTIO_REMOTE_URL_ALLOWLIST")
    if allowlist:
        if host in allowlist:
            return  # explicit trust: bypass the private-range rejection
        raise RemoteURLRejected(f"Host '{host}' is not in the administrator allowlist.")

    for address in _resolve_addresses(host):
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise RemoteURLRejected(
                f"Host '{host}' resolves to a non-public address and was rejected."
            )


def _open_stream(client: httpx.Client, url: str, method: str = "GET"):
    """Follow up to MAX_REDIRECTS manually, re-validating every hop."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        request = client.build_request(method, current)
        response = client.send(request, stream=(method == "GET"))
        if response.is_redirect:
            response.close()
            location = response.headers.get("location")
            if not location:
                raise RemoteURLRejected("Redirect without a Location header.")
            current = str(httpx.URL(current).join(location))
            validate_remote_url(current)
            continue
        return response
    raise RemoteURLRejected(f"Too many redirects (> {MAX_REDIRECTS}).")


def probe_remote_url(url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """HEAD the URL through the gateway. Returns ``{"size": int, "etag": str}``
    with ``size = -1`` when unknown. s3:// URLs return unknowns (probed later
    by the object-store client)."""
    validate_remote_url(url)
    if urlparse(url).scheme == "s3":
        return {"size": -1, "etag": ""}
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
            response = _open_stream(client, url, method="HEAD")
            size_header = response.headers.get("content-length")
            size = int(size_header) if size_header and size_header.isdigit() else -1
            return {"size": size, "etag": response.headers.get("etag", "")}
    except RemoteURLRejected:
        raise
    except Exception as exc:
        # Sanitize: never echo internal fetch errors to clients.
        logger.warning(f"Remote probe failed for {url}: {exc}")
        raise RemoteURLRejected("Could not reach the provided URL.")


def bounded_download(
    url: str,
    dest_path: str,
    max_bytes: int | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> int:
    """Stream the URL to ``dest_path`` through the gateway, enforcing a size cap.

    Returns the number of bytes written. Raises ``RemoteURLRejected`` on any
    safety or fetch failure (sanitized message).
    """
    validate_remote_url(url)
    cap = max_bytes if max_bytes is not None else _max_download_bytes()
    written = 0
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
            response = _open_stream(client, url, method="GET")
            try:
                response.raise_for_status()
                with open(dest_path, "wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        written += len(chunk)
                        if written > cap:
                            raise RemoteURLRejected(
                                f"Remote file exceeds the download cap ({cap} bytes)."
                            )
                        fh.write(chunk)
            finally:
                response.close()
    except RemoteURLRejected:
        _cleanup_partial(dest_path)
        raise
    except Exception as exc:
        logger.warning(f"Remote download failed for {url}: {exc}")
        _cleanup_partial(dest_path)
        raise RemoteURLRejected("Could not download the provided URL.")
    return written


def _cleanup_partial(dest_path: str) -> None:
    """Never leave a partial download behind on failure."""
    try:
        os.unlink(dest_path)
    except OSError:
        pass
