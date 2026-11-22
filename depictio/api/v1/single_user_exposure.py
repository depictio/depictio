"""Warn when a single-user server answers a request from beyond this machine.

Single-user mode has no sign-in: whoever reaches the server is its admin. That
is the point on a laptop, where the server listens on 127.0.0.1, and a hazard
anywhere else. The server cannot see which interface a port is published on
(Docker publishes on every interface unless told otherwise), but it sees the
host each request was addressed to, which nginx forwards as-is. A request for
``192.168.1.20:5080`` or ``mylaptop.lab.example.org`` means someone reached the
server through the network, so the log says so, once per host, at error
level so the default log level shows it.

This warns and never blocks: an operator who exposes a single-user server on
purpose (behind their own authenticating proxy) keeps a working server.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from depictio.api.v1.configs.logging_init import logger

#: Bounded so a scan with random Host headers cannot grow the set forever.
_MAX_REPORTED_HOSTS = 16


def _bare_host(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [::1]:5080
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:  # name:port or v4:port
        return host.rsplit(":", 1)[0]
    return host  # bare name, bare v4 or bare v6


def host_is_local(host_header: str) -> bool:
    """True when ``host_header`` names this machine, or a container/service name.

    Dotless names that are not IPs (``depictio-backend``, ``localhost``) are
    how containers and probes call each other inside a compose or cluster
    network; they say nothing about exposure.
    """
    host = _bare_host(host_header)
    if not host:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    return host == "localhost" or host.endswith(".localhost") or "." not in host


class SingleUserExposureWarning:
    """ASGI middleware: log once per host when single-user mode is reached remotely."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._reported: set[str] = set()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket"):
            headers = dict(scope.get("headers") or [])
            raw = headers.get(b"x-forwarded-host") or headers.get(b"host") or b""
            host = raw.decode("latin-1").split(",", 1)[0].strip()
            if (
                host
                and not host_is_local(host)
                and host not in self._reported
                and len(self._reported) < _MAX_REPORTED_HOSTS
            ):
                self._reported.add(host)
                # An error, not a warning: the default log level (ERROR) is
                # what the quick-start compose runs with.
                logger.error(
                    f"Security: single-user mode answered a request addressed to {host!r}: anyone "
                    "who can reach this address is signed in as the admin, without a "
                    "password. Keep the server on 127.0.0.1 (DEPICTIO_BIND_ADDRESS in "
                    "docker-compose.yaml) or set DEPICTIO_AUTH_SINGLE_USER_MODE=false."
                )
        await self.app(scope, receive, send)
