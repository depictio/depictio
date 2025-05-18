import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from bson import ObjectId
from pydantic import BaseModel, Field, ValidationError

from depictio.api.v1.configs.custom_logging import format_pydantic
from depictio.models.models.base import (MongoModel, PyObjectId,
                                         convert_objectid_to_str)

# --------------------------------------------------------
# Tests for the convert_objectid_to_str function
# --------------------------------------------------------


def test_convert_dict():
    input_data = {
        "id": ObjectId("507f1f77bcf86cd799439011"),
        "name": "test",
        "created_at": datetime(2023, 1, 1, 12, 0, 0),
        "path": Path("/some/path"),
    }
    expected_output = {
        "id": "507f1f77bcf86cd799439011",
        "name": "test",
        "created_at": "2023-01-01 12:00:00",
        "path": "/some/path",
    }
    assert convert_objectid_to_str(input_data) == expected_output


def test_convert_list():
    input_data = [
        ObjectId("507f1f77bcf86cd799439011"),
        datetime(2023, 1, 1, 12, 0, 0),
        Path("/some/path"),
        "test",
    ]
    expected_output = [
        "507f1f77bcf86cd799439011",
        "2023-01-01 12:00:00",
        "/some/path",
        "test",
    ]
    assert convert_objectid_to_str(input_data) == expected_output


def test_convert_objectid():
    input_data = ObjectId("507f1f77bcf86cd799439011")
    expected_output = "507f1f77bcf86cd799439011"
    assert convert_objectid_to_str(input_data) == expected_output


def test_convert_datetime():
    input_data = datetime(2023, 1, 1, 12, 0, 0)
    expected_output = "2023-01-01 12:00:00"
    assert convert_objectid_to_str(input_data) == expected_output


def test_convert_path():
    input_data = Path("/some/path")
    expected_output = "/some/path"
    assert convert_objectid_to_str(input_data) == expected_output


def test_convert_other():
    input_data = "test"
    expected_output = "test"
    assert convert_objectid_to_str(input_data) == expected_output


# --------------------------------------------------------
# Tests for the PyObjectId class
# --------------------------------------------------------


# Define a test model using PyObjectId
class MyTestModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str


class TestPyObjectId:
    """Test cases for the PyObjectId class"""

    def test_valid_objectid_instance(self):
        """Test PyObjectId initialization with a valid ObjectId."""
        obj_id = ObjectId()
        py_obj_id = PyObjectId.validate(obj_id)
        assert isinstance(py_obj_id, ObjectId)
        assert str(py_obj_id) == str(obj_id)

    def test_valid_string_objectid(self):
        """Test PyObjectId initialization with a valid ObjectId string."""
        obj_id_str = "507f1f77bcf86cd799439011"
        py_obj_id = PyObjectId.validate(obj_id_str)
        assert isinstance(py_obj_id, ObjectId)
        assert str(py_obj_id) == obj_id_str

    def test_pyobjectid_instance(self):
        """Test PyObjectId initialization with another PyObjectId instance."""
        original = PyObjectId("507f1f77bcf86cd799439011")
        py_obj_id = PyObjectId.validate(original)
        assert isinstance(py_obj_id, ObjectId)
        assert str(py_obj_id) == str(original)

    def test_invalid_string(self):
        """Test exception is raised for an invalid ObjectId string."""
        with pytest.raises(ValueError, match="Invalid ObjectId:"):
            PyObjectId.validate("invalid_objectid")

    def test_invalid_type(self):
        """Test exception is raised for an invalid type."""
        with pytest.raises(ValueError, match="Invalid ObjectId:"):
            PyObjectId.validate(123)

    def test_model_creation_with_default_id(self):
        """Test creating a model with default PyObjectId."""
        model = MyTestModel(name="test")
        assert isinstance(model.id, ObjectId)

    def test_model_creation_with_string_id(self):
        """Test creating a model with a string ID."""
        id_str = "507f1f77bcf86cd799439011"
        model = MyTestModel(_id=id_str, name="test")
        assert isinstance(model.id, ObjectId)
        assert str(model.id) == id_str

    def test_model_creation_with_objectid(self):
        """Test creating a model with an ObjectId."""
        obj_id = ObjectId()
        model = MyTestModel(_id=obj_id, name="test")
        assert isinstance(model.id, ObjectId)
        assert model.id == obj_id

    def test_model_serialization(self):
        """Test model serialization with PyObjectId."""
        id_str = "507f1f77bcf86cd799439011"
        model = MyTestModel(_id=id_str, name="test")
        model_dict = model.model_dump(by_alias=True)
        assert isinstance(model_dict["_id"], str)
        assert model_dict["_id"] == id_str

    def test_model_json_serialization(self):
        """Test model JSON serialization with PyObjectId."""
        id_str = "507f1f77bcf86cd799439011"
        model = MyTestModel(_id=id_str, name="test")
        json_str = model.model_dump_json(by_alias=True)
        data = json.loads(json_str)
        assert isinstance(data["_id"], str)
        assert data["_id"] == id_str

    def test_model_validation_error(self):
        """Test validation error with invalid ObjectId."""
        with pytest.raises(ValidationError):
            MyTestModel(_id="invalid_objectid", name="test")

    def test_json_schema(self):
        """Test the JSON schema generation for PyObjectId."""
        schema = MyTestModel.model_json_schema()
        assert "properties" in schema
        assert "_id" in schema["properties"]
        assert schema["properties"]["_id"]["type"] == "string"
        assert schema["properties"]["_id"]["format"] == "objectid"

    def test_core_schema_serialization(self):
        """Test that PyObjectId is serialized correctly in the core schema."""
        id_str = "507f1f77bcf86cd799439011"
        obj_id = ObjectId(id_str)
        model = MyTestModel(_id=obj_id, name="test")
        serialized = model.model_dump(by_alias=True)
        assert serialized["_id"] == id_str
        assert isinstance(serialized["_id"], str)

    def test_equality_with_objectid(self):
        """Test that PyObjectId maintains equality with ObjectId."""
        id_str = "507f1f77bcf86cd799439011"
        py_obj_id = PyObjectId(id_str)
        obj_id = ObjectId(id_str)
        assert py_obj_id == obj_id

    def test_string_representation(self):
        """Test string representation of PyObjectId."""
        id_str = "507f1f77bcf86cd799439011"
        py_obj_id = PyObjectId(id_str)
        assert str(py_obj_id) == id_str


