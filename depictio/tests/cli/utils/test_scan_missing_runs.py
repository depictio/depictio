"""Regression test: missing-run reconciliation must not fire per location.

`scan_files_for_workflow` deletes runs that are registered server-side but no longer
present on disk. That reconciliation compares the registry against
``all_workflow_runs``, which accumulates *across* locations, so running it inside the
``for location in locations`` loop deleted the runs of every location not yet walked
(they were then re-created with fresh ids, losing their scan history).

`--attach-run` makes multi-location workflows the normal case, so this is exercised
directly here: two locations, `rescan_folders=True`, and nothing may be deleted.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from depictio.cli.cli.utils.scan import flat_run_tag_clash, scan_files_for_workflow
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow, WorkflowDataLocation, WorkflowRun

NOW = "2026-09-03 23:00:00"
OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}
WF_CONFIG_ID = "507f1f77bcf86cd799439099"


@pytest.fixture
def two_run_dirs(tmp_path):
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    for d in (run_a, run_b):
        d.mkdir()
        (d / "table.tsv").write_text("a\tb\n1\t2\n")
    return run_a, run_b


@pytest.fixture
def workflow(two_run_dirs):
    run_a, run_b = two_run_dirs
    return Workflow.model_validate(
        {
            "name": "ampliseq",
            "engine": {"name": "nextflow"},
            "catalog": {"name": "nf-core", "url": "https://nf-co.re"},
            "data_location": {
                "structure": "flat",
                "locations": [str(run_a), str(run_b)],
            },
            "config": {"version": "2.16.0"},
            "data_collections": [
                {
                    "data_collection_tag": "asv_table",
                    "config": {
                        "type": "Table",
                        "scan": {
                            "mode": "recursive",
                            "scan_parameters": {"regex_config": {"pattern": "table.tsv$"}},
                        },
                        "dc_specific_properties": {
                            "format": "TSV",
                            "polars_kwargs": {"separator": "\t"},
                        },
                    },
                }
            ],
        }
    )


def _existing_run(workflow_id, run_tag: str, location: str) -> dict:
    return WorkflowRun(
        workflow_id=workflow_id,
        run_tag=run_tag,
        workflow_config_id=PyObjectId(WF_CONFIG_ID),
        run_location=location,
        creation_time=NOW,
        last_modification_time=NOW,
        permissions=Permission(owners=[UserBase.model_validate(OWNER)]),
    ).mongo()


def _cli_config():
    cli_config = MagicMock()
    cli_config.user.model_dump.return_value = {**OWNER, "token": None}
    return cli_config


def _fake_scan(workflow):
    """scan_run_for_multiple_data_collections as it answers: the registered run it
    was given, rescanned, else a new one."""

    def fake_scan(**kwargs):
        if kwargs.get("existing_run") is not None:
            return kwargs["existing_run"]
        return WorkflowRun(
            workflow_id=workflow.id,
            run_tag=kwargs["run_tag"],
            workflow_config_id=PyObjectId(WF_CONFIG_ID),
            run_location=kwargs["run_location"],
            creation_time=NOW,
            last_modification_time=NOW,
            permissions=Permission(owners=[UserBase.model_validate(OWNER)]),
        )

    return fake_scan


def test_rescan_over_two_locations_deletes_nothing(workflow, two_run_dirs):
    """Both runs are on disk, so a full rescan must delete neither."""
    run_a, run_b = two_run_dirs
    existing = [
        _existing_run(workflow.id, run_a.name, str(run_a)),
        _existing_run(workflow.id, run_b.name, str(run_b)),
    ]

    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = []
    runs_resp = MagicMock(status_code=200)
    runs_resp.json.return_value = existing

    fake_scan = _fake_scan(workflow)

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch(
            "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
            side_effect=fake_scan,
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_runs") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files") as delete_file,
    ):
        from depictio.cli.cli.utils.scan import scan_files_for_workflow

        result = scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": True, "rich_tables": False},
        )

    assert result["result"] == "success"
    # The regression: run_b was deleted after location 1 was walked.
    assert delete_run.call_count == 0
    assert delete_file.call_count == 0
    scanned = {r.run_tag for r in upsert.call_args.args[0]}
    assert scanned == {run_a.name, run_b.name}


def test_run_that_vanished_from_disk_is_still_deleted(workflow, two_run_dirs):
    """The reconciliation must keep working: a registered run with no directory goes."""
    run_a, run_b = two_run_dirs
    gone = _existing_run(workflow.id, "run_gone", "/nowhere/run_gone")
    existing = [
        _existing_run(workflow.id, run_a.name, str(run_a)),
        _existing_run(workflow.id, run_b.name, str(run_b)),
        gone,
    ]

    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = []
    runs_resp = MagicMock(status_code=200)
    runs_resp.json.return_value = existing

    fake_scan = _fake_scan(workflow)

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch(
            "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
            side_effect=fake_scan,
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch"),
        patch("depictio.cli.cli.utils.scan.api_delete_runs") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files"),
    ):
        from depictio.cli.cli.utils.scan import scan_files_for_workflow

        scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": True, "rich_tables": False},
        )

    assert delete_run.call_count == 1
    assert delete_run.call_args.args[0] == [str(gone["_id"])]


def test_without_rescan_nothing_is_reconciled(workflow, two_run_dirs):
    """The incremental path (`--attach-run` uses it) never deletes."""
    run_a, run_b = two_run_dirs
    existing = [_existing_run(workflow.id, run_a.name, str(run_a))]

    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = []
    runs_resp = MagicMock(status_code=200)
    runs_resp.json.return_value = existing

    fake_scan = _fake_scan(workflow)

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch(
            "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
            side_effect=fake_scan,
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_runs") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files"),
    ):
        from depictio.cli.cli.utils.scan import scan_files_for_workflow

        scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": False, "rich_tables": False},
        )

    assert delete_run.call_count == 0
    # Only the run that was not already registered gets scanned.
    scanned = {r.run_tag for r in upsert.call_args.args[0]}
    assert scanned == {run_b.name}


def test_a_gone_run_the_cli_cannot_load_is_deleted_too(workflow, two_run_dirs, monkeypatch):
    """In the CLI context a run's directory must exist to load it at all.

    A refresh after a run directory was moved used to fail the whole scan on that
    run's own record; it is now removed like any run the rescan no longer finds.
    """
    run_a, run_b = two_run_dirs
    existing = [
        _existing_run(workflow.id, run_a.name, str(run_a)),
        _existing_run(workflow.id, run_b.name, str(run_b)),
    ]
    gone = _existing_run(workflow.id, "run_gone", str(run_a))
    gone["run_location"] = "/nowhere/run_gone"
    existing.append(gone)
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")

    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = []
    runs_resp = MagicMock(status_code=200)
    runs_resp.json.return_value = existing

    fake_scan = _fake_scan(workflow)

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch(
            "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
            side_effect=fake_scan,
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch"),
        patch("depictio.cli.cli.utils.scan.api_delete_runs") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files"),
    ):
        from depictio.cli.cli.utils.scan import scan_files_for_workflow

        result = scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": True, "rich_tables": False},
        )

    assert result["result"] == "success"
    assert delete_run.call_count == 1
    assert delete_run.call_args.args[0] == [str(gone["_id"])]


class TestFlatRunsOfTheSameName:
    """A flat run is named after its directory: two `results` directories would be
    one run, and every sample would be listed twice."""

    @staticmethod
    def _location(structure: str, locations: list[str], **extra) -> WorkflowDataLocation:
        return WorkflowDataLocation(structure=structure, locations=locations, **extra)

    def test_two_directories_of_the_same_name_clash(self, tmp_path):
        a, b = tmp_path / "a" / "results", tmp_path / "b" / "results"
        clash = flat_run_tag_clash(self._location("flat", [str(a), str(b)]))
        assert clash is not None
        assert f"{a} and {b} would both be run 'results'" in clash

    def test_the_same_directory_through_a_symlink_does_not(self, tmp_path):
        real = tmp_path / "results"
        real.mkdir()
        (tmp_path / "link").mkdir()
        link = tmp_path / "link" / "results"
        link.symlink_to(real)
        assert flat_run_tag_clash(self._location("flat", [str(real), str(link)])) is None

    def test_runs_of_other_names_do_not(self):
        assert flat_run_tag_clash(self._location("flat", ["/x/run_a", "/x/run_b"])) is None

    def test_sequencing_runs_are_named_otherwise(self):
        location = self._location(
            "sequencing-runs", ["/a/results", "/b/results"], runs_regex="run_.*"
        )
        assert flat_run_tag_clash(location) is None

    def test_the_scan_refuses_them_before_reading_anything(self, workflow, tmp_path):
        a, b = tmp_path / "a" / "results", tmp_path / "b" / "results"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        workflow.data_location.locations = [str(a), str(b)]

        with (
            patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id") as get_files,
            patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id") as get_runs,
            patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        ):
            with pytest.raises(ValueError, match="would both be run 'results'"):
                scan_files_for_workflow(
                    workflow=workflow,
                    data_collections=workflow.data_collections,
                    CLI_config=_cli_config(),
                    command_parameters={"rescan_folders": True, "rich_tables": False},
                )

        get_files.assert_not_called()
        get_runs.assert_not_called()
        upsert.assert_not_called()


def test_a_run_of_the_same_name_from_another_directory_is_replaced(workflow, tmp_path):
    """A refresh after a results directory moved: the run is still `results`.

    Reused, the old run kept the files of the old directory, still on disk, next
    to the new ones, and every sample was listed twice. It is now removed with its
    files, and the new directory registered as a new run.
    """
    old, new = tmp_path / "a" / "results", tmp_path / "b" / "results"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    workflow.data_location.locations = [str(new)]
    registered = _existing_run(workflow.id, "results", str(old))
    old_file = {"_id": "64b0f3c1e4a2d7f8e5b8c001", "run_id": str(registered["_id"])}
    old_file["file_location"] = str(old / "table.tsv")

    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = [old_file]
    runs_resp = MagicMock(status_code=200)
    runs_resp.json.return_value = [registered]
    scan_run = MagicMock(side_effect=_fake_scan(workflow))

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch("depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections", scan_run),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_runs") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files") as delete_file,
    ):
        scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": True, "rich_tables": False},
        )

    assert scan_run.call_args.kwargs["existing_run"] is None
    assert delete_run.call_args.args[0] == [str(registered["_id"])]
    assert delete_file.call_args.args[0] == [old_file["_id"]]
    (run,) = upsert.call_args.args[0]
    assert run.run_tag == "results"
    assert run.run_location == str(new)
    assert str(run.id) != str(registered["_id"])


def test_the_same_directory_keeps_its_run(workflow, two_run_dirs):
    """Reached through a symlink, it is the run already registered."""
    run_a, _ = two_run_dirs
    link_parent = run_a.parent / "via_link"
    link_parent.mkdir()
    (link_parent / run_a.name).symlink_to(run_a)
    workflow.data_location.locations = [str(link_parent / run_a.name)]
    registered = _existing_run(workflow.id, run_a.name, str(run_a))

    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = []
    runs_resp = MagicMock(status_code=200)
    runs_resp.json.return_value = [registered]
    scan_run = MagicMock(side_effect=_fake_scan(workflow))

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch("depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections", scan_run),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch"),
        patch("depictio.cli.cli.utils.scan.api_delete_runs") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files"),
    ):
        scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": True, "rich_tables": False},
        )

    assert str(scan_run.call_args.kwargs["existing_run"].id) == str(registered["_id"])
    delete_run.assert_not_called()
