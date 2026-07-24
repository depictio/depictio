"""Filesystem walking primitives for the scan phase.

Replaces the ``os.walk`` + per-file ``os.path.getctime/getmtime/getsize``
pattern with a single ``os.scandir`` pass that reuses the ``stat`` the kernel
already returned. Three things motivated pulling this out of ``scan.py``:

* **Syscall cost.** The old path issued ``realpath`` + ``getctime`` +
  ``getmtime`` + ``getsize`` per file, and ``File.validate_location`` then added
  ``exists`` + ``isfile`` + ``access`` on top. ``scandir`` gives all the stat
  fields in one syscall, and ``realpath`` collapses from once-per-file to
  once-per-directory.
* **``max_depth`` / ``ignore``.** Both are declared on ``ScanRecursive`` and were
  never consulted. Pruning has to happen at directory level to be worth
  anything, which ``os.walk`` makes awkward and ``scandir`` recursion makes
  natural.
* **Change detection.** :func:`run_signature` is the cheap "did anything in this
  run change" token used by the local state cache and by the watcher's polling
  trigger. Both need exactly the data a walk already collected.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from depictio.cli.cli_logging import logger


@dataclass(frozen=True, slots=True)
class ScannedPath:
    """One file discovered by :func:`iter_run_files`, with its ``stat`` pre-read.

    Two paths are carried deliberately, because the scan phase has always
    treated them differently:

    * ``walk_path`` / ``match_name`` / ``rel_path`` — the file as encountered
      while walking. Regex matching runs against these, so a data collection
      whose pattern targets a *symlink* name keeps matching it.
    * ``path`` / ``name`` — the resolved real path. This is what gets stored as
      ``File.file_location``, and what every stat field below describes.

    They differ only for symlinks, but the distinction is load-bearing: runs are
    routinely scanned through an intermediate symlink tree (per-run isolation
    pointing ``--data-root`` at a temporary tree), and the stored path must be
    the durable target rather than the transient link.
    """

    path: str
    walk_path: str
    rel_path: str
    name: str
    match_name: str
    size: int
    ctime: float
    mtime: float
    mtime_ns: int


def _is_ignored(name: str, rel_path: str, patterns: tuple[str, ...]) -> bool:
    """Whether an entry matches any ignore glob, by basename or run-relative path.

    Both are tested so that ``*.tmp`` and ``work/**`` style patterns each work
    without the user having to know which form the walker compares against.
    """
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


def iter_run_files(
    root: str,
    *,
    max_depth: int | None = None,
    ignore: list[str] | None = None,
    follow_symlinks: bool = False,
) -> Iterator[ScannedPath]:
    """Yield every file under ``root``, with its stat already read.

    Args:
        root: Directory to walk.
        max_depth: Directory levels to descend below ``root``. ``0`` restricts
            the scan to files sitting directly in ``root``; ``1`` also covers its
            immediate subdirectories; ``None`` (default) is unlimited.
        ignore: Glob patterns. A matching directory is pruned (never descended
            into), a matching file is skipped.
        follow_symlinks: Whether to descend into symlinked directories. Off by
            default, matching ``os.walk``'s default and avoiding cycles.

    Unreadable directories and entries whose ``stat`` fails (a broken symlink,
    a file deleted mid-walk) are logged and skipped rather than raised. A live
    data root is a moving target, and the previous implementation would abort a
    whole scan on a single dangling link.
    """
    root = os.path.abspath(root)
    patterns = tuple(ignore) if ignore else ()

    # Resolve the root once. Every non-symlink child then inherits its parent's
    # resolved directory, so realpath() runs per directory and per symlink
    # instead of per file.
    real_root = os.path.realpath(root)

    # (walk_path, resolved_path, run-relative path, depth) — explicit stack so
    # deep trees cannot hit the recursion limit.
    stack: list[tuple[str, str, str, int]] = [(root, real_root, "", 0)]

    while stack:
        walk_dir, real_dir, rel_dir, depth = stack.pop()

        try:
            entries = list(os.scandir(walk_dir))
        except OSError as exc:
            logger.warning(f"Cannot scan directory {walk_dir}: {exc}")
            continue

        for entry in entries:
            rel_path = f"{rel_dir}/{entry.name}" if rel_dir else entry.name

            if _is_ignored(entry.name, rel_path, patterns):
                logger.debug(f"Ignoring {rel_path} (matched ignore pattern)")
                continue

            try:
                is_symlink = entry.is_symlink()
                # follow_symlinks=True here classifies a symlink by its target,
                # so links to directories are recognised as directories and can
                # be handled by the branch below rather than leaking into the
                # file stream.
                is_dir = entry.is_dir(follow_symlinks=True)
            except OSError as exc:
                logger.warning(f"Cannot classify {rel_path}: {exc}")
                continue

            if is_dir:
                if is_symlink and not follow_symlinks:
                    # os.walk lists these under dirnames and does not descend;
                    # they are never yielded as files.
                    continue
                if max_depth is None or depth + 1 <= max_depth:
                    child_real = (
                        os.path.realpath(entry.path)
                        if is_symlink
                        else os.path.join(real_dir, entry.name)
                    )
                    stack.append((entry.path, child_real, rel_path, depth + 1))
                continue

            try:
                stat_result = entry.stat(follow_symlinks=True)
            except OSError as exc:
                # Broken symlink, or the file vanished between readdir and stat.
                logger.warning(f"Cannot stat {rel_path}: {exc}")
                continue

            real_path = (
                os.path.realpath(entry.path) if is_symlink else os.path.join(real_dir, entry.name)
            )

            yield ScannedPath(
                path=real_path,
                walk_path=entry.path,
                rel_path=rel_path,
                name=os.path.basename(real_path),
                match_name=entry.name,
                size=stat_result.st_size,
                ctime=stat_result.st_ctime,
                mtime=stat_result.st_mtime,
                mtime_ns=stat_result.st_mtime_ns,
            )


def run_signature(paths: Iterable[ScannedPath]) -> str:
    """A cheap token that changes whenever the contents of a run change.

    Built from ``(rel_path, size, mtime_ns)`` over the sorted file list, so it
    is stable across walk order and sensitive to additions, deletions, renames,
    truncations and in-place rewrites — everything a metadata-level scan can
    observe. File *contents* are never read, matching ``generate_file_hash``.

    Used by the local state cache to skip re-planning an unchanged run, and by
    the watcher's polling trigger on filesystems where inotify is not reliable.
    """
    hasher = hashlib.sha256()
    for entry in sorted(paths, key=lambda p: p.rel_path):
        hasher.update(f"{entry.rel_path}\0{entry.size}\0{entry.mtime_ns}\0".encode())
    return hasher.hexdigest()
