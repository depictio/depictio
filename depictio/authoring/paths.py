"""Path helpers shared across the studio backend.

Every studio endpoint resolves user-supplied relative paths against the single
``root`` directory the ``depictio studio <dir>`` command was launched with, and
refuses anything that escapes it (``..`` traversal, absolute paths, symlinks
pointing outside). This is the only trust boundary the service-free backend has.
"""

from __future__ import annotations

from pathlib import Path


class StudioPathError(ValueError):
    """Raised when a requested path escapes the studio root."""


def safe_resolve(root: Path, rel: str | None) -> Path:
    """Resolve ``rel`` under ``root``, rejecting any escape.

    ``rel`` is interpreted relative to ``root``; ``""``/``None`` returns ``root``
    itself. The resolved target must be ``root`` or live beneath it.
    """
    root = Path(root).resolve()
    rel = (rel or "").strip().lstrip("/")
    target = (root / rel).resolve() if rel else root
    if target != root and root not in target.parents:
        raise StudioPathError(f"path escapes studio root: {rel!r}")
    return target


def rel_to_root(root: Path, path: Path) -> str:
    """POSIX-style path of ``path`` relative to ``root`` (for API responses)."""
    return path.resolve().relative_to(Path(root).resolve()).as_posix()
