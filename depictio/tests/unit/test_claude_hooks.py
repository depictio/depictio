"""The project's Claude Code hooks read their payload from stdin.

Claude Code hands a hook one JSON document on stdin (``{"tool_input": {...}}``) and
sets no ``TOOL_INPUT`` variable. The hooks used to read that variable, so the
dangerous-command check approved everything. These tests run the real scripts the way
Claude Code does and pin the three behaviours that matter: it blocks (exit 2, reason on
stderr), it approves a plain command, and it never approves a dangerous command just
because the payload could not be parsed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[3] / ".claude" / "hooks"
PRE_BASH = HOOKS / "pre-bash-check.sh"
POST_FILE = HOOKS / "post-file-change.sh"

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _run(script: Path, stdin: str, *, path: str | None = None) -> subprocess.CompletedProcess:
    # TOOL_INPUT is deliberately absent: Claude Code never sets it.
    env = {k: v for k, v in os.environ.items() if k != "TOOL_INPUT"}
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [str(script)], input=stdin, capture_output=True, text=True, env=env, timeout=30
    )


def _bash_payload(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


@needs_bash
def test_pre_bash_blocks_force_push_main():
    result = _run(PRE_BASH, _bash_payload("git push --force origin main"))
    assert result.returncode == 2
    assert "Blocked" in result.stderr


@needs_bash
def test_pre_bash_approves_plain_command():
    result = _run(PRE_BASH, _bash_payload("ls -la"))
    assert result.returncode == 0


@needs_bash
def test_pre_bash_empty_stdin_does_not_crash():
    result = _run(PRE_BASH, "")
    assert result.returncode == 0


@needs_bash
def test_pre_bash_blocks_when_payload_is_not_json():
    # Fail closed: an unparsable payload is scanned as raw text, not approved.
    result = _run(PRE_BASH, "git push --force origin main")
    assert result.returncode == 2


@needs_bash
def test_pre_bash_blocks_when_jq_is_missing(tmp_path):
    # A PATH with only the tools the script needs, and no jq.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("grep", "cat", "sed"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    result = _run(PRE_BASH, _bash_payload("git push --force origin main"), path=str(bin_dir))
    assert result.returncode == 2


@needs_bash
def test_pre_bash_blocks_rm_rf_of_the_repo_itself():
    result = _run(PRE_BASH, _bash_payload("rm -rf /home/me/work/depictio"))
    assert result.returncode == 2


@needs_bash
def test_pre_bash_allows_rm_rf_inside_a_worktree_path():
    # The path contains "/depictio" and "/workspaces" but is not the repo or workspace root.
    command = "rm -rf /home/me/workspaces/depictio-workspace/depictio-worktrees/old-branch"
    result = _run(PRE_BASH, _bash_payload(command))
    assert result.returncode == 0


@needs_bash
def test_post_hook_ignores_non_python_path():
    payload = json.dumps({"tool_input": {"file_path": "/tmp/notes.md"}})
    result = _run(POST_FILE, payload)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


@needs_bash
def test_post_hook_reads_file_path_from_stdin_and_emits_valid_json(tmp_path):
    ruff_dir = str(Path(sys.executable).parent)
    path = ruff_dir + os.pathsep + os.environ.get("PATH", "")
    if shutil.which("ruff", path=path) is None:
        pytest.skip("ruff not available")
    target = tmp_path / "depictio" / "models" / "bad_format.py"
    target.parent.mkdir(parents=True)
    target.write_text("x   =   1\n")
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    result = _run(POST_FILE, payload, path=path)
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "Format issues" in out["hookSpecificOutput"]["additionalContext"]
