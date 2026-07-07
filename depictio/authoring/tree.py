"""Directory tree listing for the studio file picker (left column)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from depictio.authoring.paths import rel_to_root, safe_resolve

# Suffixes the studio can preview + bind (tabular). Others are still listed so
# the user sees the whole run, just flagged as non-previewable.
PREVIEWABLE_SUFFIXES = {".csv", ".tsv", ".txt", ".parquet", ".feather"}

# Noise directories never worth showing in a run tree.
_IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    ".depictio",
    ".ipynb_checkpoints",
    ".pytest_cache",
}


def _node(root: Path, path: Path, depth: int, max_depth: int) -> dict[str, Any]:
    is_dir = path.is_dir()
    node: dict[str, Any] = {
        "name": path.name,
        "path": rel_to_root(root, path),
        "type": "dir" if is_dir else "file",
    }
    if is_dir:
        node["children"] = _list_dir(root, path, depth + 1, max_depth) if depth < max_depth else []
    else:
        node["previewable"] = path.suffix.lower() in PREVIEWABLE_SUFFIXES
        try:
            node["size"] = path.stat().st_size
        except OSError:
            node["size"] = None
    return node


def _list_dir(root: Path, directory: Path, depth: int, max_depth: int) -> list[dict[str, Any]]:
    try:
        entries = sorted(
            directory.iterdir(),
            key=lambda p: (p.is_file(), p.name.lower()),  # dirs first, then files
        )
    except OSError:
        return []
    children: list[dict[str, Any]] = []
    for entry in entries:
        if entry.name.startswith(".") and entry.is_dir():
            continue
        if entry.is_dir() and entry.name in _IGNORED_DIRS:
            continue
        children.append(_node(root, entry, depth, max_depth))
    return children


def build_tree(root: Path, rel: str = "", max_depth: int = 12) -> dict[str, Any]:
    """Return a nested tree rooted at ``root/rel`` (defaults to the studio root)."""
    target = safe_resolve(root, rel)
    if target.is_file():
        return _node(root, target, depth=max_depth, max_depth=max_depth)
    return {
        "name": target.name or str(target),
        "path": rel_to_root(root, target),
        "type": "dir",
        "children": _list_dir(root, target, depth=0, max_depth=max_depth),
    }
