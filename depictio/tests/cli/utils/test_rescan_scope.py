"""A rescan deletes or replaces only what its walk covers.

A refresh walks a workflow's run folders with ``rescan_folders`` and
``sync_files`` on. Two things the walk does not cover must survive it:

- the files of the *other* runs of a collection. The per-run stale-file
  cleanup counted every registered file of the collection, so walking one run
  deleted the files of all the others, and only the last run walked kept any;
- a run another scan registered for the same workflow: one an ``s3_prefix``
  scan registered, located at a URL, which no local walk ever finds.

The synthetic runs of the single, url and manifest scans
(``<tag>-single-file-scan`` and the like) are never written to the server, so
there is nothing of theirs for a rescan to delete.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from depictio.cli.cli.utils.scan import scan_files_for_workflow
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow, WorkflowRun

NOW = "2026-10-08 12:00:00"
OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}


@pytest.fixture
def root(tmp_path):
    """Two run folders, one table each."""
    for name in ("run_a", "run_b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "table.tsv").write_text("a\tb\n1\t2\n")
    return tmp_path


@pytest.fixture
def workflow(root):
    return Workflow.model_validate(
        {
            "name": "wf",
            "engine": {"name": "nextflow"},
            "data_location": {
                "structure": "sequencing-runs",
                "locations": [str(root)],
                "runs_regex": "run_.*",
            },
            "config": {},
            "data_collections": [
                {
                    "data_collection_tag": "table",
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


def _run(workflow, tag: str, location: str) -> dict:
    return WorkflowRun(
        workflow_id=workflow.id,
        run_tag=tag,
        workflow_config_id=PyObjectId(),
        run_location=location,
        creation_time=NOW,
        last_modification_time=NOW,
        permissions=Permission(owners=[UserBase.model_validate(OWNER)]),
    ).mongo()


def _file(run: dict, location: str) -> dict:
    return {
        "_id": str(PyObjectId()),
        "file_location": os.path.realpath(location),
        "file_hash": "registered-earlier",
        "run_id": str(run["_id"]),
    }


def _rescan(workflow, runs: list[dict], files: list[dict]):
    """A refresh's walk: ``rescan_folders`` and ``sync_files`` on, the API stubbed."""
    files_response = MagicMock(status_code=200)
    files_response.json.return_value = files
    runs_response = MagicMock(status_code=200)
    runs_response.json.return_value = runs
    cli_config = MagicMock()
    cli_config.user.model_dump.side_effect = lambda: {**OWNER, "token": None}
    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_response),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_response),
        patch("depictio.cli.cli.utils.scan.api_create_files"),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_run") as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_file") as delete_file,
    ):
        result = scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=cli_config,
            command_parameters={"rescan_folders": True, "sync_files": True, "rich_tables": False},
        )
    assert result["result"] == "success"
    deleted_files = {c.kwargs["file_id"] for c in delete_file.call_args_list}
    deleted_runs = {c.kwargs["run_id"] for c in delete_run.call_args_list}
    return deleted_files, deleted_runs, upsert


def test_a_sync_rescan_keeps_the_files_of_every_run(workflow, root):
    run_a = _run(workflow, "run_a", str(root / "run_a"))
    run_b = _run(workflow, "run_b", str(root / "run_b"))
    files = [
        _file(run_a, str(root / "run_a" / "table.tsv")),
        _file(run_b, str(root / "run_b" / "table.tsv")),
    ]

    deleted_files, deleted_runs, _upsert = _rescan(workflow, [run_a, run_b], files)

    # Both files are still on disk: walking run_b used to delete run_a's.
    assert deleted_files == set()
    assert deleted_runs == set()


def test_a_sync_rescan_still_drops_a_file_gone_from_its_own_run(workflow, root):
    run_a = _run(workflow, "run_a", str(root / "run_a"))
    run_b = _run(workflow, "run_b", str(root / "run_b"))
    gone = _file(run_a, str(root / "run_a" / "old.tsv"))
    files = [
        _file(run_a, str(root / "run_a" / "table.tsv")),
        gone,
        _file(run_b, str(root / "run_b" / "table.tsv")),
    ]

    deleted_files, _deleted_runs, _upsert = _rescan(workflow, [run_a, run_b], files)

    assert deleted_files == {gone["_id"]}


def test_a_rescan_keeps_the_runs_another_scan_registered(workflow, root):
    run_a = _run(workflow, "run_a", str(root / "run_a"))
    run_b = _run(workflow, "run_b", str(root / "run_b"))
    # Registered by an s3_prefix scan of the same workflow.
    remote = _run(workflow, "run_9", "s3://b/data/run_9")
    # A run of this walk whose folder is gone still goes.
    vanished = _run(workflow, "run_c", str(root / "run_a"))
    vanished["run_location"] = str(root / "run_c")

    _deleted_files, deleted_runs, _upsert = _rescan(workflow, [run_a, run_b, remote, vanished], [])

    assert deleted_runs == {str(vanished["_id"])}


def test_a_remote_run_whose_name_the_walk_registers_again_is_replaced(workflow, root):
    """The walk registers run_a anew: the old document of that name goes, which
    frees its name for the new one, wherever the old one was located."""
    remote = _run(workflow, "run_a", "s3://b/data/run_a")
    run_b = _run(workflow, "run_b", str(root / "run_b"))

    _deleted_files, deleted_runs, upsert = _rescan(workflow, [remote, run_b], [])

    assert deleted_runs == {str(remote["_id"])}
    walked = {run.run_tag: run for run in upsert.call_args.args[0]}
    assert walked["run_a"].run_location == str(root / "run_a")
    assert str(walked["run_a"].id) != str(remote["_id"])
