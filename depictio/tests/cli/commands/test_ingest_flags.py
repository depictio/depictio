"""`depictio ingest`: what a live audit of its flags found, one class per finding.

Every server call is mocked through the harness in conftest.py, so these assert the
wiring and the exit codes only: a run where every step worked exits 0, and a run
where one did not exits non-zero, whatever the flags.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from depictio.cli.cli.commands import run as run_module
from depictio.cli.cli.commands.run import (
    load_project_file,
    merge_run_locations,
    register_run_command,
    unknown_filter_error,
)

TEMPLATE = "nf-core/ampliseq/2.16.0"

PINNED_PROJECT = """\
id: "646b0f3c1e4a2d7f8e5b8c9d"
name: "Pinned Project"
workflows:
  - id: "646b0f3c1e4a2d7f8e5b8c9e"
    name: "wf"
    engine: {name: "python"}
    data_location: {structure: "flat", locations: ["%(root)s"]}
    data_collections:
      - id: "646b0f3c1e4a2d7f8e5b8c9f"
        data_collection_tag: "samples"
        config:
          type: "Table"
          scan: {mode: "recursive", scan_parameters: {regex_config: {pattern: "s.csv"}}}
          dc_specific_properties: {format: "CSV"}
joins:
  - id: "646b0f3c1e4a2d7f8e5b8ca1"
    name: "j"
    left_dc: "samples"
    right_dc: "samples"
    on_columns: ["id"]
links:
  - source_dc_id: "646b0f3c1e4a2d7f8e5b8c9f"
    source_column: "id"
    target_dc_id: "646b0f3c1e4a2d7f8e5b8c9f"
    target_type: "table"
