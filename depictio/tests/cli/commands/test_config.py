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
            mock_project_metadata.status_code = 200
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

        @pytest.fixture
        def login(self):
            with (
                patch(
                    "depictio.cli.cli.commands.config.api_login",
                    return_value={"success": True, "email": "a@b.co"},
                ) as login,
                patch("depictio.cli.cli.commands.config.load_depictio_config"),
            ):
                yield login

        def test_success(self, command, cli_config_path, login):
            """Test successful execution"""
            with patch("depictio.cli.cli.commands.config.S3_storage_checks"):
                result = command.run("check", cli_config=cli_config_path)
            assert result.exit_code == 0, result.output

        def test_a_failed_s3_check_fails_the_command(self, command, cli_config_path, login):
            """It used to report the failure and exit 0, so a script gating on it passed."""
            with patch(
                "depictio.cli.cli.commands.config.S3_storage_checks",
                side_effect=Exception("bucket missing"),
            ):
                result = command.run("check", cli_config=cli_config_path)
            assert result.exit_code == 1
            assert "bucket missing" in result.output

        def test_a_rejected_token_fails_the_command_after_the_s3_check(
            self, command, cli_config_path, login
        ):
            login.return_value = {"success": False}
            with patch("depictio.cli.cli.commands.config.S3_storage_checks") as s3:
                result = command.run("check", cli_config=cli_config_path)
            assert result.exit_code == 1
            assert "Invalid credentials or token expired" in result.output
            s3.assert_called_once()

        def test_an_unreachable_server_fails_the_command(self, command, cli_config_path, login):
            import httpx

            login.side_effect = httpx.ConnectError("[Errno 61] Connection refused")
            with patch("depictio.cli.cli.commands.config.S3_storage_checks"):
                result = command.run("check", cli_config=cli_config_path)
            assert result.exit_code == 1
            assert "Cannot reach the Depictio server: [Errno 61] Connection refused" in (
                " ".join(result.output.split())
            )

        def test_error(self, command, cli_config_path, base_patches):
            """An unexpected error is reported, and fails the command."""
            with patch(
                "depictio.cli.cli.commands.config.api_login",
                side_effect=Exception("Test error"),
            ):
                result = command.run("check", cli_config=cli_config_path)
                assert result.exit_code == 1

    class TestSync:
        """Tests for the `config sync` command"""

        def test_invalid_config(self, command, cli_config_path, base_patches):
            """A failed validation reports the error and fails the command."""
            with patch(
                "depictio.cli.cli.commands.config.validate_project_config_and_check_S3_storage",
                return_value=(MagicMock(), {"success": False}),
            ):
                result = command.run("sync", cli_config=cli_config_path, project_config="p.yaml")
                assert result.exit_code == 1

        def test_no_project_config_path_says_it_is_needed(self, runner, cli_config_path):
            with patch(
                "depictio.cli.cli.commands.config.validate_project_config_and_check_S3_storage"
            ) as validate:
                result = runner.invoke(app, ["sync", "--server", cli_config_path])
            assert result.exit_code == 2
            assert "needs --project-config-path" in " ".join(result.output.split())
            validate.assert_not_called()

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
                result = runner.invoke(
                    app,
                    [
                        "sync",
                        "--CLI-config-path",
                        cli_config_path,
                        "--project-config-path",
                        "p.yaml",
                    ],
                )
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
                result = runner.invoke(
                    app,
                    [
                        "sync",
                        "--CLI-config-path",
                        cli_config_path,
                        "--project-config-path",
                        "p.yaml",
                    ],
                )
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
        # Named once, as what --server was called before, and not listed as an option.
        assert "Formerly" in result.output
        assert result.output.count("--CLI-config-path") == 1

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

        assert result.exit_code == 1, result.output  # the mocked validation fails
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


def _real_config(path, api_base_url="http://127.0.0.1:1"):
    """A loadable CLI configuration at ``path``: port 1, where nothing listens."""
    import yaml

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
    return str(path)


def _flat(result) -> str:
    return " ".join(result.output.split())


class TestFailuresAreReportedNotRaised:
    """Each failure is one clear line naming the file or the server, and exit code 1."""

    runner = CliRunner()

    @pytest.fixture(autouse=True)
    def isolated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
        for var in ("DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"):
            monkeypatch.delenv(var, raising=False)

    def test_check_without_any_configuration_says_so_once(self):
        result = self.runner.invoke(app, ["check"])

        assert result.exit_code == 1
        assert _flat(result).count("configuration file not found") == 1
        assert "Unable to access server" not in result.output
        assert "unreadable" not in result.output

    def test_check_with_a_broken_server_configuration(self, tmp_path):
        broken = tmp_path / "broken.yaml"
        broken.write_text("user: [unclosed\n")

        result = self.runner.invoke(app, ["check", "--server", str(broken)])

        assert result.exit_code == 1
        assert "is not valid YAML" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_check_project_against_an_unreachable_server(self, tmp_path):
        """It used to end on a 334-line traceback."""
        project = tmp_path / "project.yaml"
        project.write_text("name: p\n")
        config = _real_config(tmp_path / "CLI.yaml")

        result = self.runner.invoke(
            app, ["check", "--server", config, "--project-config-path", str(project)]
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "Cannot reach the Depictio server" in result.output
        assert "http://127.0.0.1:1" in _flat(result)

    def test_sync_with_a_missing_project_file(self, tmp_path):
        result = self.runner.invoke(
            app,
            ["sync", "--server", "nope.yaml", "--project-config-path", str(tmp_path / "p.yaml")],
        )

        assert result.exit_code == 1
        assert "Project configuration file not found" in _flat(result)

    def test_sync_with_a_broken_project_yaml(self, tmp_path):
        project = tmp_path / "project.yaml"
        project.write_text("name: [unclosed\n")
        config = _real_config(tmp_path / "CLI.yaml")

        with (
            patch(
                "depictio.cli.cli.utils.config.api_login",
                return_value={"success": True},
            ),
        ):
            result = self.runner.invoke(
                app, ["sync", "--server", config, "--project-config-path", str(project)]
            )

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert f"{project} is not valid YAML" in _flat(result)

    def test_show_a_project_the_server_does_not_have(self, tmp_path):
        config = _real_config(tmp_path / "CLI.yaml", "http://named.test")
        missing = MagicMock(status_code=404)
        missing.json.return_value = {"detail": "Project not found."}

        with patch(
            "depictio.cli.cli.commands.config.api_get_project_from_name", return_value=missing
        ):
            result = self.runner.invoke(
                app, ["show", "--server", config, "--project-name", "ghost"]
            )

        assert result.exit_code == 1
        assert "No project named 'ghost' on http://named.test" in _flat(result)
        assert "Server metadata" not in result.output

    def test_show_a_project_with_the_server_down(self, tmp_path):
        config = _real_config(tmp_path / "CLI.yaml")

        result = self.runner.invoke(app, ["show", "--server", config, "--project-name", "p"])

        assert result.exit_code == 1
        assert "Cannot reach the Depictio server" in result.output
        assert "Unable to load configuration" not in result.output
        assert "http://127.0.0.1:1" in _flat(result)

    def test_show_a_configuration_without_user(self, tmp_path):
        config = tmp_path / "CLI.yaml"
        config.write_text("api_base_url: http://x.test\n")

        result = self.runner.invoke(app, ["show", "--server", str(config)])

        assert result.exit_code == 1
        assert "has no 'user' key" in _flat(result)
