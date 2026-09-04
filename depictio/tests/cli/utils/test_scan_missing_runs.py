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

from depictio.models.models.base import PyObjectId
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow, WorkflowRun

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

    def fake_scan(**kwargs):
        return WorkflowRun(
            workflow_id=workflow.id,
            run_tag=kwargs["run_tag"],
            workflow_config_id=PyObjectId(WF_CONFIG_ID),
            run_location=kwargs["run_location"],
            creation_time=NOW,
            last_modification_time=NOW,
            permissions=Permission(owners=[UserBase.model_validate(OWNER)]),
        )

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch(
            "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
            side_effect=fake_scan,
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_run") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_file") as delete_file,
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

    def fake_scan(**kwargs):
        return WorkflowRun(
            workflow_id=workflow.id,
            run_tag=kwargs["run_tag"],
            workflow_config_id=PyObjectId(WF_CONFIG_ID),
            run_location=kwargs["run_location"],
            creation_time=NOW,
            last_modification_time=NOW,
            permissions=Permission(owners=[UserBase.model_validate(OWNER)]),
        )

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch(
            "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
            side_effect=fake_scan,
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch"),
        patch("depictio.cli.cli.utils.scan.api_delete_run") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_file"),
    ):
        from depictio.cli.cli.utils.scan import scan_files_for_workflow

        scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": True, "rich_tables": False},
        )

    assert delete_run.call_count == 1
    assert delete_run.call_args.kwargs["run_id"] == str(gone["_id"])


def test_without_rescan_nothing_is_reconciled(workflow, two_run_dirs):
    """The incremental path (`--attach-run` uses it) never deletes."""
    run_a, run_b = two_run_dirs
    existing = [_existing_run(workflow.id, run_a.name, str(run_a))]

    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = []
    runs_resp = MagicMock(status_code=200)
    runs_resp.json.return_value = existing

    def fake_scan(**kwargs):
        return WorkflowRun(
            workflow_id=workflow.id,
            run_tag=kwargs["run_tag"],
            workflow_config_id=PyObjectId(WF_CONFIG_ID),
            run_location=kwargs["run_location"],
            creation_time=NOW,
            last_modification_time=NOW,
            permissions=Permission(owners=[UserBase.model_validate(OWNER)]),
        )

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
        patch(
            "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
            side_effect=fake_scan,
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_run") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_file"),
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
