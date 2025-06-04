import os
from unittest.mock import patch

import pytest
import yaml
from bson import ObjectId
from fastapi import HTTPException
from mongomock import MongoClient

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.api.v1.endpoints.projects_endpoints.utils import (
    _async_get_all_projects,
    _async_get_project_from_id,
    _async_get_project_from_name,
    _helper_create_project_beanie,
)
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase


# Fixtures available for all test classes
@pytest.fixture
def sample_user():
    """Create a sample user for testing."""
    user_id = str(ObjectId())
    return UserBase(
        id=user_id,
        email="test@example.com",
        is_admin=True,
    )


@pytest.fixture
def sample_viewer_user():
    """Create a sample viewer user for testing."""
    user_id = str(ObjectId())
    return UserBase(
        id=user_id,
        email="viewer@example.com",
        is_admin=False,
    )


@pytest.fixture
def sample_editor_user():
    """Create a sample editor user for testing."""
    user_id = str(ObjectId())
    return UserBase(
        id=user_id,
        email="editor@example.com",
        is_admin=False,
    )


@pytest.fixture
def get_test_config():
    """Function to load the YAML configuration file used in tests."""

    def _get_config(filepath):
        with open(filepath) as file:
            return yaml.safe_load(file)

    return _get_config


@pytest.fixture
def test_yaml_path():
    """Path to the test YAML configuration file."""
    from depictio import BASE_PATH

    return os.path.join(
        BASE_PATH,
        "depictio",
        "api",
        "v1",
        "configs",
        "iris_dataset",
        "initial_project.yaml",
    )


@pytest.fixture
def yaml_config(get_test_config, test_yaml_path):
    """Load the YAML configuration from file."""
    return get_test_config(test_yaml_path)


@pytest.fixture
def mock_projects_collection():
    """Mock the projects_collection with mongomock for each test."""
    client = MongoClient()
    db = client.test_db
    collection = db.projects

    with patch(
        "depictio.api.v1.endpoints.projects_endpoints.utils.projects_collection",
        collection,
    ):
        with patch("depictio.api.v1.db.projects_collection", collection):
            yield collection
            # Make sure to clean up after each test
            client.close()


@pytest.fixture(autouse=True)
def set_depictio_context(monkeypatch):
    """Set DEPICTIO_CONTEXT to 'api' for all tests."""
    # Use monkeypatch instead of patch to ensure it works globally
    monkeypatch.setattr("depictio.models.models.projects.DEPICTIO_CONTEXT", "api")
    monkeypatch.setattr("depictio.models.models.workflows.DEPICTIO_CONTEXT", "api")
    monkeypatch.setattr("depictio.models.models.data_collections.DEPICTIO_CONTEXT", "api")


@pytest.mark.asyncio
class TestProjectCreation:
    @pytest.fixture
    def sample_project_config(self, sample_user, test_yaml_path, yaml_config):
        """Create a sample project for testing using YAML config."""
        permission = Permission(owners=[sample_user])
        project_config = yaml_config.copy()
        project_config["yaml_config_path"] = test_yaml_path
        project_config["permissions"] = permission
        project_config["name"] = f"{project_config['name']} - Test-{ObjectId()}"
        print(f"Sample project config: {project_config}")
        return project_config

    @pytest.mark.asyncio
    async def test__helper_create_project_beanie_success(
        self, sample_project_config, mock_projects_collection
    ):
        """Test successful project creation."""

        sample_project = Project(**sample_project_config)
        print(f"Sample project object: {format_pydantic(sample_project)}")

        result = await _helper_create_project_beanie(sample_project)

        assert result["success"] is True
        assert result["message"] == "Project created successfully."
        assert result["project"] == sample_project

        retrieved_project_dict = mock_projects_collection.find_one({"name": sample_project.name})
        assert retrieved_project_dict is not None
        assert retrieved_project_dict["name"] == sample_project.name
        assert "_id" in retrieved_project_dict
        assert len(retrieved_project_dict["workflows"]) == len(sample_project.workflows)
        assert retrieved_project_dict["is_public"] is False
        assert len(retrieved_project_dict["permissions"]["owners"]) == 1
        assert retrieved_project_dict["permissions"]["owners"][0]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_helper_create_project_duplicate(
        self, sample_project_config, mock_projects_collection
    ):
        """Test project creation with duplicate name."""
        sample_project = Project(**sample_project_config)

        await _helper_create_project_beanie(sample_project)

        with pytest.raises(HTTPException) as excinfo:
            await _helper_create_project_beanie(sample_project)

        assert excinfo.value.status_code == 400
        assert f"Project with name '{sample_project.name}' already exists" in excinfo.value.detail


