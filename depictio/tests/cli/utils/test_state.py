"""Tests for the local scan-state cache.

The cache is advisory: every failure mode must degrade to "rescan everything"
rather than to a wrong answer. These tests are mostly about the ways it is
allowed to say no.
"""

import json

import pytest

from depictio.cli.cli.utils.state import (
    STATE_DIR_ENV_VAR,
    STATE_SCHEMA_VERSION,
    ProjectScanState,
    RunState,
    load_state,
    save_state,
    state_path,
)

API_URL = "http://localhost:8058"
OTHER_API_URL = "http://staging.example.org"
PROJECT_ID = "6a63de3c7577b6bb68993a94"


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(tmp_path / "state"))
    return tmp_path / "state"


def make_state(**kwargs) -> ProjectScanState:
    state = ProjectScanState(
        api_base_url=kwargs.pop("api_base_url", API_URL),
        project_id=kwargs.pop("project_id", PROJECT_ID),
        project_hash=kwargs.pop("project_hash", "hash-1"),
    )
    state.record_run(
        "wf-1",
        RunState(run_tag="run-a", run_location="/data/run-a", signature="sig-a", file_count=3),
    )
    return state


class TestRoundTrip:
    def test_save_then_load(self):
        save_state(make_state())
        loaded = load_state(API_URL, PROJECT_ID)

        assert loaded is not None
        cached = loaded.run_state("wf-1", "run-a")
        assert cached is not None
        assert cached.signature == "sig-a"
        assert cached.file_count == 3

    def test_missing_file_is_a_miss_not_an_error(self):
        assert load_state(API_URL, PROJECT_ID) is None

    def test_unknown_workflow_or_run_returns_none(self):
        save_state(make_state())
        loaded = load_state(API_URL, PROJECT_ID)

        assert loaded is not None
        assert loaded.run_state("wf-other", "run-a") is None
        assert loaded.run_state("wf-1", "run-unknown") is None

    def test_record_run_overwrites_in_place(self):
        state = make_state()
        state.record_run(
            "wf-1",
            RunState(run_tag="run-a", run_location="/data/run-a", signature="sig-b"),
        )
        cached = state.run_state("wf-1", "run-a")
        assert cached is not None
        assert cached.signature == "sig-b"

    def test_forget_runs_drops_only_the_named_tags(self):
        state = make_state()
        state.record_run(
            "wf-1",
            RunState(run_tag="run-b", run_location="/data/run-b", signature="sig-b"),
        )
        state.forget_runs("wf-1", {"run-a", "never-existed"})

        assert state.run_state("wf-1", "run-a") is None
        assert state.run_state("wf-1", "run-b") is not None


class TestInvalidation:
    def test_project_hash_change_discards_state(self):
        save_state(make_state(project_hash="hash-1"))
        # A different config can change which files match, so an unchanged tree
        # is no longer sufficient evidence that nothing needs re-scanning.
        assert load_state(API_URL, PROJECT_ID, project_hash="hash-2") is None

    def test_matching_project_hash_keeps_state(self):
        save_state(make_state(project_hash="hash-1"))
        assert load_state(API_URL, PROJECT_ID, project_hash="hash-1") is not None

    def test_absent_project_hash_check_keeps_state(self):
        save_state(make_state(project_hash="hash-1"))
        assert load_state(API_URL, PROJECT_ID) is not None

    def test_schema_bump_discards_state(self):
        save_state(make_state())
        path = state_path(API_URL, PROJECT_ID)
        raw = json.loads(path.read_text())
        raw["schema_version"] = STATE_SCHEMA_VERSION + 1
        path.write_text(json.dumps(raw))

        assert load_state(API_URL, PROJECT_ID) is None

    def test_corrupt_json_is_a_miss_not_a_crash(self):
        save_state(make_state())
        state_path(API_URL, PROJECT_ID).write_text("{not json")

        assert load_state(API_URL, PROJECT_ID) is None

    def test_structurally_invalid_state_is_a_miss(self):
        save_state(make_state())
        state_path(API_URL, PROJECT_ID).write_text(json.dumps({"schema_version": 1}))

        assert load_state(API_URL, PROJECT_ID) is None


class TestServerNamespacing:
    def test_different_servers_do_not_share_state(self):
        save_state(make_state(api_base_url=API_URL))
        # The same project ingested against staging and production has two
        # independent registration states; a signature match against one says
        # nothing about the other.
        assert load_state(OTHER_API_URL, PROJECT_ID) is None

    def test_paths_differ_per_server(self):
        assert state_path(API_URL, PROJECT_ID) != state_path(OTHER_API_URL, PROJECT_ID)

    def test_path_is_stable_for_the_same_inputs(self):
        assert state_path(API_URL, PROJECT_ID) == state_path(API_URL, PROJECT_ID)


class TestDurability:
    def test_save_is_atomic_and_leaves_no_temp_files(self):
        save_state(make_state())
        path = state_path(API_URL, PROJECT_ID)
        leftovers = [p.name for p in path.parent.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_save_failure_does_not_raise(self, monkeypatch):
        def explode(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr("depictio.cli.cli.utils.state.os.replace", explode)
        # A cache that cannot be written must never take an ingestion down.
        save_state(make_state())

    def test_second_save_replaces_the_first(self):
        save_state(make_state())
        state = make_state()
        state.record_run(
            "wf-1",
            RunState(run_tag="run-a", run_location="/data/run-a", signature="sig-updated"),
        )
        save_state(state)

        loaded = load_state(API_URL, PROJECT_ID)
        assert loaded is not None
        cached = loaded.run_state("wf-1", "run-a")
        assert cached is not None
        assert cached.signature == "sig-updated"


class TestLockPath:
    """The lock must be namespaced exactly like the state file."""

    def test_lock_sits_beside_the_state_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CLI_STATE_DIR", str(tmp_path))
        from depictio.cli.cli.utils.state import lock_path, state_path

        state = state_path("http://api.example", "proj1")
        lock = lock_path("http://api.example", "proj1")
        assert lock.parent == state.parent
        assert lock.name == "proj1.lock"

    def test_same_project_on_two_servers_gets_two_locks(self, tmp_path, monkeypatch):
        # The project id comes from the YAML, so a config pointed at staging and
        # at production shares it. An unscoped lock would make those two
        # watchers contend and one would refuse to start.
        monkeypatch.setenv("DEPICTIO_CLI_STATE_DIR", str(tmp_path))
        from depictio.cli.cli.utils.state import lock_path

        assert lock_path("http://staging", "proj1") != lock_path("http://prod", "proj1")

    def test_different_projects_on_one_server_get_two_locks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CLI_STATE_DIR", str(tmp_path))
        from depictio.cli.cli.utils.state import lock_path

        assert lock_path("http://api", "proj1") != lock_path("http://api", "proj2")
