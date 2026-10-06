"""
Unit Tests for Dashboard CLI Commands.

Tests the CLI commands for dashboard YAML validation, import, and export,
and the server they talk to: --server, the hidden -c/--config and --api, and
the default configuration ($DEPICTIO_CLI_CONFIG_PATH, else ~/.depictio/CLI.yaml).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from depictio.cli.cli.commands.dashboard import app

runner = CliRunner()

# The --api default before --server; now only an explicit override.
OLD_API_DEFAULT = "http://localhost:8058"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch):
    """No developer configuration: HOME is empty and the CLI env vars are unset."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in ("DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return home


def _write_cli_config(path: Path, api_base_url: str) -> Path:
    """A loadable CLI configuration whose api_base_url marks which file was read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "api_base_url": api_base_url,
                "user": {
                    "email": "admin@example.com",
                    "is_admin": True,
                    "id": "507f1f77bcf86cd799439011",
                    "token": {
                        "user_id": "507f1f77bcf86cd799439011",
                        "access_token": "test-access-token",
                        "refresh_token": "test-refresh-token",
                        "token_type": "bearer",
                        "token_lifetime": "short-lived",
                        "expire_datetime": "2099-12-31T23:59:59",
                        "refresh_expire_datetime": "2099-12-31T23:59:59",
                        "name": "test-token",
                        "created_at": "2025-06-30T18:00:00",
                        "logged_in": False,
                    },
                },
                "s3_storage": {
                    "service_name": "minio",
                    "service_port": 9000,
                    "external_host": "localhost",
                    "external_port": 9000,
                    "external_protocol": "http",
                    "root_user": "minio",
                    "root_password": "minio123",
                    "bucket": "depictio-bucket",
                },
            }
        )
    )
    return path


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
        assert "configuration file not found" in result.output
        assert "--dry-run" in result.output

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
        """Export with no --server and no default configuration names the file it missed."""
        result = runner.invoke(
            app,
            [
                "export",
                "some-dashboard-id",
                # No --server, and HOME holds no ~/.depictio/CLI.yaml
            ],
        )
        assert result.exit_code == 1
        assert "configuration file not found" in result.output

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
# The server: --server, its hidden aliases, and the default configuration
# ============================================================================


def _ok_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.text = "title: exported\n"
    return response


@pytest.fixture
def http_client():
    """httpx.Client as the import/export commands use it; records the requested URLs."""
    client = MagicMock()
    client.post.return_value = _ok_response({"dashboard_id": "d1", "title": "T", "project_id": "p"})
    client.get.return_value = _ok_response({})
    client.__enter__.return_value = client
    with patch("depictio.cli.cli.commands.dashboard.httpx.Client", return_value=client):
        yield client


class TestServerSelection:
    """The bug: the group ignored the default configuration and took the URL from --api."""

    def test_help_shows_server_and_hides_the_legacy_options(self):
        for command in ("validate", "import", "export"):
            result = runner.invoke(app, [command, "--help"], terminal_width=200)

            assert result.exit_code == 0
            assert "--server" in result.output
            for legacy in ("--config", "-c ", "--api"):
                assert legacy not in result.output, f"{command} --help shows {legacy}"

    def test_import_reads_the_default_configuration_and_its_url(
        self, valid_yaml_file: Path, isolated_home: Path, http_client
    ):
        _write_cli_config(isolated_home / ".depictio" / "CLI.yaml", "http://default.test:8123")

        result = runner.invoke(app, ["import", str(valid_yaml_file), "--offline"])

        assert result.exit_code == 0, result.output
        url = http_client.post.call_args.args[0]
        assert url == "http://default.test:8123/depictio/api/v1/dashboards/import/yaml"

    def test_import_honours_the_config_path_env_var(
        self, valid_yaml_file: Path, tmp_path: Path, monkeypatch, http_client
    ):
        config = _write_cli_config(tmp_path / "env" / "CLI.yaml", "http://from-env.test")
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(config))

        result = runner.invoke(app, ["import", str(valid_yaml_file), "--offline"])

        assert result.exit_code == 0, result.output
        assert http_client.post.call_args.args[0].startswith("http://from-env.test/")

    @pytest.mark.parametrize("flag", ["--server", "--config", "-c"])
    def test_import_takes_the_url_from_the_named_configuration(
        self, valid_yaml_file: Path, tmp_path: Path, http_client, flag
    ):
        config = _write_cli_config(tmp_path / "named.yaml", "http://named.test")

        result = runner.invoke(
            app, ["import", str(valid_yaml_file), flag, str(config), "--offline"]
        )

        assert result.exit_code == 0, result.output
        assert http_client.post.call_args.args[0].startswith("http://named.test/")

    def test_an_explicit_api_wins_even_at_the_old_default(
        self, valid_yaml_file: Path, tmp_path: Path, http_client
    ):
        """The old default could not be chosen on purpose: it meant "use the config"."""
        config = _write_cli_config(tmp_path / "named.yaml", "http://named.test")

        result = runner.invoke(
            app,
            ["import", str(valid_yaml_file), "--server", str(config), "--api", OLD_API_DEFAULT],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert http_client.post.call_args.args[0].startswith(f"{OLD_API_DEFAULT}/")

    def test_server_local_is_the_local_stack_configuration(
        self, valid_yaml_file: Path, tmp_path: Path, monkeypatch, http_client
    ):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
        _write_cli_config(tmp_path / "local" / "cli" / "admin_config.yaml", "http://local.test")

        result = runner.invoke(
            app, ["import", str(valid_yaml_file), "--server", "local", "--offline"]
        )

        assert result.exit_code == 0, result.output
        assert http_client.post.call_args.args[0].startswith("http://local.test/")

    def test_server_and_config_together_are_refused(self, valid_yaml_file: Path):
        result = runner.invoke(
            app, ["import", str(valid_yaml_file), "--server", "a.yaml", "--config", "b.yaml"]
        )

        assert result.exit_code == 2
        assert "not both" in result.output

    def test_export_reads_the_default_configuration_and_its_url(
        self, isolated_home: Path, tmp_path: Path, http_client
    ):
        _write_cli_config(isolated_home / ".depictio" / "CLI.yaml", "http://default.test:8123")
        out = tmp_path / "out.yaml"

        result = runner.invoke(app, ["export", "abc123", "-o", str(out)])

        assert result.exit_code == 0, result.output
        url = http_client.get.call_args.args[0]
        assert url == "http://default.test:8123/depictio/api/v1/dashboards/abc123/yaml"
        assert out.read_text() == "title: exported\n"

    def test_export_keeps_the_legacy_short_flag(self, tmp_path: Path, http_client):
        config = _write_cli_config(tmp_path / "named.yaml", "http://named.test")

        result = runner.invoke(
            app, ["export", "abc123", "-c", str(config), "-o", str(tmp_path / "o.yaml")]
        )

        assert result.exit_code == 0, result.output
        assert http_client.get.call_args.args[0].startswith("http://named.test/")


class TestValidateServer:
    """validate checks against a server only when one is configured."""

    @pytest.fixture
    def online(self):
        """validate_schema_online, recording the URL it was handed."""
        with patch(
            "depictio.cli.cli.commands.dashboard.validate_schema_online", return_value=[]
        ) as check:
            yield check

    def test_no_server_and_no_default_stays_offline(self, valid_yaml_file: Path, online):
        result = runner.invoke(app, ["validate", str(valid_yaml_file)])

        assert result.exit_code == 0, result.output
        assert "Pass 2: skipped" in result.output
        online.assert_not_called()

    def test_the_default_configuration_is_used_with_its_url(
        self, valid_yaml_file: Path, isolated_home: Path, online
    ):
        _write_cli_config(isolated_home / ".depictio" / "CLI.yaml", "http://default.test")

        result = runner.invoke(app, ["validate", str(valid_yaml_file)])

        assert result.exit_code == 0, result.output
        assert online.call_args.args[1] == "http://default.test"

    def test_the_env_var_configuration_is_used(
        self, valid_yaml_file: Path, tmp_path: Path, monkeypatch, online
    ):
        config = _write_cli_config(tmp_path / "env.yaml", "http://from-env.test")
        monkeypatch.setenv("DEPICTIO_CLI_CONFIG_PATH", str(config))

        result = runner.invoke(app, ["validate", str(valid_yaml_file)])

        assert result.exit_code == 0, result.output
        assert online.call_args.args[1] == "http://from-env.test"

    @pytest.mark.parametrize("flag", ["--server", "--config", "-c"])
    def test_a_named_configuration_that_is_missing_is_an_error(
        self, valid_yaml_file: Path, tmp_path: Path, online, flag
    ):
        result = runner.invoke(app, ["validate", str(valid_yaml_file), flag, str(tmp_path / "no")])

        assert result.exit_code == 1
        assert "configuration file not found" in result.output
        online.assert_not_called()

    def test_an_unreachable_default_server_does_not_fail_the_file(
        self, valid_yaml_file: Path, isolated_home: Path, online
    ):
        _write_cli_config(isolated_home / ".depictio" / "CLI.yaml", "http://down.test")
        online.return_value = [
            {"component_id": "-", "field": "-", "message": "Server unreachable: refused"}
        ]

        result = runner.invoke(app, ["validate", str(valid_yaml_file)])

        assert result.exit_code == 0, result.output
        assert "unreachable" in result.output

    def test_an_unreachable_named_server_fails(self, valid_yaml_file: Path, tmp_path: Path, online):
        config = _write_cli_config(tmp_path / "named.yaml", "http://down.test")
        online.return_value = [
            {"component_id": "-", "field": "-", "message": "Server unreachable: refused"}
        ]

        result = runner.invoke(app, ["validate", str(valid_yaml_file), "--server", str(config)])

        assert result.exit_code == 1

    def test_offline_skips_even_a_named_server(self, valid_yaml_file: Path, tmp_path: Path, online):
        config = _write_cli_config(tmp_path / "named.yaml", "http://named.test")

        result = runner.invoke(
            app, ["validate", str(valid_yaml_file), "--server", str(config), "--offline"]
        )

        assert result.exit_code == 0, result.output
        online.assert_not_called()


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
        """--overwrite without a configuration should fail (same as normal import)."""
        result = runner.invoke(
            app,
            ["import", str(valid_yaml_file), "--overwrite"],
        )
        assert result.exit_code == 1
        assert "configuration file not found" in result.output

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