@pytest.mark.asyncio
class TestGetAllProjects:
    @pytest.fixture
    def setup_multiple_projects(
        self,
        sample_user,
        sample_viewer_user,
        yaml_config,
        test_yaml_path,
        mock_projects_collection,
    ):
        """Create multiple projects for testing."""
        # Clear the collection first
        mock_projects_collection.delete_many({})

        # Owner project
        owner_project_config = yaml_config.copy()
        owner_project_config["yaml_config_path"] = test_yaml_path
        owner_project_config["name"] = f"Owner Project - {ObjectId()}"
        owner_project_config["permissions"] = Permission(owners=[sample_user])
        owner_project = Project(**owner_project_config)
        # Set an explicit _id to avoid duplicates
        owner_project.id = ObjectId()
        mongo_doc = owner_project.mongo()
        mongo_doc["_id"] = owner_project.id
        mock_projects_collection.insert_one(mongo_doc)

        # Viewer project
        viewer_project_config = yaml_config.copy()
        viewer_project_config["yaml_config_path"] = test_yaml_path
        viewer_project_config["name"] = f"Viewer Project - {ObjectId()}"
        viewer_project_config["permissions"] = Permission(
            owners=[sample_viewer_user], viewers=[sample_user]
        )
        viewer_project = Project(**viewer_project_config)
        viewer_project.id = ObjectId()
        mongo_doc = viewer_project.mongo()
        mongo_doc["_id"] = viewer_project.id
        mock_projects_collection.insert_one(mongo_doc)

        # Public project
        public_project_config = yaml_config.copy()
        public_project_config["yaml_config_path"] = test_yaml_path
        public_project_config["name"] = f"Public Project - {ObjectId()}"
        public_project_config["permissions"] = Permission(owners=[sample_viewer_user])
        public_project_config["is_public"] = True
        public_project = Project(**public_project_config)
        public_project.id = ObjectId()
        mongo_doc = public_project.mongo()
        mongo_doc["_id"] = public_project.id
        mock_projects_collection.insert_one(mongo_doc)

        return [owner_project, viewer_project, public_project]

    @pytest.fixture(autouse=True)
    def set_depictio_context(self, monkeypatch):
        """Set DEPICTIO_CONTEXT to 'api' for all tests."""
        # Use monkeypatch instead of patch to ensure it works globally
        monkeypatch.setattr("depictio.models.models.projects.DEPICTIO_CONTEXT", "api")
        monkeypatch.setattr("depictio.models.models.workflows.DEPICTIO_CONTEXT", "api")
        monkeypatch.setattr("depictio.models.models.data_collections.DEPICTIO_CONTEXT", "api")

    async def test_async_get_all_projects_user(
        self, sample_user, mock_projects_collection, setup_multiple_projects
    ):
        """Test getting all projects for a regular user."""
        current_user = UserBase(id=sample_user.id, email=sample_user.email, is_admin=False)
        result = _async_get_all_projects(current_user, mock_projects_collection)

        assert len(result) == 3  # owner, viewer, and public projects
        assert all(isinstance(p, Project) for p in result)

    async def test_async_get_all_projects_admin(
        self, sample_user, mock_projects_collection, setup_multiple_projects
    ):
        """Test getting all projects for an admin user."""
        admin_user = UserBase(id=sample_user.id, email=sample_user.email, is_admin=True)
        result = _async_get_all_projects(admin_user, mock_projects_collection)

        assert len(result) == 3  # admin sees all projects
        assert all(isinstance(p, Project) for p in result)


