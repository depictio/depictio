import os
import yaml
from datetime import datetime
from typing import List, Optional
import pytest
from beanie import init_beanie, PydanticObjectId
from mongomock_motor import AsyncMongoMockClient
from fastapi import HTTPException
from unittest.mock import patch, MagicMock

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.endpoints.projects_endpoints.utils import (
    helper_create_project_beanie,
)
from depictio_models.models.projects import Project, ProjectBeanie
from depictio_models.models.users import UserBase, Group, Permission
from depictio_models.models.workflows import Workflow
from depictio_models.models.data_collections import DataCollection, DataCollectionConfig
from depictio_models.models.data_collections_types.table import DCTableConfig


@pytest.mark.asyncio
class TestProjectBeanie:
    @pytest.fixture
    def sample_user(self):
        """Create a sample user for testing."""
        user_id = PydanticObjectId()
        return UserBase(
            id=user_id,
            email="test@example.com",
            is_admin=True,
            # groups=[Group(id=PydanticObjectId(), name="admin_group")],
        )

    @pytest.fixture
    def get_test_config(self):
        """Function to load the YAML configuration file used in tests."""

        def _get_config(filepath):
            with open(filepath, "r") as file:
                return yaml.safe_load(file)

        return _get_config

    @pytest.fixture
    def test_yaml_path(self):
        """Path to the test YAML configuration file."""
        from depictio import BASE_PATH

        return os.path.join(
            BASE_PATH, "depictio", "api", "v1", "configs", "initial_project.yaml"
        )

    @pytest.fixture
    def yaml_config(self, get_test_config, test_yaml_path):
        """Load the YAML configuration from file."""
        return get_test_config(test_yaml_path)

    @pytest.fixture
    def sample_project_config(self, sample_user, test_yaml_path, yaml_config):
        """Create a sample project for testing using YAML config."""
        permission = Permission(owners=[sample_user])

        # Create a project using the YAML config
        project_config = yaml_config.copy()
        project_config["yaml_config_path"] = test_yaml_path
        project_config["permissions"] = permission

        # Add a test suffix to the name to avoid conflicts
        project_config["name"] = f"{project_config['name']} - Test"
        print(f"Sample project config: {project_config}")
        return project_config

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_success(self, sample_project_config):
        """Test successful project creation."""
        # Setup database at function level
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

        # Create the project object
        sample_project = ProjectBeanie(**sample_project_config)
        print(f"Sample project object: {format_pydantic(sample_project)}")

        # Act
        result = await helper_create_project_beanie(sample_project)

        # Assert
        assert result["success"] is True
        assert result["message"] == "Project created successfully."
        assert result["project"] == sample_project

        # Verify the project was saved to the database
        retrieved_project = await ProjectBeanie.find_one({"name": sample_project.name})
        assert retrieved_project is not None
        assert retrieved_project.name == sample_project.name
        assert len(retrieved_project.workflows) == 1
        assert (
            retrieved_project.workflows[0].name == retrieved_project.workflows[0].name
        )
        assert retrieved_project.is_public is False
        assert len(retrieved_project.permissions.owners) == 1
        assert retrieved_project.permissions.owners[0].email == "test@example.com"

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_duplicate(self, sample_project_config):
        """Test project creation with duplicate name."""
        # Setup database at function level
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

        # Create the project object
        sample_project = ProjectBeanie(**sample_project_config)

        # Arrange - First save the project
        await sample_project.insert()

        # Act & Assert - Attempt to create it again
        with pytest.raises(HTTPException) as exc_info:
            await helper_create_project_beanie(sample_project)

        # Check exception details
        assert exc_info.value.status_code == 400
        assert (
            f"Project with name '{sample_project.name}' already exists."
            in exc_info.value.detail
        )

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_with_data_management_platform_url(
        self, sample_project_config
    ):
        """Test project creation with a data management platform URL."""
        # Setup database at function level
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

        # Create the project object
        sample_project = ProjectBeanie(**sample_project_config)

        # Arrange
        sample_project.data_management_platform_project_url = (
            "https://platform.example.com/projects/123"
        )

        # Act
        result = await helper_create_project_beanie(sample_project)

        # Assert
        assert result["success"] is True
        retrieved_project = await ProjectBeanie.find_one({"name": sample_project.name})
        assert (
            retrieved_project.data_management_platform_project_url
            == "https://platform.example.com/projects/123"
        )

    # @pytest.mark.asyncio
    # async def test_helper_create_project_beanie_with_hash(self, sample_project_config):
    #     """Test project creation with a hash value. Check if hash is not saved. Must be updated using the hash function."""
    #     # Setup database at function level
    #     client = AsyncMongoMockClient()
    #     await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

    #     # Create the project object
    #     sample_project = ProjectBeanie(**sample_project_config)

    #     # Arrange
    #     sample_project.hash = "abc123hash456def"

    #     # Act
    #     result = await helper_create_project_beanie(sample_project)

    #     # Assert
    #     assert result["success"] is True
    #     retrieved_project = await ProjectBeanie.find_one({"name": sample_project.name})
    #     # assert retrieved_project.hash != "abc123hash456def"

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_public_project(
        self, sample_project_config
    ):
        """Test creation of a public project."""
        # Setup database at function level
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

        # Create the project object
        sample_project = ProjectBeanie(**sample_project_config)

        # Arrange
        sample_project.is_public = True

        # Act
        result = await helper_create_project_beanie(sample_project)

        # Assert
        assert result["success"] is True
        retrieved_project = await ProjectBeanie.find_one({"name": sample_project.name})
        assert retrieved_project.is_public is True

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_complex_permissions(
        self, sample_project_config, sample_user
    ):
        """Test creation of a project with complex permissions structure."""
        # Setup database at function level
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

        # Create the project object
        sample_project = ProjectBeanie(**sample_project_config)

        # Arrange
        editor_user = UserBase(
            id=PydanticObjectId(),
            email="editor@example.com",
            is_admin=False,
            # groups=[Group(id=PydanticObjectId(), name="editors_group")],
        )

        viewer_user = UserBase(
            id=PydanticObjectId(),
            email="viewer@example.com",
            is_admin=False,
            # groups=[Group(id=PydanticObjectId(), name="viewers_group")],
        )

        sample_project.permissions.editors = [editor_user]
        sample_project.permissions.viewers = [viewer_user]

        # Act
        result = await helper_create_project_beanie(sample_project)

        # Assert
        assert result["success"] is True
        retrieved_project = await ProjectBeanie.find_one({"name": sample_project.name})
        assert len(retrieved_project.permissions.owners) == 1
        assert len(retrieved_project.permissions.editors) == 1
        assert len(retrieved_project.permissions.viewers) == 1
        assert retrieved_project.permissions.editors[0].email == "editor@example.com"
        assert retrieved_project.permissions.viewers[0].email == "viewer@example.com"

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_multiple_workflows(
        self, sample_project_config
    ):
        """Test creation of a project with multiple workflows."""
        # Setup database at function level
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

        # Create the project object

        # # Arrange
        # # Create a modified copy of the sample workflow with a different name
        # workflow_data = sample_project_config["workflows"][0].copy()
        # workflow_data["name"] = "second_workflow"
        # workflow_data["data_location"]["structure"] = "sequencing-runs"
        # workflow_data["data_location"]["runs_regex"] = ".*_testrun"

        # workflow_data["data_collections"][0]["data_collection_tag"] = "another_table"
        # workflow_data["data_collections"][0]["description"] = "Another dataset"

        sample_project = ProjectBeanie(**sample_project_config)

        print(format_pydantic(sample_project))

        # sample_project_config["workflows"].append(workflow_data)
        print(f"Sample project config with multiple workflows: {sample_project_config}")
        # add a second workflow to the sample project config
        from depictio_models.models.data_collections import Scan, ScanSingle
        from depictio_models.models.workflows import (
            WorkflowEngine,
            WorkflowDataLocation,
        )

        # First create the engine
        workflow_engine = {"name": "python"}

        # Create the data location
        data_location = WorkflowDataLocation(
            structure="sequencing-runs",
            locations=["test_location"],
            runs_regex=".*_testrun",
        )

        # Create scan object
        scan = Scan(
            mode="single", scan_parameters=ScanSingle(filename="another_table.xlsx")
        )

        # Create config object
        collection_config = DataCollectionConfig(
            type="table",
            metatype="metadata",
            scan=scan,
            dc_specific_properties=DCTableConfig(format="xlsx"),
        )

        # Create data collection
        data_collection = DataCollection(
            data_collection_tag="another_table",
            description="Another dataset",
            config=collection_config,
        )

        # Create the second workflow
        second_workflow = Workflow(
            name="second_workflow",
            engine=workflow_engine,
            data_location=data_location,
            data_collections=[data_collection],
        )

        # Add the second workflow to the project
        sample_project.workflows.append(second_workflow)
        print(f"After addind 2nd : {sample_project}")

        # sample_project = Project(**sample_project_config)

        # Act
        result = await helper_create_project_beanie(sample_project)

        # # Assert
        assert result["success"] is True
        retrieved_project = await ProjectBeanie.find_one({"name": sample_project.name})
        await retrieved_project.fetch_all_links()
        print(format_pydantic(retrieved_project))
        print(format_pydantic(retrieved_project.workflows))
        assert len(retrieved_project.workflows) == 2
        # assert len(retrieved_project.model_dump()["workflows"]) == 2
        workflow_names = [w.name for w in retrieved_project.workflows]
        assert sample_project.workflows[0].name in workflow_names
        assert "second_workflow" in workflow_names

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_with_application_workflow(
        self, get_test_config, test_yaml_path
    ):
        """Test project creation mimicking the application workflow."""
        # Setup database at function level
        client = AsyncMongoMockClient()
        await init_beanie(database=client.test_db, document_models=[ProjectBeanie])

        # This test follows the pattern shown in the example code
        # Load config as done in the application
        project_config = get_test_config(test_yaml_path)
        project_config["yaml_config_path"] = test_yaml_path

        # Create admin user
        admin_user = UserBase(
            id=PydanticObjectId(),
            email="admin@example.com",
            is_admin=True,
            # groups=[Group(id=PydanticObjectId(), name="admin_group")],
        )

        # Simulate admin_user.fetch_all_links() by creating a copy
        admin_user_copy = admin_user.model_copy()
        # admin_user_copy.groups = admin_user.groups

        # Set up permissions as shown in the example
        project_config["permissions"] = {
            "owners": [
                UserBase(
                    id=admin_user.id,
                    email=admin_user.email,
                    is_admin=True,
                    # groups=[
                        # Group(id=g.id, name=g.name) for g in admin_user_copy.groups
                    # ],
                )
            ],
            "editors": [],
            "viewers": [],
        }

        # Create the project object
        project = ProjectBeanie(**project_config)

        # Execute the helper function
        result = await helper_create_project_beanie(project)

        # Verify results
        assert result["success"] is True
        assert result["message"] == "Project created successfully."
        assert result["project"] == project

        # Verify the project was saved to the database
        retrieved_project = await ProjectBeanie.find_one({"name": project.name})
        assert retrieved_project is not None
        assert retrieved_project.name == project.name
        assert len(retrieved_project.workflows) > 0
        assert retrieved_project.workflows[0].name == project.workflows[0].name
