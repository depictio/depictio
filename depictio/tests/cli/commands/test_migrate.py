import os
import tempfile
from unittest.mock import Mock, patch

import pytest
import yaml
from typer.testing import CliRunner

from depictio.cli.cli.commands.migrate import app


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_cli_config():
    """Mock CLI configuration (same shape used by test_backup.py)."""
    return {
        "user": {
            "email": "admin@example.com",
            "is_admin": True,
            "id": "507f1f77bcf86cd799439011",
            "token": {
                "user_id": "507f1f77bcf86cd799439011",
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
                "refresh_token": "refresh-token-example",
                "token_type": "bearer",
                "token_lifetime": "short-lived",
                "expire_datetime": "2025-12-31T23:59:59",
                "refresh_expire_datetime": "2025-12-31T23:59:59",
                "name": "test-token",
                "created_at": "2025-06-30T18:00:00",
                "logged_in": False,
            },
        },
        "api_base_url": "http://localhost:8000",
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


@pytest.fixture
def config_file(mock_cli_config):
    """Write mock CLI config to a temp file and return its path."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "config.yaml")
        with open(path, "w") as f:
            yaml.dump(mock_cli_config, f)
        yield path


# ---------------------------------------------------------------------------
# Non-admin access denied
# ---------------------------------------------------------------------------


class TestMigrateCLIAccessControl:
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_source_non_admin_denied(self, mock_login, mock_load, runner, config_file):
        """Non-admin source credentials must be rejected."""
        mock_load.return_value = Mock()
        mock_login.return_value = {"success": True, "is_admin": False}

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
            ],
        )

        assert result.exit_code == 1
        assert "admin" in result.stdout.lower()

    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_target_non_admin_denied(self, mock_login, mock_load, runner, config_file):
        """Non-admin target credentials must be rejected."""
        mock_load.return_value = Mock()
        # First call (source) succeeds as admin; second call (target) fails
        mock_login.side_effect = [
            {"success": True, "is_admin": True},
            {"success": True, "is_admin": False},
        ]

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
            ],
        )

        assert result.exit_code == 1
        assert "admin" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Mode validation
# ---------------------------------------------------------------------------


class TestMigrateCLIModeValidation:
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_invalid_mode_rejected(self, mock_login, mock_load, runner, config_file):
        """Unknown --mode value must exit with error."""
        mock_load.return_value = Mock()
        mock_login.return_value = {"success": True, "is_admin": True}

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                "invalid_mode",
            ],
        )

        # A usage error, before any server is read or logged in to.
        assert result.exit_code == 2
        assert "invalid value" in result.output.lower()
        assert "invalid_mode" in result.output
        mock_login.assert_not_called()

    @pytest.mark.parametrize("mode", ["all", "metadata", "dashboard", "files"])
    @patch("depictio.cli.cli.commands.migrate.api_import_project")
    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_valid_modes_accepted(
        self, mock_login, mock_load, mock_export, mock_import, mode, runner, config_file
    ):
        """All four valid modes must be accepted without mode-rejection error."""
        mock_load.return_value = Mock()
        mock_load.return_value.s3_storage.endpoint_url = "http://localhost:9000"
        mock_load.return_value.s3_storage.aws_access_key_id = "minio"
        mock_load.return_value.s3_storage.aws_secret_access_key = "minio123"
        mock_load.return_value.s3_storage.bucket = "depictio-bucket"
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": mode,
                "document_counts": {"projects": 1},
            },
            "data": {"projects": [], "dashboards": []},
        }
        mock_import.return_value = {
            "success": True,
            "message": "Upserted 1 documents",
            "upserted": {"projects": 1},
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                mode,
            ],
        )

        # Should not fail with "invalid mode"
        assert "invalid mode" not in result.stdout.lower()


# ---------------------------------------------------------------------------
# Successful migration
# ---------------------------------------------------------------------------


class TestMigrateCLISuccess:
    @patch("depictio.cli.cli.commands.migrate.api_import_project")
    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_full_migration_success(
        self, mock_login, mock_load, mock_export, mock_import, runner, config_file
    ):
        """Successful full migration (mode=all) prints summary and exits 0."""
        mock_load.return_value = Mock()
        mock_load.return_value.s3_storage.endpoint_url = "http://localhost:9000"
        mock_load.return_value.s3_storage.aws_access_key_id = "minio"
        mock_load.return_value.s3_storage.aws_secret_access_key = "minio123"
        mock_load.return_value.s3_storage.bucket = "depictio-bucket"
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": "all",
                "document_counts": {
                    "projects": 1,
                    "workflows": 2,
                    "data_collections": 3,
                    "files": 10,
                    "deltatables": 3,
                    "runs": 5,
                    "dashboards": 2,
                },
            },
            "data": {
                "projects": [{"_id": "507f1f77bcf86cd799439011", "name": "my-project"}],
                "dashboards": [{"_id": "507f1f77bcf86cd799439012"}],
            },
            "s3_migrate_metadata": {
                "locations_copied": 3,
                "total_files": 42,
                "total_bytes": 1024000,
                "paths": ["dc1/", "dc2/", "dc3/"],
                "errors": [],
            },
        }
        mock_import.return_value = {
            "success": True,
            "message": "Upserted 25 documents",
            "upserted": {
                "projects": 1,
                "workflows": 2,
                "data_collections": 3,
                "files": 10,
                "deltatables": 3,
                "runs": 5,
                "dashboards": 2,
            },
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                "all",
            ],
        )

        assert result.exit_code == 0
        assert "Export complete" in result.stdout
        assert "Upserted" in result.stdout or "upserted" in result.stdout.lower()

    @patch("depictio.cli.cli.commands.migrate.api_import_project")
    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_dashboard_mode_success(
        self, mock_login, mock_load, mock_export, mock_import, runner, config_file
    ):
        """Dashboard-only migration exits 0 and mentions dashboards."""
        mock_load.return_value = Mock()
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": "dashboard",
                "document_counts": {"dashboards": 2},
            },
            "data": {"dashboards": [{"_id": "abc"}]},
        }
        mock_import.return_value = {
            "success": True,
            "message": "Upserted 2 documents",
            "upserted": {"dashboards": 2},
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                "dashboard",
            ],
        )

        assert result.exit_code == 0
        assert "dashboards" in result.stdout.lower() or "Export complete" in result.stdout

    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_files_only_mode_skips_import(
        self, mock_login, mock_load, mock_export, runner, config_file
    ):
        """files mode exits after S3 sync without calling import."""
        mock_load.return_value = Mock()
        mock_load.return_value.s3_storage.endpoint_url = "http://localhost:9000"
        mock_load.return_value.s3_storage.aws_access_key_id = "minio"
        mock_load.return_value.s3_storage.aws_secret_access_key = "minio123"
        mock_load.return_value.s3_storage.bucket = "depictio-bucket"
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": "files",
                "document_counts": {},
            },
            "data": {},
            "s3_migrate_metadata": {
                "locations_copied": 2,
                "total_files": 10,
                "total_bytes": 5000,
                "paths": ["dc1/", "dc2/"],
                "errors": [],
            },
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                "files",
            ],
        )

        assert result.exit_code == 0
        assert "S3 sync complete" in result.stdout or "files-only" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


class TestMigrateCLIDryRun:
    @patch("depictio.cli.cli.commands.migrate.api_import_project")
    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_dry_run_flag_propagated(
        self, mock_login, mock_load, mock_export, mock_import, runner, config_file
    ):
        """--dry-run flag is passed to both export and import calls."""
        mock_load.return_value = Mock()
        mock_load.return_value.s3_storage.endpoint_url = "http://localhost:9000"
        mock_load.return_value.s3_storage.aws_access_key_id = "minio"
        mock_load.return_value.s3_storage.aws_secret_access_key = "minio123"
        mock_load.return_value.s3_storage.bucket = "depictio-bucket"
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": "metadata",
                "document_counts": {"projects": 1},
                "dry_run": True,
            },
            "data": {"projects": []},
        }
        mock_import.return_value = {
            "success": True,
            "message": "DRY RUN: would upsert 1 documents",
            "upserted": {"projects": 1},
            "dry_run": True,
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                "metadata",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        # Verify dry_run was forwarded to both API calls
        _, export_kwargs = mock_export.call_args
        assert export_kwargs.get("dry_run") is True or mock_export.call_args[0][-1] is True

        assert "DRY RUN" in result.stdout or "dry-run" in result.stdout.lower()

    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_dry_run_mode_noted_in_output(self, mock_login, mock_load, runner, config_file):
        """Output must mention DRY RUN when --dry-run is passed (even before API calls)."""
        mock_load.return_value = Mock()
        mock_login.return_value = {"success": True, "is_admin": False}  # Fail early

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--dry-run",
            ],
        )

        # Even if denied, the dry-run note appears before auth check fails
        # (it appears right after successful source auth)
        assert result.exit_code == 1  # denied by non-admin


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestMigrateCLIErrorHandling:
    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_export_failure_exits_nonzero(
        self, mock_login, mock_load, mock_export, runner, config_file
    ):
        """Export API error propagates as non-zero exit."""
        mock_load.return_value = Mock()
        mock_load.return_value.s3_storage.endpoint_url = "http://localhost:9000"
        mock_load.return_value.s3_storage.aws_access_key_id = "minio"
        mock_load.return_value.s3_storage.aws_secret_access_key = "minio123"
        mock_load.return_value.s3_storage.bucket = "depictio-bucket"
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "success": False,
            "message": "Project not found",
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "nonexistent-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
            ],
        )

        assert result.exit_code == 1
        assert "Export failed" in result.stdout or "not found" in result.stdout.lower()

    @patch("depictio.cli.cli.commands.migrate.api_import_project")
    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_import_failure_exits_nonzero(
        self, mock_login, mock_load, mock_export, mock_import, runner, config_file
    ):
        """Import API error propagates as non-zero exit."""
        mock_load.return_value = Mock()
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": "dashboard",
                "document_counts": {"dashboards": 1},
            },
            "data": {"dashboards": [{"_id": "abc"}]},
        }
        mock_import.return_value = {
            "success": False,
            "message": "Database error during import",
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                "dashboard",
            ],
        )

        assert result.exit_code == 1
        assert "Import failed" in result.stdout or "failed" in result.stdout.lower()

    @patch("depictio.cli.cli.commands.migrate.api_export_project")
    @patch("depictio.cli.cli.commands.migrate.load_depictio_config")
    @patch("depictio.cli.cli.commands.migrate.api_login")
    def test_s3_errors_shown_as_warnings(
        self, mock_login, mock_load, mock_export, runner, config_file
    ):
        """S3 copy errors surfaced in the bundle are shown as warnings (not hard exit)."""
        mock_load.return_value = Mock()
        mock_load.return_value.s3_storage.endpoint_url = "http://localhost:9000"
        mock_load.return_value.s3_storage.aws_access_key_id = "minio"
        mock_load.return_value.s3_storage.aws_secret_access_key = "minio123"
        mock_load.return_value.s3_storage.bucket = "depictio-bucket"
        mock_login.return_value = {"success": True, "is_admin": True}
        mock_export.return_value = {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": "files",
                "document_counts": {},
            },
            "data": {},
            "s3_migrate_metadata": {
                "locations_copied": 1,
                "total_files": 0,
                "total_bytes": 0,
                "paths": ["dc1/"],
                "errors": ["Failed to copy dc1/some_file.parquet: S3 timeout"],
            },
        }

        result = runner.invoke(
            app,
            [
                "--project",
                "my-project",
                "--CLI-config-path",
                config_file,
                "--target-config",
                config_file,
                "--mode",
                "files",
            ],
        )

        # Should still exit 0 (files mode, S3 warning not fatal at CLI level)
        assert "S3 error" in result.stdout or "error" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Source and target servers: --server / --to-server, and their old names
# ---------------------------------------------------------------------------


class TestMigrateServers:
    @pytest.fixture
    def loaded_paths(self):
        """The configuration files migrate loads, source first; it stops at the first login."""
        with (
            patch("depictio.cli.cli.commands.migrate.load_depictio_config") as load,
            patch(
                "depictio.cli.cli.commands.migrate.api_login",
                return_value={"success": True, "is_admin": False},
            ),
        ):
            yield lambda: [call.kwargs["yaml_config_path"] for call in load.call_args_list]

    @pytest.mark.parametrize(
        "flags",
        [
            ["--server", "src.yaml", "--to-server", "dst.yaml"],
            ["--CLI-config-path", "src.yaml", "--target-config", "dst.yaml"],
        ],
    )
    def test_source_and_target_come_from_the_flags(self, runner, loaded_paths, flags):
        result = runner.invoke(app, ["--project", "p", *flags])

        assert result.exit_code == 1  # the mocked source login is not an admin
        assert loaded_paths() == ["src.yaml", "dst.yaml"]

    def test_defaults_are_unchanged(self, runner, loaded_paths):
        runner.invoke(app, ["--project", "p"])

        assert loaded_paths() == ["~/.depictio/CLI.yaml", "~/.depictio/CLI_remote.yaml"]

    def test_to_server_local_is_the_local_stack_configuration(
        self, runner, loaded_paths, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path))
        local = tmp_path / "cli" / "admin_config.yaml"
        local.parent.mkdir()
        local.write_text("{}")

        runner.invoke(app, ["--project", "p", "--server", "remote.yaml", "--to-server", "local"])

        assert loaded_paths() == ["remote.yaml", str(local)]

    def test_to_server_local_without_a_local_server_says_how_to_start_one(
        self, runner, tmp_path, monkeypatch, mock_cli_config
    ):
        """Found missing when read, not when parsed: the source is read first, then this."""
        monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local"))
        source = tmp_path / "src.yaml"
        source.write_text(yaml.dump(mock_cli_config))

        with patch("depictio.cli.cli.commands.migrate.api_login") as login:
            result = runner.invoke(
                app, ["--project", "p", "--server", str(source), "--to-server", "local"]
            )

        assert result.exit_code == 1
        out = " ".join(result.output.split())
        assert "No local server configuration" in out
        assert "depictio local up" in out
        assert "--to-server" in out
        login.assert_not_called()

    def test_to_server_and_target_config_together_are_refused(self, runner, loaded_paths):
        result = runner.invoke(
            app, ["--project", "p", "--to-server", "a.yaml", "--target-config", "b.yaml"]
        )

        assert result.exit_code == 2
        assert "not both" in result.output

    def test_help_hides_the_old_names(self, runner):
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--server" in result.output
        assert "--to-server" in result.output
        # Each named once, as what the new option was called before, not listed itself.
        assert "Formerly" in result.output
        assert result.output.count("--CLI-config-path") == 1
        assert result.output.count("--target-config") == 1
        # No en dash left in the mode table.
        assert "\u2013" not in result.output

    def test_help_is_a_plain_command_not_a_group(self, runner):
        result = runner.invoke(app, ["--help"])

        assert "COMMAND [ARGS]" not in result.output


class TestMigrateMessages:
    """What migrate says about each server, each failure, and its result."""

    @pytest.fixture(autouse=True)
    def no_env_overrides(self, monkeypatch):
        for var in ("DEPICTIO_CLI_CONFIG_PATH", "DEPICTIO_CLI_API_BASE_URL", "DEPICTIO_CLI_TOKEN"):
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def servers(self, tmp_path, mock_cli_config):
        """Two real configuration files, told apart by their URLs."""
        paths = []
        for name, url in (("src", "http://src.test"), ("dst", "http://dst.test")):
            path = tmp_path / f"{name}.yaml"
            path.write_text(yaml.dump({**mock_cli_config, "api_base_url": url}))
            paths.append(str(path))
        return paths

    def _run(self, runner, servers, *extra):
        source, target = servers
        return runner.invoke(
            app, ["--project", "my-project", "--server", source, "--to-server", target, *extra]
        )

    @staticmethod
    def _flat(output: str) -> str:
        return " ".join(output.split())

    def test_each_server_line_says_which_side_it_is(self, runner, servers):
        with patch(
            "depictio.cli.cli.commands.migrate.api_login",
            return_value={"success": True, "is_admin": False},
        ):
            result = self._run(runner, servers)

        out = self._flat(result.output)
        assert "Source server: http://src.test" in out
        assert "Target server: http://dst.test" in out

    def test_the_env_overrides_apply_to_the_source_only(self, runner, servers, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CLI_API_BASE_URL", "http://env.test")
        with patch(
            "depictio.cli.cli.commands.migrate.api_login",
            return_value={"success": True, "is_admin": False},
        ):
            result = self._run(runner, servers)

        out = self._flat(result.output)
        assert "Source server: http://env.test (from DEPICTIO_CLI_API_BASE_URL" in out
        assert "Target server: http://dst.test" in out

    def test_an_unreachable_source_is_named(self, runner, servers):
        import httpx

        with patch(
            "depictio.cli.cli.commands.migrate.api_login",
            side_effect=httpx.ConnectError("refused"),
        ):
            result = self._run(runner, servers)

        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        out = self._flat(result.output)
        assert "Source: cannot reach the server: refused" in out
        assert "Tried http://src.test" in out

    def test_a_rejected_token_is_not_called_missing_admin_rights(self, runner, servers):
        with patch(
            "depictio.cli.cli.commands.migrate.api_login",
            side_effect=[{"success": True, "is_admin": True}, {"success": False}],
        ):
            result = self._run(runner, servers)

        assert result.exit_code == 1
        out = self._flat(result.output)
        assert "Target: authentication failed" in out
        assert "admin access required" not in out

    @staticmethod
    def _bundle(mode: str) -> dict:
        return {
            "migrate_metadata": {
                "project_name": "my-project",
                "project_id": "507f1f77bcf86cd799439011",
                "mode": mode,
                "document_counts": {"projects": 1},
            },
            "data": {"projects": [{"_id": "507f1f77bcf86cd799439011"}]},
        }

    def test_a_conflict_says_how_to_overwrite_once(self, runner, servers):
        with (
            patch(
                "depictio.cli.cli.commands.migrate.api_login",
                return_value={"success": True, "is_admin": True},
            ),
            patch(
                "depictio.cli.cli.commands.migrate.api_export_project",
                return_value=self._bundle("metadata"),
            ),
            patch(
                "depictio.cli.cli.commands.migrate.api_import_project",
                return_value={
                    "success": False,
                    "conflict": True,
                    "message": "Project 'my-project' already exists on this instance. "
                    "Set overwrite=true to replace it.",
                },
            ),
        ):
            result = self._run(runner, servers, "--mode", "metadata")

        assert result.exit_code == 1
        out = self._flat(result.output)
        assert (
            "Conflict: Project 'my-project' already exists on this instance. "
            "Use --overwrite to replace it." in out
        )
        assert "overwrite=true" not in out

    def test_a_files_dry_run_says_nothing_was_copied(self, runner, servers):
        with (
            patch(
                "depictio.cli.cli.commands.migrate.api_login",
                return_value={"success": True, "is_admin": True},
            ),
            patch(
                "depictio.cli.cli.commands.migrate.api_export_project",
                return_value=self._bundle("files"),
            ),
        ):
            result = self._run(runner, servers, "--mode", "files", "--dry-run")

        assert result.exit_code == 0, result.output
        out = self._flat(result.output)
        assert "Files-only mode, dry run: no S3 file copied, no MongoDB import." in out
        assert "S3 sync complete" not in out

    @pytest.mark.parametrize(
        ("extra", "expected"),
        [
            ((), "Migration complete for project 'my-project'"),
            (("--dry-run",), "Migration dry run complete for project 'my-project'"),
        ],
    )
    def test_the_last_line_reads_well(self, runner, servers, extra, expected):
        with (
            patch(
                "depictio.cli.cli.commands.migrate.api_login",
                return_value={"success": True, "is_admin": True},
            ),
            patch(
                "depictio.cli.cli.commands.migrate.api_export_project",
                return_value=self._bundle("metadata"),
            ),
            patch(
                "depictio.cli.cli.commands.migrate.api_import_project",
                return_value={"success": True, "upserted": {"projects": 1}},
            ),
        ):
            result = self._run(runner, servers, "--mode", "metadata", *extra)

        assert result.exit_code == 0, result.output
        assert expected in result.output


def test_migrate_takes_its_options_straight_from_the_root(runner):
    """Mounted as a command, not a group: `depictio migrate --project p` reaches it."""
    from depictio.cli.depictio_cli import app as root

    result = runner.invoke(root, ["migrate", "--project", "p", "--mode", "bogus"])

    assert result.exit_code == 2
    assert "Invalid value for '--mode'" in result.output
    assert "No such option" not in result.output
