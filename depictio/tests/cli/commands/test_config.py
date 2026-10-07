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
                args.extend(["--server", cli_config])

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

        def test_success(self, command, cli_config_path, base_patches):
            """Test successful execution"""
            with patch("depictio.cli.cli.commands.config.load_depictio_config") as mock_load_config:
                result = command.run("show", cli_config=cli_config_path)
            assert result.exit_code == 0, result.output
            mock_load_config.assert_called_once()

        def test_error(self, command, cli_config_path, base_patches):
            """A configuration it cannot show is a failure, for scripts too."""
            with patch(
                "depictio.cli.cli.commands.config.load_depictio_config",
                side_effect=Exception("Test error"),
            ):
                result = command.run("show", cli_config=cli_config_path)
                assert result.exit_code == 1

        def test_with_project_name(self, runner, cli_config_path, base_patches):
            """`config show --project-name` also fetches server metadata."""
            mock_project_metadata = MagicMock()
            mock_project_metadata.json.return_value = {"name": "test-project"}

            with (
                patch("depictio.cli.cli.commands.config.load_depictio_config"),
                patch(
                    "depictio.cli.cli.commands.config.api_get_project_from_name",
                    return_value=mock_project_metadata,
                ),
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


class TestServerOption:
    """--server picks the configuration; the hidden --CLI-config-path still does."""

    runner = CliRunner()

    @pytest.fixture
    def check_calls(self):
        """`config check` with every server call mocked; yields the api_login mock."""
        with (
            patch(
                "depictio.cli.cli.commands.config.api_login",
                return_value={"success": True, "email": "a@b.co"},
            ) as login,
            patch("depictio.cli.cli.commands.config.load_depictio_config"),
            patch("depictio.cli.cli.commands.config.S3_storage_checks"),
        ):
            yield login

    @pytest.mark.parametrize("command", ["show", "check", "sync"])
    def test_help_shows_server_not_the_legacy_option(self, command):
        result = self.runner.invoke(app, [command, "--help"])

        assert result.exit_code == 0
        assert "--server" in result.output
        assert "--CLI-config-path" not in result.output

    @pytest.mark.parametrize("flag", ["--server", "--CLI-config-path"])
    def test_check_uses_the_named_configuration(self, check_calls, flag):
        result = self.runner.invoke(app, ["check", flag, "/etc/depictio/CLI.yaml"])

        assert result.exit_code == 0, result.output
        check_calls.assert_called_once_with("/etc/depictio/CLI.yaml")

    def test_check_without_server_keeps_the_default(self, check_calls):
        """Left at the default, so load_depictio_config still applies the env var."""
        result = self.runner.invoke(app, ["check"])

        assert result.exit_code == 0, result.output
        check_calls.assert_called_once_with("~/.depictio/CLI.yaml")

    def test_check_server_local_is_the_local_stack_configuration(
        self, check_calls, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
        local = tmp_path / "cli" / "admin_config.yaml"
        local.parent.mkdir()
        local.write_text("{}")

        result = self.runner.invoke(app, ["check", "--server", "local"])

        assert result.exit_code == 0, result.output
        check_calls.assert_called_once_with(str(local))

    def test_sync_passes_the_server_to_validation(self):
        with patch(
            "depictio.cli.cli.commands.config.validate_project_config_and_check_S3_storage",
            return_value=(MagicMock(), {"success": False}),
        ) as validate:
            result = self.runner.invoke(
                app, ["sync", "--server", "s.yaml", "--project-config-path", "p.yaml"]
            )

        assert result.exit_code == 0, result.output
        validate.assert_called_once_with(CLI_config_path="s.yaml", project_config_path="p.yaml")

    def test_show_server_and_legacy_together_are_refused(self):
        result = self.runner.invoke(
            app, ["show", "--server", "a.yaml", "--CLI-config-path", "b.yaml"]
        )

        assert result.exit_code == 2
        assert "not both" in result.output


def test_show_prints_a_real_configuration_with_its_secrets_masked(tmp_path):
    """Not mocked: SecretStr fields made `config show` fail on every real configuration."""
    import yaml

    config = tmp_path / "CLI.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "api_base_url": "http://127.0.0.1:8058",
                "user": {
                    "email": "admin@example.com",
                    "is_admin": True,
                    "id": "507f1f77bcf86cd799439011",
                    "token": {
                        "user_id": "507f1f77bcf86cd799439011",
                        "access_token": "access-token-example",
                        "refresh_token": "refresh-token-example",
                        "token_type": "bearer",
                        "token_lifetime": "short-lived",
                        "expire_datetime": "2099-12-31T23:59:59",
                        "refresh_expire_datetime": "2099-12-31T23:59:59",
                        "name": "test_token",
                        "created_at": "2025-06-30T18:00:00",
                        "logged_in": False,
                    },
                },
                "s3_storage": {
                    "service_name": "localhost",
                    "service_port": 9000,
                    "external_host": "localhost",
                    "external_port": 9000,
                    "external_protocol": "http",
                    "root_user": "depictio",
                    "root_password": "s3-password-example",
                    "bucket": "depictio-bucket",
                },
            }
        )
    )

    result = CliRunner().invoke(app, ["show", "--server", str(config)])

    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:8058" in result.output
    for secret in ("s3-password-example", "access-token-example", "refresh-token-example"):
        assert secret not in result.output
    assert "**********" in result.output
