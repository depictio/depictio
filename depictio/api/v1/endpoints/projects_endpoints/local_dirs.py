"""Browse folders on the server's own disk: ``GET /projects/local_dirs``.

Only for a server that is the user's own computer (``depictio local``): local
folders are on when ``settings_models.local_data_policy`` says so, which needs
server context, single-user mode and ``DEPICTIO_LOCAL_DATA_ROOTS``. The listing
feeds the viewer's folder picker for ``POST /projects/from_run``; both go
through the same :class:`~depictio.models.local_access.LocalDataPolicy`, so the
picker never offers a folder the creation then refuses.

Two guards sit in front of any local read, here and in ``from_run``:

- the caller is an administrator (in single-user mode, the one user is);
- the request's ``Host`` is a loopback name. A web page the user happens to
  visit can make the browser call ``http://127.0.0.1:<port>`` through a name it
  controls (DNS rebinding); the browser then sends that name as ``Host``, which
  is how such a request is told apart from the user's own tab.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterator

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from depictio.api.v1.configs.settings_models import local_data_policy
from depictio.models.local_access import LocalDataPolicy, LocalPathRefused
from depictio.models.logging import logger

# More sub-directories than this and the listing says ``truncated``.
MAX_ENTRIES = 500

# A folder holding one of these is very likely one pipeline run's output.
RUN_MARKERS = ("pipeline_info", "multiqc")

LOCAL_FOLDERS_OFF = "Local folders are not enabled on this server."
NON_LOOPBACK_HOST = (
    "Folders on this computer can only be used from this computer: open Depictio at "
    "http://localhost or http://127.0.0.1."
)
ADMIN_ONLY = "Only an administrator can use folders on this computer."


class CodedHTTPException(HTTPException):
    """An ``HTTPException`` with a machine-readable ``code`` next to its detail.

    A route that catches it answers ``{detail, code}`` through :meth:`response`,
    the body ``main.py`` gives ``S3AccessError``. One that does not still
    answers its status and ``{detail}``, FastAPI's default.
    """

    def __init__(self, status_code: int, detail: str, code: str):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code, content={"detail": self.detail, "code": self.code}
        )


class LocalDirEntry(BaseModel):
    name: str
    path: str
    looks_like_run: bool = False
    # Whether opening the folder would list anything: the picker draws no
    # expand arrow on a leaf.
    has_children: bool = False


class LocalDirListing(BaseModel):
    """One folder's sub-directories, or the allowed roots when ``path`` is None.

    ``looks_like_run`` says it of the listed folder itself (False for the roots).
    """

    path: str | None = None
    root: str | None = None
    parent: str | None = None
    looks_like_run: bool = False
    entries: list[LocalDirEntry] = Field(default_factory=list)
    truncated: bool = False


def is_loopback_host(host: str | None) -> bool:
    """Whether a ``Host`` header names this machine: ``localhost`` or a loopback IP,
    with or without a port (``[::1]:8058`` included)."""
    if not host:
        return False
    host = host.strip()
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return False
        name = host[1:end]
    elif host.count(":") == 1:
        name = host.rsplit(":", 1)[0]
    else:
        name = host
    name = name.lower()
    if name in ("localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def require_local_caller(request, current_user) -> None:
    """Refuse (403) a request for a local read that is not the user's own.

    ``request`` is the incoming Starlette request; None (a call that did not
    come over HTTP) is refused like a foreign host, so the guard fails closed.
    """
    host = request.headers.get("host") if request is not None else None
    if not is_loopback_host(host):
        raise CodedHTTPException(403, NON_LOOPBACK_HOST, "non_loopback_host")
    if not getattr(current_user, "is_admin", False):
        raise CodedHTTPException(403, ADMIN_ONLY, "local_admin_only")


def active_local_policy() -> LocalDataPolicy:
    """The local-data policy, or a 404 when local folders are off."""
    policy = local_data_policy()
    if policy is None:
        raise CodedHTTPException(404, LOCAL_FOLDERS_OFF, "local_folders_off")
    return policy


def looks_like_run(folder: str) -> bool:
    """Whether ``folder`` holds ``pipeline_info/`` or ``multiqc/``."""
    return any(os.path.isdir(os.path.join(folder, marker)) for marker in RUN_MARKERS)


def _entry(policy: LocalDataPolicy, name: str, real: str) -> LocalDirEntry:
    return LocalDirEntry(
        name=name,
        path=real,
        looks_like_run=looks_like_run(real),
        has_children=has_visible_sub_directory(policy, real),
    )


def sub_directory_names(folder: str) -> list[str] | None:
    """The sorted names of the sub-directories of ``folder``, dot-names left out.

    None when the server may not read it (a permission error, a folder gone
    since it was listed): the callers treat that as empty, never as a failure.
    """
    try:
        with os.scandir(folder) as scan:
            return sorted(
                entry.name
                for entry in scan
                if not entry.name.startswith(".") and is_directory(entry)
            )
    except PermissionError:
        return None
    except OSError as exc:
        logger.info(f"local_dirs: cannot list {folder}: {exc}")
        return None


def is_directory(entry: os.DirEntry[str]) -> bool:
    """``entry.is_dir`` through a symlink, False for a link that leads nowhere."""
    try:
        return entry.is_dir(follow_symlinks=True)
    except OSError:
        return False


def visible_sub_directories(policy: LocalDataPolicy, folder: str) -> Iterator[tuple[str, str]]:
    """``(name, real path)`` of each sub-directory of real folder ``folder`` the
    policy would list, in name order, lazily.

    Hidden: dot-names, and anything the policy would refuse to open (a symlink
    that leaves the roots, a folder Depictio keeps for itself). A folder the
    server may not read yields nothing.
    """
    for name in sub_directory_names(folder) or ():
        try:
            real = policy.confine(os.path.join(folder, name), want="dir")
        except LocalPathRefused:
            continue
        yield name, real


def has_visible_sub_directory(policy: LocalDataPolicy, folder: str) -> bool:
    """Whether real folder ``folder`` holds a sub-directory the policy would list.

    Stops at the first one the policy accepts: one listing of ``folder``, and
    usually a single path resolved.
    """
    return next(visible_sub_directories(policy, folder), None) is not None


def _sub_directories(policy: LocalDataPolicy, folder: str) -> tuple[list[LocalDirEntry], bool]:
    """The visible sub-directories of real folder ``folder``, sorted, and whether
    there were more than :data:`MAX_ENTRIES` (see :func:`visible_sub_directories`)."""
    entries: list[LocalDirEntry] = []
    for name, real in visible_sub_directories(policy, folder):
        if len(entries) == MAX_ENTRIES:
            return entries, True
        entries.append(_entry(policy, name, real))
    return entries, False


def list_local_dirs(path: str | None, *, request, current_user) -> LocalDirListing:
    """The sub-directories of ``path``, or the allowed roots without one.

    Refusals: 404 when local folders are off, or the path is outside every
    root, denied, hidden, missing or not a folder (the policy refuses the first
    three before looking at the disk, so nothing here says whether a path
    exists where the user may not browse); 403 for a foreign ``Host`` or a
    non-administrator.
    """
    policy = active_local_policy()
    require_local_caller(request, current_user)

    if not path:
        return LocalDirListing(
            entries=[
                _entry(policy, os.path.basename(root) or root, root)
                for root in policy.roots
                if os.path.isdir(root) and policy.allows(root)
            ]
        )

    try:
        real = policy.confine(path, want="dir")
    except LocalPathRefused as exc:
        raise CodedHTTPException(404, exc.detail, exc.code) from exc
    root = policy.root_of(real)
    entries, truncated = _sub_directories(policy, real)
    return LocalDirListing(
        path=real,
        root=root,
        parent=None if real == root else os.path.dirname(real),
        looks_like_run=looks_like_run(real),
        entries=entries,
        truncated=truncated,
    )
