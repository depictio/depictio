from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from depictio.dash.utils import (
    generate_unique_index,
    get_columns_from_data_collection,
    get_component_data,
    list_workflows,
    load_depictio_data_mongo,
    return_dc_tag_from_id,
    return_mongoid,
    return_user_from_token,
    return_wf_tag_from_id,
    serialize_dash_component,
)

# Mark all tests in this module to skip database setup
pytestmark = pytest.mark.no_db


class TestGenerateUniqueIndex:
    """Test unique index generation functionality."""

    def test_generate_unique_index_returns_string(self):
        """Test that generate_unique_index returns a string."""
        result = generate_unique_index()
        assert isinstance(result, str)

    def test_generate_unique_index_is_unique(self):
        """Test that consecutive calls return different values."""
        result1 = generate_unique_index()
        result2 = generate_unique_index()
        assert result1 != result2

    def test_generate_unique_index_format(self):
        """Test that generated index follows UUID format."""
        result = generate_unique_index()
        # UUID4 format: 8-4-4-4-12 characters separated by hyphens
        parts = result.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4


class TestGetComponentData:
    """Test component data retrieval functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        # Clear cache before each test
        from depictio.dash.utils import _component_data_cache

        _component_data_cache.clear()

    @patch("depictio.dash.utils.httpx.get")
    def test_get_component_data_success(self, mock_httpx_get):
        """Test successful component data retrieval."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "component_type": "card",
            "wf_id": "workflow_123",
            "dc_id": "datacoll_456",
        }
        mock_httpx_get.return_value = mock_response

        # Act
        result = get_component_data("comp_1", "dashboard_1", "test_token")

        # Assert
        assert result is not None
        assert result["component_type"] == "card"
        assert result["wf_id"] == "workflow_123"
        mock_httpx_get.assert_called_once()

    @patch("depictio.dash.utils.httpx.get")
    def test_get_component_data_failure(self, mock_httpx_get):
        """Test component data retrieval failure."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_get.return_value = mock_response

        # Act
        result = get_component_data("comp_1", "dashboard_1", "test_token")

        # Assert
        assert result is None
        mock_httpx_get.assert_called_once()

    @patch("depictio.dash.utils.httpx.get")
    def test_get_component_data_caching(self, mock_httpx_get):
        """Test that component data is cached properly."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"component_type": "card"}
        mock_httpx_get.return_value = mock_response

        # Act - Call twice with same parameters
        result1 = get_component_data("comp_1", "dashboard_1", "test_token")
        result2 = get_component_data("comp_1", "dashboard_1", "test_token")

        # Assert
        assert result1 == result2
        # Should only call HTTP once due to caching
        assert mock_httpx_get.call_count == 1


class TestGetColumnsFromDataCollection:
    """Test data collection columns retrieval functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        from depictio.dash.utils import _data_collection_specs_cache

        _data_collection_specs_cache.clear()

    @patch("depictio.dash.utils.httpx.get")
    def test_get_columns_from_data_collection_success(self, mock_httpx_get):
        """Test successful data collection columns retrieval."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "name": "column1",
                "type": "int64",
                "description": "First column",
                "specs": {"min": 0, "max": 100},
            },
            {"name": "column2", "type": "object", "description": "Second column", "specs": {}},
        ]
        mock_httpx_get.return_value = mock_response

        # Act
        result = get_columns_from_data_collection("wf_1", "dc_1", "test_token")

        # Assert
        assert "column1" in result
        assert "column2" in result
        assert result["column1"]["type"] == "int64"
        assert result["column1"]["description"] == "First column"
        assert result["column2"]["type"] == "object"

    @patch("depictio.dash.utils.httpx.get")
    def test_get_columns_from_data_collection_error(self, mock_httpx_get):
        """Test data collection columns retrieval with API error."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_httpx_get.return_value = mock_response

        # Act
        result = get_columns_from_data_collection("wf_1", "dc_1", "test_token")

        # Assert
        assert len(result) == 0  # Should return empty defaultdict

    @patch("depictio.dash.utils.httpx.get")
    def test_get_columns_from_data_collection_caching(self, mock_httpx_get):
        """Test that columns data is cached properly."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "col1", "type": "int64", "description": "Test", "specs": {}}
        ]
        mock_httpx_get.return_value = mock_response

        # Act
        result1 = get_columns_from_data_collection("wf_1", "dc_1", "test_token")
        result2 = get_columns_from_data_collection("wf_1", "dc_1", "test_token")

        # Assert
        assert result1 == result2
        assert mock_httpx_get.call_count == 1


