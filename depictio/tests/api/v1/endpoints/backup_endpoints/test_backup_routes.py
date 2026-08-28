import json
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.backup_endpoints.routes import (
    _compute_file_sha256,
    backup_endpoint_router,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User


def _write_backup(backup_dir, backup_id, data, with_sidecar=True, metadata=None):
    """Write a backup file (and optional .sha256 sidecar) the way /create does."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    filename = f"depictio_backup_{backup_id}.json"
    backup_path = backup_dir / filename
    payload = {
        "backup_metadata": metadata
        or {
            "timestamp": "2025-01-01T00:00:00",
            "created_by": "admin@example.com",
            "depictio_version": "1.5.1",
            "total_documents": sum(len(docs) for docs in data.values()),
            "excluded_documents": 0,
            "collections": list(data.keys()),
            "backup_id": backup_id,
        },
        "data": data,
    }
    backup_path.write_text(json.dumps(payload, indent=2, default=str))
    if with_sidecar:
        digest = _compute_file_sha256(str(backup_path))
        (backup_dir / f"{filename}.sha256").write_text(f"{digest}  {filename}\n")
    return backup_path


@pytest.fixture
def backup_dir(tmp_path):
    """Point the routes module's settings at a temporary backup directory."""
    mock_settings = MagicMock()
    mock_settings.backup.backup_path = str(tmp_path / "backups")
    with patch("depictio.api.v1.endpoints.backup_endpoints.routes.settings", mock_settings):
        yield tmp_path / "backups"


@pytest.fixture
def as_admin(client, admin_user):
    """Authenticate the test client as an admin for the duration of a test."""
    from depictio.api.v1.endpoints.backup_endpoints.routes import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: admin_user
    yield client
    client.app.dependency_overrides.clear()


@pytest.fixture
def as_regular_user(client, regular_user):
    """Authenticate the test client as a non-admin for the duration of a test."""
    from depictio.api.v1.endpoints.backup_endpoints.routes import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: regular_user
    yield client
    client.app.dependency_overrides.clear()


@pytest.fixture
def client():
    """Create test client for backup endpoints."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(backup_endpoint_router, prefix="/backup")
    return TestClient(app)


@pytest.fixture
def admin_user():
    """Create mock admin user."""
    return User(
        id=PyObjectId("507f1f77bcf86cd799439011"),
        email="admin@example.com",
        password="$2b$12$example.hashed.password.string",
        is_admin=True,
        is_active=True,
        is_verified=True,
    )


@pytest.fixture
def regular_user():
    """Create mock regular user."""
    return User(
        id=PyObjectId("507f1f77bcf86cd799439012"),
        email="user@example.com",
        password="$2b$12$example.hashed.password.string",
        is_admin=False,
        is_active=True,
        is_verified=True,
    )


class TestBackupEndpoints:
    """Test backup API endpoints."""

    def test_create_backup_access_denied_for_non_admin(self, client, regular_user):
        """Test that non-admin users cannot create backups."""
        from depictio.api.v1.endpoints.backup_endpoints.routes import get_current_user

        # Override the dependency
        def override_get_current_user():
            return regular_user

        client.app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            response = client.post("/backup/create", json={"include_s3_data": False})

            assert response.status_code == 403
            assert "Only administrators can create backups" in response.json()["detail"]
        finally:
            # Clean up the override
            client.app.dependency_overrides.clear()

    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.users_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.projects_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.dashboards_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.data_collections_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.workflows_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.files_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.deltatables_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.runs_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.groups_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.instance_settings_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.branding_assets_collection")
    def test_create_backup_success(
        self,
        mock_branding_assets,
        mock_instance_settings,
        mock_groups,
        mock_runs,
        mock_deltatables,
        mock_files,
        mock_workflows,
        mock_data_collections,
        mock_dashboards,
        mock_projects,
        mock_users,
        client,
        admin_user,
    ):
        """Test successful backup creation by admin user."""
        from depictio.api.v1.endpoints.backup_endpoints.routes import get_current_user

        # Override the dependency
        def override_get_current_user():
            return admin_user

        client.app.dependency_overrides[get_current_user] = override_get_current_user

        # Mock database collections to return empty results
        mock_users.find.return_value = []
        mock_users.count_documents.return_value = 0
        mock_projects.find.return_value = []
        mock_dashboards.find.return_value = []
        mock_data_collections.find.return_value = []
        mock_workflows.find.return_value = []
        mock_files.find.return_value = []
        mock_deltatables.find.return_value = []
        mock_runs.find.return_value = []
        mock_groups.find.return_value = []
        mock_instance_settings.find.return_value = []
        mock_branding_assets.find.return_value = []

        try:
            response = client.post("/backup/create", json={"include_s3_data": False})

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert "collections_backed_up" in response_data
            assert "backup_id" in response_data
            assert response_data["total_documents"] >= 0

        finally:
            # Clean up the override
            client.app.dependency_overrides.clear()

    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.users_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.projects_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.dashboards_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.data_collections_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.workflows_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.files_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.deltatables_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.runs_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.groups_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.instance_settings_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.branding_assets_collection")
    def test_create_backup_with_temporary_users_exclusion(
        self,
        mock_branding_assets,
        mock_instance_settings,
        mock_groups,
        mock_runs,
        mock_deltatables,
        mock_files,
        mock_workflows,
        mock_data_collections,
        mock_dashboards,
        mock_projects,
        mock_users,
        client,
        admin_user,
    ):
        """Test that temporary users and their resources are excluded from backup."""
        from depictio.api.v1.endpoints.backup_endpoints.routes import get_current_user

        # Override the dependency
        def override_get_current_user():
            return admin_user

        client.app.dependency_overrides[get_current_user] = override_get_current_user

        # Configure all mocked collections to return empty iterables
        mock_users.find.return_value = [{"_id": "temp_user_123", "is_temporary": True}]
        mock_users.count_documents.return_value = 0
        mock_projects.find.return_value = []
        mock_projects.count_documents.return_value = 0
        mock_dashboards.find.return_value = []
        mock_dashboards.count_documents.return_value = 1  # Simulate excluded dashboard
        mock_data_collections.find.return_value = []
        mock_data_collections.count_documents.return_value = 0
        mock_workflows.find.return_value = []
        mock_workflows.count_documents.return_value = 0
        mock_files.find.return_value = []
        mock_files.count_documents.return_value = 0
        mock_deltatables.find.return_value = []
        mock_deltatables.count_documents.return_value = 0
        mock_runs.find.return_value = []
        mock_runs.count_documents.return_value = 0
        mock_groups.find.return_value = []
        mock_groups.count_documents.return_value = 0
        mock_instance_settings.find.return_value = []
        mock_instance_settings.count_documents.return_value = 0
        mock_branding_assets.find.return_value = []
        mock_branding_assets.count_documents.return_value = 0

        try:
            response = client.post("/backup/create", json={"include_s3_data": False})

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["excluded_documents"] >= 1  # At least the temp user

        finally:
            # Clean up the override
            client.app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.users_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.projects_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.dashboards_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.data_collections_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.workflows_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.files_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.deltatables_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.runs_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.groups_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.instance_settings_collection")
    @patch("depictio.api.v1.endpoints.backup_endpoints.routes.branding_assets_collection")
    async def test_backup_metadata_records_real_version(
        self,
        mock_branding_assets,
        mock_instance_settings,
        mock_groups,
        mock_runs,
        mock_deltatables,
        mock_files,
        mock_workflows,
        mock_data_collections,
        mock_dashboards,
        mock_projects,
        mock_users,
        admin_user,
    ):
        """Backup metadata must record the actual project version, not a stale literal.

        Guards against regression of the previously hardcoded ``"0.1.0"`` value,
        which made backups impossible to reason about across releases.
        """
        from depictio.api.v1.endpoints.backup_endpoints.routes import _create_mongodb_backup
        from depictio.version import get_version

        for mock_collection in (
            mock_users,
            mock_projects,
            mock_dashboards,
            mock_data_collections,
            mock_workflows,
            mock_files,
            mock_deltatables,
            mock_runs,
            mock_groups,
            mock_instance_settings,
            mock_branding_assets,
        ):
            mock_collection.find.return_value = []
            mock_collection.count_documents.return_value = 0

        backup = await _create_mongodb_backup(admin_user)

        recorded_version = backup["backup_metadata"]["depictio_version"]
        assert recorded_version, "depictio_version must not be empty"
        assert recorded_version != "0.1.0", (
            "depictio_version must reflect the real project version, not the old hardcoded literal"
        )
        assert recorded_version == get_version()

    def test_backup_request_model(self):
        """Test BackupRequest model validation."""
        from depictio.api.v1.endpoints.backup_endpoints.routes import BackupRequest

        # Valid request with defaults
        request = BackupRequest()
        assert not request.include_s3_data
        assert request.s3_backup_prefix == "backup"
        assert not request.dry_run

        # Valid request with custom values
        request = BackupRequest(include_s3_data=True, s3_backup_prefix="test_backup", dry_run=True)
        assert request.include_s3_data
        assert request.s3_backup_prefix == "test_backup"
        assert request.dry_run

    def test_backup_response_model(self):
        """Test BackupResponse model validation."""
        from depictio.api.v1.endpoints.backup_endpoints.routes import BackupResponse

        # Valid response
        response = BackupResponse(
            success=True,
            message="Backup created successfully",
            backup_id="backup_123456",
            total_documents=100,
            excluded_documents=5,
            collections_backed_up=["users", "projects"],
            timestamp="2024-01-01T12:00:00",
            filename="backup_123456.json",
        )

        assert response.success is True
        assert response.backup_id == "backup_123456"
        assert response.total_documents == 100
        assert response.excluded_documents == 5
        assert len(response.collections_backed_up) == 2
        assert response.filename == "backup_123456.json"


EMPTY_DATA = {
    "users": [],
    "projects": [],
    "dashboards": [],
    "data_collections": [],
    "workflows": [],
    "files": [],
    "deltatables": [],
    "runs": [],
    "groups": [],
}


class TestBackupDownload:
    """Tests for GET /backup/download/{backup_id}."""

    def test_download_success(self, as_admin, backup_dir):
        _write_backup(backup_dir, "20250101_010101", EMPTY_DATA)

        response = as_admin.get("/backup/download/20250101_010101")

        assert response.status_code == 200
        assert "depictio_backup_20250101_010101.json" in response.headers["content-disposition"]
        payload = response.json()
        assert payload["backup_metadata"]["backup_id"] == "20250101_010101"
        assert set(payload["data"].keys()) == set(EMPTY_DATA.keys())

    def test_download_denied_for_non_admin(self, as_regular_user, backup_dir):
        _write_backup(backup_dir, "20250101_010101", EMPTY_DATA)

        response = as_regular_user.get("/backup/download/20250101_010101")

        assert response.status_code == 403

    def test_download_rejects_malformed_id(self, as_admin, backup_dir):
        response = as_admin.get("/backup/download/not-a-backup-id")

        assert response.status_code == 422

    def test_download_missing_backup(self, as_admin, backup_dir):
        response = as_admin.get("/backup/download/20250101_010101")

        assert response.status_code == 404


class TestBackupUpload:
    """Tests for POST /backup/upload."""

    def _upload(self, client, body: bytes):
        return client.post(
            "/backup/upload", files={"file": ("backup.json", body, "application/json")}
        )

    def test_upload_success_makes_first_class_backup(self, as_admin, backup_dir):
        body = json.dumps(
            {
                "backup_metadata": {
                    "backup_id": "20200101_000000",
                    "created_by": "admin@example.com",
                    "depictio_version": "1.5.0",
                    "total_documents": 0,
                    "collections": list(EMPTY_DATA.keys()),
                },
                "data": EMPTY_DATA,
            }
        ).encode()

        response = self._upload(as_admin, body)

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert re.fullmatch(r"\d{8}_\d{6}", result["backup_id"])
        assert result["validation"]["valid"] is True

        # The file and its checksum sidecar exist on disk under the new id.
        stored = backup_dir / f"depictio_backup_{result['backup_id']}.json"
        assert stored.exists()
        assert (backup_dir / f"{stored.name}.sha256").exists()
        # The embedded metadata id was rewritten to the server-side id.
        assert json.loads(stored.read_text())["backup_metadata"]["backup_id"] == result["backup_id"]

        # The uploaded backup is listed like any server-created one.
        listing = as_admin.get("/backup/list").json()
        entry = next(b for b in listing["backups"] if b["backup_id"] == result["backup_id"])
        assert entry["has_checksum"] is True
        assert entry["depictio_version"] == "1.5.0"

    def test_upload_rejects_invalid_json(self, as_admin, backup_dir):
        response = self._upload(as_admin, b"this is not json")

        assert response.status_code == 400
        assert "not valid JSON" in response.json()["detail"]

    def test_upload_rejects_missing_data_section(self, as_admin, backup_dir):
        response = self._upload(as_admin, json.dumps({"backup_metadata": {}}).encode())

        assert response.status_code == 400
        assert "missing 'data' section" in response.json()["detail"]

    def test_upload_rejects_oversized_file(self, as_admin, backup_dir):
        with patch("depictio.api.v1.endpoints.backup_endpoints.routes.MAX_BACKUP_UPLOAD_BYTES", 10):
            response = self._upload(as_admin, json.dumps({"data": EMPTY_DATA}).encode())

        assert response.status_code == 413

    def test_upload_denied_for_non_admin(self, as_regular_user, backup_dir):
        response = self._upload(as_regular_user, json.dumps({"data": {}}).encode())

        assert response.status_code == 403

    def test_upload_reports_validation_errors_but_stores_file(self, as_admin, backup_dir):
        data = dict(EMPTY_DATA)
        data["users"] = [{"email": "not-an-email"}]
        response = self._upload(as_admin, json.dumps({"data": data}).encode())

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True  # stored anyway; restore gate protects the DB
        assert result["validation"]["valid"] is False
        assert result["validation"]["invalid_documents"] == 1
        assert (backup_dir / f"depictio_backup_{result['backup_id']}.json").exists()


class TestBackupListMetadata:
    """Tests for the enriched /backup/list entries."""

    def test_list_surfaces_version_and_checksum(self, as_admin, backup_dir):
        _write_backup(backup_dir, "20250101_010101", EMPTY_DATA)
        _write_backup(backup_dir, "20250102_010101", EMPTY_DATA, with_sidecar=False)

        listing = as_admin.get("/backup/list").json()

        assert listing["success"] is True
        by_id = {b["backup_id"]: b for b in listing["backups"]}
        assert by_id["20250101_010101"]["has_checksum"] is True
        assert by_id["20250101_010101"]["depictio_version"] == "1.5.1"
        assert by_id["20250102_010101"]["has_checksum"] is False


@patch("depictio.api.v1.endpoints.backup_endpoints.routes.users_collection")
@patch("depictio.api.v1.endpoints.backup_endpoints.routes.projects_collection")
class TestRestoreValidationGate:
    """Tests for the pre-restore Pydantic validation gate."""

    INVALID_USERS_DATA = {
        "users": [{"email": "not-an-email"}],
        "projects": [],
    }

    def test_restore_refuses_invalid_backup(self, mock_projects, mock_users, as_admin, backup_dir):
        _write_backup(backup_dir, "20250101_010101", self.INVALID_USERS_DATA)

        response = as_admin.post(
            "/backup/restore", json={"backup_id": "20250101_010101", "dry_run": False}
        )

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is False
        assert "failed model validation" in result["message"]
        assert result["errors"]  # per-document errors surfaced
        mock_users.delete_many.assert_not_called()
        mock_projects.delete_many.assert_not_called()

    def test_skip_validation_overrides_gate(self, mock_projects, mock_users, as_admin, backup_dir):
        data = {
            "users": [{"_id": "507f1f77bcf86cd799439011", "email": "not-an-email"}],
        }
        _write_backup(backup_dir, "20250101_010101", data)

        response = as_admin.post(
            "/backup/restore",
            json={"backup_id": "20250101_010101", "dry_run": False, "skip_validation": True},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_users.delete_many.assert_called_once()
        mock_users.insert_many.assert_called_once()

    def test_gate_scoped_to_selected_collections(
        self, mock_projects, mock_users, as_admin, backup_dir
    ):
        _write_backup(backup_dir, "20250101_010101", self.INVALID_USERS_DATA)

        response = as_admin.post(
            "/backup/restore",
            json={
                "backup_id": "20250101_010101",
                "dry_run": False,
                "collections": ["projects"],
            },
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_projects.delete_many.assert_called_once()
        mock_users.delete_many.assert_not_called()

    def test_dry_run_skips_validation(self, mock_projects, mock_users, as_admin, backup_dir):
        _write_backup(backup_dir, "20250101_010101", self.INVALID_USERS_DATA)

        with patch(
            "depictio.cli.cli.utils.backup_validation.validate_backup_file"
        ) as mock_validate:
            response = as_admin.post(
                "/backup/restore", json={"backup_id": "20250101_010101", "dry_run": True}
            )

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert "DRY RUN" in result["message"]
        mock_validate.assert_not_called()
        mock_users.delete_many.assert_not_called()

    def test_restore_without_sidecar_requires_allow_unverified(
        self, mock_projects, mock_users, as_admin, backup_dir
    ):
        _write_backup(backup_dir, "20250101_010101", {"projects": []}, with_sidecar=False)

        refused = as_admin.post(
            "/backup/restore", json={"backup_id": "20250101_010101", "dry_run": False}
        )
        assert refused.status_code == 409

        allowed = as_admin.post(
            "/backup/restore",
            json={
                "backup_id": "20250101_010101",
                "dry_run": False,
                "allow_unverified": True,
            },
        )
        assert allowed.status_code == 200
        assert allowed.json()["success"] is True
