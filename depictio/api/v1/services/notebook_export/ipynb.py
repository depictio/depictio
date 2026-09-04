"""Derive a Jupyter notebook from a marimo file, with marimo's own converter.

One generator, two artefacts: the ``.ipynb`` is never written by a second
template. ``marimo export ipynb`` is run as a subprocess with
``--no-include-outputs`` so nothing executes on the server, and ``--sort
top-down`` so the reading order the generator chose survives.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


class IpynbExportUnavailable(RuntimeError):
    """marimo (or nbformat) is missing, timed out or failed."""


def marimo_version() -> str | None:
    try:
        import marimo

        return str(marimo.__version__)
    except Exception:
        return None


def ipynb_available() -> bool:
    try:
        import marimo  # noqa: F401
        import nbformat  # noqa: F401
    except Exception:
        return False
    return True


def to_ipynb(marimo_source: str, *, timeout_s: int = 60, stem: str = "notebook") -> bytes:
    """The ``.ipynb`` bytes for a marimo file's source."""
    if not ipynb_available():
        raise IpynbExportUnavailable(
            "marimo and nbformat must be installed on the server to derive a Jupyter notebook"
        )
    with tempfile.TemporaryDirectory(prefix="depictio-nb-") as tmp:
        src = Path(tmp) / f"{stem}.py"
        out = Path(tmp) / f"{stem}.ipynb"
        src.write_text(marimo_source, encoding="utf-8")
        cmd = [
            sys.executable,
            "-m",
            "marimo",
            "export",
            "ipynb",
            str(src),
            "-o",
            str(out),
            "--no-include-outputs",
            "--sort",
            "top-down",
            "--force",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_s, cwd=tmp, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise IpynbExportUnavailable(
                f"marimo export ipynb timed out after {timeout_s}s"
            ) from exc
        if proc.returncode != 0 or not out.exists():
            detail = (proc.stderr or proc.stdout or "").strip()[-800:]
            raise IpynbExportUnavailable(f"marimo export ipynb failed: {detail}")
        return out.read_bytes()
