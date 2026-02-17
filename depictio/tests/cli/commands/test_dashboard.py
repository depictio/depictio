"""
Unit Tests for Dashboard CLI Commands.

Tests the CLI commands for dashboard YAML validation, import, and export,
focusing on the mandatory --config requirement for server operations.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands.dashboard import app

runner = CliRunner()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def valid_yaml_content() -> str:
    """Valid dashboard YAML content."""
    return """
title: "Test Dashboard"
subtitle: "Testing the CLI commands"
components:
  - tag: scatter-1
    component_type: figure
    workflow_tag: python/test_workflow
    data_collection_tag: test_table
    visu_type: scatter
    dict_kwargs:
      x: col1
      y: col2
"""


@pytest.fixture
def valid_yaml_file(tmp_path: Path, valid_yaml_content: str) -> Path:
    """Create a temporary valid YAML file."""
    yaml_file = tmp_path / "dashboard.yaml"
    yaml_file.write_text(valid_yaml_content, encoding="utf-8")
    return yaml_file


@pytest.fixture
def invalid_yaml_file(tmp_path: Path) -> Path:
    """Create a temporary invalid YAML file."""
    yaml_file = tmp_path / "invalid.yaml"
    yaml_file.write_text("title: [unclosed bracket\ncomponents: []", encoding="utf-8")
    return yaml_file


# ============================================================================
# Test CLI config requirement (--config mandatory for import/export)
# ============================================================================


class TestCLIConfigRequirement:
    """Tests for mandatory --config option in import and export commands."""

    def test_import_without_config_fails(self, valid_yaml_file: Path):
        """Import without --config (and without --dry-run) should fail."""
        result = runner.invoke(
            app,
            [
                "import",
                str(valid_yaml_file),
                # No --config and no --dry-run
            ],
        )
        assert result.exit_code == 1
        assert "--config is required" in result.output

    def test_import_dry_run_without_config_succeeds(self, valid_yaml_file: Path):
        """Import with --dry-run should work without --config."""
        result = runner.invoke(
            app,
            [
                "import",
                str(valid_yaml_file),
                "--dry-run",
                # No --config needed for dry-run
            ],
        )
        assert result.exit_code == 0
        assert "Dry run mode" in result.output

    def test_import_with_config_attempts_server(self, valid_yaml_file: Path, tmp_path: Path):
        """Import with --config should attempt server connection."""
        # Create a fake config file
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
api_base_url: http://localhost:9999
access_token: fake-token
""",
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            [
                "import",
                str(valid_yaml_file),
                "--config",
                str(config_file),
            ],
        )
        # Should fail to connect (no server), but should NOT fail on missing config
        assert "Error loading CLI config" in result.output or "Cannot connect" in result.output

    def test_export_without_config_fails(self):
        """Export without --config should fail (missing required argument)."""
        result = runner.invoke(
            app,
            [
                "export",
                "some-dashboard-id",
                # No --config
            ],
        )
        # Typer should report missing required option
        assert result.exit_code != 0
        assert "config" in result.output.lower() or "missing" in result.output.lower()

    def test_export_with_config_attempts_server(self, tmp_path: Path):
        """Export with --config should attempt server connection."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
api_base_url: http://localhost:9999
access_token: fake-token
""",
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            [
                "export",
                "some-dashboard-id",
                "--config",
                str(config_file),
            ],
        )
        # Should fail to connect (no server), but config is provided
        assert "Error loading CLI config" in result.output or "Error" in result.output


# ============================================================================
# Test CLI validate command (no config needed)
# ============================================================================


class TestCLIValidateCommand:
    """Tests for the 'depictio dashboard validate' CLI command."""

    def test_validate_valid_file(self, valid_yaml_file: Path):
        """Valid YAML file should pass validation."""
        result = runner.invoke(app, ["validate", str(valid_yaml_file)])
        assert result.exit_code == 0
        assert "Validation passed" in result.output

    def test_validate_invalid_file(self, invalid_yaml_file: Path):
        """Invalid YAML file should fail validation."""
        result = runner.invoke(app, ["validate", str(invalid_yaml_file)])
        assert result.exit_code == 1
        assert "validation failed" in result.output.lower()

    def test_validate_nonexistent_file(self):
        """Non-existent file should fail with error."""
        result = runner.invoke(app, ["validate", "/nonexistent/path/dashboard.yaml"])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_validate_no_config_required(self, valid_yaml_file: Path):
        """Validate should work without any --config option."""
        # Validate is purely local - no server config needed
        result = runner.invoke(app, ["validate", str(valid_yaml_file)])
        assert result.exit_code == 0
        # No mention of config errors
        assert "config" not in result.output.lower() or "Configuration" not in result.output


# ============================================================================
# Test CLI import command dry-run mode
# ============================================================================


