"""SSRF-hardened gateway for reads of user-supplied URLs.

Every remote fetch triggered by user input (``create_from_url``, manifest
ingestion, Celery tasks, and the scan/read helpers the API runs in-process)
must go through this module in server context. Never call httpx on a
user-supplied URL directly there. See docs/design/rfc-remote-data-manifests.md
section 5.2.

What it enforces:
- scheme allowlist (https, s3; http only behind ``DEPICTIO_REMOTE_ALLOW_HTTP``);
- DNS resolution + rejection of private / loopback / link-local / reserved
  ranges (including the cloud metadata endpoint 169.254.169.254);
- re-validation on every redirect hop, with a hop cap;
- bounded, streamed downloads (size cap + timeout);
- optional admin allow/deny lists via ``DEPICTIO_REMOTE_URL_ALLOWLIST`` /
  ``DEPICTIO_REMOTE_URL_DENYLIST`` (comma-separated host names; an allowlisted
  host bypasses the private-range rejection, which is how airgapped/internal
  deployments and tests against 127.0.0.1 opt in).

Policy knobs live in ``RemoteConfig`` (``depictio.api.v1.configs.settings_models``)
and are read from the environment on every call through :func:`remote_policy`.
CLI context (``DEPICTIO_CONTEXT=CLI``) reads directly, since loopback and
intranet hosts are the user's own, but reuses the same redirect and size caps
through the ``direct_*`` counterparts at the bottom of this module.

Known residual risk (documented in the RFC): DNS rebinding between the check
and the fetch. Hardened deployments should run allowlist-only.
"""

import ipaddress
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

import httpx

# Import-light on purpose: the settings section is a plain pydantic-settings
# model, and the models logger avoids the API logging stack. Pulling
# ``depictio.api.v1.configs.config`` here would run full Settings validation
# (and mint JWT keys) in the CLI process and in unit tests.
from depictio.api.v1.configs.settings_models import RemoteConfig
from depictio.models.logging import logger
from depictio.models.utils import get_depictio_context

_CHUNK_BYTES = 1024 * 1024


class RemoteURLRejected(ValueError):
    """Raised when a URL fails the gateway's safety checks.

    The message is safe to surface to API clients (no internal details).
    """


class RemoteFetchFailed(RemoteURLRejected):
    """Raised when a URL passed validation but could not be fetched.

    Covers transport errors and HTTP error statuses, with the original cause
    logged and a sanitized message. Subclass of :class:`RemoteURLRejected` so
    existing ``except RemoteURLRejected`` handlers keep catching it; callers
    that want to degrade on reachability but abort on policy catch this one.
    """


def remote_policy() -> RemoteConfig:
    """Current gateway policy, read from ``DEPICTIO_REMOTE_*`` on every call.

    Instantiated here rather than taken from the ``settings`` singleton so the
    CLI and the Celery worker apply the same policy without importing the full
    API config, and so tests can monkeypatch env vars between calls. A
    malformed value raises pydantic's ``ValidationError``, which names the
    offending variable; there is deliberately no silent fallback.
    """
    return RemoteConfig()


def is_server_context() -> bool:
    """Whether remote reads must go through the gateway.

    Uses the process-wide ``DEPICTIO_CONTEXT`` switch (``depictio_cli.py`` sets
    it to ``CLI``; the API and worker run as ``server``). Only an explicit
    ``cli`` value opts out of the gateway, so an unset or unexpected value
    fails closed. Same rule as ``templates._is_cli_context``.
    """
    return get_depictio_context().strip().lower() != "cli"


def _split_hosts(raw: str) -> set[str]:
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


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


def validate_remote_url(url: str, policy: RemoteConfig | None = None) -> None:
    """Validate a user-supplied URL before any fetch. Raises ``RemoteURLRejected``.

    ``s3://`` URLs skip the DNS/IP checks: they are read through the object
    store client with the instance's configured credentials, not fetched over
    arbitrary HTTP. ``policy`` lets the redirect loop reuse one policy read
    across hops; callers normally leave it unset.
    """
    policy = policy if policy is not None else remote_policy()
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "s3") and not (scheme == "http" and policy.allow_http):
        raise RemoteURLRejected(
            "URL scheme not allowed. Use s3:// or https:// "
            "(http:// only when DEPICTIO_REMOTE_ALLOW_HTTP is set)."
        )

    if scheme == "s3":
        if not parsed.netloc:
            raise RemoteURLRejected("s3:// URL must include a bucket.")
        return

    host = (parsed.hostname or "").lower()
    if not host:
        raise RemoteURLRejected("URL has no host.")

    if host in _split_hosts(policy.url_denylist):
        raise RemoteURLRejected(f"Host '{host}' is denied by the administrator.")

    allowlist = _split_hosts(policy.url_allowlist)
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


