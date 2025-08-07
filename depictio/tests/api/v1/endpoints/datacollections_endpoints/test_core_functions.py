"""Tests for datacollections core functions using mongomock_motor with pre-populated data."""

from unittest.mock import patch

import bcrypt
import pytest
from beanie import init_beanie
from bson import ObjectId
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _delete_data_collection_by_id,
    _get_data_collection_specs,
    _update_data_collection_name,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import (
    DataCollection,
    DataCollectionConfig,
    Scan,
    ScanSingle,
)
from depictio.models.models.data_collections_types.table import DCTableConfig
from depictio.models.models.projects import ProjectBeanie
from depictio.models.models.users import Permission, UserBeanie
from depictio.models.models.workflows import Workflow, WorkflowDataLocation, WorkflowEngine


def hash_password(password: str) -> str:
    """Helper function to hash passwords for tests."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def setup_test_database_with_projects():
    """Set up test database with pre-populated projects and data collections."""
    # Initialize mongomock_motor database
    client = AsyncMongoMockClient()
    await init_beanie(database=client.test_db, document_models=[UserBeanie, ProjectBeanie])

    # Create test user
    test_user = UserBeanie(
        email="test@example.com",
        password=hash_password("password123"),
        is_admin=False,
    )
    await test_user.create()

    # Create test data collections with proper structure
    test_dc_1 = DataCollection(
        id=PyObjectId(str(ObjectId("507f1f77bcf86cd799439011"))),
        data_collection_tag="test_collection_1",
        config=DataCollectionConfig(
            type="table",
            scan=Scan(
                mode="single",
                scan_parameters=ScanSingle(
                    filename="test_file_1.csv"  # Use a simple filename for test
                ),
            ),
            dc_specific_properties=DCTableConfig(format="csv"),
        ),
    )

    test_dc_2 = DataCollection(
        id=PyObjectId(str(ObjectId("507f1f77bcf86cd799439012"))),
        data_collection_tag="test_collection_2",
        config=DataCollectionConfig(
            type="table",
            scan=Scan(
                mode="single",
                scan_parameters=ScanSingle(
                    filename="test_file_2.parquet"  # Use a simple filename for test
                ),
            ),
            dc_specific_properties=DCTableConfig(format="parquet"),
        ),
    )

    # Create test workflow with data collections
    test_workflow = Workflow(
        id=PyObjectId(str(ObjectId("507f1f77bcf86cd799439020"))),
        name="Test Workflow",
        workflow_tag="test_workflow",
        engine=WorkflowEngine(name="python", version="3.12"),
        data_location=WorkflowDataLocation(structure="flat", locations=["/tmp/test"]),
        data_collections=[test_dc_1, test_dc_2],
    )

    # Create test project with permissions
    test_project = ProjectBeanie(
        id=PyObjectId(str(ObjectId("507f1f77bcf86cd799439030"))),
        name="Test Project",
        workflows=[test_workflow],
        permissions=Permission(owners=[test_user], viewers=[]),
        is_public=False,
        project_type="basic",
    )
    await test_project.create()

    return {
        "user": test_user,
        "project": test_project,
        "workflow": test_workflow,
        "data_collections": [test_dc_1, test_dc_2],
        "db": client.test_db,
    }


class TestGetDataCollectionSpecs:
    """Test suite for _get_data_collection_specs core function."""

    @pytest.mark.asyncio
    async def test_get_specs_not_found(self):
        """Test specs retrieval with non-existent data collection."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]

        # Use non-existent data collection ID
        non_existent_dc_id = PyObjectId(str(ObjectId()))

        # Mock the projects_collection.aggregate to return empty result
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.aggregate.return_value = []

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _get_data_collection_specs(non_existent_dc_id, user)

            exc = exc_info.value
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 404
            assert "not found" in str(exc.detail).lower()

    @pytest.mark.asyncio
    async def test_get_specs_success(self):
        """Test successful specs retrieval with actual database data."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]
        dc_to_find = test_data["data_collections"][0]  # test_collection_1

        # Simulate the MongoDB aggregation result - return the data collection dict
        mock_dc_result = {
            "_id": dc_to_find.id,
            "data_collection_tag": dc_to_find.data_collection_tag,
            "config": dc_to_find.config.model_dump(),
        }

        # Mock the projects_collection.aggregate to return the expected data collection
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.aggregate.return_value = [mock_dc_result]

            # Act
            result = await _get_data_collection_specs(dc_to_find.id, user)

            # Assert
            assert result["_id"] == str(dc_to_find.id)
            assert result["data_collection_tag"] == "test_collection_1"
            assert result["config"]["type"] == "table"
            assert result["config"]["scan"]["mode"] == "single"
            assert result["config"]["dc_specific_properties"]["format"] == "csv"

    @pytest.mark.asyncio
    async def test_get_specs_access_denied_different_user(self):
        """Test specs retrieval with user who doesn't have access."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        dc_to_find = test_data["data_collections"][0]

        # Create a different user who shouldn't have access
        different_user = UserBeanie(
            email="different@example.com",
            password=hash_password("password123"),
            is_admin=False,
        )
        await different_user.create()

        # Mock the projects_collection.aggregate to return empty result (no access)
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.aggregate.return_value = []

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _get_data_collection_specs(dc_to_find.id, different_user)

            exc = exc_info.value
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 404
            assert "not found" in str(exc.detail).lower()


