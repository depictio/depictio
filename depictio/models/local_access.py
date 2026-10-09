"""Which folders on this machine a Depictio server may read for its user.

``depictio local`` runs the API and the workers on the user's own computer, the
way a Shiny app runs locally, so a run folder on that computer's disk is the
natural thing to point a new project at. A server that reads its own disk for a
browser is also exactly what an attacker wants, so the reads are confined:
only below the allowed roots, never in the folders Depictio keeps for itself
(keys, admin token, backups, the local home), never in a hidden folder
(``.ssh``, ``.aws`` and every other dot-name below a root), and always judged
on the real path, so neither a symlink nor ``..`` walks out.

This module is the policy alone: paths in, a verdict out. It reads no settings
and imports nothing from ``depictio.api``; the server builds the policy from
its configuration (``settings_models.local_data_policy``) and hands it to the
code that reads.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from depictio.models.logging import logger

Want = Literal["dir", "file", "any"]


class LocalPathRefused(ValueError):
    """A local path the policy does not let the server read.

    The message is plain English and names the path only as the caller wrote
    it: never where a symlink leads, nor which folders are allowed. ``code``
    tells the refusals apart: ``local_path_invalid``,
    ``local_path_not_absolute``, ``local_path_outside``, ``local_path_denied``,
    ``local_path_hidden``, ``local_path_missing``, ``local_path_not_a_folder``
    and ``local_path_not_a_file``.
    """

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.detail = message
        self.code = code


def _under(path: str, base: str) -> bool:
    """Whether real path ``path`` is ``base`` or below it."""
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


@dataclass(frozen=True)
class LocalDataPolicy:
    """The folders a server may read on its own disk, every path already real.

    ``roots`` are where data may come from: they are what the folder browser
    lists and what a project may be created from. ``server_dirs`` are folders
    the server writes and reads itself (its temporary directory, where uploads
    land, and the bundled reference projects): the read paths accept them,
    nothing else does. ``denied`` wins over both.
    """

    roots: tuple[str, ...]
    denied: tuple[str, ...] = ()
    server_dirs: tuple[str, ...] = ()
    home: str = ""

    @classmethod
    def build(
        cls,
        roots: Iterable[str],
        *,
        denied: Iterable[str] = (),
        server_dirs: Iterable[str] = (),
        home: str | None = None,
    ) -> LocalDataPolicy:
        """A policy from configured paths: ``~/`` expanded, each made real.

        Real on this side too, or a root such as ``/tmp/runs`` would contain
        nothing on macOS, where every path below it resolves to
        ``/private/tmp/runs``. A relative or empty entry is dropped: it would
        mean whatever folder the server happened to start in.
        """
        home = home or os.path.expanduser("~")

        def real_paths(paths: Iterable[str]) -> tuple[str, ...]:
            out: list[str] = []
            for raw in paths:
                path = _expand_home((raw or "").strip(), home)
                if not path:
                    continue
                if not os.path.isabs(path) or "\x00" in path:
                    logger.warning(f"Local data policy ignores {path!r}: not an absolute path")
                    continue
                real = os.path.realpath(path)
                if real not in out:
                    out.append(real)
            return tuple(out)

        return cls(
            roots=real_paths(roots),
            denied=real_paths(denied),
            server_dirs=real_paths(server_dirs),
            home=home,
        )

    def expand(self, path: str) -> str:
        """``path`` with a leading ``~`` or ``~/`` replaced by the server user's home."""
        return _expand_home(path, self.home or os.path.expanduser("~"))

    def root_of(self, real: str) -> str | None:
        """The innermost allowed root holding real path ``real``, or None."""
        return _innermost(real, self.roots)

    def confine(self, path: str, want: Want = "dir") -> str:
        """The real path of ``path`` when the policy lets it be read as data.

        ``want`` is what it has to be: a folder, a file, or anything that
        exists. Raises :class:`LocalPathRefused` otherwise.

        The one method that expands a leading ``~``, for a path a user typed
        (``~/results/run42``): the real path it returns is what the caller
        stores and reads, so the expansion is never lost on the way to a read.
        """
        real = self._place(path, self.roots, expand_home=True)
        if not os.path.exists(real):
            raise LocalPathRefused(f"'{path}' does not exist.", "local_path_missing")
        if want == "dir" and not os.path.isdir(real):
            raise LocalPathRefused(f"'{path}' is not a folder.", "local_path_not_a_folder")
        if want == "file" and not os.path.isfile(real):
            raise LocalPathRefused(f"'{path}' is not a file.", "local_path_not_a_file")
        return real

    def allows(self, path: str) -> bool:
        """Whether ``path`` lies where data may be read: below a root, not denied
        nor hidden. Says nothing about whether it exists.

        Judged on ``path`` exactly as the caller will open it: a leading ``~`` is
        not expanded, since ``open("~/x")`` does not expand it either, so such a
        path is not absolute and is refused. Expand it with :meth:`confine`.
        """
        try:
            self._place(path, self.roots)
        except LocalPathRefused:
            return False
        return True

    def allows_read(self, path: str) -> bool:
        """:meth:`allows`, widened to the server's own folders: the test every
        file read on this server passes, whoever registered the file. Judged
        on the literal path, as :meth:`allows` is."""
        try:
            self._place(path, self.roots + self.server_dirs)
        except LocalPathRefused:
            return False
        return True

    def _place(self, path: str, bases: tuple[str, ...], *, expand_home: bool = False) -> str:
        """The real path of ``path`` once it is known to lie where it may be read.

        ``expand_home`` expands a leading ``~`` first; only :meth:`confine`
        asks for it, since only its caller reads the real path returned here
        rather than ``path`` itself.
        """
        if not isinstance(path, str) or not path.strip() or "\x00" in path:
            raise LocalPathRefused("That is not a folder path.", "local_path_invalid")
        expanded = self.expand(path) if expand_home else path
        if not os.path.isabs(expanded):
            raise LocalPathRefused(
                f"'{path}' is not an absolute path: give the full path of a folder, "
                "such as /Users/me/results/run42, or one starting with ~/.",
                "local_path_not_absolute",
            )
        real = os.path.realpath(expanded)
        base = _innermost(real, bases)
        if base is None:
            raise LocalPathRefused(
                f"'{path}' is not inside a folder this server may read.", "local_path_outside"
            )
        if any(_under(real, denied) for denied in self.denied):
            raise LocalPathRefused(
                f"'{path}' is inside a folder Depictio keeps for itself, so it cannot be "
                "read as data.",
                "local_path_denied",
            )
        relative = os.path.relpath(real, base)
        if relative != "." and any(part.startswith(".") for part in relative.split(os.sep)):
            raise LocalPathRefused(
                f"'{path}' is inside a hidden folder (one whose name starts with a dot), "
                "which this server does not read.",
                "local_path_hidden",
            )
        return real


def _expand_home(path: str, home: str) -> str:
    """Only ``~`` and ``~/...``: ``~someone`` would name another user's home."""
    if path == "~":
        return home
    if path.startswith("~/"):
        return os.path.join(home, path[2:])
    return path


def _innermost(real: str, bases: tuple[str, ...]) -> str | None:
    """The longest of ``bases`` holding ``real``, so the hidden-segment rule is
    counted from the most specific folder an administrator allowed."""
    holding = [base for base in bases if _under(real, base)]
    return max(holding, key=len) if holding else None