class TestListWorkflows:
    """Test workflows listing functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        from depictio.dash.utils import _workflows_cache

        _workflows_cache.clear()

    @patch("depictio.dash.utils.httpx.get")
    def test_list_workflows_success(self, mock_httpx_get):
        """Test successful workflows listing."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "wf_1", "workflow_tag": "workflow_1", "name": "First Workflow"},
            {"id": "wf_2", "workflow_tag": "workflow_2", "name": "Second Workflow"},
        ]
        mock_httpx_get.return_value = mock_response

        # Act
        result = list_workflows("test_token")

        # Assert
        assert len(result) == 2
        assert result[0]["workflow_tag"] == "workflow_1"
        assert result[1]["workflow_tag"] == "workflow_2"

    def test_list_workflows_no_token(self):
        """Test workflows listing without token."""
        # Act
        result = list_workflows(None)

        # Assert
        assert result is None

    @patch("depictio.dash.utils.httpx.get")
    def test_list_workflows_caching(self, mock_httpx_get):
        """Test that workflows are cached properly."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "wf_1", "workflow_tag": "workflow_1"}]
        mock_httpx_get.return_value = mock_response

        # Act
        result1 = list_workflows("test_token")
        result2 = list_workflows("test_token")

        # Assert
        assert result1 == result2
        assert mock_httpx_get.call_count == 1


class TestLoadDepictioDataMongo:
    """Test MongoDB data loading functionality."""

    @patch("depictio.dash.utils.httpx.get")
    def test_load_depictio_data_mongo_success(self, mock_httpx_get):
        """Test successful MongoDB data loading."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "dashboard_id": "dash_1",
            "components": [],
            "metadata": {},
        }
        mock_httpx_get.return_value = mock_response

        # Act
        result = load_depictio_data_mongo("dashboard_1", "test_token")

        # Assert
        assert result is not None
        assert result["dashboard_id"] == "dash_1"

    @patch("depictio.dash.utils.httpx.get")
    def test_load_depictio_data_mongo_failure(self, mock_httpx_get):
        """Test MongoDB data loading failure."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_get.return_value = mock_response

        # Act
        result = load_depictio_data_mongo("dashboard_1", "test_token")

        # Assert
        assert result is None

    @patch("depictio.dash.utils.httpx.get")
    def test_load_depictio_data_mongo_exception(self, mock_httpx_get):
        """Test MongoDB data loading with exception."""
        # Arrange
        mock_httpx_get.side_effect = Exception("Network error")

        # Act
        result = load_depictio_data_mongo("dashboard_1", "test_token")

        # Assert
        assert result is None


class TestReturnUserFromToken:
    """Test user retrieval from token functionality."""

    @patch("depictio.dash.utils.httpx.get")
    def test_return_user_from_token_success(self, mock_httpx_get):
        """Test successful user retrieval from token."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "email": "test@example.com",
            "id": "user_123",
            "is_admin": False,
        }
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_user_from_token("test_token")

        # Assert
        assert result is not None
        assert result["email"] == "test@example.com"
        assert result["id"] == "user_123"

    @patch("depictio.dash.utils.httpx.get")
    def test_return_user_from_token_failure(self, mock_httpx_get):
        """Test user retrieval from token failure."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_user_from_token("invalid_token")

        # Assert
        assert result is None

    @patch("depictio.dash.utils.httpx.get")
    def test_return_user_from_token_valid_token(self, mock_httpx_get):
        """Test user retrieval with valid token format."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"email": "admin@example.com", "is_admin": True}
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_user_from_token("valid.jwt.token")

        # Assert
        assert result is not None
        assert result["is_admin"] is True


class TestReturnWfTagFromId:
    """Test workflow tag retrieval from ID functionality."""

    @patch("depictio.dash.utils.httpx.get")
    def test_return_wf_tag_from_id_success(self, mock_httpx_get):
        """Test successful workflow tag retrieval."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = "test_workflow_tag"
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_wf_tag_from_id(ObjectId(), "test_token")

        # Assert
        assert result == "test_workflow_tag"

    @patch("depictio.dash.utils.httpx.get")
    def test_return_wf_tag_from_id_not_found(self, mock_httpx_get):
        """Test workflow tag retrieval when not found."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_wf_tag_from_id(ObjectId(), "test_token")

        # Assert
        assert result is None

    @patch("depictio.dash.utils.httpx.get")
    def test_return_wf_tag_from_id_with_valid_objectid(self, mock_httpx_get):
        """Test workflow tag retrieval with valid ObjectId."""
        # Arrange
        test_id = ObjectId()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = f"workflow_for_{test_id}"
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_wf_tag_from_id(test_id, "test_token")

        # Assert
        assert result == f"workflow_for_{test_id}"