"""


def normalize(output: str) -> str:
    return re.sub(r"\s+", " ", output)


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
def project_file(tmp_path, data_root):
    path = tmp_path / "project.yaml"
    path.write_text(PINNED_PROJECT % {"root": data_root})
    return path


@pytest.fixture
def dashboard_file(tmp_path):
    path = tmp_path / "dashboard.yaml"
    path.write_text("title: irrelevant\n")
    return path


def _invoke(app, runner, harness, args, extra_patches=()):
    patches = [*harness.patches(), *extra_patches]
    for p in patches:
        p.start()
    try:
        return runner.invoke(app, args)
    finally:
        for p in reversed(patches):
            p.stop()


def _template(data_root, *flags):
    return [
        "ingest",
        "--template",
        TEMPLATE,
        "--data-root",
        str(data_root),
        "--skip-server-check",
        "--skip-s3-check",
        *flags,
    ]


def _project_mode(harness, project_file, *flags):
    """Args and the extra patch for --project-config-path, validated by the harness."""
    validate = MagicMock(
        return_value=(MagicMock(), {"success": True, "project_config": harness.project})
    )
    args = [
        "ingest",
        "--project-config-path",
        str(project_file),
        "--skip-server-check",
        "--skip-s3-check",
        *flags,
    ]
    return args, [
        patch.object(run_module, "validate_project_config_and_check_S3_storage", validate)
    ]


class TestFailedJoinFailsTheRun:
    """A join that fails used to come back as "partial", counted as a success."""

    def test_partial_join_result_exits_non_zero(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        harness.project.joins = [SimpleNamespace(name="penguins_complete")]
        joins = MagicMock(
            return_value={
                "result": "partial",
                "processed": [{"join": "ok"}],
                "errors": [{"join": "penguins_complete", "errors": ["no column"]}],
            }
        )
        result = _invoke(
            app,
            runner,
            harness,
            # The sync would serialise the stand-in join definition.
            _template(data_root, "--skip-sync"),
            [patch("depictio.cli.cli.utils.joins.process_project_joins", joins)],
        )
        assert result.exit_code == 1
        output = normalize(result.output)
        assert "Join execution failed: 1 join(s) failed: penguins_complete" in output
        assert "Join execution completed" not in output

    def test_under_continue_on_error_the_run_still_exits_non_zero(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        harness.project.joins = [SimpleNamespace(name="j")]
        joins = MagicMock(return_value={"result": "partial", "errors": [{"join": "j"}]})
        result = _invoke(
            app,
            runner,
            harness,
            _template(data_root, "--continue-on-error", "--skip-sync"),
            [patch("depictio.cli.cli.utils.joins.process_project_joins", joins)],
        )
        assert result.exit_code == 1
        assert "failed: joins" in normalize(result.output)


class TestUpdateKeepsAttachedRuns:
    def test_the_server_runs_are_kept_and_a_missing_one_is_reported(
        self, app, runner, tmp_path, data_root, make_harness
    ):
        attached = tmp_path / "run_a"
        attached.mkdir()
        gone = str(tmp_path / "run_gone")
        harness = make_harness(data_root, remote_locations=[str(attached), gone])

        result = _invoke(app, runner, harness, _template(data_root, "--update-config"))

        assert result.exit_code == 0, result.output
        synced = harness.sync.call_args.kwargs["ProjectConfig"]["workflows"][0]
        assert synced["data_location"]["locations"] == [str(attached), str(data_root)]
        output = normalize(result.output)
        assert "run_gone is no longer on disk" in output
        assert "removes its runs and files" in output
        assert "The project keeps 2 run location(s), 1 of them from earlier ingests" in output

    def test_a_project_with_this_run_only_keeps_it(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[str(data_root)])

        result = _invoke(app, runner, harness, _template(data_root, "--update-config"))

        assert result.exit_code == 0, result.output
        output = normalize(result.output)
        assert "The project keeps 1 run location(s)" in output
        assert "earlier ingests" not in output


class TestMergeRunLocations:
    def _project(self, make_harness, root):
        return make_harness(root, remote_locations=[]).project

    def _remote(self, project, locations):
        return {
            "workflows": [
                {
                    "workflow_tag": project.workflows[0].workflow_tag,
                    "data_location": {"locations": locations},
                }
            ]
        }

    def test_a_symlink_to_a_known_run_is_not_a_second_run(self, tmp_path, make_harness):
        real = tmp_path / "my run 3"
        real.mkdir()
        link = tmp_path / "link3"
        link.symlink_to(real)
        project = self._project(make_harness, link)

        report = merge_run_locations(project, self._remote(project, [str(real)]))

        assert report["added"] == {project.workflows[0].workflow_tag: []}
        assert project.workflows[0].data_location.locations == [str(real)]

    def test_missing_locations_are_dropped_only_when_asked(self, tmp_path, make_harness):
        root = tmp_path / "run"
        root.mkdir()
        project = self._project(make_harness, root)
        remote = self._remote(project, ["/nowhere/run_x"])

        merge_run_locations(project, remote)
        assert project.workflows[0].data_location.locations == ["/nowhere/run_x", str(root)]

        project = self._project(make_harness, root)
        report = merge_run_locations(project, remote, drop_missing=True)
        assert project.workflows[0].data_location.locations == [str(root)]
        assert report["missing"] == {project.workflows[0].workflow_tag: ["/nowhere/run_x"]}


class TestProjectNameAppliesToAProjectFile:
    def test_the_file_is_validated_under_the_new_name(
        self, app, runner, data_root, project_file, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        validate = MagicMock(
            return_value=(MagicMock(), {"success": True, "project_config": harness.project})
        )
        args, _ = _project_mode(harness, project_file, "--project-name", "Renamed")

        result = _invoke(
            app,
            runner,
            harness,
            args,
            [patch("depictio.cli.cli.utils.config.validate_template_project_config", validate)],
        )

        assert result.exit_code == 0, result.output
        config = validate.call_args.kwargs["resolved_config"]
        assert config["name"] == "Renamed"
        # The ids the file pins belong to the project it names.
        assert "id" not in config
        assert "id" not in config["workflows"][0]

    def test_pinned_ids_are_dropped_and_links_follow_by_tag(self, project_file):
        config = load_project_file(str(project_file), "Renamed")

        assert config["name"] == "Renamed"
        assert config["yaml_config_path"] == str(project_file)
        assert "id" not in config["workflows"][0]["data_collections"][0]
        assert "id" not in config["joins"][0]
        link = config["links"][0]
        assert "source_dc_id" not in link and "target_dc_id" not in link
        assert link["source_dc_tag"] == link["target_dc_tag"] == "samples"

    def test_the_same_name_keeps_the_file_as_it_is(self, project_file):
        config = load_project_file(str(project_file), "Pinned Project")

        assert config["id"] == "646b0f3c1e4a2d7f8e5b8c9d"
        assert config["links"][0]["source_dc_id"] == "646b0f3c1e4a2d7f8e5b8c9f"


class TestContinueOnErrorStopsWithoutAProject:
    def test_after_a_failed_template_resolution(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        harness.resolve = MagicMock(side_effect=FileNotFoundError("Template 'x' not found"))

        result = _invoke(app, runner, harness, _template(data_root, "--continue-on-error"))

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "Stopping despite --continue-on-error" in normalize(result.output)
        harness.sync.assert_not_called()

    def test_after_a_failed_validation(self, app, runner, data_root, project_file, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        args, _ = _project_mode(harness, project_file, "--continue-on-error")
        invalid = MagicMock(return_value=(MagicMock(), {"success": False}))

        result = _invoke(
            app,
            runner,
            harness,
            args,
            [patch.object(run_module, "validate_project_config_and_check_S3_storage", invalid)],
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "Stopping despite --continue-on-error" in normalize(result.output)
        harness.sync.assert_not_called()


class TestFailedDashboardFailsTheRun:
    def test_under_continue_on_error(self, app, runner, data_root, dashboard_file, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        harness.import_dashboards.return_value = [
            {"path": str(dashboard_file), "success": False, "error": "expected '[unclosed'"}
        ]

        result = _invoke(
            app,
            runner,
            harness,
            _template(data_root, "--dashboard", str(dashboard_file), "--continue-on-error"),
        )

        assert result.exit_code == 1
        output = normalize(result.output)
        assert "Dashboard import failed: 1 dashboard(s) failed to import" in output
        assert "Dashboard import completed" not in output
        # Rich markup no longer swallows the bracketed part of the error.
        assert "expected '[unclosed'" in output


class TestEveryStepWorkedExitsZero:
    @pytest.mark.parametrize(
        ("flags", "steps", "reason"),
        [
            (["--update-config", "--skip-dashboard-import"], "8/8", "--skip-dashboard-import"),
            (["--attach-run"], "9/9", "--attach-run"),
        ],
    )
    def test_a_skipped_dashboard_outside_template_mode(
        self,
        app,
        runner,
        data_root,
        project_file,
        dashboard_file,
        make_harness,
        flags,
        steps,
        reason,
    ):
        harness = make_harness(data_root, remote_locations=[str(data_root)])
        args, extra = _project_mode(
            harness, project_file, "--dashboard", str(dashboard_file), *flags
        )

        result = _invoke(app, runner, harness, args, extra)

        assert result.exit_code == 0, result.output
        output = normalize(result.output)
        assert f"({steps} steps)" in output
        assert f"Skipping dashboard import ({reason})" in output
        harness.import_dashboards.assert_not_called()


class TestDryRun:
    def test_an_invalid_project_file_fails(self, app, runner, tmp_path):
        project = tmp_path / "project.yaml"
        project.write_text("name: x\nworkflows: not-a-list\n")

        result = runner.invoke(
            app,
            [
                "ingest",
                "--project-config-path",
                str(project),
                "--dry-run",
                "--skip-server-check",
                "--skip-s3-check",
            ],
        )

        assert result.exit_code == 1
        assert "validation failed" in normalize(result.output)

    def test_the_steps_say_what_they_would_do(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        origin = SimpleNamespace(
            template_id=TEMPLATE, template_version="2.16.0", data_root=str(data_root)
        )
        meta = MagicMock(template_id=TEMPLATE)
        harness.resolve = MagicMock(
            return_value=(
                {
                    "name": "Resolved Name",
                    "workflows": [
                        {"name": "ampliseq", "data_collections": [{"data_collection_tag": "a"}]}
                    ],
                },
                meta,
                origin,
                [],
                {},
            )
        )
        validate = MagicMock(return_value=harness.project)

        result = _invoke(
            app,
            runner,
            harness,
            _template(data_root, "--dry-run"),
            [patch.object(run_module, "validate_project_locally", validate)],
        )

        assert result.exit_code == 0, result.output
        output = normalize(result.output)
        # The template summary prints at the default verbosity.
        assert "Project: Resolved Name" in output
        assert "Workflow 'ampliseq': 1 data collection(s): a" in output
        assert "Would scan the data files" in output
        assert "Would process the data collections" in output
        assert "Data scanning completed" not in output
        assert "Dry run complete" in output
        harness.sync.assert_not_called()


class TestOverwriteIsUpdateConfig:
    def test_overwrite_alone_updates_the_existing_project(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[str(data_root)])

        result = _invoke(app, runner, harness, _template(data_root, "--overwrite"))

        assert result.exit_code == 0, result.output
        assert harness.sync.call_args.kwargs["update"] is True
        assert harness.scan.call_args.kwargs["command_parameters"]["rescan_folders"] is True
        assert harness.process.call_args.kwargs["command_parameters"]["overwrite"] is True


class TestArgumentsCheckedUpfront:
    def test_a_missing_dashboard_file_stops_before_any_step(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])

        result = _invoke(
            app, runner, harness, _template(data_root, "--dashboard", "/nope/dash.yaml")
        )

        assert result.exit_code == 1
        assert "--dashboard does not exist or is not a file: /nope/dash.yaml" in normalize(
            result.output
        )
        assert "Step" not in result.output
        harness.sync.assert_not_called()

    def test_neither_template_nor_project_file_is_a_usage_error(self, app, runner):
        result = runner.invoke(app, ["ingest", "--skip-server-check", "--skip-s3-check"])

        assert result.exit_code == 2
        output = normalize(result.output)
        assert "--template" in output and "--project-config-path" in output
        assert "Step" not in result.output


class TestSelectionFilters:
    def test_an_unknown_tag_is_an_error_naming_the_known_ones(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])

        result = _invoke(
            app, runner, harness, _template(data_root, "--data-collection-tag", "nosuchdc")
        )

        assert result.exit_code == 1
        assert "Known: asv_table" in normalize(result.output)
        harness.sync.assert_not_called()

    def test_the_filters_reach_the_processing_and_the_images(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        tag = harness.project.workflows[0].workflow_tag
        collections = MagicMock(return_value=[])

        result = _invoke(
            app,
            runner,
            harness,
            _template(data_root, "--workflow-name", tag, "--data-collection-tag", "asv_table"),
            [patch.object(run_module, "image_collections_to_upload", collections)],
        )

        assert result.exit_code == 0, result.output
        assert harness.process.call_args.kwargs["workflow_name"] == tag
        assert harness.process.call_args.kwargs["data_collection_tag"] == "asv_table"
        assert collections.call_args.kwargs == {
            "workflow_name": tag,
            "data_collection_tag": "asv_table",
        }

    def test_unknown_workflow_and_tag_messages(self, data_root, make_harness):
        project = make_harness(data_root, remote_locations=[]).project
        tag = project.workflows[0].workflow_tag

        assert "Known: " + tag in unknown_filter_error(project, "nope", None)
        assert unknown_filter_error(project, tag, "asv_table") is None
        assert "of workflow" in unknown_filter_error(project, tag, "nope")


class TestServerCheckKeepsAReportedExit:
    def test_an_exit_from_the_config_load_is_not_reported_again(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        login = MagicMock(side_effect=typer.Exit(code=1))

        result = _invoke(
            app,
            runner,
            harness,
            ["ingest", "--template", TEMPLATE, "--data-root", str(data_root), "--skip-s3-check"],
            [patch.object(run_module, "api_login", login)],
        )

        assert result.exit_code == 1
        assert "Server accessibility check failed" not in result.output


class TestAttachMessages:
    def test_already_attached_run_says_no_run_is_added(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[str(data_root)])

        result = _invoke(app, runner, harness, _template(data_root, "--attach-run"))

        assert result.exit_code == 0, result.output
        output = normalize(result.output)
        assert "already one of the project's runs, so no run is added" in output
        assert "Re-scanning it only" not in output
        assert "Skipping dashboard import (--attach-run)" in output

    def test_exists_in_project_file_mode_does_not_offer_the_file_as_a_run(
        self, app, runner, data_root, project_file, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        harness.sync = MagicMock(return_value={"action": "exists"})
        args, extra = _project_mode(harness, project_file)

        result = _invoke(app, runner, harness, args, extra)

        assert result.exit_code == 2
        output = normalize(result.output)
        assert "the data locations this configuration lists" in output
        assert str(project_file) not in output


class TestRunAliasHelp:
    def test_run_help_names_the_new_command(self, app, runner):
        result = runner.invoke(app, ["run", "--help"], terminal_width=200)

        assert result.exit_code == 0
        output = normalize(result.output)
        assert "Old name of `ingest`" in output or "Old name of ingest" in output
        assert "Formerly" not in output.split("Options")[0]


class TestProvisioningReadsTheConfigurationInUse:
    def test_the_environment_variable_names_the_file(
        self, app, runner, tmp_path, data_root, make_harness, monkeypatch
    ):
        config = tmp_path / "env-CLI.yaml"
        config.write_text("api_base_url: http://localhost\n")
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(config))
        get_config = MagicMock(return_value={})
        provision = MagicMock(side_effect=RuntimeError("stop here"))

        result = _invoke(
            app,
            runner,
            make_harness(data_root, remote_locations=[]),
            _template(data_root, "--user", "someone@example.org", "--provisioning-key", "k"),
            [
                patch.object(run_module, "load_depictio_config", MagicMock()),
                patch("depictio.models.utils.get_config", get_config),
                patch.object(run_module, "api_provision_user", provision),
            ],
        )

        assert result.exit_code == 1
        get_config.assert_called_once_with(str(config))
