"""Outbound HTTP to a paired instance, behind an SSRF guard (#1303).

An admin may add a push target in the UI. Its URL is then dialled by the
server, so without a guard it is a way to make the server probe its own
network (loopback, cloud metadata, the LAN). Targets declared in the
environment are trusted by the operator and skip the guard; the others must be
https and resolve to public addresses, unless their host is explicitly
allowlisted. The check runs again before every call, not only when the target
is saved, because a DNS record can change between the two (rebinding).

A third kind is the *ad-hoc destination*: a project owner types a URL and an
invite code (never stored). Its host must end with one of
``DEPICTIO_MIGRATION_DESTINATION_DOMAINS`` and it goes through the same guard,
both checked again before every call.

The pairing key (or invite code) is only ever placed in a request header here. It is never
logged, and error details quoted from the remote are bounded and never echo
request headers.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

PAIRING_HEADER = "X-Depictio-Pairing-Key"
INVITE_HEADER = "X-Depictio-Invite-Code"
REQUEST_TOKEN_HEADER = "X-Depictio-Request-Token"
#: JSON answers of a target are small; anything bigger is not a Depictio.
MAX_JSON_BYTES = 1024 * 1024
_MAX_DETAIL_CHARS = 500

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_METADATA = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}


class TargetURLRejected(ValueError):
    """The target URL is not allowed to be dialled from this server."""


class RemoteError(Exception):
    """The target answered with an error, or could not be reached."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ResolvedTarget:
    """A push target with its credential in the clear, for one call only.

    ``pairing_key`` holds whatever goes into ``credential_header``: a pairing
    key, an invite code, or a request's status token.
    """

    id: str
    name: str
    url: str
    pairing_key: str
    trusted: bool
    credential_header: str = PAIRING_HEADER
    #: Set for an ad-hoc destination: the host must end with one of these.
    domain_suffixes: tuple[str, ...] | None = None

    def __repr__(self) -> str:  # keep the key out of tracebacks and logs
        return f"ResolvedTarget(id={self.id!r}, name={self.name!r}, url={self.url!r})"


def _blocked_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip in _METADATA:
        return "cloud metadata address"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return "carrier-grade NAT address"
    if ip.is_private:
        return "private address"
    if ip.is_reserved:
        return "reserved address"
    return None


def check_target_url(url: str, *, trusted: bool, host_allowlist: list[str]) -> None:
    """Raise ``TargetURLRejected`` unless ``url`` may be dialled.

    ``trusted`` (operator-declared target) skips every check. A host on
    ``host_allowlist`` may use http and private addresses; everything else must
    be https and resolve only to public addresses.
    """
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        _ = parts.port  # raises on a malformed port
    except ValueError as exc:
        raise TargetURLRejected(f"Target URL is not valid: {exc}") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise TargetURLRejected("Target URL must be an http(s) URL with a host")
    if trusted:
        return
    if parts.username or parts.password:
        raise TargetURLRejected("Target URL must not carry credentials")
    if host in {h.strip().lower() for h in host_allowlist}:
        return
    if parts.scheme != "https":
        raise TargetURLRejected("Target URL must use https (or its host must be allowlisted)")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise TargetURLRejected(f"Target host {host!r} does not resolve") from exc
    if not infos:
        raise TargetURLRejected(f"Target host {host!r} does not resolve")
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise TargetURLRejected(
                f"Target host resolves to an invalid address: {address}"
            ) from exc
        reason = _blocked_reason(ip)
        if reason:
            raise TargetURLRejected(f"Target host {host!r} resolves to a {reason}")


def check_destination_domain(url: str, suffixes: list[str] | tuple[str, ...]) -> None:
    """Raise ``TargetURLRejected`` unless the URL's host is, or is under, a suffix."""
    try:
        host = (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise TargetURLRejected(f"Destination URL is not valid: {exc}") from exc
    if not suffixes:
        raise TargetURLRejected("Publishing to a destination URL is not enabled here")
    for suffix in suffixes:
        suffix = suffix.lower().strip(".")
        if suffix and (host == suffix or host.endswith("." + suffix)):
            return
    raise TargetURLRejected(
        f"Destination host {host!r} is not in an allowed domain ({', '.join(suffixes)})"
    )


def _detail(response: httpx.Response, body: bytes) -> str:
    try:
        payload = json.loads(body)
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    except ValueError:
        detail = f"HTTP {response.status_code}"
    text = detail if isinstance(detail, str) else json.dumps(detail, default=str)
    return text[:_MAX_DETAIL_CHARS]


class TargetClient:
    """Calls the ``/migrate/inbound`` API of one paired instance."""

    def __init__(self, target: ResolvedTarget, *, transport: httpx.BaseTransport | None = None):
        self._target = target
        self._base = target.url.rstrip("/") + "/depictio/api/v1/migrate/inbound"
        timeout = float(settings.migration.http_timeout_s)
        self._timeout = timeout
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=False, verify=True, transport=transport
        )

    def __enter__(self) -> TargetClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _guard(self) -> None:
        if self._target.domain_suffixes is not None:
            check_destination_domain(self._target.url, self._target.domain_suffixes)
        check_target_url(
            self._target.url,
            trusted=self._target.trusted,
            host_allowlist=list(settings.migration.ui_target_host_allowlist),
        )

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            self._guard()
        except TargetURLRejected as exc:
            raise RemoteError(400, str(exc)) from exc
        headers = {self._target.credential_header: self._target.pairing_key}
        try:
            with self._client.stream(
                method, self._base + path, headers=headers, **kwargs
            ) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_JSON_BYTES:
                        raise RemoteError(502, "Target answer is too large")
                status = response.status_code
                if status >= 400:
                    raise RemoteError(status, _detail(response, bytes(body)))
        except RemoteError:
            raise
        except httpx.HTTPError as exc:
            logger.warning("migrate push: target %s unreachable: %s", self._target.name, type(exc))
            raise RemoteError(502, f"Could not reach the target ({type(exc).__name__})") from exc
        try:
            payload = json.loads(bytes(body))
        except ValueError as exc:
            raise RemoteError(502, "Target did not answer with JSON") from exc
        if not isinstance(payload, dict):
            raise RemoteError(502, "Target answered with an unexpected payload")
        return payload

    def info(self) -> dict[str, Any]:
        return self._call("GET", "/info")

    def preflight(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/preflight", json=body)

    def check(self, body: dict[str, Any]) -> dict[str, Any]:
        """``/info`` + ``/preflight`` + ``/probe`` in one call (targets from #1303 slice 2)."""
        return self._call("POST", "/check", json=body)

    def probe(self, bucket: str, key: str) -> dict[str, Any]:
        return self._call("POST", "/probe", json={"bucket": bucket, "key": key})

    def submit(self, bundle_path: str | Path, fields: dict[str, Any]) -> dict[str, Any]:
        """Stream the bundle from disk as multipart; memory does not grow with it."""
        data = {k: str(v) for k, v in fields.items() if v is not None}
        with open(bundle_path, "rb") as fh:
            return self._call(
                "POST",
                "/requests",
                data=data,
                files={"file": ("bundle.zip", fh, "application/zip")},
                timeout=httpx.Timeout(self._timeout, write=None),
            )

    def request_status(self, request_id: str) -> dict[str, Any]:
        return self._call("GET", f"/requests/{request_id}")