def _follow_redirects(
    client: httpx.Client, url: str, method: str, policy: RemoteConfig
) -> httpx.Response:
    """Follow up to ``policy.max_redirects`` hops manually, re-validating each."""
    current = url
    for _ in range(policy.max_redirects + 1):
        request = client.build_request(method, current)
        response = client.send(request, stream=True)
        if response.is_redirect:
            response.close()
            location = response.headers.get("location")
            if not location:
                raise RemoteURLRejected("Redirect without a Location header.")
            current = str(httpx.URL(current).join(location))
            validate_remote_url(current, policy=policy)
            continue
        return response
    raise RemoteURLRejected(f"Too many redirects (> {policy.max_redirects}).")


@contextmanager
def open_validated_stream(
    url: str, *, timeout: float | None = None, method: str = "GET"
) -> Iterator[httpx.Response]:
    """Validate ``url`` through the gateway and open a streamed response for it.

    Runs :func:`validate_remote_url`, then follows redirects manually with
    every ``Location`` re-validated, capped at ``policy.max_redirects``. Yields
    the final (non-redirect) ``httpx.Response`` with its body unread; read it
    with ``iter_bytes`` and it is closed on exit. ``timeout`` defaults to
    ``policy.timeout_s``.

    Raises ``RemoteURLRejected`` on any policy failure. Transport errors and
    the response status are left to the caller (see :func:`bounded_download`
    for the sanitizing pattern). ``s3://`` URLs are rejected here: they are
    read through the object store client, never streamed over HTTP.
    """
    policy = remote_policy()
    validate_remote_url(url, policy=policy)
    if urlparse(url).scheme.lower() == "s3":
        raise RemoteURLRejected("s3:// URLs are read through the object store, not over HTTP.")
    timeout_s = policy.timeout_s if timeout is None else timeout
    with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
        response = _follow_redirects(client, url, method, policy)
        try:
            yield response
        finally:
            response.close()