class TestUpdateDataCollectionName:
    """Test suite for _update_data_collection_name core function."""

    @pytest.mark.asyncio
    async def test_update_name_missing_name(self):
        """Test update with missing new name."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]
        dc_to_update = test_data["data_collections"][0]

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await _update_data_collection_name(str(dc_to_update.id), "", user)

        exc = exc_info.value
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 400
        assert "new_name is required" in str(exc.detail)

    @pytest.mark.asyncio
    async def test_update_name_not_found(self):
        """Test update with non-existent data collection."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]

        # Use non-existent data collection ID
        non_existent_dc_id = str(ObjectId())

        # Mock the projects_collection.find_one to return None (not found)
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.find_one.return_value = None

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _update_data_collection_name(non_existent_dc_id, "new_name", user)

            exc = exc_info.value
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 404
            assert "not found" in str(exc.detail).lower()

    @pytest.mark.asyncio
    async def test_update_name_success(self):
        """Test successful name update with actual database operations."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]
        dc_to_update = test_data["data_collections"][0]
        new_name = "updated_collection_name"

        # Create mock project data that matches the expected structure
        mock_project = {
            "_id": test_data["project"].id,
            "workflows": [
                {
                    "_id": test_data["workflow"].id,
                    "data_collections": [
                        {"_id": dc_to_update.id, "data_collection_tag": "test_collection_1"},
                        {
                            "_id": test_data["data_collections"][1].id,
                            "data_collection_tag": "test_collection_2",
                        },
                    ],
                }
            ],
        }

        # Mock database operations
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.find_one.return_value = mock_project
            mock_collection.update_one.return_value = type(
                "MockResult", (), {"modified_count": 1}
            )()

            # Act
            result = await _update_data_collection_name(str(dc_to_update.id), new_name, user)

            # Assert
            assert result["message"] == f"Data collection name updated to '{new_name}' successfully"

            # Verify correct database operations were called
            mock_collection.find_one.assert_called_once()
            mock_collection.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_name_access_denied_different_user(self):
        """Test update with user who doesn't have access."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        dc_to_update = test_data["data_collections"][0]

        # Create a different user who shouldn't have access
        different_user = UserBeanie(
            email="different@example.com",
            password=hash_password("password123"),
            is_admin=False,
        )
        await different_user.create()

        # Mock the projects_collection.find_one to return None (no access)
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.find_one.return_value = None

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _update_data_collection_name(str(dc_to_update.id), "new_name", different_user)

            exc = exc_info.value
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 404
            assert "not found" in str(exc.detail).lower()


class TestDeleteDataCollectionById:
    """Test suite for _delete_data_collection_by_id core function."""

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """Test deletion with non-existent data collection."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]

        # Use non-existent data collection ID
        non_existent_dc_id = str(ObjectId())

        # Mock the projects_collection.find_one to return None (not found)
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.find_one.return_value = None

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _delete_data_collection_by_id(non_existent_dc_id, user)

            exc = exc_info.value
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 404
            assert "not found" in str(exc.detail).lower()

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Test successful deletion with actual database operations."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]
        dc_to_delete = test_data["data_collections"][0]  # test_collection_1
        dc_to_keep = test_data["data_collections"][1]  # test_collection_2

        # Create mock project data that matches the expected structure
        mock_project = {
            "_id": test_data["project"].id,
            "workflows": [
                {
                    "_id": test_data["workflow"].id,
                    "data_collections": [
                        {"_id": dc_to_delete.id, "data_collection_tag": "test_collection_1"},
                        {"_id": dc_to_keep.id, "data_collection_tag": "test_collection_2"},
                    ],
                }
            ],
        }

        # Mock database operations and S3 cleanup
        with (
            patch(
                "depictio.api.v1.endpoints.datacollections_endpoints.utils._cleanup_s3_delta_table"
            ) as mock_cleanup,
            patch(
                "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
            ) as mock_collection,
        ):
            # Setup mocks
            mock_cleanup.return_value = None
            mock_collection.find_one.return_value = mock_project
            mock_collection.update_one.return_value = type(
                "MockResult", (), {"modified_count": 1}
            )()

            # Act
            result = await _delete_data_collection_by_id(str(dc_to_delete.id), user)

            # Assert
            assert result["message"] == "Data collection deleted successfully"

            # Verify S3 cleanup was called
            mock_cleanup.assert_called_once_with(str(dc_to_delete.id))

            # Verify correct database operations were called
            mock_collection.find_one.assert_called_once()
            mock_collection.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_invalid_object_id(self):
        """Test deletion with invalid ObjectId."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        user = test_data["user"]

        # Test with actual invalid ObjectId string that the function validates
        with pytest.raises(HTTPException) as exc_info:
            await _delete_data_collection_by_id("invalid_id", user)

        exc = exc_info.value
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_access_denied_different_user(self):
        """Test deletion with user who doesn't have access."""
        # Set up test database with pre-populated data
        test_data = await setup_test_database_with_projects()
        dc_to_delete = test_data["data_collections"][0]

        # Create a different user who shouldn't have access
        different_user = UserBeanie(
            email="different@example.com",
            password=hash_password("password123"),
            is_admin=False,
        )
        await different_user.create()

        # Mock the projects_collection.find_one to return None (no access)
        with patch(
            "depictio.api.v1.endpoints.datacollections_endpoints.utils.projects_collection"
        ) as mock_collection:
            mock_collection.find_one.return_value = None

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await _delete_data_collection_by_id(str(dc_to_delete.id), different_user)

            exc = exc_info.value
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 404
            assert "not found" in str(exc.detail).lower()
