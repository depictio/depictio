"""Schema readers skip an aggregation that does not describe the table yet.

An offloaded upsert appends its aggregation as ``pending`` with no column specs
while a job computes them, for minutes on a large table, and for good when the
job fails or is cancelled. A row edit from the table-management endpoints
records no specs either. Every reader took ``aggregation[-1]``, so in that
window ``/specs`` answered ``[]``, schema integrity reported every column as
removed, and a dashboard save stamped an empty schema.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId

from depictio.models.models.deltatables import latest_complete_aggregation

COMPLETE_SPECS = [{"name": "sepal_length", "type": "float64", "specs": {}}]


def _complete(version: int, **extra) -> dict:
    return {
        "aggregation_version": version,
        "aggregation_status": "complete",
        "aggregation_columns_specs": COMPLETE_SPECS,
        "delta_version": version - 1,
        "rows_total": 150,
        **extra,
    }


def _pending(version: int) -> dict:
    return {
        "aggregation_version": version,
        "aggregation_status": "pending",
        "aggregation_columns_specs": [],
        "delta_version": version - 1,
        "rows_total": 300,
    }


class TestLatestCompleteAggregation:
    def test_a_pending_entry_after_a_complete_one_reads_the_complete_one(self):
        assert latest_complete_aggregation([_complete(1), _pending(2)])["aggregation_version"] == 1

    def test_a_row_edit_without_specs_is_passed_over(self):
        row_edit = {"aggregation_version": 2, "aggregation_columns_specs": []}

        assert latest_complete_aggregation([_complete(1), row_edit])["aggregation_version"] == 1

    def test_the_newest_complete_entry_wins(self):
        assert latest_complete_aggregation([_complete(1), _complete(2)])["aggregation_version"] == 2

    def test_an_entry_from_before_the_status_field_counts_as_complete(self):
        legacy = {"aggregation_version": 1, "aggregation_columns_specs": COMPLETE_SPECS}

        assert latest_complete_aggregation([legacy]) is legacy

    @pytest.mark.parametrize("aggregations", [None, [], [_pending(1)]])
    def test_nothing_qualifies(self, aggregations):
        assert latest_complete_aggregation(aggregations) is None


@pytest.fixture
def stored(monkeypatch):
    """A data collection whose newest aggregation is still pending."""
    from depictio.api.v1 import db as api_db
    from depictio.api.v1.endpoints.dashboards_endpoints import schema_integrity, versioning
    from depictio.api.v1.endpoints.deltatables_endpoints import routes as dt_routes

    database = mongomock.MongoClient().db
    dc_id = ObjectId()
    database.projects.insert_one(
        {
            "_id": ObjectId(),
            "workflows": [{"data_collections": [{"_id": dc_id, "config": {"type": "table"}}]}],
        }
    )
    database.deltatables.insert_one(
        {"data_collection_id": dc_id, "aggregation": [_complete(1), _pending(2)]}
    )
    for module in (dt_routes, schema_integrity, versioning, api_db):
        monkeypatch.setattr(module, "deltatables_collection", database.deltatables)
    monkeypatch.setattr(dt_routes, "projects_collection", database.projects)
    return dc_id


def test_specs_endpoint_serves_the_complete_schema(stored):
    from depictio.api.v1.endpoints.deltatables_endpoints.routes import specs

    admin = SimpleNamespace(id=ObjectId(), is_admin=True)

    result = asyncio.run(specs(stored, current_user=admin))

    assert [column["name"] for column in result] == ["sepal_length"]


def test_specs_endpoint_answers_empty_when_nothing_is_complete(stored, monkeypatch):
    from depictio.api.v1.endpoints.deltatables_endpoints import routes as dt_routes

    dt_routes.deltatables_collection.update_one(
        {"data_collection_id": stored}, {"$set": {"aggregation": [_pending(1)]}}
    )
    admin = SimpleNamespace(id=ObjectId(), is_admin=True)

    assert asyncio.run(dt_routes.specs(stored, current_user=admin)) == []


def test_schema_integrity_reads_the_complete_schema(stored):
    from depictio.api.v1.endpoints.dashboards_endpoints.schema_integrity import read_dc_schema

    schema = read_dc_schema(str(stored))

    assert schema["columns"] == [{"name": "sepal_length", "type": "float64"}]
    assert schema["aggregation_version"] == 1


def test_group_resolution_reads_the_complete_column_names(stored):
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _dc_column_names

    assert _dc_column_names(str(stored)) == {"sepal_length"}


def test_a_version_stamp_pins_the_newest_commit_with_the_known_schema(stored):
    """Data from the newest entry, schema from the newest described one.

    The Delta commit of a pending entry already exists and is what live reads
    serve, so a time-travel read of this version must pin it. Pinning the
    older complete entry instead would show older data than the user saw.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import build_dc_stamps
    from depictio.models.models.dashboard_versions import TabSnapshot

    tab = TabSnapshot(
        dashboard_id=str(ObjectId()),
        stored_metadata=[{"index": "a", "dc_id": str(stored), "dc_config": {"type": "table"}}],
    )

    (stamp,) = build_dc_stamps([tab])

    assert stamp.delta_version == 1
    assert stamp.aggregation_version == 2
    assert [column["name"] for column in stamp.columns] == ["sepal_length"]
