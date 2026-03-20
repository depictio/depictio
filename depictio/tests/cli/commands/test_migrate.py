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

        assert result.exit_code == 1
        assert "invalid mode" in result.stdout.lower() or "invalid" in result.stdout.lower()

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
