"""Opening data roots for the builder, and keeping the paths it is handed inside them."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from depictio.cli.cli.utils.data_root import DataRoot, LocalDataRoot
from depictio.project_builder.errors import BuilderRefused

PATH_REFUSED = "builder_path_refused"

# How long an s3:// root's listing is reused before the prefix is listed again.
S3_ROOT_TTL_S = 60.0


def confine_rel(rel: str | None) -> str:
    """``rel`` as a clean root-relative POSIX path; refused when it could leave the root.

    The SPA only ever sends paths it was given by a listing, so an absolute
    path, a ``..`` segment or a NUL byte is a request to read elsewhere, never a
    mistake to repair. Confinement past that (symlinks, the server's allowed
    folders) is the root's own: every read goes through it.
    """
    raw = (rel or "").replace("\\", "/")
    if "\x00" in raw or raw.startswith("/") or raw.startswith("~"):
        raise BuilderRefused(400, f"'{rel}' is not a path inside the data root.", PATH_REFUSED)
    parts = [part for part in raw.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise BuilderRefused(400, f"'{rel}' is not a path inside the data root.", PATH_REFUSED)
    return "/".join(parts)


def standalone_root(folder: str | Path) -> LocalDataRoot:
    """The one root ``depictio project-builder <dir>`` serves."""
    path = Path(folder).expanduser().resolve()
    if not path.is_dir():
        raise BuilderRefused(400, f"Not a folder: {path}", "builder_root_missing")
    return LocalDataRoot(str(path))


class RootCache:
    """Remote roots, reused for a short while.

    An ``s3://`` root answers every question from one listing taken when it is
    built, which is what makes it cheap to ask, and costly to build: a match
    request per keystroke would re-list up to 100,000 keys each time. A local
    root reads the disk at each question, so it is never cached.
    """

    def __init__(self, ttl_s: float = S3_ROOT_TTL_S, max_entries: int = 32):
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._entries: dict[Any, tuple[float, DataRoot]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any, build: Callable[[], DataRoot], *, refresh: bool = False) -> DataRoot:
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and not refresh and now - hit[0] < self._ttl_s:
                return hit[1]
        root = build()
        if not root.is_remote:
            return root
        with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=lambda k: self._entries[k][0])
                self._entries.pop(oldest, None)
            self._entries[key] = (now, root)
        return root

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
