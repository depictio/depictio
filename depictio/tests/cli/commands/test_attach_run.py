"""Tests for `depictio-cli run --attach-run`: folding a run into an existing project.

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
        assert report["kept_single"] == []


class TestSingleFileBindingIsPreserved:
    """A `scan.mode: single` collection points at ONE absolute path.

    The template resolved it against the NEW run, but the next scan deletes files
    whose location no longer matches the config, so re-pointing it would silently
    drop the file ingested from the original run. Attaching must not do that.
    """

    def test_single_file_collection_keeps_the_original_binding(self, remote):
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        report = attach_run_to_project(local, remote)
        metadata_dc = local.workflows[0].data_collections[1]
        assert metadata_dc.config.scan.scan_parameters.filename == "/data/run_a/metadata.tsv"
        assert report["kept_single"] == ["metadata"]

    def test_recursive_collection_is_left_alone(self, remote):
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        before = copy.deepcopy(local.workflows[0].data_collections[0].config.scan.model_dump())
        attach_run_to_project(local, remote)
        after = local.workflows[0].data_collections[0].config.scan.model_dump()
        assert after == before

    def test_unchanged_binding_is_not_reported_as_kept(self, remote):
        local = _project(["/data/run_b"], "/data/run_a/metadata.tsv")
        report = attach_run_to_project(local, remote)
        assert report["kept_single"] == []

    def test_collection_absent_from_the_remote_keeps_this_run_binding(self, remote):
        remote["workflows"][0]["data_collections"] = [
            dc
            for dc in remote["workflows"][0]["data_collections"]
            if dc["data_collection_tag"] != "metadata"
        ]
        local = _project(["/data/run_b"], "/data/run_b/metadata.tsv")
        report = attach_run_to_project(local, remote)
        metadata_dc = local.workflows[0].data_collections[1]
        assert metadata_dc.config.scan.scan_parameters.filename == "/data/run_b/metadata.tsv"
        assert report["kept_single"] == []
