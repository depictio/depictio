"""The viewer bundle `depictio local up` builds when run from a source checkout."""

import os
import time

import pytest

from depictio.cli.cli import local_stack
from depictio.cli.cli.local_stack import (
    LocalStackError,
    build_viewer,
    viewer_outdated,
    viewer_workspace,
)


def _write(path, text="x", mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def repo(tmp_path):
    """A checkout whose viewer bundle was built after its sources last changed."""
    root = tmp_path / "repo"
    old = time.time() - 3600
    _write(root / "pnpm-workspace.yaml", mtime=old)
    _write(root / "pnpm-lock.yaml", mtime=old)
    _write(root / "depictio" / "viewer" / "package.json", mtime=old)
    _write(root / "depictio" / "viewer" / "src" / "main.tsx", mtime=old)
    _write(root / "packages" / "depictio-react-core" / "src" / "index.ts", mtime=old)
    _write(root / "depictio" / "viewer" / "dist" / "index.html", mtime=old + 60)
    return root


def test_a_checkout_is_its_pnpm_workspace(repo, monkeypatch):
    monkeypatch.setattr(local_stack, "package_root", lambda: repo / "depictio")

    assert viewer_workspace() == repo


def test_a_wheel_has_no_workspace(tmp_path, monkeypatch):
    # A wheel ships the built bundle, not the viewer's sources.
    package = tmp_path / "site-packages" / "depictio"
    _write(package / "viewer" / "dist" / "index.html")
    monkeypatch.setattr(local_stack, "package_root", lambda: package)

    assert viewer_workspace() is None


def test_a_bundle_newer_than_its_sources_is_up_to_date(repo):
    assert viewer_outdated(repo) is None


def test_a_missing_bundle_is_outdated(repo):
    (repo / "depictio" / "viewer" / "dist" / "index.html").unlink()

    assert viewer_outdated(repo) == "not built yet"


@pytest.mark.parametrize(
    "source",
    [
        "depictio/viewer/src/main.tsx",
        "packages/depictio-react-core/src/index.ts",
        "pnpm-lock.yaml",
    ],
)
def test_a_source_changed_since_the_build_makes_it_outdated(repo, source):
    os.utime(repo / source)

    assert viewer_outdated(repo) == f"{source} changed since the last build"


@pytest.mark.parametrize(
    "not_a_source",
    [
        "depictio/viewer/node_modules/react/index.js",
        "depictio/viewer/dist/assets/main.js",
        "depictio/viewer/src/generated/iconSubset.ts",
        "depictio/viewer/src/.DS_Store",
        "depictio/viewer/.vite/deps.json",
        "depictio/viewer/pnpm-debug.log",
        "packages/tool-studio/src/App.tsx",
    ],
)
def test_files_the_build_does_not_read_leave_it_up_to_date(repo, not_a_source):
    _write(repo / not_a_source)

    assert viewer_outdated(repo) is None


@pytest.fixture
def pnpm(tmp_path, monkeypatch):
    """A pnpm on PATH that records each call; FAKE_PNPM_EXIT is its exit code."""
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls.txt"
    _write(
        bin_dir / "pnpm",
        "#!/bin/sh\n"
        'echo "pnpm $*"\n'
        f'echo "$* | $(pwd) | $VITE_NO_SOURCEMAP | $NODE_OPTIONS" >> "{calls}"\n'
        "exit ${FAKE_PNPM_EXIT:-0}\n",
    ).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    return calls


def test_the_build_installs_then_builds_as_a_release_does(repo, pnpm, tmp_path):
    log = tmp_path / "home" / "logs" / "viewer-build.log"

    build_viewer(repo, log)

    viewer = repo / "depictio" / "viewer"
    assert pnpm.read_text().splitlines() == [
        f"install --frozen-lockfile | {repo} | true | --max-old-space-size=4096",
        f"run build | {viewer} | true | --max-old-space-size=4096",
    ]
    text = log.read_text()
    assert "$ pnpm install --frozen-lockfile" in text
    assert "pnpm run build" in text


def test_a_failed_step_names_itself_and_the_log(repo, pnpm, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PNPM_EXIT", "3")
    log = tmp_path / "viewer-build.log"

    with pytest.raises(LocalStackError) as exc:
        build_viewer(repo, log)

    assert str(exc.value) == f"pnpm install --frozen-lockfile failed (exit 3, see {log})"
    # The build is not attempted after a failed install.
    assert len(pnpm.read_text().splitlines()) == 1


def test_without_pnpm_the_build_says_what_to_install(repo, monkeypatch, tmp_path):
    monkeypatch.setattr(local_stack.shutil, "which", lambda name: None)

    with pytest.raises(LocalStackError, match="pnpm is not installed.*corepack enable pnpm"):
        build_viewer(repo, tmp_path / "viewer-build.log")
