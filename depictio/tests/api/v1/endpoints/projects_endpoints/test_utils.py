import os
import yaml
import pytest
from bson import ObjectId
from mongomock import MongoClient
from unittest.mock import patch
from fastapi import HTTPException

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.endpoints.projects_endpoints.utils import helper_create_project_beanie
from depictio.models.models.projects import Project
from depictio.models.models.users import UserBase, Permission

@pytest.mark.asyncio
class TestProjectCreation:
    @pytest.fixture
    def sample_user(self):
        """Create a sample user for testing."""
        user_id = str(ObjectId())  # Convert to string to avoid Beanie-specific types
        return UserBase(
            id=user_id,
            email="test@example.com",
            is_admin=True,
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
            BASE_PATH, "depictio", "api", "v1", "configs", "iris_dataset", "initial_project.yaml"
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
        project_config["name"] = f"{project_config['name']} - Test-{ObjectId()}"  # Add unique identifier
        print(f"Sample project config: {project_config}")
        return project_config
    
    @pytest.fixture
    def mock_projects_collection(self):
        """Mock the projects_collection with mongomock."""
        # Create a mongomock client and database
        client = MongoClient()
        db = client.test_db
        
        # Create and return a temporary collection
        collection = db.projects
        
        # Patch the projects_collection
        with patch('depictio.api.v1.endpoints.projects_endpoints.utils.projects_collection', collection):
            with patch('depictio.api.v1.db.projects_collection', collection):
                yield collection
                
                # Clean up after test
                collection.drop()

    @pytest.mark.asyncio
    async def test_helper_create_project_beanie_success(self, sample_project_config, mock_projects_collection):
        """Test successful project creation."""
        # Create the project object
        sample_project = Project(**sample_project_config)
        print(f"Sample project object: {format_pydantic(sample_project)}")

        # Act
        result = await helper_create_project_beanie(sample_project)

        # Assert
        assert result["success"] is True
        assert result["message"] == "Project created successfully."
        assert result["project"] == sample_project

        # Verify the project was saved to the database using PyMongo
        retrieved_project_dict = mock_projects_collection.find_one({"name": sample_project.name})
        assert retrieved_project_dict is not None
        assert retrieved_project_dict["name"] == sample_project.name
        
        # Verify _id exists and is of correct type
        assert "_id" in retrieved_project_dict
        
        # Verify some key properties
        assert len(retrieved_project_dict["workflows"]) == len(sample_project.workflows)
        assert retrieved_project_dict["is_public"] is False
        
        # Check permissions
        assert len(retrieved_project_dict["permissions"]["owners"]) == 1
        assert retrieved_project_dict["permissions"]["owners"][0]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_helper_create_project_duplicate(self, sample_project_config, mock_projects_collection):
        """Test project creation with duplicate name."""
        # Create the project object
        sample_project = Project(**sample_project_config)
        
        # First creation should succeed
        await helper_create_project_beanie(sample_project)
        
        # Second creation should fail with HTTPException
        with pytest.raises(HTTPException) as excinfo:
            await helper_create_project_beanie(sample_project)
        
        assert excinfo.value.status_code == 400
        assert f"Project with name '{sample_project.name}' already exists" in excinfo.value.detail
       