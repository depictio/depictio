"""Disk-persistent storage for pre-rendered MultiQC figures.

Each figure is a gzipped JSON dict (the Plotly figure dict produced by
``go.Figure.to_dict()``) under ``<prerender_dir>/<dc_id>/<sha>.json.gz`` where
``<sha>`` is the trailing hash segment of the Phase-1 bare cache key.

The store is intentionally dumb: pure filesystem, no MongoDB, no Redis. The
build task writes here after rendering; the render endpoint reads from here on
Redis miss. Freshness is tracked separately via the
``multiqc_prerender_collection`` doc + s3_locations_hash.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


def _split_cache_key(cache_key: str) -> str:
    """Extract the trailing hash digest from a Phase-1 bare cache key.

    Bare keys have the shape ``multiqc:figure:dc=<id>:<16-hex>``. The hash is
    deterministic over (s3_locations, module, plot, dataset, theme), so we use
    it as the on-disk filename without re-hashing.
    """
    return cache_key.rsplit(":", 1)[-1]


def prerender_dir() -> Path:
    """Resolve and create the configured prerender directory."""
    raw = settings.multiqc_prerender.prerender_dir
    path = Path(os.path.expanduser(raw)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def dc_dir(dc_id: str) -> Path:
    """Per-DC directory; created on demand."""
    path = prerender_dir() / str(dc_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def figure_path(dc_id: str, cache_key: str) -> Path:
    """Absolute path for a single figure file (does not check existence)."""
    return dc_dir(dc_id) / f"{_split_cache_key(cache_key)}.json.gz"


def write_figure(dc_id: str, cache_key: str, fig_dict: dict) -> None:
    """Atomically gzip-write ``fig_dict`` to the figure path.

    Uses tmpfile+rename so partial writes (worker crash mid-build) never leave
    a corrupt gzip on disk that the render endpoint would then try to
    deserialize.
    """
    target = figure_path(dc_id, cache_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp.", suffix=".json.gz", dir=target.parent)
    try:
        os.close(fd)
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            json.dump(fig_dict, f, separators=(",", ":"))
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def read_figure(dc_id: str, cache_key: str) -> Optional[dict]:
    """Return the persisted figure dict, or ``None`` if missing / unreadable.

    Failures (corrupt gzip, partial write surviving a crash, permission error)
    are logged at warning and treated as miss — the caller falls through to the
    build path, which is the safer outcome than crashing the render endpoint.
    """
    path = figure_path(dc_id, cache_key)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, EOFError) as exc:
        logger.warning(f"multiqc_prerender_store: failed to read {path}: {exc}")
        return None


def delete_dc_dir(dc_id: str) -> int:
    """Remove the entire DC subdir, returning file count deleted.

    Called from the invalidator on append/replace so the next build task
    rebuilds against the new file set. Idempotent: missing dir returns 0.
    """
    path = prerender_dir() / str(dc_id)
    if not path.exists():
        return 0
    count = sum(1 for _ in path.rglob("*") if _.is_file())
    shutil.rmtree(path, ignore_errors=True)
    return count
