"""Tests for `depictio-cli ingest --attach-run`: folding a run into an existing project.

These exercise :func:`attach_run_to_project`, the pure part of the feature: it takes
the locally resolved project plus the project document the server already holds, and
merges the two in place. No server or filesystem is involved.
"""

from __future__ import annotations

import copy

import pytest

from depictio.cli.cli.commands.run import attach_run_to_project
from depictio.models.models.projects import Project

OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}


def _project(locations: list[str], single_filename: str) -> Project:
    """A one-workflow project with a recursive and a single-file data collection."""
    return Project.model_validate(
        {
            "name": "Ampliseq Microbial Community Analysis",
            "project_type": "advanced",
            "permissions": {"owners": [OWNER], "editors": [], "viewers": []},
            "workflows": [
                {
                    "name": "ampliseq",
                    "engine": {"name": "nextflow"},
                    "catalog": {"name": "nf-core", "url": "https://nf-co.re"},
                    "data_location": {"structure": "flat", "locations": list(locations)},
                    "data_collections": [
                        {
                            "data_collection_tag": "asv_table",
                            "config": {
                                "type": "Table",
                                "scan": {
                                    "mode": "recursive",
                                    "scan_parameters": {
                                        "regex_config": {"pattern": "asv_table.tsv$"}
                                    },
                                },
                                "dc_specific_properties": {
                                    "format": "TSV",
                                    "polars_kwargs": {"separator": "\t"},
                                },
                            },
                        },
                        {
                            "data_collection_tag": "metadata",
                            "config": {
                                "type": "Table",
                                "scan": {
                                    "mode": "single",
                                    "scan_parameters": {"filename": single_filename},
                                },
                                "dc_specific_properties": {
                                    "format": "TSV",
                                    "polars_kwargs": {"separator": "\t"},
                                },
                            },
                        },
                    ],
                }
            ],
        }
    )


def _remote_doc(project: Project) -> dict:
    """The shape `GET /projects/get/from_name/{name}` returns, from a Project."""
    wf = project.workflows[0]
    return {
        "name": project.name,
        "workflows": [
            {
                "workflow_tag": wf.workflow_tag,
                "data_location": {
                    "structure": wf.data_location.structure,
                    "locations": list(wf.data_location.locations),
                },
                "data_collections": [
                    {
                        "data_collection_tag": dc.data_collection_tag,
                        "config": {
                            "scan": {
                                "mode": dc.config.scan.mode,
                                "scan_parameters": (
                                    {"filename": dc.config.scan.scan_parameters.filename}
                                    if dc.config.scan.mode.lower() == "single"
                                    else {}
                                ),
                            }
                        },
                    }
                    for dc in wf.data_collections
                ],
            }
        ],
    }


@pytest.fixture
def remote() -> dict:
    """The project as already ingested from run_a."""
    return _remote_doc(_project(["/data/run_a"], "/data/run_a/metadata.tsv"))


class TestLocationMerge:
    def test_new_run_is_appended_after_the_existing_one(self, remote):
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        report = attach_run_to_project(local, remote)
        # The already-ingested run must survive, and order must stay stable.
        assert local.workflows[0].data_location.locations == ["/data/run_a", "/data/run_b"]
        assert report["added"] == {"ampliseq": ["/data/run_b"]}

    def test_reattaching_the_same_run_adds_nothing(self, remote):
        local = _project(["/data/run_a"], "/data/run_a/metadata.tsv")
        report = attach_run_to_project(local, remote)
        assert local.workflows[0].data_location.locations == ["/data/run_a"]
        assert report["added"] == {"ampliseq": []}

    def test_a_third_run_keeps_both_predecessors(self):
        remote = _remote_doc(_project(["/data/run_a"], "/data/run_a/metadata.tsv"))
        remote["workflows"][0]["data_location"]["locations"] = ["/data/run_a", "/data/run_b"]
        local = _project(["/data/run_c"], "/data/run_c/metadata.tsv")
        attach_run_to_project(local, remote)
        assert local.workflows[0].data_location.locations == [
            "/data/run_a",
            "/data/run_b",
            "/data/run_c",
        ]

    def test_workflow_absent_from_the_remote_keeps_its_own_locations(self, remote):
        remote["workflows"][0]["workflow_tag"] = "some/other-workflow"
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        report = attach_run_to_project(local, remote)
        assert local.workflows[0].data_location.locations == ["/data/run_b"]
        assert report["added"] == {"ampliseq": ["/data/run_b"]}

    def test_empty_remote_document_is_tolerated(self):
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        report = attach_run_to_project(local, {})
        assert local.workflows[0].data_location.locations == ["/data/run_b"]
        assert report["bindings"].per_run_single == []
        assert local.workflows[0].data_collections[1].config.scan.scan_parameters.run_files is None