# Fixture for creating test models
@pytest.fixture
def sample_model():
    """Fixture to create a sample TestModel."""
    return MyTestModel(_id="507f1f77bcf86cd799439011", name="test")


def test_model_with_fixture(sample_model):
    """Test using the sample model fixture."""
    assert isinstance(sample_model.id, ObjectId)
    assert str(sample_model.id) == "507f1f77bcf86cd799439011"
    assert sample_model.name == "test"


# Parameterized tests for PyObjectId validation
@pytest.mark.parametrize(
    "input_value,expected_valid",
    [
        (ObjectId(), True),
        ("507f1f77bcf86cd799439011", True),
        (PyObjectId("507f1f77bcf86cd799439011"), True),
        ("invalid_id", False),
        (123, False),
        (None, False),
    ],
)
def test_pyobjectid_validation(input_value, expected_valid):
    """Test PyObjectId validation with different input values."""
    if expected_valid:
        validated = PyObjectId.validate(input_value)
        assert isinstance(validated, ObjectId)
    else:
        with pytest.raises(ValueError, match="Invalid ObjectId:"):
            PyObjectId.validate(input_value)


# ---------------------------------------------------------
# MongoModel class for testing
# ---------------------------------------------------------


class TestMongoModel:
    """Test cases for the MongoModel class."""

    def test_create_with_default_id(self):
        """Test creating a model with default ID."""
        model = MongoModel()
        assert isinstance(model.id, ObjectId)
        assert model.description is None
        assert model.flexible_metadata is None
        assert model.hash is None

    def test_create_with_object_id(self):
        """Test creating a model with ObjectId."""
        obj_id = ObjectId()
        model = MongoModel(id=obj_id)
        assert model.id == obj_id
        assert isinstance(model.id, ObjectId)

    def test_create_with_string_id(self):
        """Test creating a model with string ID."""
        id_str = "507f1f77bcf86cd799439011"
        model = MongoModel(id=id_str)
        assert isinstance(model.id, ObjectId)
        assert str(model.id) == id_str

    def test_create_with_underscore_id(self):
        """Test creating a model with _id instead of id."""
        id_str = "507f1f77bcf86cd799439011"
        model = MongoModel(_id=id_str)
        print(format_pydantic(model))
        assert isinstance(model.id, ObjectId)
        assert str(model.id) == id_str

    def test_create_with_invalid_id(self):
        """Test that invalid ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid ObjectId"):
            MongoModel(id="invalid_id")

    def test_id_serialization(self):
        """Test serialization of ID field."""
        obj_id = ObjectId()
        model = MongoModel(_id=obj_id)
        print(format_pydantic(model))
        serialized = model.model_dump()
        print(f"Serialized: {serialized}")
        assert isinstance(serialized["id"], str)
        assert serialized["id"] == str(obj_id)

    def test_description_sanitization_none(self):
        """Test sanitization of None description."""
        model = MongoModel(description=None)
        assert model.description is None

    def test_description_sanitization_empty(self):
        """Test sanitization of empty description."""
        model = MongoModel(description="")
        assert model.description is None

    def test_description_sanitization_plain_text(self):
        """Test sanitization of plain text description."""
        desc = "This is a plain text description"
        model = MongoModel(description=desc)
        assert model.description == desc

    def test_description_sanitization_html(self):
        """Test sanitization of HTML in description."""
        desc = "<script>alert('XSS')</script><b>Bold text</b>"
        # Based on the logs, HTML content should cause a validation error
        with pytest.raises(ValueError, match="disallowed HTML content"):
            MongoModel(description=desc)

    def test_description_sanitization_length_limit(self):
        """Test description length limit."""
        long_desc = "a" * 1001
        with pytest.raises(ValueError, match="less than 1000 characters"):
            MongoModel(description=long_desc)

    def test_description_with_disallowed_content(self):
        """Test description with disallowed HTML content."""
        # From the logs, we can see that bleach.clean doesn't actually remove the HTML entities,
        # it just returns them encoded. The check for disallowed HTML content is looking for
        # both literal "<", ">" and their encoded forms "&lt;", "&gt;"
        # Mock bleach.clean to return a string that would trigger the check
        with patch("bleach.clean", return_value="<still>has tags</still>"):
            with pytest.raises(ValueError, match="disallowed HTML content"):
                MongoModel(description="<p>Test</p>")

    def test_from_mongo_empty_data(self):
        """Test from_mongo with empty data."""
        result = MongoModel.from_mongo({})
        print(format_pydantic(result))
        assert isinstance(result, MongoModel)
        assert isinstance(result.id, ObjectId)

    def test_from_mongo_with_id(self):
        """Test from_mongo with _id field."""
        obj_id = ObjectId()
        data = {"_id": obj_id, "description": "Test"}
        model = MongoModel.from_mongo(data)
        assert isinstance(model.id, ObjectId)
        assert model.id == obj_id
        assert model.description == "Test"

    def test_from_mongo_with_hash(self):
        """Test from_mongo with hash field."""
        hash_value = "test_hash_value"
        data = {"_id": ObjectId(), "hash": hash_value}
        model = MongoModel.from_mongo(data)
        assert model.hash == hash_value

    def test_from_mongo_with_nested_objects(self):
        """Test from_mongo with nested objects containing _id."""
        nested_id = ObjectId()
        data = {
            "_id": ObjectId(),
            "flexible_metadata": {"nested": {"_id": nested_id, "value": "test"}},
        }
        print(format_pydantic(data))
        model = MongoModel.from_mongo(data)
        print(format_pydantic(model))
        assert isinstance(model.flexible_metadata["nested"]["id"], ObjectId)
        assert model.flexible_metadata["nested"]["id"] == nested_id

    def test_from_mongo_with_nested_arrays(self):
        """Test from_mongo with nested arrays containing objects with _id."""
        item_id = ObjectId()
        data = {
            "_id": ObjectId(),
            "flexible_metadata": {"items": [{"_id": item_id, "value": "test"}]},
        }
        model = MongoModel.from_mongo(data)
        assert isinstance(model.flexible_metadata["items"][0]["id"], ObjectId)
        assert model.flexible_metadata["items"][0]["id"] == item_id

    def test_mongo_basic(self):
        """Test mongo method with basic data."""
        obj_id = ObjectId()
        model = MongoModel(id=obj_id, description="Test")
        print(format_pydantic(model))
        mongo_data = model.mongo()
        print(format_pydantic(mongo_data))
        assert "_id" in mongo_data
        assert "id" not in mongo_data
        assert isinstance(mongo_data["_id"], ObjectId)
        assert mongo_data["_id"] == obj_id
        assert mongo_data["description"] == "Test"

    def test_mongo_with_string_id(self):
        """Test mongo method with string ID."""
        id_str = "507f1f77bcf86cd799439011"
        model = MongoModel(id=id_str)
        mongo_data = model.mongo()
        assert isinstance(mongo_data["_id"], ObjectId)
        assert str(mongo_data["_id"]) == id_str

    def test_mongo_with_nested_id(self):
        """Test mongo method with nested ID."""
        nested_id_str = "507f1f77bcf86cd799439011"
        model = MongoModel(id=ObjectId())
        print(format_pydantic(model))
        model.flexible_metadata = {"nested": {"id": nested_id_str}}
        print(format_pydantic(model))
        mongo_data = model.mongo()
        print(format_pydantic(mongo_data))
        assert isinstance(mongo_data["flexible_metadata"]["nested"]["_id"], ObjectId)
        assert str(mongo_data["flexible_metadata"]["nested"]["_id"]) == nested_id_str

    # IMPORTANT test
    def test_mongo_with_non_canonical_id_field(self):
        """Test mongo method with non-canonical ID field."""
        model = MongoModel(
            id=ObjectId(),
            flexible_metadata={"non_canonical_id": ObjectId("507f1f77bcf86cd799439011")},
        )
        print(format_pydantic(model))
        print(format_pydantic(model.flexible_metadata))
        assert model.flexible_metadata["non_canonical_id"] == ObjectId("507f1f77bcf86cd799439011")
        mongo_data = model.mongo()
        print(format_pydantic(mongo_data))
        assert "_id" not in mongo_data["flexible_metadata"]
        assert mongo_data["flexible_metadata"]["non_canonical_id"] == ObjectId(
            "507f1f77bcf86cd799439011"
        )

    def test_mongo_with_nested_arrays(self):
        """Test mongo method with nested arrays containing IDs."""
        item_id = "507f1f77bcf86cd799439011"
        model = MongoModel(id=ObjectId())
        model.flexible_metadata = {"items": [{"id": item_id}]}
        mongo_data = model.mongo()
        assert isinstance(mongo_data["flexible_metadata"]["items"][0]["_id"], ObjectId)
        assert str(mongo_data["flexible_metadata"]["items"][0]["_id"]) == item_id

    def test_mongo_with_exclude_unset(self):
        """Test mongo method with exclude_unset=True."""
        model = MongoModel(id=ObjectId())
        # Only id is set, other fields are unset
        mongo_data = model.mongo(exclude_unset=True)
        assert "_id" in mongo_data
        assert "description" not in mongo_data
        assert "flexible_metadata" not in mongo_data
        assert "hash" not in mongo_data

    def test_mongo_with_by_alias_false(self):
        """Test mongo method with by_alias=False."""
        obj_id = ObjectId()
        model = MongoModel(id=obj_id)
        mongo_data = model.mongo(by_alias=False)
        # Even with by_alias=False, id should be converted to _id
        assert "_id" in mongo_data
        assert "id" not in mongo_data

    def test_ensure_id_non_dict(self):
        """Test ensure_id with non-dict input."""
        result = MongoModel.ensure_id("not a dict")
        assert result == "not a dict"

    def test_forbid_extra_fields(self):
        """Test that extra fields are forbidden."""
        with pytest.raises(ValueError):
            MongoModel(id=ObjectId(), extra_field="should not be allowed")

    def test_model_validation_complex(self):
        """Test model validation with complex data structure."""
        # Create a complex nested structure
        model = MongoModel(
            id=ObjectId("507f1f77bcf86cd799439011"),
            description="Test description",
            flexible_metadata={
                "nested": {"id": ObjectId("507f1f77bcf86cd799439012")},
                "items": [{"id": ObjectId("507f1f77bcf86cd799439013")}],
            },
            hash="test_hash",
        )

        # Test from_mongo
        print(format_pydantic(model))
        assert isinstance(model.id, ObjectId)
        assert str(model.id) == "507f1f77bcf86cd799439011"
        assert model.description == "Test description"
        print(format_pydantic(model.flexible_metadata))
        assert isinstance(model.flexible_metadata["nested"]["id"], ObjectId)
        assert str(model.flexible_metadata["nested"]["id"]) == "507f1f77bcf86cd799439012"
        assert isinstance(model.flexible_metadata["items"][0]["id"], ObjectId)
        assert model.hash == "test_hash"

        # Test mongo
        mongo_data = model.mongo()
        assert isinstance(mongo_data["_id"], ObjectId)
        assert str(mongo_data["_id"]) == "507f1f77bcf86cd799439011"
        assert isinstance(mongo_data["flexible_metadata"]["nested"]["_id"], ObjectId)
        assert str(mongo_data["flexible_metadata"]["items"][0]["_id"]) == "507f1f77bcf86cd799439013"
