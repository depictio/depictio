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
from typer.main import get_command
from typer.testing import CliRunner

from depictio.cli.cli.commands import run as run_module
from depictio.cli.cli.commands.run import (
    AUTOMATION_PANEL,
    DASHBOARDS_PANEL,
    DEBUG_PANEL,
    PROJECT_PANEL,
    SKIP_STEPS,
    STEPS_PANEL,
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


def usage_error(output: str) -> str:
    """A usage error's text, out of the panel it wraps in."""
    return normalize(output.replace("│", " "))


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
        str(data_root),
        "--skip",
        "server-check,s3-check",
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
        "--skip",
        "server-check,s3-check",
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
            _template(data_root, "--skip", "sync"),
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
            _template(data_root, "--continue-on-error", "--skip", "sync"),
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
    # --project-name is its former name, still taken.
    @pytest.mark.parametrize("option", ["--project", "--project-name"])
    def test_the_file_is_validated_under_the_new_name(
        self, app, runner, data_root, project_file, make_harness, option
    ):
        harness = make_harness(data_root, remote_locations=[])
        validate = MagicMock(
            return_value=(MagicMock(), {"success": True, "project_config": harness.project})
        )
        args, _ = _project_mode(harness, project_file, option, "Renamed")

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
    # --skip-dashboard-import is the former spelling, still taken.
    @pytest.mark.parametrize(
        "flags", [["--skip", "dashboards"], ["--skip-dashboard-import"]], ids=["skip", "former"]
    )
    def test_a_skipped_dashboard_outside_template_mode(
        self, app, runner, data_root, project_file, dashboard_file, make_harness, flags
    ):
        harness = make_harness(data_root, remote_locations=[str(data_root)])
        args, extra = _project_mode(
            harness, project_file, "--dashboard", str(dashboard_file), "--update-config", *flags
        )

        result = _invoke(app, runner, harness, args, extra)

        assert result.exit_code == 0, result.output
        output = normalize(result.output)
        assert "(8/8 steps)" in output
        assert "Skipping dashboard import (--skip dashboards)" in output
        harness.import_dashboards.assert_not_called()

    def test_an_attached_run_imports_the_dashboards_too(
        self, app, runner, data_root, project_file, dashboard_file, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[str(data_root)])
        args, extra = _project_mode(
            harness, project_file, "--dashboard", str(dashboard_file), "--attach-run"
        )

        result = _invoke(app, runner, harness, args, extra)

        assert result.exit_code == 0, result.output
        assert "(9/9 steps)" in normalize(result.output)
        # Keeping the ones the project has: a reset is asked for, never implied.
        assert harness.import_dashboards.call_args.kwargs["reset"] is False


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
                "--skip",
                "server-check,s3-check",
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
        result = runner.invoke(app, ["ingest", "--skip", "server-check", "--skip", "s3-check"])

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
            ["ingest", "--template", TEMPLATE, str(data_root), "--skip", "s3-check"],
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
        assert "Formerly `run`" not in output


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


def _resolve_into(harness):
    """Record the template resolution: what DATA_DIR and --project reached it as."""
    meta = MagicMock(template_id=TEMPLATE)
    harness.resolve = MagicMock(
        return_value=({"name": harness.project.name, "workflows": []}, meta, {}, [], {})
    )
    return harness.resolve


class TestDataDirArgument:
    """The results to ingest are ingest's argument. --data-root, their former option,
    is still taken from the scripts, CI jobs and Nextflow hooks that pass it."""

    def test_the_argument_is_what_the_template_resolves_against(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        resolve = _resolve_into(harness)

        result = _invoke(app, runner, harness, _template(data_root))

        assert result.exit_code == 0, result.output
        assert resolve.call_args.kwargs["data_root"] == str(data_root)
        assert "is now" not in result.output

    def test_the_former_option_still_works_and_says_its_new_name(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        resolve = _resolve_into(harness)
        args = ["ingest", "--template", TEMPLATE, "--data-root", str(data_root)]

        result = _invoke(app, runner, harness, [*args, "--skip", "server-check,s3-check"])

        assert result.exit_code == 0, result.output
        assert resolve.call_args.kwargs["data_root"] == str(data_root)
        assert "--data-root is now the DATA_DIR argument" in normalize(result.stderr)

    def test_both_are_a_usage_error(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        args = _template(data_root, "--data-root", str(data_root))

        result = _invoke(app, runner, harness, args)

        assert result.exit_code == 2
        assert "give DATA_DIR or --data-root, not both" in usage_error(result.output)
        harness.sync.assert_not_called()

    def test_a_missing_directory_is_named_as_the_argument(self, app, runner, tmp_path):
        result = runner.invoke(app, ["ingest", str(tmp_path / "nope"), "--template", TEMPLATE])

        assert result.exit_code == 1
        assert "DATA_DIR does not exist or is not a directory" in normalize(result.output)

    def test_a_template_without_it_names_the_argument(self, app, runner):
        result = runner.invoke(app, ["ingest", "--template", TEMPLATE])

        assert result.exit_code == 1
        assert "--template needs DATA_DIR" in normalize(result.output)


class TestProjectOption:
    def test_project_names_the_project(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        resolve = _resolve_into(harness)

        result = _invoke(app, runner, harness, _template(data_root, "--project", "Mine"))

        assert result.exit_code == 0, result.output
        assert resolve.call_args.kwargs["project_name"] == "Mine"

    def test_the_former_name_still_works_and_says_its_new_one(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        resolve = _resolve_into(harness)

        result = _invoke(app, runner, harness, _template(data_root, "--project-name", "Mine"))

        assert result.exit_code == 0, result.output
        assert resolve.call_args.kwargs["project_name"] == "Mine"
        assert "--project-name is now --project" in normalize(result.stderr)

    def test_both_are_a_usage_error(self, app, runner, data_root):
        result = runner.invoke(
            app, ["ingest", str(data_root), "--project", "a", "--project-name", "b"]
        )

        assert result.exit_code == 2
        assert "give --project or --project-name, not both" in usage_error(result.output)


class TestSkip:
    @pytest.mark.parametrize(
        "flags",
        [
            ["--skip", "sync,scan"],
            ["--skip", "sync", "--skip", "scan"],
            ["--skip", " Scan , SYNC,"],
        ],
        ids=["comma", "repeated", "spaced-and-cased"],
    )
    def test_the_steps_named_are_skipped(self, app, runner, data_root, make_harness, flags):
        harness = make_harness(data_root, remote_locations=[])

        result = _invoke(app, runner, harness, _template(data_root, *flags))

        assert result.exit_code == 0, result.output
        harness.sync.assert_not_called()
        harness.scan.assert_not_called()
        harness.process.assert_called_once()
        output = normalize(result.output)
        assert "Skipping project configuration sync" in output
        assert "Skipping data scanning" in output

    def test_an_unknown_step_is_a_usage_error_naming_the_known_ones(self, app, runner):
        result = runner.invoke(app, ["ingest", "--skip", "scan,joins"])

        assert result.exit_code == 2
        output = usage_error(result.output)
        assert "unknown step 'joins'" in output
        for step in SKIP_STEPS:
            assert step in output

    def test_the_former_flags_still_skip_and_say_what_they_are_now(
        self, app, runner, data_root, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[])
        args = ["ingest", str(data_root), "--template", TEMPLATE]
        former = ["--skip-server-check", "--skip-s3-check", "--skip-sync", "--skip-scan"]

        result = _invoke(app, runner, harness, [*args, *former])

        assert result.exit_code == 0, result.output
        harness.sync.assert_not_called()
        harness.scan.assert_not_called()
        stderr = normalize(result.stderr)
        assert "--skip-sync is now --skip sync" in stderr
        assert "--skip-server-check is now --skip server-check" in stderr

    def test_every_step_has_its_former_flag(self, app):
        command = get_command(app).commands["ingest"]
        options = {opt for param in command.params for opt in param.opts}
        assert set(SKIP_STEPS.values()) <= options


class TestHelpSurface:
    """`ingest --help` shows the essentials first, the rest in named panels, and
    neither the former names nor the flags --update-config folds in."""

    HIDDEN = {
        "--CLI-config-path",
        "--data-root",
        "--project-name",
        *SKIP_STEPS.values(),
        "--overwrite",
        "--rescan-folders",
        "--sync-files",
    }
    ESSENTIALS = [
        "--server",
        "--template",
        "--project-config-path",
        "--update-config",
        "--var",
        "--dry-run",
        "--help",
    ]
    PANELS = [
        "Arguments",
        "Options",
        PROJECT_PANEL,
        DASHBOARDS_PANEL,
        STEPS_PANEL,
        AUTOMATION_PANEL,
        DEBUG_PANEL,
    ]

    @pytest.fixture
    def help_text(self, app, runner, monkeypatch):
        monkeypatch.setenv("COLUMNS", "200")
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0, result.output
        return result.output

    def test_the_hidden_options(self, app):
        command = get_command(app).commands["ingest"]
        hidden = {param.opts[0] for param in command.params if getattr(param, "hidden", False)}
        assert hidden == self.HIDDEN

    def test_hidden_options_have_no_row(self, help_text):
        rows = set(re.findall(r"│ +(--[\w-]+)", help_text))
        assert not rows & self.HIDDEN
        assert "--skip" in rows and "--project" in rows

    def test_the_panels_in_order(self, help_text):
        starts = [help_text.index(f"─ {panel} ─") for panel in self.PANELS]
        assert starts == sorted(starts)

    def test_the_argument_and_the_essentials_come_first(self, help_text):
        arguments = help_text[help_text.index("─ Arguments ─") : help_text.index("─ Options ─")]
        assert "DATA_DIR" in arguments
        options = help_text[
            help_text.index("─ Options ─") : help_text.index(f"─ {PROJECT_PANEL} ─")
        ]
        assert re.findall(r"│ +(--[\w-]+)", options) == self.ESSENTIALS

    def test_the_new_names_say_their_former_ones(self, help_text):
        text = normalize(help_text.replace("│", " "))
        assert "Formerly `--data-root`" in text
        assert "Formerly `--project-name`" in text
        assert "Formerly the `--skip-<step>` flags" in text

    def test_run_shows_the_same_panels(self, app, runner, monkeypatch):
        monkeypatch.setenv("COLUMNS", "200")
        output = runner.invoke(app, ["run", "--help"]).output
        for panel in self.PANELS:
            assert f"─ {panel} ─" in output


class TestDashboardsOnARefresh:
    """A refresh keeps the dashboards the project has, edits made in the viewer
    included; --reset-dashboards replaces them, as a refresh used to."""

    @staticmethod
    def _results(*statuses):
        return [
            {
                "path": f"/d/{i}.yaml",
                "success": True,
                "dashboard_id": f"id{i}",
                "title": f"D{i}",
                "status": status,
            }
            for i, status in enumerate(statuses)
        ]

    @pytest.mark.parametrize(
        ("flags", "reset", "update"),
        [
            ([], False, False),
            (["--update-config"], False, True),
            (["--attach-run"], False, True),
            (["--reset-dashboards"], True, True),
            (["--update-config", "--reset-dashboards"], True, True),
        ],
        ids=["first-ingest", "update-config", "attach-run", "reset", "update-and-reset"],
    )
    def test_what_each_mode_asks_of_the_import(
        self, app, runner, data_root, dashboard_file, make_harness, flags, reset, update
    ):
        harness = make_harness(data_root, remote_locations=[str(data_root)])
        harness.import_dashboards.return_value = self._results("created")

        result = _invoke(
            app, runner, harness, _template(data_root, "--dashboard", str(dashboard_file), *flags)
        )

        assert result.exit_code == 0, result.output
        harness.import_dashboards.assert_called_once()
        assert harness.import_dashboards.call_args.kwargs["reset"] is reset
        assert harness.sync.call_args.kwargs["update"] is update

    def test_each_dashboard_says_what_became_of_it(
        self, app, runner, data_root, dashboard_file, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[str(data_root)])
        harness.import_dashboards.return_value = self._results("created", "kept", "replaced")

        result = _invoke(
            app,
            runner,
            harness,
            _template(data_root, "--dashboard", str(dashboard_file), "--update-config"),
        )

        assert result.exit_code == 0, result.output
        output = normalize(result.output)
        for line in ("Dashboard created: D0", "Dashboard kept: D1", "Dashboard replaced: D2"):
            assert line in output
        # Again in the summary, where a pipeline log is read.
        summary = output[output.index("Ingestion summary") :]
        for line in ("Dashboard 'D0' created", "Dashboard 'D1' kept", "Dashboard 'D2' replaced"):
            assert line in summary
        assert "--reset-dashboards replaces them" in output

    def test_reset_warns_that_the_viewer_edits_are_lost(
        self, app, runner, data_root, dashboard_file, make_harness
    ):
        harness = make_harness(data_root, remote_locations=[str(data_root)])
        harness.import_dashboards.return_value = self._results("replaced")

        result = _invoke(
            app,
            runner,
            harness,
            _template(data_root, "--dashboard", str(dashboard_file), "--reset-dashboards"),
        )

        assert result.exit_code == 0, result.output
        output = normalize(result.output)
        assert "layout and components edited in the viewer are lost" in output
        # It refreshes the project, tables included, as --update-config does.
        assert harness.scan.call_args.kwargs["command_parameters"]["rescan_folders"] is True
        assert harness.process.call_args.kwargs["command_parameters"]["overwrite"] is True

    def test_a_refresh_does_not_warn(self, app, runner, data_root, dashboard_file, make_harness):
        harness = make_harness(data_root, remote_locations=[str(data_root)])
        harness.import_dashboards.return_value = self._results("kept")

        result = _invoke(
            app,
            runner,
            harness,
            _template(data_root, "--dashboard", str(dashboard_file), "--update-config"),
        )

        assert result.exit_code == 0, result.output
        assert "are lost" not in normalize(result.output)

    def test_reset_with_the_dashboards_skipped_is_a_usage_error(self, app, runner, data_root):
        result = runner.invoke(
            app, ["ingest", str(data_root), "--reset-dashboards", "--skip", "dashboards"]
        )

        assert result.exit_code == 2
        assert "give --reset-dashboards or --skip dashboards" in usage_error(result.output)

    def test_the_dry_run_says_which(self, app, runner, data_root, dashboard_file, make_harness):
        harness = make_harness(data_root, remote_locations=[])
        origin = SimpleNamespace(
            template_id=TEMPLATE, template_version="2.16.0", data_root=str(data_root)
        )
        harness.resolve = MagicMock(
            return_value=(
                {"name": "n", "workflows": []},
                MagicMock(template_id=TEMPLATE),
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
            _template(
                data_root, "--dashboard", str(dashboard_file), "--update-config", "--dry-run"
            ),
            [patch.object(run_module, "validate_project_locally", validate)],
        )

        assert result.exit_code == 0, result.output
        assert "Would import 1 dashboard(s), keeping those the project already has" in normalize(
            result.output
        )
