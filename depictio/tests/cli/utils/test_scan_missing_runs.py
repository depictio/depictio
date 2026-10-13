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

from depictio.cli.cli.utils.delta_versioning import plan_scoped_write
from depictio.cli.cli.utils.deltatables import skip_unchanged_reason
from depictio.cli.cli.utils.scan import flat_run_tag_clash, scan_files_for_workflow
from depictio.cli.cli.utils.scan_walk import iter_run_files, run_signature
from depictio.cli.cli.utils.state import load_state, settle_collections
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow, WorkflowDataLocation, WorkflowRun

NOW = "2026-09-03 23:00:00"
OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}
WF_CONFIG_ID = "507f1f77bcf86cd799439099"
# What the server answers a run upsert and a delete that went through.
STORED = MagicMock(status_code=200)


def all_deleted(ids, *_args, **_kwargs) -> int:
    return len(ids)


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
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch", return_value=STORED) as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=all_deleted) as delete_run,
        patch(
            "depictio.cli.cli.utils.scan.api_delete_files", side_effect=all_deleted
        ) as delete_file,
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
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch", return_value=STORED),
        patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=all_deleted) as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files", side_effect=all_deleted),
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
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch", return_value=STORED) as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=all_deleted) as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files", side_effect=all_deleted),
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
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch", return_value=STORED),
        patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=all_deleted) as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files", side_effect=all_deleted),
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
            patch(
                "depictio.cli.cli.utils.scan.api_upsert_runs_batch", return_value=STORED
            ) as upsert,
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
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch", return_value=STORED) as upsert,
        patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=all_deleted) as delete_run,
        patch(
            "depictio.cli.cli.utils.scan.api_delete_files", side_effect=all_deleted
        ) as delete_file,
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
        patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch", return_value=STORED),
        patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=all_deleted) as delete_run,
        patch("depictio.cli.cli.utils.scan.api_delete_files", side_effect=all_deleted),
    ):
        scan_files_for_workflow(
            workflow=workflow,
            data_collections=workflow.data_collections,
            CLI_config=_cli_config(),
            command_parameters={"rescan_folders": True, "rich_tables": False},
        )

    assert str(scan_run.call_args.kwargs["existing_run"].id) == str(registered["_id"])
    delete_run.assert_not_called()


class TestARunRegisteredAheadOfItsTable:
    """The scan registers a run's files before the process step writes its table.

    When that write fails, the next scan finds the files unchanged against the
    registry and the state. It must not vouch for the collection then: a skip, or
    a write scoped to the runs that moved since, would leave the run out of the
    table for good.
    """

    SERVER = "http://depictio.test"

    @pytest.fixture
    def scan(self, workflow, two_run_dirs):
        run_a, run_b = two_run_dirs
        existing = [
            _existing_run(workflow.id, run_a.name, str(run_a)),
            _existing_run(workflow.id, run_b.name, str(run_b)),
        ]
        files_resp = MagicMock(status_code=200)
        files_resp.json.return_value = []
        runs_resp = MagicMock(status_code=200)
        runs_resp.json.return_value = existing
        cli_config = _cli_config()
        # A fresh dict per scan: the scan pops the token out of the one it gets.
        cli_config.user.model_dump.side_effect = lambda: {**OWNER, "token": None}
        cli_config.api_base_url = self.SERVER
        upserted: list[set[str]] = []

        def fake_scan(**kwargs):
            run = _fake_scan(workflow)(**kwargs)
            # What the real scan attaches, and the state records.
            files = list(iter_run_files(kwargs["run_location"]))
            run._scan_signature = run_signature(files)
            run._scan_file_count = len(files)
            return run

        def upsert(runs, *_args):
            upserted.append({r.run_tag for r in runs})
            return self.upsert_response

        def _scan():
            with (
                patch(
                    "depictio.cli.cli.utils.scan.api_get_files_by_dc_id", return_value=files_resp
                ),
                patch("depictio.cli.cli.utils.scan.api_get_runs_by_wf_id", return_value=runs_resp),
                patch(
                    "depictio.cli.cli.utils.scan.scan_run_for_multiple_data_collections",
                    side_effect=fake_scan,
                ),
                patch("depictio.cli.cli.utils.scan.api_upsert_runs_batch", side_effect=upsert),
                patch("depictio.cli.cli.utils.scan.api_delete_runs", side_effect=all_deleted),
                patch("depictio.cli.cli.utils.scan.api_delete_files", side_effect=all_deleted),
            ):
                return scan_files_for_workflow(
                    workflow=workflow,
                    data_collections=workflow.data_collections,
                    CLI_config=cli_config,
                    command_parameters={
                        "rescan_folders": True,
                        "rich_tables": False,
                        "state_cache": True,
                        "project_id": "p1",
                    },
                )

        self.upsert_response = STORED
        _scan.upserted = upserted
        return _scan

    @staticmethod
    def _scoped(signal, dc_id):
        return plan_scoped_write(
            probe=MagicMock(version=3),
            changed_runs=signal["changed_dcs"].get(dc_id, []),
            removed_runs=signal["removed_runs"],
            write_mode="replace-runs",
            incremental_write=True,
            signal_complete=signal["complete"],
            covered=dc_id in signal["covered_dcs"],
        )

    def test_a_write_that_failed_is_rebuilt_in_full_by_the_next_cycle(
        self, scan, workflow, two_run_dirs
    ):
        run_a, _ = two_run_dirs
        dc = workflow.data_collections[0]
        dc_id = str(dc.id)
        # A first ingestion that wrote its table.
        scan()
        settle_collections(self.SERVER, "p1", [dc_id])

        # Cycle N: run_a changes, the scan registers it, and the write fails.
        (run_a / "table.tsv").write_text("a\tb\n1\t2\n3\t4\n")
        cycle_n = scan()
        assert scan.upserted[-1] == {run_a.name}
        assert dc_id in cycle_n["covered_dcs"]
        assert load_state(self.SERVER, "p1").unsettled_dcs == [dc_id]

        # Cycle N+1: nothing moved on disk since, so no run is rescanned.
        cycle_n1 = scan()
        assert len(scan.upserted) == 2
        assert dc_id not in cycle_n1["covered_dcs"]
        plan = self._scoped(cycle_n1, dc_id)
        assert plan.scoped is False and "failed" in plan.declined
        signal = {"skip_unchanged": True, "scan_signal": cycle_n1}
        assert skip_unchanged_reason(dc, MagicMock(version=3), signal) is None

        # Once a write succeeds, the scan vouches for it again.
        settle_collections(self.SERVER, "p1", [dc_id])
        assert dc_id in scan()["covered_dcs"]

    def test_a_first_scan_on_this_host_vouches_for_nothing(self, scan, workflow):
        assert scan()["covered_dcs"] == []

    def test_runs_the_server_refused_are_not_recorded_as_seen(self, scan, workflow):
        self.upsert_response = MagicMock(status_code=500, text="boom")

        with pytest.raises(RuntimeError, match=r"Registering 2 run\(s\) failed \(HTTP 500\)"):
            scan()

        state = load_state(self.SERVER, "p1")
        assert state.run_state(str(workflow.id), "run_a") is None
        assert state.unsettled_dcs == [str(workflow.data_collections[0].id)]
