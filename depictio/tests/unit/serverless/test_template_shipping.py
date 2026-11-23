"""The static runtime ships wherever a producer runs.

Producer A (API), producer C (the Celery `export_static` task, worker) and
producer B (`depictio build-static`, a pip-installed CLI) all compose their
bundle page from `depictio/viewer/dist-static/combined-runtime.{js,css}` —
gitignored build output, the same runtime a rendered report embeds, shipped
once (there is no second `static.html` copy). It used to be built nowhere but
CI, so A/C failed in the released containers and B failed after `pip install`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def test_the_wheel_ships_the_runtime_once() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    globs = data["tool"]["setuptools"]["package-data"]["depictio"]
    check = (REPO / "scripts" / "check_depictio_wheel.py").read_text()
    # No second copy of the runtime as a single-file template.
    assert "viewer/dist-static/static.html" not in globs
    assert r"depictio/viewer/dist-static/static\.html" in check.split("FORBIDDEN")[1]
    # Bundles (serverless/bundle_html.py) and reports (serverless/combined.py).
    for name in ("combined-runtime.js", "combined-runtime.css"):
        assert f"viewer/dist-static/{name}" in globs
        assert f"depictio/viewer/dist-static/{name.replace('.', chr(92) + '.')}" in check


def test_every_producer_image_builds_and_copies_the_runtime() -> None:
    for name in ("Dockerfile.api", "Dockerfile.worker", "allinone/Dockerfile"):
        text = (REPO / "docker-images" / name).read_text()
        assert "build:static" in text, name
        assert "dist-static/static.html" not in text, name
        assert re.search(r"dist-static/combined-runtime\.js", text), name


def test_the_wheel_ci_builds_it_before_packaging() -> None:
    for name in ("local-server-smoke.yaml", "publish-pypi.yaml"):
        text = (REPO / ".github" / "workflows" / name).read_text()
        assert "pnpm run build:static" in text, name
