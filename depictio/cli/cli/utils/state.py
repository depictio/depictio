"""Local scan state, cached between CLI invocations.

Every scan currently re-derives everything from scratch: walk the tree, build a
``File`` for each match, fetch the whole registered-file list per data
collection, compare. That is the right thing to do once. It is the wrong thing
to do every sixty seconds, which is what a watcher does.

This module records, per run, a signature of the run's file tree at the moment
it was last scanned successfully. A rescan whose signature matches can skip the
per-data-collection regex pass, the ``File`` construction (seven syscalls each,
via ``File.validate_location``) and the payload build.

What it deliberately does **not** do:

* **Store per-file hashes.** For a 100k-file project that is ~12 MB of JSON to
  parse on every invocation, and it buys nothing — ``generate_file_hash`` is a
  SHA-256 over four short strings, free once the ``stat`` is already in hand.
* **Short-circuit on the run directory's mtime.** Directory mtimes do not
  propagate from nested changes: a file modified three levels down leaves the
  run root untouched. Any check of that shape is silently wrong, so it is not
  here — please do not add one.
* **Decide what exists server-side.** The cache is advisory. A miss, a corrupt
  file, a schema bump or a changed project config all fall through to the full
  path. It only ever answers "is this run byte-for-byte as I last left it".
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from depictio.cli.cli_logging import logger

#: Bumped whenever the on-disk shape changes. A mismatch is a cache miss, never
#: a migration — the cache is cheap to rebuild and never authoritative.
STATE_SCHEMA_VERSION = 1

#: Overrides the state root. Useful for CI, for read-only home directories, and
#: for running several watchers against different servers from one account.
STATE_DIR_ENV_VAR = "DEPICTIO_CLI_STATE_DIR"

DEFAULT_STATE_DIR = Path("~/.depictio/state")


class RunState(BaseModel):
    """One run's tree as of its last successful scan."""

    run_tag: str
    run_location: str
    signature: str
    file_count: int = 0
    last_scanned_at: datetime = Field(default_factory=datetime.now)


class WorkflowState(BaseModel):
    runs: dict[str, RunState] = Field(default_factory=dict)


class ProjectScanState(BaseModel):
    schema_version: int = STATE_SCHEMA_VERSION
    api_base_url: str
    project_id: str
    #: The project config hash at write time. A changed config can change which
    #: files match, so an unchanged tree is no longer sufficient evidence.
    project_hash: str | None = None
    workflows: dict[str, WorkflowState] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.now)

    def run_state(self, workflow_id: str, run_tag: str) -> RunState | None:
        workflow = self.workflows.get(workflow_id)
        return workflow.runs.get(run_tag) if workflow else None

    def record_run(self, workflow_id: str, run: RunState) -> None:
        self.workflows.setdefault(workflow_id, WorkflowState()).runs[run.run_tag] = run

    def forget_runs(self, workflow_id: str, run_tags: set[str]) -> None:
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return
        for run_tag in run_tags:
            workflow.runs.pop(run_tag, None)


def state_dir() -> Path:
    override = os.environ.get(STATE_DIR_ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT_STATE_DIR.expanduser()


def server_key(api_base_url: str) -> str:
    """Short, stable directory name for one API server."""
    return hashlib.sha256(api_base_url.encode()).hexdigest()[:12]


def state_path(api_base_url: str, project_id: str) -> Path:
    """Where one project's state lives, namespaced by server.

    Keying on the API URL keeps staging and production from contaminating each
    other: the same project config ingested against two servers has two
    independent registration states, and a signature match against one says
    nothing about the other.
    """
    return state_dir() / server_key(api_base_url) / f"{project_id}.json"


def lock_path(api_base_url: str, project_id: str) -> Path:
    """Where the per-project ingestion lock lives.

    Namespaced by server for the same reason as the state file, and for one
    practical consequence: the project id comes from the YAML, so the same
    config pointed at staging and at production yields the *same* id. An
    unscoped lock would make those two watchers contend, and one would refuse
    to start for no real reason.
    """
    return state_dir() / server_key(api_base_url) / f"{project_id}.lock"


def load_state(
    api_base_url: str, project_id: str, *, project_hash: str | None = None
) -> ProjectScanState | None:
    """Read cached state, or ``None`` when it is absent or unusable.

    Never raises: a cache that cannot be read is simply a cache miss.
    """
    path = state_path(api_base_url, project_id)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        logger.debug(f"No scan state cached at {path}")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Ignoring unreadable scan state at {path}: {exc}")
        return None

    try:
        state = ProjectScanState.model_validate(raw)
    except Exception as exc:
        logger.warning(f"Ignoring invalid scan state at {path}: {exc}")
        return None

    if state.schema_version != STATE_SCHEMA_VERSION:
        logger.info(
            f"Discarding scan state at {path}: schema {state.schema_version} "
            f"!= {STATE_SCHEMA_VERSION}"
        )
        return None

    if project_hash is not None and state.project_hash != project_hash:
        logger.info(f"Discarding scan state at {path}: project config changed since it was written")
        return None

    return state


def save_state(state: ProjectScanState) -> None:
    """Persist state atomically. Never raises — this is a cache, not a record."""
    state.updated_at = datetime.now()
    path = state_path(state.api_base_url, state.project_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write cannot leave a half-written
        # file that the next run would have to treat as corrupt.
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, prefix=f"{path.stem}.", suffix=".tmp", delete=False
        ) as handle:
            handle.write(state.model_dump_json(indent=2))
            temp_path = handle.name
        os.replace(temp_path, path)
        logger.debug(f"Wrote scan state to {path}")
    except OSError as exc:
        logger.warning(f"Could not persist scan state to {path}: {exc}")
