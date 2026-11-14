"""A recipe aggregation's lineage survives a Mongo round trip (epic #1399)."""

from __future__ import annotations

from bson import ObjectId

from depictio.models.models.deltatables import AggregationInput, DeltaTableAggregated


def test_an_input_read_back_from_mongo_keeps_its_collection_id():
    # Mongo hands an id back as an ObjectId: the next write re-reads the
    # document, and must not fail on its own lineage.
    dc_id = ObjectId()
    assert AggregationInput(dc_id=dc_id, dc_tag="metadata", delta_version=2).dc_id == str(dc_id)


def test_a_stored_aggregation_with_inputs_loads():
    doc = {
        "_id": ObjectId(),
        "data_collection_id": ObjectId(),
        "delta_table_location": "s3://bucket/x",
        "aggregation": [
            {
                "aggregation_time": "2026-11-13T10:00:00",
                "aggregation_by": {"id": ObjectId(), "email": "a@b.c", "is_admin": True},
                "aggregation_version": 1,
                "aggregation_hash": "h",
                "run_scope": "aggregate",
                "computed_from_runs": ["run_athens", "run_barcelona"],
                "inputs": [{"dc_id": ObjectId(), "dc_tag": "metadata", "delta_version": 2}],
            }
        ],
    }
    table = DeltaTableAggregated.from_mongo(doc)
    [agg] = table.aggregation
    assert agg.run_scope == "aggregate"
    assert isinstance(agg.inputs[0].dc_id, str)
