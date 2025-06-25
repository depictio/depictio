"""
Tests for depictio.api.v1.endpoints.datacollections_endpoints.utils module.
"""

from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    generate_join_dict,
    normalize_join_details,
    symmetrize_join_details,
)


class TestSymmetrizeJoinDetails:
    """Test join details symmetrization functionality."""

    def test_symmetrize_join_details_basic(self):
        """Test basic symmetrization of join details."""
        # Arrange
        join_details_map = {"dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]}]}

        # Act
        symmetrize_join_details(join_details_map)

        # Assert
        assert "dc2" in join_details_map
        assert len(join_details_map["dc2"]) == 1

        dc2_join = join_details_map["dc2"][0]
        assert dc2_join["on_columns"] == ["id"]
        assert dc2_join["how"] == "inner"
        assert dc2_join["with_dc"] == ["dc1"]

    def test_symmetrize_join_details_already_symmetric(self):
        """Test symmetrization when joins are already symmetric."""
        # Arrange
        join_details_map = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]}],
            "dc2": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc1"]}],
        }
        original_dc2_joins = len(join_details_map["dc2"])

        # Act
        symmetrize_join_details(join_details_map)

        # Assert
        # Should not add duplicate symmetric joins
        assert len(join_details_map["dc2"]) == original_dc2_joins
        assert len(join_details_map["dc1"]) == 1

    def test_symmetrize_join_details_multiple_with_dc(self):
        """Test symmetrization with multiple related data collections."""
        # Arrange
        join_details_map = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2", "dc3"]}]
        }

        # Act
        symmetrize_join_details(join_details_map)

        # Assert
        assert "dc2" in join_details_map
        assert "dc3" in join_details_map

        # Check dc2 symmetric join
        dc2_join = join_details_map["dc2"][0]
        assert dc2_join["on_columns"] == ["id"]
        assert dc2_join["how"] == "inner"
        assert dc2_join["with_dc"] == ["dc1"]

        # Check dc3 symmetric join
        dc3_join = join_details_map["dc3"][0]
        assert dc3_join["on_columns"] == ["id"]
        assert dc3_join["how"] == "inner"
        assert dc3_join["with_dc"] == ["dc1"]

    def test_symmetrize_join_details_complex_network(self):
        """Test symmetrization with a complex network of joins."""
        # Arrange
        join_details_map = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]}],
            "dc2": [{"on_columns": ["ref_id"], "how": "left", "with_dc": ["dc3"]}],
        }

        # Act
        symmetrize_join_details(join_details_map)

        # Assert
        assert len(join_details_map) == 3

        # Check dc1 -> dc2 symmetric relationship
        dc2_joins = [j for j in join_details_map["dc2"] if "dc1" in j["with_dc"]]
        assert len(dc2_joins) == 1
        assert dc2_joins[0]["on_columns"] == ["id"]
        assert dc2_joins[0]["how"] == "inner"

        # Check dc2 -> dc3 symmetric relationship
        dc3_joins = join_details_map["dc3"]
        assert len(dc3_joins) == 1
        assert dc3_joins[0]["on_columns"] == ["ref_id"]
        assert dc3_joins[0]["how"] == "left"
        assert dc3_joins[0]["with_dc"] == ["dc2"]

    def test_symmetrize_join_details_empty_input(self):
        """Test symmetrization with empty input."""
        # Arrange
        join_details_map = {}

        # Act
        symmetrize_join_details(join_details_map)

        # Assert
        assert join_details_map == {}

    def test_symmetrize_join_details_multiple_joins_per_dc(self):
        """Test symmetrization with multiple joins per data collection."""
        # Arrange
        join_details_map = {
            "dc1": [
                {"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]},
                {"on_columns": ["category_id"], "how": "left", "with_dc": ["dc3"]},
            ]
        }

        # Act
        symmetrize_join_details(join_details_map)

        # Assert
        assert "dc2" in join_details_map
        assert "dc3" in join_details_map

        # Check dc2 has symmetric join with dc1
        dc2_join = join_details_map["dc2"][0]
        assert dc2_join["on_columns"] == ["id"]
        assert dc2_join["how"] == "inner"
        assert dc2_join["with_dc"] == ["dc1"]

        # Check dc3 has symmetric join with dc1
        dc3_join = join_details_map["dc3"][0]
        assert dc3_join["on_columns"] == ["category_id"]
        assert dc3_join["how"] == "left"
        assert dc3_join["with_dc"] == ["dc1"]


class TestGenerateJoinDict:
    """Test join dictionary generation functionality."""

    def test_generate_join_dict_basic(self):
        """Test basic join dictionary generation."""
        # Arrange
        workflow = {
            "_id": ObjectId(),
            "data_collections": [
                {
                    "_id": ObjectId(),
                    "data_collection_tag": "users",
                    "config": {
                        "type": "table",
                        "join": {"how": "inner", "on_columns": ["user_id"], "with_dc": ["orders"]},
                    },
                },
                {"_id": ObjectId(), "data_collection_tag": "orders", "config": {"type": "table"}},
            ],
        }

        # Act
        result = generate_join_dict(workflow)

        # Assert
        wf_id = str(workflow["_id"])
        assert wf_id in result
        assert len(result[wf_id]) == 1

        # Check the join configuration
        join_key = list(result[wf_id].keys())[0]
        join_config = result[wf_id][join_key]
        assert join_config["how"] == "inner"
        assert join_config["on_columns"] == ["user_id"]
        assert "users" in join_config["dc_tags"]
        assert "orders" in join_config["dc_tags"]

    def test_generate_join_dict_no_joins(self):
        """Test join dictionary generation with no joins configured."""
        # Arrange
        workflow = {
            "_id": ObjectId(),
            "data_collections": [
                {
                    "_id": ObjectId(),
                    "data_collection_tag": "standalone",
                    "config": {"type": "table"},
                }
            ],
        }

        # Act
        result = generate_join_dict(workflow)

        # Assert
        wf_id = str(workflow["_id"])
        assert wf_id in result
        assert len(result[wf_id]) == 0

    def test_generate_join_dict_multiple_joins(self):
        """Test join dictionary generation with multiple joins."""
        # Arrange
        dc1_id = ObjectId()
        dc2_id = ObjectId()
        dc3_id = ObjectId()

        workflow = {
            "_id": ObjectId(),
            "data_collections": [
                {
                    "_id": dc1_id,
                    "data_collection_tag": "users",
                    "config": {
                        "type": "table",
                        "join": {"how": "inner", "on_columns": ["user_id"], "with_dc": ["orders"]},
                    },
                },
                {
                    "_id": dc2_id,
                    "data_collection_tag": "orders",
                    "config": {
                        "type": "table",
                        "join": {
                            "how": "left",
                            "on_columns": ["product_id"],
                            "with_dc": ["products"],
                        },
                    },
                },
                {"_id": dc3_id, "data_collection_tag": "products", "config": {"type": "table"}},
            ],
        }

        # Act
        result = generate_join_dict(workflow)

        # Assert
        wf_id = str(workflow["_id"])
        assert wf_id in result
        assert len(result[wf_id]) == 2  # Two join configurations

        # Verify join configurations exist
        join_keys = list(result[wf_id].keys())
        assert any(f"{dc1_id}--{dc2_id}" in key for key in join_keys)
        assert any(f"{dc2_id}--{dc3_id}" in key for key in join_keys)

    def test_generate_join_dict_non_table_collections(self):
        """Test join dictionary generation excluding non-table collections."""
        # Arrange
        workflow = {
            "_id": ObjectId(),
            "data_collections": [
                {
                    "_id": ObjectId(),
                    "data_collection_tag": "table_data",
                    "config": {
                        "type": "table",
                        "join": {"how": "inner", "on_columns": ["id"], "with_dc": ["other_table"]},
                    },
                },
                {
                    "_id": ObjectId(),
                    "data_collection_tag": "other_table",
                    "config": {"type": "table"},
                },
                {
                    "_id": ObjectId(),
                    "data_collection_tag": "image_data",
                    "config": {
                        "type": "image"  # Non-table type
                    },
                },
            ],
        }

        # Act
        result = generate_join_dict(workflow)

        # Assert
        wf_id = str(workflow["_id"])
        assert wf_id in result
        # Should only process table-type collections
        assert len(result[wf_id]) == 1

    def test_generate_join_dict_circular_joins(self):
        """Test join dictionary generation with circular joins."""
        # Arrange
        dc1_id = ObjectId()
        dc2_id = ObjectId()
        dc3_id = ObjectId()

        workflow = {
            "_id": ObjectId(),
            "data_collections": [
                {
                    "_id": dc1_id,
                    "data_collection_tag": "dc1",
                    "config": {
                        "type": "table",
                        "join": {"how": "inner", "on_columns": ["id"], "with_dc": ["dc2"]},
                    },
                },
                {
                    "_id": dc2_id,
                    "data_collection_tag": "dc2",
                    "config": {
                        "type": "table",
                        "join": {"how": "inner", "on_columns": ["id"], "with_dc": ["dc3"]},
                    },
                },
                {
                    "_id": dc3_id,
                    "data_collection_tag": "dc3",
                    "config": {
                        "type": "table",
                        "join": {
                            "how": "inner",
                            "on_columns": ["id"],
                            "with_dc": ["dc1"],  # Circular reference
                        },
                    },
                },
            ],
        }

        # Act
        result = generate_join_dict(workflow)

        # Assert
        wf_id = str(workflow["_id"])
        assert wf_id in result
        # Should handle circular references without infinite recursion
        assert len(result[wf_id]) >= 1


class TestNormalizeJoinDetails:
    """Test join details normalization functionality."""

    def test_normalize_join_details_basic(self):
        """Test basic normalization of join details."""
        # Arrange
        join_details = {
            "dc1": [
                {"on_columns": ["id"], "how": "inner", "with_dc": ["tag1"], "with_dc_id": ["dc2"]}
            ]
        }

        # Act
        result = normalize_join_details(join_details)

        # Assert
        assert "dc1" in result
        assert "dc2" in result

        # Check dc1 normalization
        dc1_normalized = result["dc1"]
        assert dc1_normalized["on_columns"] == ["id"]
        assert dc1_normalized["how"] == "inner"
        assert "tag1" in dc1_normalized["with_dc"]
        assert "dc2" in dc1_normalized["with_dc_id"]

        # Check reciprocal relationship in dc2
        dc2_normalized = result["dc2"]
        assert dc2_normalized["on_columns"] == ["id"]
        assert dc2_normalized["how"] == "inner"
        assert "dc1" in dc2_normalized["with_dc_id"]

    def test_normalize_join_details_multiple_relationships(self):
        """Test normalization with multiple relationships."""
        # Arrange
        join_details = {
            "dc1": [
                {
                    "on_columns": ["id"],
                    "how": "inner",
                    "with_dc": ["tag2", "tag3"],
                    "with_dc_id": ["dc2", "dc3"],
                }
            ]
        }

        # Act
        result = normalize_join_details(join_details)

        # Assert
        assert len(result) == 3  # dc1, dc2, dc3

        dc1_normalized = result["dc1"]
        assert set(dc1_normalized["with_dc"]) == {"tag2", "tag3"}
        assert set(dc1_normalized["with_dc_id"]) == {"dc2", "dc3"}

        # Check reciprocal relationships
        assert "dc1" in result["dc2"]["with_dc_id"]
        assert "dc1" in result["dc3"]["with_dc_id"]

    def test_normalize_join_details_existing_reciprocal(self):
        """Test normalization when reciprocal relationships already exist."""
        # Arrange
        join_details = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc_id": ["dc2"]}],
            "dc2": [{"on_columns": ["id"], "how": "inner", "with_dc_id": ["dc1"]}],
        }

        # Act
        result = normalize_join_details(join_details)

        # Assert
        assert len(result) == 2
        assert "dc2" in result["dc1"]["with_dc_id"]
        assert "dc1" in result["dc2"]["with_dc_id"]

        # Should not create duplicates
        assert len(result["dc1"]["with_dc_id"]) == 1
        assert len(result["dc2"]["with_dc_id"]) == 1

    def test_normalize_join_details_mixed_relationships(self):
        """Test normalization with mixed tag and ID relationships."""
        # Arrange
        join_details = {
            "dc1": [
                {
                    "on_columns": ["user_id"],
                    "how": "left",
                    "with_dc": ["users_tag"],
                    "with_dc_id": ["dc2"],
                }
            ],
            "dc3": [{"on_columns": ["product_id"], "how": "inner", "with_dc": ["products_tag"]}],
        }

        # Act
        result = normalize_join_details(join_details)

        # Assert
        assert len(result) >= 2

        # Check dc1 relationships
        dc1_normalized = result["dc1"]
        assert "users_tag" in dc1_normalized["with_dc"]
        assert "dc2" in dc1_normalized["with_dc_id"]

        # Check dc3 relationships
        dc3_normalized = result["dc3"]
        assert "products_tag" in dc3_normalized["with_dc"]

    def test_normalize_join_details_empty_input(self):
        """Test normalization with empty input."""
        # Arrange
        join_details = {}

        # Act
        result = normalize_join_details(join_details)

        # Assert
        assert result == {}

    def test_normalize_join_details_duplicate_prevention(self):
        """Test that normalization prevents duplicate relationships."""
        # Arrange
        join_details = {
            "dc1": [
                {
                    "on_columns": ["id"],
                    "how": "inner",
                    "with_dc_id": ["dc2", "dc2"],  # Duplicate relationship
                }
            ]
        }

        # Act
        result = normalize_join_details(join_details)

        # Assert
        dc1_normalized = result["dc1"]
        # Should remove duplicates due to set usage
        assert len(dc1_normalized["with_dc_id"]) == 1
        assert dc1_normalized["with_dc_id"] == ["dc2"]
