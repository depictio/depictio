"""
Tests for server-side join utilities.

Note: Join execution tests are in depictio/tests/cli/utils/test_joins.py
since joins execute client-side in the CLI. These tests focus on
server-side metadata generation and symmetrization.
"""

from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    generate_join_dict,
    normalize_join_details,
    symmetrize_join_details,
)


class TestSymmetrizeJoinDetails:
    """Test join details symmetrization functionality."""

    def test_basic_symmetrization(self):
        """Creates symmetric join entry for the related DC."""
        join_details_map = {"dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]}]}

        symmetrize_join_details(join_details_map)

        assert "dc2" in join_details_map
        dc2_join = join_details_map["dc2"][0]
        assert dc2_join["on_columns"] == ["id"]
        assert dc2_join["how"] == "inner"
        assert dc2_join["with_dc"] == ["dc1"]

    def test_already_symmetric_no_duplicates(self):
        """Does not add duplicates when joins are already symmetric."""
        join_details_map = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]}],
            "dc2": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc1"]}],
        }

        symmetrize_join_details(join_details_map)

        assert len(join_details_map["dc1"]) == 1
        assert len(join_details_map["dc2"]) == 1

    def test_multiple_related_dcs(self):
        """Creates symmetric entries for each related DC."""
        join_details_map = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2", "dc3"]}]
        }

        symmetrize_join_details(join_details_map)

        assert join_details_map["dc2"][0]["with_dc"] == ["dc1"]
        assert join_details_map["dc3"][0]["with_dc"] == ["dc1"]

    def test_complex_network(self):
        """Handles chains of relationships (dc1 -> dc2 -> dc3)."""
        join_details_map = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]}],
            "dc2": [{"on_columns": ["ref_id"], "how": "left", "with_dc": ["dc3"]}],
        }

        symmetrize_join_details(join_details_map)

        assert len(join_details_map) == 3
        dc2_to_dc1 = [j for j in join_details_map["dc2"] if "dc1" in j["with_dc"]]
        assert len(dc2_to_dc1) == 1
        assert join_details_map["dc3"][0]["with_dc"] == ["dc2"]

    def test_empty_input(self):
        """Empty input remains empty."""
        join_details_map = {}
        symmetrize_join_details(join_details_map)
        assert join_details_map == {}

    def test_multiple_joins_per_dc(self):
        """Each join definition gets its own symmetric entry."""
        join_details_map = {
            "dc1": [
                {"on_columns": ["id"], "how": "inner", "with_dc": ["dc2"]},
                {"on_columns": ["category_id"], "how": "left", "with_dc": ["dc3"]},
            ]
        }

        symmetrize_join_details(join_details_map)

        assert join_details_map["dc2"][0]["on_columns"] == ["id"]
        assert join_details_map["dc3"][0]["on_columns"] == ["category_id"]


class TestGenerateJoinDict:
    """Test join dictionary generation for server-side metadata."""

    def test_basic_project_level_join(self):
        """Generates join dict from project-level join definitions."""
        result_dc_id = ObjectId()
        workflow_id = ObjectId()
        workflow = {
            "_id": workflow_id,
            "name": "test_workflow",
            "data_collections": [
                {"_id": ObjectId(), "data_collection_tag": "users", "config": {"type": "table"}},
                {"_id": ObjectId(), "data_collection_tag": "orders", "config": {"type": "table"}},
                {
                    "_id": result_dc_id,
                    "data_collection_tag": "users_orders_joined",
                    "config": {"type": "table"},
                },
            ],
        }
        project = {
            "joins": [
                {
                    "name": "users_orders",
                    "workflow_name": "test_workflow",
                    "left_dc": "users",
                    "right_dc": "orders",
                    "on_columns": ["user_id"],
                    "how": "inner",
                    "result_dc_id": str(result_dc_id),
                    "description": "Join users with orders",
                }
            ]
        }

        result = generate_join_dict(workflow, project)

        wf_id = str(workflow_id)
        assert wf_id in result
        assert str(result_dc_id) in result[wf_id]

        join_config = result[wf_id][str(result_dc_id)]
        assert join_config["how"] == "inner"
        assert join_config["on_columns"] == ["user_id"]
        assert join_config["dc_tags"] == ["users", "orders"]
        assert join_config["join_name"] == "users_orders"

    def test_no_joins_returns_empty(self):
        """Returns empty join dict when no joins are configured."""
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

        result = generate_join_dict(workflow)

        assert len(result[str(workflow["_id"])]) == 0


class TestNormalizeJoinDetails:
    """Test join details normalization functionality."""

    def test_basic_normalization(self):
        """Normalizes join details and creates reciprocal relationships."""
        join_details = {
            "dc1": [
                {"on_columns": ["id"], "how": "inner", "with_dc": ["tag1"], "with_dc_id": ["dc2"]}
            ]
        }

        result = normalize_join_details(join_details)

        assert "dc1" in result
        assert "dc2" in result
        assert result["dc1"]["on_columns"] == ["id"]
        assert "dc1" in result["dc2"]["with_dc_id"]

    def test_multiple_relationships(self):
        """Handles multiple relationships from a single DC."""
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

        result = normalize_join_details(join_details)

        assert len(result) == 3
        assert set(result["dc1"]["with_dc_id"]) == {"dc2", "dc3"}
        assert "dc1" in result["dc2"]["with_dc_id"]
        assert "dc1" in result["dc3"]["with_dc_id"]

    def test_existing_reciprocal_no_duplicates(self):
        """Does not duplicate existing reciprocal relationships."""
        join_details = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc_id": ["dc2"]}],
            "dc2": [{"on_columns": ["id"], "how": "inner", "with_dc_id": ["dc1"]}],
        }

        result = normalize_join_details(join_details)

        assert len(result["dc1"]["with_dc_id"]) == 1
        assert len(result["dc2"]["with_dc_id"]) == 1

    def test_mixed_tag_and_id_relationships(self):
        """Handles mixed with_dc (tags) and with_dc_id (IDs)."""
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

        result = normalize_join_details(join_details)

        assert "users_tag" in result["dc1"]["with_dc"]
        assert "products_tag" in result["dc3"]["with_dc"]

    def test_empty_input(self):
        """Empty input returns empty result."""
        assert normalize_join_details({}) == {}

    def test_duplicate_prevention(self):
        """Removes duplicate relationships."""
        join_details = {
            "dc1": [{"on_columns": ["id"], "how": "inner", "with_dc_id": ["dc2", "dc2"]}]
        }

        result = normalize_join_details(join_details)

        assert result["dc1"]["with_dc_id"] == ["dc2"]
