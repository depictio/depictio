"""Recognise the workflow run behind any data root, a local folder or an ``s3://`` prefix.

The run-info connectors (:mod:`depictio.models.models.run_info`) read a
directory on disk. A remote run folder is not one, so rather than give every
connector a second way of reading, the few entries they look at are copied
into a temporary directory and the connectors read that copy. Each connector
declares those entries itself, ``footprint`` for the files it opens and
``markers`` for the files and directories it only looks for, so the copy reads
as the original does.

Staging is bounded: only the declared patterns, at most ``MAX_STAGED_ENTRIES``
entries, ``MAX_FILE_BYTES`` per file and ``MAX_TOTAL_BYTES`` in all. Entries
are staged in path order, so a folder of many runs that reaches the cap still
has its first runs staged whole.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from depictio.api.v1.configs.settings_models import local_data_policy
from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.cli.cli_logging import logger
from depictio.models.models.run_info import WorkflowRunInfo, read_run_info, registered_readers

if TYPE_CHECKING:
    from depictio.cli.cli.utils.data_root import DataRoot

MAX_STAGED_ENTRIES = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024

# How an entry is staged. One path wanted two ways is staged the stronger way.
_DIRECTORY, _MARKER, _CONTENT = 0, 1, 2


def detect_template_for_root(root: DataRoot) -> tuple[str | None, WorkflowRunInfo | None]:
    """Template id and run provenance for a run folder (LocalDataRoot or S3DataRoot).

    The data-root form of ``templates.detect_template_from_run_dir``, with the
    same answer: ``(None, None)`` when no connector recognises the folder, and
    ``(None, info)`` when one does but no bundled template fits it.
    """
    info = read_run_info_for_root(root)
    if info is None:
        logger.info(f"No workflow run provenance recognised in {root.location}")
        return None, None
    # Imported here: templates.py is heavy, and may come to import this module.
    from depictio.cli.cli.utils.templates import select_template_for_run

    return select_template_for_run(info), info


def read_run_info_for_root(root: DataRoot) -> WorkflowRunInfo | None:
    """The provenance of the run in ``root``, or None when no connector recognises it.

    A local root is read in place, unless the server confines its own disk
    (``settings_models.local_data_policy``): then it is staged like a remote one,
    through ``LocalDataRoot``, which hides and refuses what leaves the allowed
    folders, so a symlinked ``pipeline_info`` cannot be read through. Any other root
    is staged: the entries the
    connectors declare are fetched into a temporary directory named like the
    root (a connector may name the pipeline after its folder), and the paths in
    the answer are mapped back to locations under the root.

    An ``S3AccessError`` from a read propagates unchanged. A file the listing
    named but the store no longer has is left out, like any other absent file.
    """
    if isinstance(root, LocalDataRoot) and local_data_policy() is None:
        return read_run_info(root.location)
    with tempfile.TemporaryDirectory(prefix="depictio-run-") as tmp:
        stage = Path(tmp) / _stage_name(root.name)
        stage.mkdir()
        _stage(root, stage)
        info = read_run_info(stage)
        return _relocated(info, stage, root) if info is not None else None


def _stage_name(name: str) -> str:
    """``name`` as a single, safe folder name."""
    if not name or name in (".", "..") or "/" in name or "\x00" in name:
        return "run"
    return name


def _file_sizes(root: DataRoot) -> dict[str, int]:
    """Size of every file under ``root``, by root-relative path (-1 when unknown).

    Read from the listing the root already holds, so staging asks the store for
    nothing but the files it copies.
    """
    objects = getattr(root, "objects", None)
    if objects is None and isinstance(root, LocalDataRoot):
        # No listing to read sizes from: stat what the connectors would stage,
        # as the (confined) root lists it.
        sizes: dict[str, int] = {}
        for reader in registered_readers():
            for pattern in (*getattr(reader, "footprint", ()), *getattr(reader, "markers", ())):
                for rel in root.glob(pattern):
                    path = Path(root.url(rel))
                    if path.is_file():
                        sizes[rel] = path.stat().st_size
        return sizes
    if objects is None:
        raise TypeError(f"{type(root).__name__} holds no listing to stage a run folder from")
    return {obj.relative: obj.size for obj in objects}


def _wanted(root: DataRoot, sizes: dict[str, int]) -> dict[str, int]:
    """Every entry the registered connectors declare, by root-relative path."""
    wanted: dict[str, int] = {}
    for reader in registered_readers():
        # A reader registered without the declarations is never staged for.
        for kind, patterns in (
            (_CONTENT, getattr(reader, "footprint", ())),
            (_MARKER, getattr(reader, "markers", ())),
        ):
            for pattern in patterns:
                for rel in root.glob(pattern):
                    # A root's glob also yields the directories its keys imply.
                    entry = kind if rel in sizes else _DIRECTORY
                    wanted[rel] = max(wanted.get(rel, entry), entry)
    return wanted


def _target(stage: Path, rel: str) -> Path | None:
    """Where ``rel`` is staged, or None when it would land outside ``stage``.

    An S3 key may hold ``..`` segments, which ``**/`` and ``*`` patterns match.
    """
    parts = PurePosixPath(rel).parts
    if not parts or parts[0] == "/" or ".." in parts or "\x00" in rel:
        return None
    return stage.joinpath(*parts)


def _over_limit(size: int, fetched: int) -> str | None:
    """Why a file of ``size`` bytes is not fetched after ``fetched`` bytes, if it is not."""
    if size > MAX_FILE_BYTES:
        return f"{size} bytes, over the {MAX_FILE_BYTES}-byte limit for one file"
    if fetched + max(size, 0) > MAX_TOTAL_BYTES:
        return f"the {MAX_TOTAL_BYTES}-byte limit for one run folder is reached"
    return None


def _stage(root: DataRoot, stage: Path) -> None:
    """Copy into ``stage`` what the connectors need to read ``root``."""
    sizes = _file_sizes(root)
    wanted = _wanted(root, sizes)
    staged = fetched = 0
    for rel in sorted(wanted):
        target = _target(stage, rel)
        if target is None:
            logger.warning(f"Run detection skips {rel!r} in {root.location}: not a plain path")
            continue
        if staged >= MAX_STAGED_ENTRIES:
            logger.warning(
                f"Run detection stopped at {MAX_STAGED_ENTRIES} of the {len(wanted)} "
                f"provenance entries in {root.location}; the others are not looked at"
            )
            break
        kind = wanted[rel]
        body = b""
        if kind == _CONTENT:
            reason = _over_limit(sizes[rel], fetched)
            if reason is None:
                try:
                    body = root.read_bytes(rel)
                except FileNotFoundError:
                    logger.debug(f"Run detection: {root.url(rel)} is gone since the listing")
                    continue
                # A listing that reported no size is bounded once read.
                reason = _over_limit(len(body), fetched)
            if reason is not None:
                logger.warning(f"Run detection skips {root.url(rel)}: {reason}")
                continue
            fetched += len(body)
        try:
            if kind == _DIRECTORY:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
        except OSError as exc:
            # S3 can hold one path as a file and as a folder; a disk cannot.
            logger.debug(f"Run detection skips {rel!r} in {root.location}: {exc}")
            continue
        staged += 1


def _relocated(info: WorkflowRunInfo, stage: Path, root: DataRoot) -> WorkflowRunInfo:
    """``info`` with every path under ``stage`` replaced by its location under ``root``."""
    prefixes = tuple(dict.fromkeys((str(stage), str(stage.resolve()))))

    def back(value):
        if not isinstance(value, str):
            return value
        for prefix in prefixes:
            if value == prefix:
                return root.url("")
            if value.startswith(prefix + os.sep):
                return root.url(Path(value[len(prefix) + 1 :]).as_posix())
        return value

    update = {name: back(getattr(info, name)) for name in WorkflowRunInfo.model_fields}
    update["extra"] = {key: back(value) for key, value in info.extra.items()}
    return info.model_copy(update=update)
