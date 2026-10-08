"""The viewer bundle `depictio local up` builds when run from a source checkout."""

import os
import signal
import subprocess
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


SOURCES = [
    "pnpm-lock.yaml",
    "depictio/viewer/package.json",
    "depictio/viewer/src/main.tsx",
    "depictio/viewer/src/assets/fonts/Virgil.ttf",
    "depictio/viewer/public/logos/logo.svg",
    "packages/depictio-react-core/src/index.ts",
    # Scanned for icon names by scripts/generate-icon-subset.mjs.
    "depictio/models/components/advanced_viz/schemas.py",
    "depictio/projects/init/iris/dashboards/iris.yaml",
    "depictio/projects/init/iris/.db_seeds/iris.json",
]
NOT_SOURCES = [
    "depictio/viewer/node_modules/react/index.js",
    "depictio/viewer/dist/assets/main.js",
    "depictio/viewer/dist-catalog-preview/assets/main.js",
    "depictio/viewer/dist-table-harness/index.html",
    "depictio/viewer/src/generated/iconSubset.ts",
    "depictio/viewer/src/.DS_Store",
    "depictio/viewer/src/CLAUDE.md",
    "depictio/viewer/.vite/deps.json",
    "depictio/viewer/pnpm-debug.log",
    "packages/tool-studio/src/App.tsx",
    "depictio/projects/init/iris/iris.csv",
    "depictio/projects/init/__pycache__/x.cpython-312.pyc",
]


def _age(root, mtime):
    """Set every folder under ``root`` to ``mtime``: creating its files made them new."""
    for folder, _dirs, _files in os.walk(root):
        os.utime(folder, (mtime, mtime))


@pytest.fixture
def repo(tmp_path):
    """A checkout whose viewer bundle was built after its sources last changed."""
    root = tmp_path / "repo"
    old = time.time() - 3600
    for name in ["pnpm-workspace.yaml", *SOURCES, *NOT_SOURCES]:
        _write(root / name, mtime=old)
    _write(root / "depictio" / "viewer" / "dist" / "index.html", mtime=old + 60)
    _age(root, old)
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


@pytest.mark.parametrize("source", SOURCES)
def test_a_source_changed_since_the_build_makes_it_outdated(repo, source):
    os.utime(repo / source)

    assert viewer_outdated(repo) == f"{source} changed since the last build"


@pytest.mark.parametrize(
    "source",
    ["depictio/viewer/src/main.tsx", "depictio/projects/init/iris/.db_seeds/iris.json"],
)
def test_a_source_deleted_since_the_build_makes_it_outdated(repo, source):
    (repo / source).unlink()

    folder = os.path.dirname(source)
    assert viewer_outdated(repo) == f"a file in {folder} was added or deleted since the last build"


@pytest.mark.parametrize("not_a_source", NOT_SOURCES)
def test_files_the_build_does_not_read_leave_it_up_to_date(repo, not_a_source):
    os.utime(repo / not_a_source)

    assert viewer_outdated(repo) is None


def test_another_vite_run_leaves_it_up_to_date(repo):
    # `pnpm dev`, or the catalog preview build: vite writes a copy of its config next
    # to it, and deletes it once read.
    config_copy = repo / "depictio" / "viewer" / "vite.config.ts.timestamp-1700000000000-ab.mjs"
    _write(config_copy)
    config_copy.unlink()

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


def _running(pid: int) -> bool:
    """Alive and not a zombie (an orphan's reaper may take a moment)."""
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(out.stdout.strip()) and not out.stdout.strip().startswith("Z")


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP], ids=["SIGTERM", "SIGHUP"])
def test_a_signal_during_the_build_stops_pnpm_and_what_it_runs(repo, tmp_path, monkeypatch, signum):
    bin_dir, child = tmp_path / "bin", tmp_path / "child.pid"
    # pnpm runs a long step (vite, say), then `kill` arrives or the terminal closes.
    _write(
        bin_dir / "pnpm",
        f"#!/bin/sh\nsleep 60 &\necho $! > '{child}'\nkill -{signum.name[3:]} $PPID\nwait\n",
    ).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    def unhandled(signum, _frame):
        raise AssertionError(f"{signal.Signals(signum).name} reached the default handler")

    # Without build_viewer's own handler, this fails the test rather than end the run.
    previous = signal.signal(signum, unhandled)
    try:
        with pytest.raises(local_stack.Interrupted) as err:
            build_viewer(repo, tmp_path / "viewer-build.log")
    finally:
        signal.signal(signum, previous)

    assert err.value.signum == signum
    vite = int(child.read_text())
    deadline = time.monotonic() + 10
    while _running(vite) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _running(vite)


def _signal_inside_popen(monkeypatch, signum, ready):
    """subprocess.Popen, but the signal arrives before it returns, as on a loaded CI
    runner where the child runs `kill $PPID` before the parent is scheduled again."""
    real = subprocess.Popen
    sent = []

    def popen(*args, **kwargs):
        proc = real(*args, **kwargs)
        if not sent:
            sent.append(signum)
            deadline = time.monotonic() + 10
            while not ready() and time.monotonic() < deadline:
                time.sleep(0.05)
            os.kill(os.getpid(), signum)
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP], ids=["SIGTERM", "SIGHUP"])
def test_a_signal_inside_popen_still_stops_what_pnpm_runs(repo, tmp_path, monkeypatch, signum):
    bin_dir, child = tmp_path / "bin", tmp_path / "child.pid"
    _write(bin_dir / "pnpm", f"#!/bin/sh\nsleep 60 &\necho $! > '{child}'\nwait\n").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    _signal_inside_popen(monkeypatch, signum, ready=lambda: child.exists() and child.read_text())

    with pytest.raises(local_stack.Interrupted):
        build_viewer(repo, tmp_path / "viewer-build.log")

    vite = int(child.read_text())
    deadline = time.monotonic() + 10
    while _running(vite) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _running(vite)


def test_without_pnpm_the_build_says_what_to_install(repo, monkeypatch, tmp_path):
    monkeypatch.setattr(local_stack.shutil, "which", lambda name: None)

    with pytest.raises(LocalStackError, match="pnpm is not installed.*corepack enable pnpm"):
        build_viewer(repo, tmp_path / "viewer-build.log")