class TestAttachedRecord:
    """An attach records its run, so that a refresh keeps it and drops the rest."""

    def test_the_new_run_is_recorded_and_the_first_one_is_not(self, remote):
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        report = attach_run_to_project(local, remote)
        assert local.workflows[0].data_location.attached_locations == ["/data/run_b"]
        assert report["recorded"] == {"ampliseq": ["/data/run_b"]}

    def test_the_record_the_server_holds_is_kept(self, remote):
        remote["workflows"][0]["data_location"]["locations"] = ["/data/run_a", "/data/run_b"]
        remote["workflows"][0]["data_location"]["attached_locations"] = ["/data/run_b"]
        local = _project(["/data/run_c"], "/data/run_c/metadata.tsv")
        attach_run_to_project(local, remote)
        assert local.workflows[0].data_location.attached_locations == [
            "/data/run_b",
            "/data/run_c",
        ]

    def test_reattaching_a_run_records_it_without_adding_it(self, remote):
        """How a run attached before the record existed is kept by later refreshes."""
        local = _project(["/data/run_a"], "/data/run_a/metadata.tsv")
        report = attach_run_to_project(local, remote)
        assert report["added"] == {"ampliseq": []}
        assert report["recorded"] == {"ampliseq": ["/data/run_a"]}
        assert local.workflows[0].data_location.attached_locations == ["/data/run_a"]

    def test_a_run_already_recorded_is_not_recorded_twice(self, remote):
        remote["workflows"][0]["data_location"]["attached_locations"] = ["/data/run_a"]
        local = _project(["/data/run_a"], "/data/run_a/metadata.tsv")
        report = attach_run_to_project(local, remote)
        assert report["recorded"] == {"ampliseq": []}
        assert local.workflows[0].data_location.attached_locations == ["/data/run_a"]


class TestSingleFileBindingIsPreserved:
    """A `scan.mode: single` collection points at ONE absolute path per run.

    The template resolved it against the NEW run. The first run's file stays the
    project-level ``filename``, and each run's file is kept in ``run_files``, so
    neither run's file is dropped by the next scan (epic #1399).
    """

    def test_first_run_file_stays_project_level(self, remote):
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        report = attach_run_to_project(local, remote)
        params = local.workflows[0].data_collections[1].config.scan.scan_parameters
        assert params.filename == "/data/run_a/metadata.tsv"
        # Not on this host: the new run keeps the file of the run before it.
        assert params.run_files == {
            "/data/run_a": "/data/run_a/metadata.tsv",
            "/data/run_b": "/data/run_a/metadata.tsv",
        }
        assert report["bindings"].missing_single == ["metadata"]

    def test_each_run_binds_its_own_file(self, tmp_path):
        run_a, run_b = tmp_path / "run_a", tmp_path / "run_b"
        for run, body in ((run_a, "s\ta\n"), (run_b, "s\tb\n")):
            run.mkdir()
            (run / "metadata.tsv").write_text(body)
        remote = _remote_doc(_project([str(run_a)], str(run_a / "metadata.tsv")))
        local = _project([str(run_b)], str(run_b / "metadata.tsv"))
        report = attach_run_to_project(local, remote)
        params = local.workflows[0].data_collections[1].config.scan.scan_parameters
        assert params.filename == str(run_a / "metadata.tsv")
        assert params.run_files == {
            str(run_a): str(run_a / "metadata.tsv"),
            str(run_b): str(run_b / "metadata.tsv"),
        }
        assert report["bindings"].per_run_single == ["metadata"]

    def test_recursive_collection_is_left_alone(self, remote):
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        before = copy.deepcopy(local.workflows[0].data_collections[0].config.scan.model_dump())
        attach_run_to_project(local, remote)
        after = local.workflows[0].data_collections[0].config.scan.model_dump()
        assert after == before

    def test_same_path_is_not_reported_as_per_run(self, remote):
        local = _project(["/data/run_b"], "/data/run_a/metadata.tsv")
        report = attach_run_to_project(local, remote)
        assert report["bindings"].per_run_single == []

    def test_collection_absent_from_the_remote_binds_this_run(self, remote):
        remote["workflows"][0]["data_collections"] = [
            dc
            for dc in remote["workflows"][0]["data_collections"]
            if dc["data_collection_tag"] != "metadata"
        ]
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        attach_run_to_project(local, remote)
        params = local.workflows[0].data_collections[1].config.scan.scan_parameters
        assert params.filename == "/data/run_b/metadata.tsv"
        # Bound to run_b explicitly, or the scan would read it as run_a's.
        assert params.run_files == {"/data/run_b": "/data/run_b/metadata.tsv"}
