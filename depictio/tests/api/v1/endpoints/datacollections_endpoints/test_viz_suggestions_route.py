"""Contract of GET /datacollections/viz-suggestions/{id}: match, reasons, context."""

from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import routes

SCHEMA = {
    "assembly_id": "String",
    "n_contigs": "Int64",
    "total_length": "Int64",
    "n50": "Int64",
    "l50": "Int64",
    "gc_percent": "Float64",
}


async def _call(**query):
    with (
        patch.object(
            routes,
            "_get_data_collection_specs",
            AsyncMock(return_value={"config": {"type": "table"}}),
        ),
        patch.object(routes, "_get_data_collection_polars_schema", AsyncMock(return_value=SCHEMA)),
    ):
        return await routes.viz_suggestions(
            data_collection_id=ObjectId(),  # type: ignore[arg-type]
            min_confidence=0.0,
            selection_columns=query.get("selection_columns"),
            existing_kinds=query.get("existing_kinds"),
            current_user="user",
        )


@pytest.mark.asyncio
async def test_every_entry_carries_match_and_reasons() -> None:
    body = await _call()
    for entry in body["viz_kinds"]:
        assert entry["match"] in {"named", "shape", "context", "weak"}
        assert isinstance(entry["reasons"], list)
    by = {e["viz_kind"]: e for e in body["viz_kinds"]}
    assert by["record_card"]["match"] == "weak"


@pytest.mark.asyncio
async def test_selection_columns_make_the_record_card_a_context_match() -> None:
    body = await _call(selection_columns=["assembly_id"], existing_kinds=["scatter_xy"])
    by = {e["viz_kind"]: e for e in body["viz_kinds"]}
    assert by["record_card"]["match"] == "context"
    assert by["record_card"]["score"] >= 0.8
    assert "already used on this tab" in by["scatter_xy"]["reasons"]
