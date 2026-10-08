"""Tests for redaction of project-scoped ingestion runs.

The threat these guard against is specific: a project with ``is_public: True``
passes ``_async_get_project_from_id`` for *any* authenticated user, so without
redaction, making a project public would also publish the operator's absolute
filesystem paths, their hostname, and their command line to strangers.
"""

from __future__ import annotations

from depictio.api.v1.endpoints.projects_endpoints.routes import _OPERATOR_FIELDS, _redact_run


def _run() -> dict:
    return {
        "run_id": "r1",
        "status": "success",
        "project_id": "p1",
        "project_name": "Demo",
        "command": "run",
        "command_line": "depictio run --project-config /home/alice/secret/project.yaml",
        "cli_config_path": "/home/alice/.depictio/CLI.yaml",
        "project_config_path": "/home/alice/work/project.yaml",
        "data_root": "/scratch/alice/runs",
        "cli_hostname": "hpc-login1",
        "cli_instance_label": "alice-laptop",
        "email": "alice@example.org",
        "user_id": "u-alice",
        "trigger": "watch",
        "steps": [{"name": "scan", "status": "success", "counters": {"files_new": 3}}],
        "counters": {"files_new": 3},
        "data_collections": [
            {
                "tag": "reads",
                "file_count": 3,
                "files_new": 3,
                "locations": ["/scratch/alice/runs/run1"],
                "scan_pattern": "*.fastq.gz",
                "sample_rejected": ["/scratch/alice/runs/run1/notes.txt"],
                "dirs_walked": 12,
            }
        ],
        "errors": [{"message": "bad row", "file_path": "/scratch/alice/runs/run1/bad.csv"}],
    }


class TestRedaction:
    def test_full_access_is_untouched(self):
        run = _run()
        assert _redact_run(run, full=True) == run

    def test_operator_fields_are_removed(self):
        redacted = _redact_run(_run(), full=False)
        for field in _OPERATOR_FIELDS:
            assert field not in redacted, f"{field} leaked to a non-editor"

    def test_identity_fields_are_removed(self):
        redacted = _redact_run(_run(), full=False)
        assert "email" not in redacted
        assert "user_id" not in redacted

    def test_dc_paths_and_patterns_are_removed(self):
        redacted = _redact_run(_run(), full=False)
        dc = redacted["data_collections"][0]
        assert "locations" not in dc
        assert "scan_pattern" not in dc
        # sample_rejected holds real scanned paths — the same class of leak as
        # locations, and easy to forget because it lives under diagnostics.
        assert "sample_rejected" not in dc

    def test_error_file_paths_are_removed_but_messages_kept(self):
        redacted = _redact_run(_run(), full=False)
        err = redacted["errors"][0]
        assert "file_path" not in err
        # The message is what makes the failure understandable; keep it.
        assert err["message"] == "bad row"

    def test_useful_fields_survive_redaction(self):
        redacted = _redact_run(_run(), full=False)
        # Without these the pane would be pointless for a viewer trying to tell
        # whether the data they see is current.
        assert redacted["status"] == "success"
        assert redacted["trigger"] == "watch"
        assert redacted["cli_instance_label"] == "alice-laptop"
        assert redacted["counters"] == {"files_new": 3}
        assert redacted["steps"][0]["counters"] == {"files_new": 3}
        assert redacted["data_collections"][0]["file_count"] == 3
        assert redacted["data_collections"][0]["dirs_walked"] == 12

    def test_does_not_mutate_the_input(self):
        original = _run()
        _redact_run(original, full=False)
        # Runs come straight from a Mongo query that may be reused; mutating in
        # place would redact the admin's copy too.
        assert original["data_root"] == "/scratch/alice/runs"
        assert "locations" in original["data_collections"][0]

    def test_tolerates_missing_optional_sections(self):
        minimal = {"run_id": "r2", "status": "running"}
        redacted = _redact_run(minimal, full=False)
        assert redacted == {"run_id": "r2", "status": "running"}

    def test_tolerates_malformed_nested_entries(self):
        # Documents written by an older CLI, or hand-edited, must not 500 the
        # endpoint for everyone else.
        weird = {"run_id": "r3", "data_collections": ["not-a-dict"], "errors": [None]}
        redacted = _redact_run(weird, full=False)
        assert redacted["data_collections"] == ["not-a-dict"]
        assert redacted["errors"] == [None]
