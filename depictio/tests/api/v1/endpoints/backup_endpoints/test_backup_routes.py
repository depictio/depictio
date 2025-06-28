from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.backup_endpoints.routes import backup_endpoint_router
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User


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
    def test_create_backup_success(
        self,
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
    def test_create_backup_with_temporary_users_exclusion(
        self,
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

        try:
            response = client.post("/backup/create", json={"include_s3_data": False})

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["excluded_documents"] >= 1  # At least the temp user

        finally:
            # Clean up the override
            client.app.dependency_overrides.clear()

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