def stream_to_file(response: httpx.Response, dest_path: str, max_bytes: int) -> int:
    """Write a streamed response body to ``dest_path``, aborting past ``max_bytes``.

    Shared by the gateway and the CLI's direct read path so both enforce the
    same cap. Returns the bytes written; raises ``RemoteURLRejected`` when the
    cap is exceeded (the caller removes the partial file).
    """
    written = 0
    with open(dest_path, "wb") as fh:
        for chunk in response.iter_bytes(chunk_size=_CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                raise RemoteURLRejected(
                    f"Remote file exceeds the download cap ({max_bytes} bytes)."
                )
            fh.write(chunk)
    return written


def stream_to_text(response: httpx.Response, max_bytes: int) -> str:
    """Read a streamed response body as text, aborting past ``max_bytes``.

    Decodes with the response's declared charset (utf-8 when absent); undecodable
    bytes are replaced rather than raised, matching ``httpx.Response.text``.
    """
    buffer = bytearray()
    for chunk in response.iter_bytes(chunk_size=_CHUNK_BYTES):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise RemoteURLRejected(
                f"Remote document exceeds the download cap ({max_bytes} bytes)."
            )
    return bytes(buffer).decode(response.encoding or "utf-8", errors="replace")


def _content_length(response: httpx.Response) -> int:
    size_header = response.headers.get("content-length")
    return int(size_header) if size_header and size_header.isdigit() else -1


def probe_remote_url(url: str, timeout_s: float | None = None) -> dict:
    """HEAD the URL through the gateway. Returns ``{"size": int, "etag": str}``
    with ``size = -1`` when unknown. s3:// URLs return unknowns (probed later
    by the object-store client).

    Policy failures raise ``RemoteURLRejected``; reachability failures raise
    the narrower :class:`RemoteFetchFailed` with a sanitized message.
    """
    if urlparse(url).scheme.lower() == "s3":
        validate_remote_url(url)
        return {"size": -1, "etag": ""}
    try:
        with open_validated_stream(url, timeout=timeout_s, method="HEAD") as response:
            return {"size": _content_length(response), "etag": response.headers.get("etag", "")}
    except RemoteURLRejected:
        raise
    except Exception as exc:
        # Sanitize: never echo internal fetch errors to clients.
        logger.warning(f"Remote probe failed for {url}: {exc}")
        raise RemoteFetchFailed("Could not reach the provided URL.")


def bounded_download(
    url: str,
    dest_path: str,
    max_bytes: int | None = None,
    timeout_s: float | None = None,
) -> int:
    """Stream the URL to ``dest_path`` through the gateway, enforcing a size cap.

    ``max_bytes`` and ``timeout_s`` default to the policy values. Returns the
    number of bytes written. Raises ``RemoteURLRejected`` on any safety failure
    and :class:`RemoteFetchFailed` on transport/HTTP failures (sanitized
    message); a partial file never survives either.
    """
    cap = remote_policy().max_download_bytes if max_bytes is None else max_bytes
    try:
        with open_validated_stream(url, timeout=timeout_s) as response:
            response.raise_for_status()
            return stream_to_file(response, dest_path, cap)
    except RemoteURLRejected:
        _cleanup_partial(dest_path)
        raise
    except Exception as exc:
        logger.warning(f"Remote download failed for {url}: {exc}")
        _cleanup_partial(dest_path)
        raise RemoteFetchFailed("Could not download the provided URL.")


def fetch_validated_text(
    url: str, *, max_bytes: int | None = None, timeout: float | None = None
) -> str:
    """GET a small text document (a manifest) through the gateway.

    Same validation, redirect and size rules as :func:`bounded_download`, held
    in memory instead of a temp file. ``max_bytes`` defaults to the policy cap.
    """
    cap = remote_policy().max_download_bytes if max_bytes is None else max_bytes
    try:
        with open_validated_stream(url, timeout=timeout) as response:
            response.raise_for_status()
            return stream_to_text(response, cap)
    except RemoteURLRejected:
        raise
    except Exception as exc:
        logger.warning(f"Remote fetch failed for {url}: {exc}")
        raise RemoteFetchFailed("Could not fetch the provided URL.")


def _cleanup_partial(dest_path: str) -> None:
    """Never leave a partial download behind on failure."""
    try:
        os.unlink(dest_path)
    except OSError:
        pass


# ── CLI-context counterparts ────────────────────────────────────────────────
# The CLI reads without host gating (loopback and intranet hosts are the user's
# own), but with the very same policy timeout, redirect cap and size cap. They
# live here so no call site has to know the shape of ``RemoteConfig``, and so
# the CLI and gateway paths cannot drift apart. Unlike the gateway functions
# these do not sanitize failures: httpx's own error is what the user needs.


def _direct_client(policy: RemoteConfig, timeout: float | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=policy.timeout_s if timeout is None else timeout,
        follow_redirects=True,
        max_redirects=policy.max_redirects,
    )


def direct_probe(url: str, timeout_s: float | None = None) -> dict:
    """CLI counterpart of :func:`probe_remote_url`, same ``{"size", "etag"}`` shape."""
    with _direct_client(remote_policy(), timeout=timeout_s) as client:
        response = client.head(url)
        return {"size": _content_length(response), "etag": response.headers.get("etag", "")}


def direct_download(url: str, dest_path: str) -> int:
    """CLI counterpart of :func:`bounded_download`. Returns the bytes written.

    Removing a partial file on failure is the caller's job here, since the CLI
    owns the temp file it asked for.
    """
    policy = remote_policy()
    with _direct_client(policy) as client, client.stream("GET", url) as response:
        response.raise_for_status()
        return stream_to_file(response, dest_path, policy.max_download_bytes)


def direct_fetch_text(url: str) -> str:
    """CLI counterpart of :func:`fetch_validated_text`."""
    policy = remote_policy()
    with _direct_client(policy) as client, client.stream("GET", url) as response:
        response.raise_for_status()
        return stream_to_text(response, policy.max_download_bytes)
