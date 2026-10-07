"""`depictio ingest`: its hidden alias `run`, --server, and the image upload in step 6.

Every server and storage call is mocked, through the harness in conftest.py.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.main import get_command
from typer.testing import CliRunner

from depictio.cli.cli.commands.run import register_run_command
from depictio.cli.cli.utils.image_upload import ImageUploadError

UNKNOWN_MANIFEST = "acme/not-a-real-pipeline/9.9.9"


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
    root = tmp_path / "run_a"
    root.mkdir()
    return root


def _invoke(app, runner, harness, args, extra_patches=()):
    patches = [*harness.patches(), *extra_patches]
    for p in patches:
        p.start()
    try:
        return runner.invoke(app, args)
    finally:
        for p in reversed(patches):
            p.stop()


def _template_args(command, data_root, *flags):
    return [
        command,
        # A configuration that is not there: the summary's best-effort read of it
        # then fails fast, instead of reaching whatever ~/.depictio/CLI.yaml names.
        "--server",
        str(data_root.parent / "absent-CLI.yaml"),
        "--template",
        "nf-core/ampliseq/2.16.0",
        "--data-root",
        str(data_root),
        "--skip-server-check",
        "--skip-s3-check",
        *flags,
    ]


class TestTheRunAlias:
    """`run` was the command's name. Nextflow hooks installed from older releases,
    CI and scripts still call it, so it stays, out of the help."""

    def test_run_takes_the_same_options_as_ingest(self, app):
        commands = get_command(app).commands
        ingest, run = commands["ingest"], commands["run"]

        assert [p.name for p in run.params] == [p.name for p in ingest.params]
        assert run.hidden and not ingest.hidden

    def test_run_behaves_like_ingest(self, app, runner):
        results = [
            runner.invoke(app, [name, "--pipeline-id", UNKNOWN_MANIFEST])
            for name in ("ingest", "run")
        ]

        assert [r.exit_code for r in results] == [1, 1]
        assert all("No bundled depictio template" in normalize(r.output) for r in results)

    def test_run_still_ingests(self, app, runner, data_root, make_harness):
        harness = make_harness(data_root, remote_locations=[])

        result = _invoke(app, runner, harness, _template_args("run", data_root))

        assert result.exit_code == 0, result.output
        harness.sync.assert_called_once()
        harness.process.assert_called_once()
        assert "Ingestion completed successfully" in normalize(result.output)


class TestServerOption:
    def test_server_is_the_configuration_the_steps_read(
        self, app, runner, data_root, make_harness, tmp_path
    ):
        config = tmp_path / "other.yaml"
        login = MagicMock(return_value={"success": False})

        result = _invoke(
            app,
            runner,
            make_harness(data_root, remote_locations=[]),
            [
                "ingest",
                "--server",
                str(config),
                "--template",
                "nf-core/ampliseq/2.16.0",
                "--data-root",
                str(data_root),
                "--skip-s3-check",
            ],
            [patch("depictio.cli.cli.commands.run.api_login", login)],
        )

        assert result.exit_code == 1
        login.assert_called_once_with(str(config))

    def test_the_former_option_still_names_it(self, app, runner, data_root, make_harness, tmp_path):
        config = tmp_path / "old.yaml"
        login = MagicMock(return_value={"success": False})

        _invoke(
            app,
            runner,
            make_harness(data_root, remote_locations=[]),
            [
                "run",
                "--CLI-config-path",
                str(config),
                "--template",
                "nf-core/ampliseq/2.16.0",
                "--data-root",
                str(data_root),
                "--skip-s3-check",
            ],
            [patch("depictio.cli.cli.commands.run.api_login", login)],
        )

        login.assert_called_once_with(str(config))

    def test_both_together_are_refused(self, app, runner):
        result = runner.invoke(
            app, ["ingest", "--server", "a.yaml", "--CLI-config-path", "b.yaml", "--dry-run"]
        )

        assert result.exit_code == 2
        assert "not both" in normalize(result.output)

    def test_local_without_a_local_server_says_how_to_start_one(
        self, app, runner, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
        # A project to ingest, or the run stops on the missing one first.
        project = tmp_path / "project.yaml"
        project.write_text("name: irrelevant\n")

        result = runner.invoke(
            app,
            ["ingest", "--server", "local", "--project-config-path", str(project), "--dry-run"],
        )

        assert result.exit_code != 0
        assert "depictio local up" in normalize(result.output)

    def test_the_help_shows_server_not_the_former_option(self, app, runner):
        result = runner.invoke(app, ["ingest", "--help"], terminal_width=200)

        assert "--server" in result.output
        # Named only inside the "Formerly" backticks of --server, never as an option row.
        assert not re.search(r"(?<!`)--CLI-config-path", result.output)


class TestImagesInStepSix:
    """Image collections with local_images_path get their images uploaded once the
    tables are processed: the table says which images it references."""

    @pytest.fixture
    def image_dc(self):
        return SimpleNamespace(data_collection_tag="sample_images")

    def _run(self, app, runner, harness, data_root, upload, collections, *flags):
        return _invoke(
            app,
            runner,
            harness,
            _template_args("ingest", data_root, *flags),
            [
                patch(
                    "depictio.cli.cli.commands.run.image_collections_to_upload",
                    MagicMock(return_value=collections),
                ),
                patch("depictio.cli.cli.commands.run.upload_collection_images", upload),
            ],
        )

    def test_the_images_are_uploaded_after_the_tables(
        self, app, runner, data_root, make_harness, image_dc
    ):
        harness = make_harness(data_root, remote_locations=[])
        calls: list[str] = []
        harness.process.side_effect = lambda **_: calls.append("process") or {"total_failed": 0}
        upload = MagicMock(
            side_effect=lambda dc, cfg, **_: (
                calls.append("images") or {"uploaded": 9, "skipped": 0, "error": 0}
            )
        )

        result = self._run(app, runner, harness, data_root, upload, [image_dc])

        assert result.exit_code == 0, result.output
        assert calls == ["process", "images"]
        assert upload.call_args.args[0] is image_dc

    def test_missing_images_fail_the_step(self, app, runner, data_root, make_harness, image_dc):
        harness = make_harness(data_root, remote_locations=[])
        upload = MagicMock(
            side_effect=ImageUploadError("'sample_images': 2 image(s) the table references")
        )

        result = self._run(app, runner, harness, data_root, upload, [image_dc])

        assert result.exit_code == 1
        output = normalize(result.output)
        assert "Data processing failed: 'sample_images': 2 image(s)" in output
        # The steps after it do not run.
        harness.import_dashboards.assert_not_called()

    def test_skip_process_skips_the_upload(self, app, runner, data_root, make_harness, image_dc):
        upload = MagicMock()

        result = self._run(
            app,
            runner,
            make_harness(data_root, remote_locations=[]),
            data_root,
            upload,
            [image_dc],
            "--skip-process",
        )

        assert result.exit_code == 0, result.output
        upload.assert_not_called()

    def test_a_project_without_image_collections_uploads_nothing(
        self, app, runner, data_root, make_harness
    ):
        upload = MagicMock()

        result = _invoke(
            app,
            runner,
            make_harness(data_root, remote_locations=[]),
            _template_args("ingest", data_root),
            [patch("depictio.cli.cli.commands.run.upload_collection_images", upload)],
        )

        assert result.exit_code == 0, result.output
        upload.assert_not_called()
