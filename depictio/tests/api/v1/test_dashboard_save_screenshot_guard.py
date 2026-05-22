"""Invariants on the screenshot-enqueue idempotency guard.

Every React viewer interaction (open tab, duplicate, rename, no-op edit)
hits ``POST /dashboards/save/{id}``. Without this guard each one would
fire ``generate_dashboard_screenshot_dual.delay(...)`` and saturate the
celery worker pool — blocking advanced-viz ``compute_*`` tasks behind a
wall of Playwright renders at boot and after every click.

The guard returns True only when there's actual work to do: dual-theme
PNGs missing on disk, or older than the 1-hour staleness threshold
shared with the Dash auto-screenshot callback (``save.py:140``).
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from depictio.api.v1.endpoints.dashboards_endpoints import routes


def _touch(path: Path, mtime: float | None = None) -> None:
    path.write_bytes(b"")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_enqueue_when_pngs_missing() -> None:
    with tempfile.TemporaryDirectory() as td, patch.object(routes, "_SCREENSHOTS_DIR", td):
        assert routes._should_enqueue_screenshot("abc123") is True, "no PNGs on disk → must enqueue"


def test_enqueue_when_only_one_theme_missing() -> None:
    with tempfile.TemporaryDirectory() as td, patch.object(routes, "_SCREENSHOTS_DIR", td):
        _touch(Path(td) / "abc123_light.png")
        # dark missing → must enqueue
        assert routes._should_enqueue_screenshot("abc123") is True


def test_skip_when_both_pngs_fresh() -> None:
    with tempfile.TemporaryDirectory() as td, patch.object(routes, "_SCREENSHOTS_DIR", td):
        now = time.time()
        _touch(Path(td) / "abc123_light.png", mtime=now - 10)
        _touch(Path(td) / "abc123_dark.png", mtime=now - 10)
        assert routes._should_enqueue_screenshot("abc123", now_s=now) is False, (
            "both PNGs present and <1h old → skip — saves a Playwright run"
        )


def test_enqueue_when_pngs_stale() -> None:
    with tempfile.TemporaryDirectory() as td, patch.object(routes, "_SCREENSHOTS_DIR", td):
        now = time.time()
        # 2 hours past the 1h threshold
        old = now - (routes._SCREENSHOT_STALE_AFTER_S + 60 * 60)
        _touch(Path(td) / "abc123_light.png", mtime=old)
        _touch(Path(td) / "abc123_dark.png", mtime=old)
        assert routes._should_enqueue_screenshot("abc123", now_s=now) is True


def test_boundary_at_exactly_stale_threshold() -> None:
    """Equal-to-threshold counts as stale (>=) so the guard never drifts."""
    with tempfile.TemporaryDirectory() as td, patch.object(routes, "_SCREENSHOTS_DIR", td):
        now = time.time()
        old = now - routes._SCREENSHOT_STALE_AFTER_S
        _touch(Path(td) / "abc123_light.png", mtime=old)
        _touch(Path(td) / "abc123_dark.png", mtime=old)
        assert routes._should_enqueue_screenshot("abc123", now_s=now) is True
