"""
Tests for the `run` command's Nextflow manifest resolution (--nextflow-manifest).

These exercise only the early resolution branch, which runs before any server or
S3 interaction, so no network/mocking of the full pipeline is needed.
"""

import pytest
import typer
from typer.testing import CliRunner

from depictio.cli.cli.commands.run import register_run_command


@pytest.fixture
def run_app():
    """A minimal Typer app exposing just the `run` command."""
    app = typer.Typer()
    register_run_command(app)
    return app


@pytest.fixture
def runner():
    return CliRunner()


class TestNextflowManifestResolution:
    """Tests for auto-resolving a bundled template from a Nextflow manifest."""

    def test_unknown_manifest_errors(self, run_app, runner):
        """An unknown manifest (no bundled template) exits with a clear error."""
        result = runner.invoke(
            run_app,
            ["--nextflow-manifest", "acme/not-a-real-pipeline/9.9.9"],
        )
        assert result.exit_code == 1
        assert "No bundled depictio template" in result.output

    def test_known_manifest_resolves_to_template(self, run_app, runner):
        """A known nf-core manifest resolves to a template.

        Resolution succeeds (template is set), so the next guard — '--data-root is
        required when using --template' — fires instead of the 'no template' error.
        """
        result = runner.invoke(
            run_app,
            ["--nextflow-manifest", "nf-core/ampliseq/2.16.0"],
        )
        assert result.exit_code == 1
        assert "No bundled depictio template" not in result.output
        assert "data-root is required" in result.output

    def test_explicit_project_config_takes_precedence(self, run_app, runner, tmp_path):
        """An explicit --project-config-path wins; the manifest is not resolved."""
        project_yaml = tmp_path / "depictio_project.yaml"
        project_yaml.write_text("name: dummy\n")
        result = runner.invoke(
            run_app,
            [
                "--nextflow-manifest",
                "acme/not-a-real-pipeline/9.9.9",
                "--project-config-path",
                str(project_yaml),
                "--dry-run",
                "--skip-server-check",
                "--skip-s3-check",
                "--skip-sync",
                "--skip-scan",
                "--skip-process",
                "--skip-join",
            ],
        )
        # The unknown-manifest error must NOT fire because project config wins.
        assert "No bundled depictio template" not in result.output
