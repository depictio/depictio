"""End-to-end flag contract for `depictio-cli run --attach-run`.

Attaching a run to an existing project is a specific combination of the flags the
pipeline already had, and getting any one of them wrong is silently destructive:

* sync must UPDATE the project (otherwise nothing is written);
* the scan must stay INCREMENTAL (a full rescan deletes runs missing from disk);
* process must OVERWRITE (write_delta_table refuses to rewrite an existing table
  otherwise, and the rebuild has to include the runs already ingested);
* dashboards must NOT be re-imported over the ones the user has since edited.

Every server call is mocked, so this runs offline and asserts the wiring only.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from depictio.cli.cli.commands.run import register_run_command
from depictio.models.models.projects import Project

OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}


@pytest.fixture
def app():
    application = typer.Typer()
    register_run_command(application)
    return application


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "run_b"
    root.mkdir()
    return root


def _project(locations: list[str]) -> Project:
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
                        }
                    ],
                }
            ],
        }
    )


class _Harness:
    """Every mock the run pipeline needs, plus the recorded call arguments."""

    def __init__(self, data_root, remote_locations: list[str], project_found: bool = True):
        self.project = _project([str(data_root)])
        self.remote_doc = {
            "name": self.project.name,
            "hash": None,
            "workflows": [
                {
                    "workflow_tag": self.project.workflows[0].workflow_tag,
                    "data_location": {"structure": "flat", "locations": remote_locations},
                    "data_collections": [],
                }
            ],
        }
        self.project_found = project_found
        self.sync = MagicMock(return_value={"action": "updated"})
        self.scan = MagicMock(return_value={"result": "success"})
        self.process = MagicMock(return_value={"total_failed": 0})
        self.import_dashboards = MagicMock(return_value=[])

    def _get_project(self, *args, **kwargs):
        response = MagicMock()
        response.status_code = 200 if self.project_found else 404
        response.json.return_value = self.remote_doc
        return response

    def patches(self):
        template_meta = MagicMock()
        template_meta.template_id = "nf-core/ampliseq/2.16.0"
        resolve = MagicMock(
            return_value=({"name": self.project.name, "workflows": []}, template_meta, {}, [], {})
        )
        validate = MagicMock(
            return_value=(MagicMock(), {"success": True, "project_config": self.project})
        )
        return [
            patch("depictio.cli.cli.utils.templates.resolve_template", resolve),
            patch("depictio.cli.cli.utils.config.validate_template_project_config", validate),
            patch("depictio.cli.cli.commands.run.api_get_project_from_name", self._get_project),
            patch("depictio.cli.cli.commands.run.api_sync_project_config_to_server", self.sync),
            patch("depictio.cli.cli.commands.run.scan_project_files", self.scan),
            patch("depictio.cli.cli.commands.run.process_project_helper", self.process),
            patch("depictio.cli.cli.commands.run.api_monitoring_ingestion_start", MagicMock()),
            patch("depictio.cli.cli.commands.run.api_monitoring_ingestion_finish", MagicMock()),
            patch("depictio.cli.cli.commands.run.generate_api_headers", MagicMock(return_value={})),
            patch(
                "depictio.cli.cli.utils.templates.import_dashboards_from_template",
                self.import_dashboards,
            ),
        ]


def _invoke(app, runner, harness, extra_args):
    with_patches = harness.patches()
    for p in with_patches:
        p.start()
    try:
        return runner.invoke(
            app,
            [
                "--template",
                "nf-core/ampliseq/2.16.0",
                "--data-root",
                str(extra_args["data_root"]),
                "--skip-server-check",
                "--skip-s3-check",
                *extra_args["flags"],
            ],
        )
    finally:
        for p in with_patches:
            p.stop()


class TestAttachRunFlags:
    def test_attach_updates_scans_incrementally_and_overwrites_the_tables(
        self, app, runner, data_root
    ):
        harness = _Harness(data_root, remote_locations=["/data/run_a"])
        result = _invoke(app, runner, harness, {"data_root": data_root, "flags": ["--attach-run"]})
        assert result.exit_code == 0, result.output

        # The project is updated, not created a second time.
        assert harness.sync.call_args.kwargs["update"] is True
        # The scan stays incremental: a full rescan would delete runs off disk.
        assert harness.scan.call_args.kwargs["command_parameters"]["rescan_folders"] is False
        # The delta tables are rebuilt, including the runs already ingested.
        assert harness.process.call_args.kwargs["command_parameters"]["overwrite"] is True
        # The existing dashboards are left alone.
        harness.import_dashboards.assert_not_called()
        # And the new run really was appended after the existing one.
        assert harness.sync.call_args.kwargs["ProjectConfig"]["workflows"][0]["data_location"][
            "locations"
        ] == ["/data/run_a", str(data_root)]

    def test_overwrite_alone_still_implies_a_full_rescan(self, app, runner, data_root):
        """Only attach mode decouples the two; the normal --overwrite is unchanged."""
        harness = _Harness(data_root, remote_locations=["/data/run_a"])
        result = _invoke(
            app,
            runner,
            harness,
            {"data_root": data_root, "flags": ["--overwrite", "--update-config"]},
        )
        assert result.exit_code == 0, result.output
        assert harness.scan.call_args.kwargs["command_parameters"]["rescan_folders"] is True

    def test_attach_to_a_missing_project_stops_before_writing(self, app, runner, data_root):
        harness = _Harness(data_root, remote_locations=[], project_found=False)
        result = _invoke(app, runner, harness, {"data_root": data_root, "flags": ["--attach-run"]})
        assert result.exit_code == 2
        assert "no project named" in " ".join(result.output.split())
        harness.sync.assert_not_called()
        harness.scan.assert_not_called()

    def test_without_attach_an_existing_project_is_reported_not_silently_skipped(
        self, app, runner, data_root
    ):
        """The regression: this used to exit 1 with an empty error message."""
        harness = _Harness(data_root, remote_locations=["/data/run_a"])
        harness.sync = MagicMock(return_value={"action": "exists"})
        result = _invoke(app, runner, harness, {"data_root": data_root, "flags": []})
        assert result.exit_code == 2
        normalized = " ".join(result.output.split())
        assert "already exists on this server" in normalized
        assert "--update-config" in normalized
        assert "--attach-run" in normalized
        harness.scan.assert_not_called()