class TestReturnDcTagFromId:
    """Test data collection tag retrieval from ID functionality."""

    @patch("depictio.dash.utils.httpx.get")
    def test_return_dc_tag_from_id_success(self, mock_httpx_get):
        """Test successful data collection tag retrieval."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = "test_datacollection_tag"
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_dc_tag_from_id(ObjectId(), "test_token")

        # Assert
        assert result == "test_datacollection_tag"

    @patch("depictio.dash.utils.httpx.get")
    def test_return_dc_tag_from_id_not_found(self, mock_httpx_get):
        """Test data collection tag retrieval when not found."""
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_dc_tag_from_id(ObjectId(), "test_token")

        # Assert
        assert result is None

    @patch("depictio.dash.utils.httpx.get")
    def test_return_dc_tag_from_id_with_valid_objectid(self, mock_httpx_get):
        """Test data collection tag retrieval with valid ObjectId."""
        # Arrange
        test_id = ObjectId()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = f"datacoll_for_{test_id}"
        mock_httpx_get.return_value = mock_response

        # Act
        result = return_dc_tag_from_id(test_id, "test_token")

        # Assert
        assert result == f"datacoll_for_{test_id}"


class TestReturnMongoid:
    """Test MongoDB ID retrieval functionality."""

    @patch("depictio.dash.utils.list_workflows")
    def test_return_mongoid_with_tags(self, mock_list_workflows):
        """Test MongoDB ID retrieval using workflow and data collection tags."""
        # Arrange
        mock_list_workflows.return_value = [
            {
                "_id": "wf_123",
                "workflow_tag": "test_workflow",
                "data_collections": [{"_id": "dc_456", "data_collection_tag": "test_datacoll"}],
            }
        ]

        # Act
        wf_id, dc_id = return_mongoid(
            workflow_tag="test_workflow", data_collection_tag="test_datacoll", TOKEN="test_token"
        )

        # Assert
        assert wf_id == "wf_123"
        assert dc_id == "dc_456"

    @patch("depictio.dash.utils.list_workflows")
    def test_return_mongoid_with_workflow_id_and_dc_tag(self, mock_list_workflows):
        """Test MongoDB ID retrieval using workflow ID and data collection tag."""
        # Arrange
        test_workflow_id = ObjectId()
        mock_list_workflows.return_value = [
            {
                "_id": str(test_workflow_id),
                "workflow_tag": "test_workflow",
                "data_collections": [{"_id": "dc_456", "data_collection_tag": "test_datacoll"}],
            }
        ]

        # Act
        wf_id, dc_id = return_mongoid(
            workflow_id=test_workflow_id,
            data_collection_tag="test_datacoll",
            TOKEN="test_token",
        )

        # Assert
        assert wf_id == test_workflow_id  # Returns the original ObjectId
        assert dc_id == "dc_456"

    @patch("depictio.dash.utils.list_workflows")
    def test_return_mongoid_invalid_input(self, mock_list_workflows):
        """Test MongoDB ID retrieval with invalid input."""
        # Arrange
        mock_list_workflows.return_value = []

        # Act
        wf_id, dc_id = return_mongoid(TOKEN="test_token")

        # Assert
        assert wf_id is None
        assert dc_id is None


class TestSerializeDashComponent:
    """Test Dash component serialization functionality."""

    def test_serialize_dash_component_dict(self):
        """Test serialization of dictionary components."""
        # Arrange
        test_dict = {"key1": "value1", "key2": {"nested": "value"}}

        # Act
        result = serialize_dash_component(test_dict)

        # Assert
        assert result == test_dict
        assert isinstance(result, dict)

    def test_serialize_dash_component_list(self):
        """Test serialization of list components."""
        # Arrange
        test_list = [1, 2, {"key": "value"}, "string"]

        # Act
        result = serialize_dash_component(test_list)

        # Assert
        assert result == test_list
        assert isinstance(result, list)

    def test_serialize_dash_component_with_to_dict_method(self):
        """Test serialization of objects with to_dict method."""

        # Arrange
        class MockComponent:
            def to_dict(self):
                return {"component": "mock", "type": "test"}

        test_component = MockComponent()

        # Act
        result = serialize_dash_component(test_component)

        # Assert
        assert result == {"component": "mock", "type": "test"}
