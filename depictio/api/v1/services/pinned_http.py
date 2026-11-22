"""httpx transport that connects only to the IP address it has just validated.

The outbound guards (``outbound_http.check_target_url``,
``remote_fetch.validate_remote_url``) resolve a host and reject private,
loopback or metadata addresses. httpx then resolves the name a second time
when it connects, so a DNS server that answers a public IP to the check and
127.0.0.1 to the connect walks past the guard (DNS rebinding). The backend
here closes that gap: it resolves the host itself, runs the caller's validator
on every address, and connects to one of those exact addresses.

TLS is unaffected. httpcore calls ``connect_tcp(host=origin host)`` and then
``stream.start_tls(server_hostname=sni_hostname or origin host)``
(``httpcore/_sync/connection.py``, ``HTTPConnection._connect``, httpcore
1.0.9), so SNI and certificate verification keep using the hostname from the
URL; only the TCP socket is opened to the pinned IP. The ``Host`` header comes
from the URL too.

Proxies: an ``httpx.Client`` given ``transport=`` ignores ``HTTP(S)_PROXY``.
When a proxy applies to a URL (:func:`proxy_applies`), callers keep a plain
client and the proxy resolves the name, as before; their pre-check still runs.
Pinning only applies to direct connections.
"""

from __future__ import annotations

import ipaddress
import socket
import typing
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit

import httpcore
import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
#: Returns why an address must not be dialled, or ``None`` when it may be.
Validator = Callable[[IPAddress], str | None]


class AddressRejected(Exception):
    """The host resolved, at connect time, to an address the validator refused.

    Deliberately not an httpcore/httpx error: httpx re-raises unknown
    exceptions unchanged (``map_httpcore_exceptions``), so callers see this
    type and map it to their own "rejected" error rather than to
    "unreachable". It also escapes httpcore's connect retries.
    """

    def __init__(self, host: str, address: IPAddress, reason: str):
        super().__init__(f"Host {host!r} resolves to a {reason} ({address})")
        self.host = host
        self.address = address
        self.reason = reason


def resolve_host(host: str, port: int) -> list[IPAddress]:
    """``getaddrinfo`` answers for ``host`` as IP objects (scope ids dropped)."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise httpcore.ConnectError(f"Could not resolve host {host!r}") from exc
    addresses: list[IPAddress] = []
    for info in infos:
        try:
            address = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            continue
        if address not in addresses:
            addresses.append(address)
    return addresses


class PinnedBackend(httpcore.SyncBackend):
    """Resolve, validate every address, then connect to a validated one."""

    def __init__(self, validator: Validator):
        self._validator = validator

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        addresses = resolve_host(host, port)
        if not addresses:
            raise httpcore.ConnectError(f"Could not resolve host {host!r}")
        # All of them, not only the one dialled: a mixed answer is refused, the
        # same rule as the pre-checks.
        for address in addresses:
            reason = self._validator(address)
            if reason:
                raise AddressRejected(host, address, reason)
        last_error: Exception | None = None
        for address in addresses:
            try:
                return super().connect_tcp(
                    str(address),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


def pinned_transport(validator: Validator, **kwargs: typing.Any) -> httpx.HTTPTransport:
    """An ``httpx.HTTPTransport`` (built with ``kwargs``) that dials through
    :class:`PinnedBackend`.

    httpx does not expose ``network_backend``. ``HTTPTransport.__init__``
    (httpx 0.28) builds ``self._pool = httpcore.ConnectionPool(...)`` without a
    proxy, and the pool hands ``self._network_backend`` to every connection it
    creates (``ConnectionPool.create_connection``). Swapping that one attribute
    keeps everything else httpx configured (ssl context, limits, http2, retries)
    rather than rebuilding the pool from a copy of its arguments. If a future
    httpx/httpcore changes this layout, raise instead of silently connecting
    unpinned; ``test_pinned_http`` also checks that the backend is really used.
    """
    transport = httpx.HTTPTransport(**kwargs)
    pool = getattr(transport, "_pool", None)
    if type(pool) is not httpcore.ConnectionPool or not isinstance(
        getattr(pool, "_network_backend", None), httpcore.SyncBackend
    ):
        raise RuntimeError("Cannot pin outbound connections with this httpx/httpcore version")
    pool._network_backend = PinnedBackend(validator)
    return transport


def proxy_applies(url: str) -> bool:
    """Whether an environment proxy would carry a request to ``url``.

    Same inputs httpx reads with ``trust_env`` (``urllib.request.getproxies``,
    which includes ``ALL_PROXY`` and ``NO_PROXY``).
    """
    parts = urlsplit(url)
    proxies = urllib.request.getproxies()
    if not (proxies.get(parts.scheme.lower()) or proxies.get("all")):
        return False
    return not urllib.request.proxy_bypass(parts.hostname or "")
