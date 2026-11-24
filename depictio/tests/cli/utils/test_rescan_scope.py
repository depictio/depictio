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

The same module covers the scan-state cache of a partial scan: a
``--data-collection-tag`` walk sees a run's whole tree but scans one
collection of it, so it must not record the run as fully scanned.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from depictio.cli.cli.utils.scan import scan_files_for_workflow
from depictio.cli.cli.utils.state import STATE_DIR_ENV_VAR, load_state
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow, WorkflowRun

NOW = "2026-10-08 12:00:00"
OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}
API_URL = "http://localhost:8058"
PROJECT_ID = "6a63de3c7577b6bb68993a94"
#: The command parameters that turn the state cache on in the tests below.
STATE_ON = {"state_cache": True, "project_id": PROJECT_ID}


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


def _rescan(
    workflow, runs: list[dict], files: list[dict], data_collections=None, command_parameters=None
):
    """A refresh's walk: ``rescan_folders`` and ``sync_files`` on, the API stubbed."""
    files_response = MagicMock(status_code=200)
    files_response.json.return_value = files
    runs_response = MagicMock(status_code=200)
    runs_response.json.return_value = runs
    cli_config = MagicMock()
    cli_config.api_base_url = API_URL
    cli_config.user.model_dump.side_effect = lambda: {**OWNER, "token": None}

    def _deleted(ids, *_args, **_kwargs):
        # The batch deletes answer with how many the server removed.
        return len(ids)

    params = {
        "rescan_folders": True,
        "sync_files": True,
        "rich_tables": False,
        "state_cache": False,
    }
    params.update(command_parameters or {})

    with (
        patch("depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_response),
        patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_response),
        patch(
            "depictio.cli.cli.utils.scan.api_create_files_chunked",
            return_value=[MagicMock(status_code=200)],
        ),
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch") as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=_deleted) as delete_runs,
        patch("depictio.cli.cli.utils.scan.api_delete_files", side_effect=_deleted) as delete_files,
    ):
        upsert.return_value = MagicMock(status_code=200)
        result = scan_files_for_workflow(
            workflow=workflow,
            data_collections=data_collections or workflow.data_collections,
            CLI_config=cli_config,
            command_parameters=params,
        )
    assert result["result"] == "success"
    deleted_files = {i for c in delete_files.call_args_list for i in c.args[0]}
    deleted_runs = {i for c in delete_runs.call_args_list for i in c.args[0]}
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


def _table_dc(tag: str, pattern: str) -> dict:
    return {
        "data_collection_tag": tag,
        "config": {
            "type": "Table",
            "scan": {
                "mode": "recursive",
                "scan_parameters": {"regex_config": {"pattern": pattern}},
            },
            "dc_specific_properties": {
                "format": "TSV",
                "polars_kwargs": {"separator": "\t"},
            },
        },
    }


@pytest.fixture
def two_dc_root(tmp_path):
    """Two run folders, one file for each of two collections in every run."""
    for name in ("run_a", "run_b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "table.tsv").write_text("a\tb\n1\t2\n")
        (tmp_path / name / "other.tsv").write_text("c\td\n3\t4\n")
    return tmp_path


@pytest.fixture
def two_dc_workflow(two_dc_root):
    return Workflow.model_validate(
        {
            "name": "wf",
            "engine": {"name": "nextflow"},
            "data_location": {
                "structure": "sequencing-runs",
                "locations": [str(two_dc_root)],
                "runs_regex": "run_.*",
            },
            "config": {},
            "data_collections": [
                _table_dc("table", "table.tsv$"),
                _table_dc("other", "other.tsv$"),
            ],
        }
    )


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """An isolated scan-state cache, away from the operator's ~/.depictio."""
    path = tmp_path / "state"
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(path))
    return path


def _table_dc_of(workflow):
    return next(dc for dc in workflow.data_collections if dc.data_collection_tag == "table")


def test_a_tag_scoped_scan_records_no_run_state(two_dc_workflow, state_dir):
    """A ``--data-collection-tag`` walk sees a run's whole tree but scans only
    one collection of it. Recording the run would make the next full ingest
    skip it for the collection this scan never looked at."""
    _rescan(
        two_dc_workflow,
        [],
        [],
        data_collections=[_table_dc_of(two_dc_workflow)],
        command_parameters=STATE_ON,
    )

    loaded = load_state(API_URL, PROJECT_ID)
    recorded = [run for wf in (loaded.workflows if loaded else {}).values() for run in wf.runs]
    assert recorded == []


def test_a_full_scan_records_every_run_state(two_dc_workflow, state_dir):
    _rescan(two_dc_workflow, [], [], command_parameters=STATE_ON)

    loaded = load_state(API_URL, PROJECT_ID)
    assert loaded is not None
    for tag in ("run_a", "run_b"):
        cached = loaded.run_state(str(two_dc_workflow.id), tag)
        assert cached is not None
        # The signature covers the whole tree, both collections' files.
        assert cached.file_count == 2


def test_a_full_scan_after_a_tag_scoped_one_still_scans_every_run(
    two_dc_workflow, two_dc_root, state_dir
):
    """The bug this guards against: the tag-scoped scan recorded each run's
    whole-tree signature, so the full ingest skipped every run and found no
    files for the other collection."""
    run_a = _run(two_dc_workflow, "run_a", str(two_dc_root / "run_a"))
    run_b = _run(two_dc_workflow, "run_b", str(two_dc_root / "run_b"))

    _rescan(
        two_dc_workflow,
        [],
        [],
        data_collections=[_table_dc_of(two_dc_workflow)],
        command_parameters=STATE_ON,
    )
    # The runs are on the server now, so the full scan can only skip them
    # through the state cache, which is exactly what must not happen.
    _deleted_files, _deleted_runs, upsert = _rescan(
        two_dc_workflow, [run_a, run_b], [], command_parameters=STATE_ON
    )

    walked = {run.run_tag for run in upsert.call_args.args[0]}
    assert walked == {"run_a", "run_b"}
