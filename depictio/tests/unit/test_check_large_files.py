"""scripts/check-large-files.sh keeps the repo from growing back.

It rejects an added or modified file over 500 KB unless a pattern of
.large-files-allowlist covers it. Git keeps every version of every file for good, so the
only cheap moment to stop a big blob is before it is committed.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "check-large-files.sh"
LIMIT = 512000

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(cwd: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("x\n")
    (tmp_path / ".large-files-allowlist").write_text("# comment\n\nallowed/*.bin\nuv.lock\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=repo, capture_output=True, text=True, timeout=60
    )


def _stage(repo: Path, rel: str, size: int) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    _git(repo, "add", rel)


def test_blocks_new_file_over_500kb(repo):
    _stage(repo, "data/big.bin", LIMIT + 1)
    result = _run(repo)
    assert result.returncode == 1
    assert "data/big.bin" in result.stdout


def test_allows_file_at_the_limit(repo):
    _stage(repo, "data/edge.bin", LIMIT)
    assert _run(repo).returncode == 0


def test_allows_file_listed_in_allowlist(repo):
    _stage(repo, "allowed/big.bin", LIMIT + 1)
    _stage(repo, "uv.lock", LIMIT * 2)
    assert _run(repo).returncode == 0


def test_blocks_modification_that_grows_an_unlisted_file(repo):
    _stage(repo, "data/small.bin", 10)
    _git(repo, "commit", "-q", "-m", "small")
    _stage(repo, "data/small.bin", LIMIT + 1)
    assert _run(repo).returncode == 1


def test_allows_deleting_a_large_file(repo):
    _stage(repo, "data/big.bin", LIMIT + 1)
    _git(repo, "commit", "-q", "-m", "big", "--no-verify")
    _git(repo, "rm", "-q", "data/big.bin")
    assert _run(repo).returncode == 0


def test_allows_small_files(repo):
    _stage(repo, "data/small.bin", 1000)
    assert _run(repo).returncode == 0


def test_handles_filenames_with_spaces(repo):
    _stage(repo, "data/my big file.bin", LIMIT + 1)
    result = _run(repo)
    assert result.returncode == 1
    assert "my big file.bin" in result.stdout


def test_base_mode_checks_the_commits_since_base(repo):
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    _stage(repo, "data/big.bin", LIMIT + 1)
    _git(repo, "commit", "-q", "-m", "add big", "--no-verify")
    assert _run(repo, "--base", base).returncode == 1
    assert _run(repo).returncode == 0  # nothing staged: the default mode is clean


def test_limit_can_be_overridden_by_environment(repo):
    _stage(repo, "data/mid.bin", 2000)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "LARGE_FILE_LIMIT": "1000"},
    )
    assert result.returncode == 1


def test_every_allowlist_pattern_matches_a_tracked_file():
    """A stale entry hides nothing today but silently allows a future big file."""
    patterns = [
        line.strip()
        for line in (REPO / ".large-files-allowlist").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    stale = [p for p in patterns if not any(fnmatch.fnmatch(f, p) for f in tracked)]
    assert not stale, f"allowlist patterns that match no tracked file: {stale}"
