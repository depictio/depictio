import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest
import yaml
from typer.testing import CliRunner

from depictio.cli.cli.commands.backup import app
from depictio.cli.cli.commands.dev import app as dev_app


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_cli_config():
    """Mock CLI configuration."""
    return {
        "user": {
            "email": "test@example.com",
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


class TestBackupCLI:
    """Test backup CLI commands."""

    @patch("depictio.cli.cli.commands.backup.load_depictio_config")
    @patch("depictio.cli.cli.commands.backup.api_login")
    def test_create_backup_access_denied_for_non_admin(
        self, mock_api_login, mock_load_config, runner
    ):
        """Test that non-admin users cannot create backups via CLI."""
        mock_load_config.return_value = Mock()
        mock_api_login.return_value = {"success": True, "is_admin": False}

        result = runner.invoke(app, ["create"])

        assert result.exit_code == 1
        assert "Access denied: Only administrators can create backups" in result.stdout

    @patch("depictio.cli.cli.utils.api_calls.api_create_backup")
    @patch("depictio.cli.cli.commands.backup.load_depictio_config")
    @patch("depictio.cli.cli.commands.backup.api_login")
    def test_create_backup_success(
        self, mock_api_login, mock_load_config, mock_api_create_backup, runner
    ):
        """Test successful backup creation via CLI."""
        mock_load_config.return_value = Mock()
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_create_backup.return_value = {
            "success": True,
            "backup_id": "20250627_123456",
            "filename": "depictio_backup_20250627_123456.json",
            "timestamp": "2025-06-27T12:34:56.789",
            "total_documents": 100,
            "excluded_documents": 5,
            "collections_backed_up": ["users", "projects"],
        }

        result = runner.invoke(app, ["create"])

        assert result.exit_code == 0
        assert "Backup created successfully" in result.stdout

    @patch("depictio.cli.cli.commands.backup.api_login")
    def test_create_backup_dry_run(self, mock_api_login, runner, mock_cli_config):
        """Test dry run backup creation."""
        mock_api_login.return_value = {"success": True, "is_admin": True}

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(app, ["create", "--CLI-config-path", config_file, "--dry-run"])

            assert result.exit_code == 0
            assert "DRY RUN" in result.stdout

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.api_calls.api_list_backups")
    def test_list_backup_files_empty_directory(
        self, mock_api_list_backups, mock_api_login, runner, mock_cli_config
    ):
        """Test listing backup files in empty directory."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_list_backups.return_value = {"success": True, "backups": []}

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(app, ["list", "--CLI-config-path", config_file])

            assert result.exit_code == 0
            assert "No backup files found" in result.stdout or "backups" in result.stdout

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.api_calls.api_list_backups")
    def test_list_backup_files_with_backups(
        self, mock_api_list_backups, mock_api_login, runner, mock_cli_config
    ):
        """Test listing backup files."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_list_backups.return_value = {
            "success": True,
            "backups": [
                {"filename": "depictio_backup_20240101_120000.json", "size": 1024},
                {"filename": "depictio_backup_20240102_130000.json", "size": 2048},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            # Create mock backup files
            backup_files = [
                "depictio_backup_20240101_120000.json",
                "depictio_backup_20240102_130000.json",
                "other_file.json",  # Should be ignored
            ]

            for filename in backup_files[:2]:  # Only create actual backup files
                filepath = os.path.join(tmp_dir, filename)
                with open(filepath, "w") as f:
                    json.dump({"test": "data"}, f)

            result = runner.invoke(app, ["list", "--CLI-config-path", config_file])

            assert result.exit_code == 0
            assert "backup" in result.stdout.lower()

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.api_calls.api_list_backups")
    def test_list_backup_files_nonexistent_directory(
        self, mock_api_list_backups, mock_api_login, runner, mock_cli_config
    ):
        """Test listing backup files in nonexistent directory."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_list_backups.return_value = {"success": True, "backups": []}

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(app, ["list", "--CLI-config-path", config_file])

            # Should succeed even if no backups found
            assert result.exit_code == 0

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.api_calls.api_validate_backup")
    def test_validate_backup_success(
        self, mock_api_validate_backup, mock_api_login, runner, mock_cli_config
    ):
        """Test successful backup validation."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_validate_backup.return_value = {
            "success": True,
            "valid": True,
            "total_documents": 100,
            "valid_documents": 95,
            "invalid_documents": 5,
            "collections_validated": {"users": {"total": 50, "valid": 48, "invalid": 2}},
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            # Create backup file
            backup_path = os.path.join(tmp_dir, "test_backup.json")
            with open(backup_path, "w") as f:
                json.dump({"test": "data"}, f)

            result = runner.invoke(
                app, ["validate", "--CLI-config-path", config_file, "20250627_123456"]
            )

            assert result.exit_code == 0

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.api_calls.api_validate_backup")
    def test_validate_backup_failure(
        self, mock_api_validate_backup, mock_api_login, runner, mock_cli_config
    ):
        """Test backup validation failure."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_validate_backup.return_value = {
            "success": True,
            "valid": False,
            "errors": ["Invalid document format in users collection"],
            "total_documents": 100,
            "valid_documents": 90,
            "invalid_documents": 10,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(
                app, ["validate", "--CLI-config-path", config_file, "20250627_123456"]
            )

            assert result.exit_code == 1
            assert "Backup file validation failed" in result.stdout

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.api_calls.api_validate_backup")
    def test_validate_backup_nonexistent_file(
        self, mock_api_validate_backup, mock_api_login, runner, mock_cli_config
    ):
        """Test validation of nonexistent backup file."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_validate_backup.return_value = {
            "success": False,
            "message": "Backup file does not exist",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(
                app, ["validate", "--CLI-config-path", config_file, "nonexistent_backup"]
            )

            assert result.exit_code == 1
            assert "Validation failed" in result.stdout

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.backup_validation.check_backup_collections_coverage")
    def test_check_coverage_perfect_coverage(
        self, mock_detect, mock_api_login, runner, mock_cli_config
    ):
        """Test coverage check with perfect coverage."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_detect.return_value = {
            "valid": True,
            "expected_collections": ["users", "projects", "dashboards"],
            "collections_with_validators": ["users", "projects", "dashboards"],
            "collections_in_settings": ["users", "projects", "dashboards"],
            "missing_from_expected": [],
            "missing_validators": [],
            "errors": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(
                dev_app, ["backup", "check-coverage", "--CLI-config-path", config_file]
            )

        assert result.exit_code == 0
        assert "All expected collections have backup coverage" in result.stdout

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.backup_validation.check_backup_collections_coverage")
    def test_check_coverage_incomplete_coverage(
        self, mock_detect, mock_api_login, runner, mock_cli_config
    ):
        """Test coverage check with incomplete coverage."""
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_detect.return_value = {
            "valid": False,
            "expected_collections": ["users", "projects", "dashboards"],
            "collections_with_validators": ["users", "projects", "dashboards"],
            "collections_in_settings": ["users", "projects", "dashboards", "new_collection"],
            "missing_from_expected": ["new_collection"],
            "missing_validators": [],
            "errors": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create temporary config file
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(
                dev_app, ["backup", "check-coverage", "--CLI-config-path", config_file]
            )

        assert result.exit_code == 1
        assert "Missing backup coverage detected" in result.stdout
        assert "New collections found without backup coverage" in result.stdout
        assert "new_collection" in result.stdout

    @patch("depictio.cli.cli.commands.backup.api_login")
    @patch("depictio.cli.cli.utils.backup_validation.check_backup_collections_coverage")
    def test_check_coverage_error_handling(
        self, mock_detect, mock_api_login, runner, mock_cli_config
    ):
        """Test coverage check error handling.

        Uses a real config file like its siblings: without one the command now
        stops at "configuration file not found", so the test would pass on the
        strength of the missing file rather than the reported coverage error.
        """
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_detect.return_value = {
            "error": "Could not import settings",
            "valid": False,
            "errors": ["Unable to check collection coverage - settings not available"],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = os.path.join(tmp_dir, "config.yaml")
            with open(config_file, "w") as f:
                yaml.dump(mock_cli_config, f)

            result = runner.invoke(
                dev_app, ["backup", "check-coverage", "--CLI-config-path", config_file]
            )

        assert result.exit_code == 1
        assert "Coverage check failed" in result.stdout
        assert "Could not import settings" in result.stdout


class TestRestoreCLI:
    """Test the backup restore CLI command."""

    @patch("depictio.cli.cli.commands.backup.load_depictio_config")
    @patch("depictio.cli.cli.commands.backup.api_login")
    def test_restore_declined_confirmation_exits_cleanly(
        self, mock_api_login, mock_load_config, runner
    ):
        """Declining the confirmation prompt must exit 0, not report a failure."""
        mock_load_config.return_value = Mock()
        mock_api_login.return_value = {"success": True, "is_admin": True}

        result = runner.invoke(app, ["restore", "20250101_010101"], input="n\n")

        assert result.exit_code == 0
        assert "Restore cancelled" in result.stdout
        assert "Restore operation failed" not in result.stdout

    @patch("depictio.cli.cli.utils.api_calls.api_restore_backup")
    @patch("depictio.cli.cli.commands.backup.load_depictio_config")
    @patch("depictio.cli.cli.commands.backup.api_login")
    def test_restore_forwards_safety_flags(
        self, mock_api_login, mock_load_config, mock_api_restore, runner
    ):
        """--allow-unverified and --skip-validation are forwarded to the API call."""
        mock_load_config.return_value = Mock()
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_restore.return_value = {
            "success": True,
            "message": "Restored 0 documents from backup",
            "restored_collections": {},
            "total_restored": 0,
            "errors": [],
        }

        result = runner.invoke(
            app,
            [
                "restore",
                "20250101_010101",
                "--force",
                "--allow-unverified",
                "--skip-validation",
            ],
        )

        assert result.exit_code == 0
        assert "Restore completed successfully" in result.stdout
        _args, kwargs = mock_api_restore.call_args
        assert kwargs["allow_unverified"] is True
        assert kwargs["skip_validation"] is True

    @patch("depictio.cli.cli.utils.api_calls.api_restore_backup")
    @patch("depictio.cli.cli.commands.backup.load_depictio_config")
    @patch("depictio.cli.cli.commands.backup.api_login")
    def test_restore_refused_by_validation_gate(
        self, mock_api_login, mock_load_config, mock_api_restore, runner
    ):
        """A server-side validation refusal surfaces the message and errors."""
        mock_load_config.return_value = Mock()
        mock_api_login.return_value = {"success": True, "is_admin": True}
        mock_api_restore.return_value = {
            "success": False,
            "message": "Backup failed model validation: 2 invalid document(s) ...",
            "restored_collections": {},
            "total_restored": 0,
            "errors": ["Document 0 in users: invalid email"],
        }

        result = runner.invoke(app, ["restore", "20250101_010101", "--force"])

        assert result.exit_code == 1
        assert "failed model validation" in result.stdout
        assert "Document 0 in users" in result.stdout