@pytest.mark.asyncio
class TestGetProjectFromId:
    @pytest.fixture
    def setup_single_project(
        self, sample_user, yaml_config, test_yaml_path, mock_projects_collection
    ):
        """Create a single project for testing."""
        # Clear the collection first
        mock_projects_collection.delete_many({})

        project_config = yaml_config.copy()
        project_config["yaml_config_path"] = test_yaml_path
        project_config["name"] = f"Test Project - {ObjectId()}"
        project_config["permissions"] = Permission(owners=[sample_user])
        project = Project(**project_config)
        # Set an explicit _id
        project.id = ObjectId()
        mongo_doc = project.mongo()
        mongo_doc["_id"] = project.id
        mock_projects_collection.insert_one(mongo_doc)
        return str(project.id)

    async def test_async_get_project_from_id_success(
        self, sample_user, mock_projects_collection, setup_single_project
    ):
        """Test getting a project by ID successfully."""
        current_user = UserBase(id=sample_user.id, email=sample_user.email, is_admin=False)
        result = _async_get_project_from_id(
            setup_single_project, current_user, mock_projects_collection
        )

        assert result is not None
        assert result["_id"] == setup_single_project
        assert "permissions" in result
        assert "owners" in result["permissions"]

    async def test_async_get_project_from_id_not_found(self, sample_user, mock_projects_collection):
        """Test getting a non-existent project by ID."""
        # Clear the collection first
        mock_projects_collection.delete_many({})

        current_user = UserBase(id=sample_user.id, email=sample_user.email, is_admin=False)
        non_existent_id = str(ObjectId())

        with pytest.raises(HTTPException) as excinfo:
            _async_get_project_from_id(non_existent_id, current_user, mock_projects_collection)

        assert excinfo.value.status_code == 404
        assert "Project not found" in excinfo.value.detail


@pytest.mark.asyncio
class TestGetProjectFromName:
    @pytest.fixture
    def setup_named_project(
        self, sample_user, yaml_config, test_yaml_path, mock_projects_collection
    ):
        """Create a project with a specific name for testing."""
        # Clear the collection first
        mock_projects_collection.delete_many({})

        project_config = yaml_config.copy()
        project_config["yaml_config_path"] = test_yaml_path
        project_config["name"] = f"Named Project - {ObjectId()}"
        project_config["permissions"] = Permission(owners=[sample_user])
        project = Project(**project_config)
        # Set an explicit _id
        project.id = ObjectId()
        mongo_doc = project.mongo()
        mongo_doc["_id"] = project.id
        mock_projects_collection.insert_one(mongo_doc)
        return project.name

    @pytest.fixture(autouse=True)
    def set_depictio_context(self, monkeypatch):
        """Set DEPICTIO_CONTEXT to 'api' for all tests."""
        # Use monkeypatch instead of patch to ensure it works globally
        monkeypatch.setattr("depictio.models.models.projects.DEPICTIO_CONTEXT", "api")
        monkeypatch.setattr("depictio.models.models.workflows.DEPICTIO_CONTEXT", "api")
        monkeypatch.setattr("depictio.models.models.data_collections.DEPICTIO_CONTEXT", "api")

    async def test_async_get_project_from_name_success(
        self, sample_user, mock_projects_collection, setup_named_project
    ):
        """Test getting a project by name successfully."""
        current_user = UserBase(id=sample_user.id, email=sample_user.email, is_admin=False)
        result = _async_get_project_from_name(
            setup_named_project, current_user, mock_projects_collection
        )

        assert result is not None
        assert result["name"] == setup_named_project
        assert "permissions" in result
        assert "owners" in result["permissions"]

    async def test_async_get_project_from_name_not_found(
        self, sample_user, mock_projects_collection
    ):
        """Test getting a non-existent project by name."""
        # Clear the collection first
        mock_projects_collection.delete_many({})

        current_user = UserBase(id=sample_user.id, email=sample_user.email, is_admin=False)

        with pytest.raises(HTTPException) as excinfo:
            _async_get_project_from_name(
                "Non-existent Project", current_user, mock_projects_collection
            )

        assert excinfo.value.status_code == 404
        assert "Project not found" in excinfo.value.detail

    async def test_async_get_project_from_name_public_access(
        self, sample_user, yaml_config, test_yaml_path, mock_projects_collection
    ):
        """Test getting a public project by name with wildcard permissions."""
        # Clear the collection first
        mock_projects_collection.delete_many({})

        # Create a public project with wildcard viewers
        project_config = yaml_config.copy()
        project_config["yaml_config_path"] = test_yaml_path
        project_config["name"] = f"Public Project - {ObjectId()}"
        project_config["permissions"] = Permission(owners=[sample_user], viewers=["*"])
        project = Project(**project_config)
        # Set an explicit _id
        project.id = ObjectId()
        mongo_doc = project.mongo()
        mongo_doc["_id"] = project.id
        mock_projects_collection.insert_one(mongo_doc)

        # Create a different user
        other_user = UserBase(id=str(ObjectId()), email="other@example.com", is_admin=False)
        result = _async_get_project_from_name(project.name, other_user, mock_projects_collection)

        assert result is not None
        assert result["name"] == project.name
        assert result["permissions"]["viewers"] == ["*"]
