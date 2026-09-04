"""Tests for the ``run`` command's early option-resolution branch.

Only the guards that execute *before* any server, S3 or filesystem work are
covered here: the ``--pipeline-id`` auto-resolution added for automated
triggering, its precedence against ``--template`` / ``--project-config-path``,
and the mutual-exclusivity check. That branch is pure argument handling, so
these tests need no network and no mocking of the ingestion pipeline.
"""

import re

import pytest
import typer
from typer.testing import CliRunner

from depictio.cli.cli.commands.run import register_run_command

# Manifests for templates that really ship in this repository
# (depictio/projects/nf-core/<pipeline>/<version>/template.yaml).
SHIPPED_MANIFESTS = [
    "nf-core/ampliseq/2.16.0",
    "nf-core/ampliseq/2.18.0",
    "nf-core/viralrecon/3.0.0",
    "nf-core/variantbenchmarking/1.4.0",
]

UNKNOWN_MANIFEST = "acme/not-a-real-pipeline/9.9.9"

NO_TEMPLATE_MESSAGE = "No bundled depictio template"


def normalize(output: str) -> str:
    """Collapse Rich's line wrapping so message assertions are stable.

    Rich hard-wraps console output at the (non-TTY) default width, which can
    split an asserted phrase across two lines.
    """
    return re.sub(r"\s+", " ", output)


@pytest.fixture
def app():
    """A minimal Typer app exposing only the ``run`` command."""
    app = typer.Typer()
    register_run_command(app)
    return app


@pytest.fixture
def runner():
    return CliRunner()


class TestNextflowManifestResolution:
    """``--pipeline-id`` maps a pipeline identity onto a bundled template."""

    def test_unknown_manifest_exits_with_guidance(self, app, runner):
        """An unmatched manifest fails loudly instead of silently doing nothing."""
        result = runner.invoke(app, ["--pipeline-id", UNKNOWN_MANIFEST])

        assert result.exit_code == 1
        output = normalize(result.output)
        assert NO_TEMPLATE_MESSAGE in output
        assert UNKNOWN_MANIFEST in output
        # The message must point at the manual escape hatches.
        assert "--project-config-path" in output
        assert "--template" in output

    @pytest.mark.parametrize("manifest", SHIPPED_MANIFESTS)
    def test_known_manifest_resolves_to_template(self, app, runner, manifest):
        """A shipped manifest becomes template mode and falls through to the
        next guard (``--data-root``), proving resolution succeeded."""
        result = runner.invoke(app, ["--pipeline-id", manifest])

        output = normalize(result.output)
        assert NO_TEMPLATE_MESSAGE not in output
        assert "--data-root is required when using --template" in output
        assert result.exit_code == 1

    def test_explicit_project_config_path_wins_over_manifest(self, app, runner, tmp_path):
        """--project-config-path short-circuits manifest resolution entirely.

        The manifest is deliberately bogus: if it were resolved at all, the run
        would abort with the "no bundled template" error.
        """
        project_config = tmp_path / "project.yaml"
        project_config.write_text("name: irrelevant-under-dry-run\n")

        result = runner.invoke(
            app,
            [
                "--pipeline-id",
                UNKNOWN_MANIFEST,
                "--project-config-path",
                str(project_config),
                "--dry-run",
                "--skip-server-check",
                "--skip-s3-check",
            ],
        )

        output = normalize(result.output)
        assert NO_TEMPLATE_MESSAGE not in output
        assert result.exit_code == 0

    def test_explicit_template_wins_over_manifest(self, app, runner):
        """--template short-circuits manifest resolution too."""
        result = runner.invoke(
            app,
            [
                "--pipeline-id",
                UNKNOWN_MANIFEST,
                "--template",
                SHIPPED_MANIFESTS[0],
            ],
        )

        output = normalize(result.output)
        assert NO_TEMPLATE_MESSAGE not in output
        # Stopped at the --data-root guard, i.e. --template was used as-is.
        assert "--data-root is required when using --template" in output
        assert result.exit_code == 1


class TestMutuallyExclusiveOptions:
    """``--template`` and ``--project-config-path`` describe two different modes."""

    def test_template_with_project_config_path_is_rejected(self, app, runner, tmp_path):
        project_config = tmp_path / "project.yaml"
        project_config.write_text("name: irrelevant\n")

        result = runner.invoke(
            app,
            [
                "--template",
                SHIPPED_MANIFESTS[0],
                "--project-config-path",
                str(project_config),
            ],
        )

        assert result.exit_code == 1
        assert "--template and --project-config-path are mutually exclusive" in normalize(
            result.output
        )
