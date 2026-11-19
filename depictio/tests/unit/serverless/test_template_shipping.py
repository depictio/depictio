"""The serverless bundle template ships wherever a producer runs.

Producer A (API), producer C (the Celery `export_static` task, worker) and
producer B (`depictio build-static`, a pip-installed CLI) all inject a manifest
into `depictio/viewer/dist-static/static.html` — gitignored build output. It
used to be built nowhere but CI, so A/C failed in the released containers and B
failed after `pip install`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def test_the_wheel_ships_the_template() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    globs = data["tool"]["setuptools"]["package-data"]["depictio"]
    assert "viewer/dist-static/static.html" in globs
    check = (REPO / "scripts" / "check_depictio_wheel.py").read_text()
    assert r"depictio/viewer/dist-static/static\.html" in check
    # The runtime a rendered report embeds (serverless/combined.py).
    for name in ("combined-runtime.js", "combined-runtime.css"):
        assert f"viewer/dist-static/{name}" in globs
        assert f"depictio/viewer/dist-static/{name.replace('.', chr(92) + '.')}" in check


def test_every_producer_image_builds_and_copies_the_template() -> None:
    for name in ("Dockerfile.api", "Dockerfile.worker", "allinone/Dockerfile"):
        text = (REPO / "docker-images" / name).read_text()
        assert "build:static" in text, name
        assert re.search(r"COPY --from=\S+.*\n?.*dist-static/static\.html", text), name
        assert re.search(r"dist-static/combined-runtime\.js", text), name


def test_the_wheel_ci_builds_it_before_packaging() -> None:
    for name in ("local-server-smoke.yaml", "publish-pypi.yaml"):
        text = (REPO / ".github" / "workflows" / name).read_text()
        assert "pnpm run build:static" in text, name
