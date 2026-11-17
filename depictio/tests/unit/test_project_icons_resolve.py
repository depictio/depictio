"""Icons named by the shipped dashboards must resolve in the viewer's bundle.

The viewer bundles a subset of the installed @iconify-json collections
(``pnpm run icons``) and its CSP blocks the Iconify API, so an ``icon`` /
``tab_icon`` / ``icon_name`` under ``depictio/projects/`` that no collection
holds renders as an empty box in a built bundle. The generator only warns;
``scripts/check-icons.mjs`` (``pnpm run check:icons``) fails, and this runs it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parents[2] / "viewer"
SCRIPT = VIEWER / "scripts" / "check-icons.mjs"


def test_project_icons_resolve_in_installed_collections():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    if not (VIEWER / "node_modules" / "@iconify-json").is_dir():
        pytest.skip("viewer dependencies are not installed (pnpm install)")
    assert SCRIPT.is_file()

    result = subprocess.run(
        [node, str(SCRIPT)],
        cwd=VIEWER,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"{result.stderr}\n{result.stdout}"
