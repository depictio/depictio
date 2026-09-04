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


@pytest.fixture
def nextflow_run_dir(tmp_path):
    """A run directory carrying the provenance nf-core writes on completion."""
    root = tmp_path / "run_nf"
    info = root / "pipeline_info"
    info.mkdir(parents=True)
    (info / "software_versions.yml").write_text(
        "FASTQC:\n  fastqc: 0.12.1\n"
        "CUTADAPT_BASIC:\n  cutadapt: 5.2\n"
        "Workflow:\n"
        "    nf-core/ampliseq: v2.16.0-g3d5c7e5\n"
        "    Nextflow: 25.10.2\n"
    )
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
        resolve = getattr(self, "resolve", None) or MagicMock(
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


class TestProvenanceStamping:
    """The run's provenance must be read from the directory however the template
    was chosen. It lives only there: no manifest string carries the engine
    version or the tool list."""

    def _resolved_workflow(self, app, runner, harness, root, flags):
        with_patches = harness.patches()
        for patch_ctx in with_patches:
            patch_ctx.start()
        try:
            result = runner.invoke(
                app,
                [
                    "--data-root",
                    str(root),
                    "--skip-server-check",
                    "--skip-s3-check",
                    *flags,
                ],
            )
        finally:
            for patch_ctx in with_patches:
                patch_ctx.stop()
        return result

    @pytest.fixture
    def harness(self, nextflow_run_dir):
        harness = _Harness(nextflow_run_dir, remote_locations=[])
        template_meta = MagicMock()
        template_meta.template_id = "nf-core/ampliseq/2.16.0"
        # A single workflow dict, so the stamping has somewhere to land.
        harness.resolved_config = {
            "name": harness.project.name,
            "workflows": [{"name": "ampliseq", "config": {}}],
        }
        harness.resolve = MagicMock(
            return_value=(harness.resolved_config, template_meta, {}, [], {})
        )
        return harness

    @pytest.mark.parametrize(
        "flags",
        [
            pytest.param(["--template", "nf-core/ampliseq/2.16.0"], id="explicit-template"),
            pytest.param(
                ["--nextflow-manifest", "nf-core/ampliseq/2.16.0"], id="nextflow-manifest"
            ),
            pytest.param([], id="auto-detected"),
        ],
    )
    def test_provenance_is_stamped_however_the_template_was_chosen(
        self, app, runner, harness, nextflow_run_dir, flags
    ):
        result = self._resolved_workflow(app, runner, harness, nextflow_run_dir, flags)
        assert result.exit_code == 0, result.output

        config = harness.resolved_config["workflows"][0]["config"]
        assert config["engine_name"] == "nextflow"
        # `v2.16.0-g3d5c7e5` normalised, git-describe suffix dropped.
        assert config["pipeline_version"] == "2.16.0"
        assert config["nextflow_version"] == "25.10.2"
        assert config["tools_executed"] == ["cutadapt", "fastqc"]


class TestTriggeredByStamp:
    """`--triggered-by` records what invoked the ingestion, on every mode.

    The value reaches the server through the synced project dict, so it has to
    survive `convert_model_to_dict`. It is stamped at the single sync funnel
    rather than per mode, and these tests pin that: an attach and an update are
    exactly the paths a pipeline re-run takes, and a tag that only worked on
    first creation would be missing from every project that ever ran twice.
    """

    def test_defaults_to_manual(self, app, runner, data_root):
        harness = _Harness(data_root, remote_locations=[])
        result = _invoke(app, runner, harness, {"data_root": data_root, "flags": []})
        assert result.exit_code == 0, result.output
        assert harness.sync.call_args.kwargs["ProjectConfig"]["triggered_by"] == "manual"

    def test_the_trigger_value_reaches_the_server(self, app, runner, data_root):
        harness = _Harness(data_root, remote_locations=[])
        result = _invoke(
            app,
            runner,
            harness,
            {"data_root": data_root, "flags": ["--triggered-by", "nextflow"]},
        )
        assert result.exit_code == 0, result.output
        assert harness.sync.call_args.kwargs["ProjectConfig"]["triggered_by"] == "nextflow"

    def test_it_survives_an_attach(self, app, runner, data_root):
        harness = _Harness(data_root, remote_locations=["/data/run_a"])
        result = _invoke(
            app,
            runner,
            harness,
            {"data_root": data_root, "flags": ["--attach-run", "--triggered-by", "nextflow"]},
        )
        assert result.exit_code == 0, result.output
        assert harness.sync.call_args.kwargs["ProjectConfig"]["triggered_by"] == "nextflow"