class TestCLIImportDryRun:
    """Tests for the 'depictio dashboard import --dry-run' CLI command."""

    def test_import_dry_run_shows_validation(self, valid_yaml_file: Path):
        """Import with --dry-run should show validation results."""
        result = runner.invoke(
            app,
            ["import", str(valid_yaml_file), "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Validation passed" in result.output
        assert "Dry run mode" in result.output

    def test_import_dry_run_shows_component_count(self, valid_yaml_file: Path):
        """Import with --dry-run should show component count."""
        result = runner.invoke(
            app,
            ["import", str(valid_yaml_file), "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Components:" in result.output

    def test_import_dry_run_invalid_yaml_fails(self, invalid_yaml_file: Path):
        """Import with --dry-run should fail for invalid YAML."""
        result = runner.invoke(
            app,
            ["import", str(invalid_yaml_file), "--dry-run"],
        )
        assert result.exit_code == 1
        assert "Validation failed" in result.output

    def test_import_dry_run_nonexistent_file(self):
        """Import with --dry-run should fail for non-existent file."""
        result = runner.invoke(
            app,
            ["import", "/nonexistent/file.yaml", "--dry-run"],
        )
        assert result.exit_code == 1
        assert "File not found" in result.output


# ============================================================================
# Test CLI import --overwrite option
# ============================================================================


class TestCLIImportOverwrite:
    """Tests for the --overwrite option in import command."""

    def test_import_overwrite_flag_accepted(self, valid_yaml_file: Path):
        """--overwrite flag should be accepted in dry-run."""
        result = runner.invoke(
            app,
            ["import", str(valid_yaml_file), "--dry-run", "--overwrite"],
        )
        # Dry-run doesn't actually check overwrite, but flag should be valid
        assert result.exit_code == 0

    def test_import_overwrite_requires_config(self, valid_yaml_file: Path):
        """--overwrite without --config should fail (same as normal import)."""
        result = runner.invoke(
            app,
            ["import", str(valid_yaml_file), "--overwrite"],
        )
        assert result.exit_code == 1
        assert "--config is required" in result.output

    def test_import_overwrite_with_config_attempts_server(
        self, valid_yaml_file: Path, tmp_path: Path
    ):
        """--overwrite with --config should attempt server connection."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
api_base_url: http://localhost:9999
access_token: fake-token
""",
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            ["import", str(valid_yaml_file), "--config", str(config_file), "--overwrite"],
        )
        # Should show "Updating" instead of "Importing"
        assert "Updating" in result.output or "Error" in result.output


# ============================================================================
# _resolve_dc_id_from_project — pure function unit tests
# ============================================================================


def _resolve(project_data: dict, workflow_tag: str, dc_tag: str) -> str | None:
    from depictio.cli.cli.commands.dashboard import _resolve_dc_id_from_project

    return _resolve_dc_id_from_project(project_data, workflow_tag, dc_tag)


def _project(wf_name: str, engine: str, dc_tag: str, dc_id: str) -> dict:
    """Build a minimal project document with one workflow and one DC."""
    return {
        "workflows": [
            {
                "name": wf_name,
                "engine": {"name": engine},
                "data_collections": [
                    {"data_collection_tag": dc_tag, "id": dc_id},
                ],
            }
        ]
    }


class TestResolveDcIdFromProject:
    """Unit tests for _resolve_dc_id_from_project."""

    def test_match_with_engine_prefix(self):
        """workflow_tag='engine/name' matches when engine+name both correct."""
        project = _project("iris_workflow", "python", "iris_table", "abc123")
        assert _resolve(project, "python/iris_workflow", "iris_table") == "abc123"

    def test_match_by_name_only_no_engine(self):
        """workflow_tag without slash matches by name when no engine is set."""
        project = _project("iris_workflow", "", "iris_table", "abc123")
        assert _resolve(project, "iris_workflow", "iris_table") == "abc123"

    def test_match_by_name_only_with_slash(self):
        """workflow_tag 'engine/name' — name part alone matches the workflow."""
        project = _project("iris_workflow", "python", "iris_table", "abc123")
        assert _resolve(project, "python/iris_workflow", "iris_table") == "abc123"

    def test_wrong_workflow_tag_returns_none(self):
        project = _project("iris_workflow", "python", "iris_table", "abc123")
        assert _resolve(project, "python/other_workflow", "iris_table") is None

    def test_wrong_dc_tag_returns_none(self):
        project = _project("iris_workflow", "python", "iris_table", "abc123")
        assert _resolve(project, "python/iris_workflow", "other_table") is None

    def test_returns_id_key_over_underscore_id(self):
        """API serialises ObjectId as 'id'; prefer that over '_id'."""
        project = {
            "workflows": [
                {
                    "name": "wf",
                    "engine": {"name": "python"},
                    "data_collections": [
                        {"data_collection_tag": "dc", "id": "from_id", "_id": "from_underscore"},
                    ],
                }
            ]
        }
        assert _resolve(project, "python/wf", "dc") == "from_id"

    def test_falls_back_to_underscore_id(self):
        """Falls back to '_id' when 'id' is absent."""
        project = {
            "workflows": [
                {
                    "name": "wf",
                    "engine": {"name": "python"},
                    "data_collections": [
                        {"data_collection_tag": "dc", "_id": "from_underscore"},
                    ],
                }
            ]
        }
        assert _resolve(project, "python/wf", "dc") == "from_underscore"

    def test_empty_project_returns_none(self):
        assert _resolve({}, "python/wf", "dc") is None

    def test_no_workflows_returns_none(self):
        assert _resolve({"workflows": []}, "python/wf", "dc") is None

    def test_multiple_workflows_picks_correct_one(self):
        project = {
            "workflows": [
                {
                    "name": "wf_a",
                    "engine": {"name": "python"},
                    "data_collections": [{"data_collection_tag": "dc", "id": "id_a"}],
                },
                {
                    "name": "wf_b",
                    "engine": {"name": "python"},
                    "data_collections": [{"data_collection_tag": "dc", "id": "id_b"}],
                },
            ]
        }
        assert _resolve(project, "python/wf_a", "dc") == "id_a"
        assert _resolve(project, "python/wf_b", "dc") == "id_b"
