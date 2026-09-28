"""``compose_offers_for_project`` is the auth-free body of the compose route.

The matching signals themselves are covered in
``test_catalog_compose_matching.py``. This file pins the extraction: a plain
project document in, ``{"modules": [...]}`` out, and ``compose_project``
returning exactly that after its permission gate. The recipe lane needs no
files collection, so a recipe DC keeps these tests DB-free.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from bson import ObjectId

from depictio.api.v1.endpoints.catalog_endpoints import routes as catalog_routes


def _project(*data_collections: dict) -> dict:
    return {
        "_id": ObjectId(),
        "name": "A project",
        "workflows": [
            {"_id": ObjectId(), "name": "wf", "data_collections": list(data_collections)}
        ],
    }


def _recipe_dc(tag: str, recipe: str) -> dict:
    """A recipe DC computed straight into a delta table: `scan: null`, known by what built it."""
    return {
        "_id": ObjectId(),
        "data_collection_tag": tag,
        "config": {
            "type": "table",
            "source": "transformed",
            "transform": {"recipe": recipe},
            "scan": None,
        },
    }


def _offer_ids(result: dict) -> set[str]:
    return {m["output_id"] for module in result["modules"] for m in module["matches"]}


class TestComposeOffersForProject:
    def test_empty_project_has_no_offers(self):
        assert catalog_routes.compose_offers_for_project({"workflows": []}) == {"modules": []}
        assert catalog_routes.compose_offers_for_project({}) == {"modules": []}

    def test_recipe_dc_is_offered_with_its_collection_identity(self):
        dc = _recipe_dc("ancombc_results", "qiime2/ancombc.py")
        project = _project(dc)

        result = catalog_routes.compose_offers_for_project(project)

        assert _offer_ids(result) == {"qiime2_ancombc"}
        (module,) = result["modules"]
        assert module["tool_id"] == "qiime2"
        (match,) = module["matches"]
        assert match["dc_id"] == str(dc["_id"])
        assert match["wf_id"] == str(project["workflows"][0]["_id"])
        assert match["dc_tag"] == "ancombc_results"
        assert match["dc_type"] == "table"

    def test_non_matchable_types_are_skipped(self):
        dc = _recipe_dc("tree", "qiime2/ancombc.py")
        dc["config"]["type"] = "phylogeny"
        assert catalog_routes.compose_offers_for_project(_project(dc)) == {"modules": []}

    def test_malformed_collections_are_skipped(self):
        project = _project("not-a-dict", {"data_collection_tag": "x", "config": None})
        assert catalog_routes.compose_offers_for_project(project) == {"modules": []}


class TestRouteDelegates:
    def test_compose_project_returns_the_helper_result(self):
        dc = _recipe_dc("ancombc_results", "qiime2/ancombc.py")
        project = _project(dc)

        admin = MagicMock()
        admin.id = ObjectId()
        admin.is_admin = True
        fake_projects = MagicMock()
        fake_projects.find_one.return_value = project

        with patch.object(catalog_routes, "projects_collection", fake_projects):
            via_route = asyncio.run(
                catalog_routes.compose_project(str(project["_id"]), current_user=admin)
            )

        assert via_route == catalog_routes.compose_offers_for_project(project)
        assert _offer_ids(via_route) == {"qiime2_ancombc"}
        fake_projects.find_one.assert_called_once_with({"_id": project["_id"]})
