"""
Tests for CLI commands in the config module.
"""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands.config import app


class TestConfigCommands:
    """Test suite for Typer app commands in config.py"""

    @pytest.fixture
    def runner(self):
        """CliRunner fixture for testing Typer commands"""
        return CliRunner()

    @pytest.fixture
    def mock_config(self):
        """Mock CLI configuration"""
        mock_config = MagicMock()
        mock_config.s3 = MagicMock()
        return mock_config

    @pytest.fixture
    def cli_config_path(self):
        """Return a test CLI config path"""
        return "test-cli-config.yaml"

    @pytest.fixture
    def project_config_path(self):
        """Return a test project config path"""
        return "test-project-config.yaml"

    @pytest.fixture
    def base_patches(self):
        """Common patches needed by most tests"""
        patches = [
            patch("depictio.cli.cli.utils.rich_utils.rich_print_command_usage"),
            patch("depictio.cli.cli.utils.rich_utils.rich_print_checked_statement"),
            patch("depictio.cli.cli.utils.rich_utils.rich_print_json"),
            patch(
                "os.path.expanduser", return_value="test-cli-config.yaml"
            ),  # Mock any path expansion
            patch("os.path.exists", return_value=True),  # Pretend all files exist
        ]
        mocks = [p.start() for p in patches]
        yield mocks
        for p in patches:
            p.stop()

    @pytest.fixture
    def mock_load_config(self, mock_config):
        """Patch the load_depictio_config function"""
        with patch(
            "depictio.cli.cli.utils.common.load_depictio_config",
            return_value=mock_config,
        ) as mock_func:
            yield mock_func

    class CommandHelper:
        """Helper class for running commands with standard arguments"""

        def __init__(self, runner):
            self.runner = runner

        def run(self, command, cli_config=None, project_config=None, update=False):
            """Run a command with standard arguments"""
            args = [command]

            if cli_config:
                args.extend(["--CLI-config-path", cli_config])

            if project_config:
                args.extend(["--project-config-path", project_config])

            if update:
                args.append("--update")

            return self.runner.invoke(app, args)

    @pytest.fixture
    def command(self, runner):
        """Command helper fixture"""
        return self.CommandHelper(runner)

    @pytest.fixture
    def positive_validation_response(self):
        """Fixture for a successful validation response"""
        project_config = MagicMock()
        return (MagicMock(), {"success": True, "project_config": project_config})

    @pytest.fixture
    def negative_validation_response(self):
        """Fixture for a failed validation response"""
        return (MagicMock(), {"success": False})

    # Test classes for each command

    class TestShow:
        """Tests for the `config show` command"""

        def test_success(self, command, cli_config_path, mock_load_config, base_patches):
            """Test successful execution"""
            result = command.run("show", cli_config=cli_config_path)
            assert result.exit_code == 0
            # mock_load_config.assert_called_once()

        def test_error(self, command, cli_config_path, base_patches):
            """Test error handling"""
            with patch(
                "depictio.cli.cli.utils.common.load_depictio_config",
                side_effect=Exception("Test error"),
            ):
                result = command.run("show", cli_config=cli_config_path)
                assert result.exit_code == 0

        def test_with_project_name(self, runner, cli_config_path, mock_load_config, base_patches):
            """`config show --project-name` also fetches server metadata."""
            mock_project_metadata = MagicMock()
            mock_project_metadata.json.return_value = {"name": "test-project"}

            with patch(
                "depictio.cli.cli.commands.config.api_get_project_from_name",
                return_value=mock_project_metadata,
            ):
                result = runner.invoke(
                    app,
                    [
                        "show",
                        "--CLI-config-path",
                        cli_config_path,
                        "--project-name",
                        "test-project",
                    ],
                )
                assert result.exit_code == 0

    class TestCheck:
        """Tests for the `config check` command (environment doctor)"""

        def test_success(self, command, cli_config_path, mock_load_config, base_patches):
            """Test successful execution"""
            with patch("depictio.cli.cli.commands.config.S3_storage_checks"):
                result = command.run("check", cli_config=cli_config_path)
                assert result.exit_code == 0

        def test_error(self, command, cli_config_path, base_patches):
            """Test error handling"""
            with patch(
                "depictio.cli.cli.utils.common.load_depictio_config",
                side_effect=Exception("Test error"),
            ):
                result = command.run("check", cli_config=cli_config_path)
                assert result.exit_code == 0

    class TestSync:
        """Tests for the `config sync` command"""

        def test_invalid_config(self, command, cli_config_path, base_patches):
            """A failed validation reports the error and exits cleanly."""
            with patch(
                "depictio.cli.cli.commands.config.validate_project_config_and_check_S3_storage",
                return_value=(MagicMock(), {"success": False}),
            ):
                result = command.run("sync", cli_config=cli_config_path)
                assert result.exit_code == 0

        @pytest.fixture
        def validated(self):
            """Patch validation so only the sync verdict decides the outcome."""
            return patch(
                "depictio.cli.cli.commands.config.validate_project_config_and_check_S3_storage",
                return_value=(
                    MagicMock(),
                    {"success": True, "project_config": {"name": "Existing project"}},
                ),
            )

        def test_existing_project_without_update_is_reported(
            self, runner, cli_config_path, validated
        ):
            """The sync returns a verdict rather than raising, so a caller that
            ignored it made refusing to touch an existing project look like
            success."""
            with (
                validated,
                patch(
                    "depictio.cli.cli.commands.config.convert_model_to_dict",
                    return_value={"name": "Existing project"},
                ),
                patch(
                    "depictio.cli.cli.commands.config.api_sync_project_config_to_server",
                    return_value={"action": "exists"},
                ),
            ):
                result = runner.invoke(app, ["sync", "--CLI-config-path", cli_config_path])
            assert result.exit_code == 2
            normalized = " ".join(result.output.split())
            assert "already exists on this server" in normalized
            assert "--update" in normalized

        def test_created_project_succeeds_quietly(self, runner, cli_config_path, validated):
            with (
                validated,
                patch(
                    "depictio.cli.cli.commands.config.convert_model_to_dict",
                    return_value={"name": "New project"},
                ),
                patch(
                    "depictio.cli.cli.commands.config.api_sync_project_config_to_server",
                    return_value={"action": "created"},
                ),
            ):
                result = runner.invoke(app, ["sync", "--CLI-config-path", cli_config_path])
            assert result.exit_code == 0
            assert "already exists" not in result.output
