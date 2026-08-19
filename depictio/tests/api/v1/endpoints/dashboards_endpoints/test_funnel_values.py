"""Tests for the funnel-filtering endpoint (issue #939).

Pins the core contract:
- each target's available values are computed under the current filters MINUS
  that target's own selection (a picked value must never grey itself out);
- a target reached by no other active filter is reported ``unrestricted``
  (and no query runs for it);
- ``include_stages`` returns the cumulative per-DC row counts that back the
  funnel overview;
- unknown targets are ``unsupported``.
"""

from unittest.mock import patch

import mongomock
import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints.routes import funnel_values_endpoint

DC1 = str(ObjectId())
PROJECT_ID = ObjectId()
WF_ID = str(ObjectId())
DASHBOARD_ID = str(ObjectId())

BASE_DF = pl.DataFrame(
    {
        "habitat": ["Groundwater", "Groundwater", "Riverwater"],
        "depth": ["1", "2", "3"],
    }
)


def _dashboard_doc() -> dict:
    def interactive(index: str, column: str) -> dict:
        return {
            "index": index,
            "component_type": "interactive",
            "interactive_component_type": "MultiSelect",
            "dc_id": DC1,
            "wf_id": WF_ID,
            "column_name": column,
            "dc_config": {"delta_location": f"memory://{DC1}", "type": "table"},
        }

    return {
        "dashboard_id": DASHBOARD_ID,
        "project_id": PROJECT_ID,
        "stored_metadata": [
            interactive("comp-habitat", "habitat"),
            interactive("comp-depth", "depth"),
            {
                "index": "fig-1",
                "component_type": "figure",
                "dc_id": DC1,
                "wf_id": WF_ID,
                "dc_config": {"delta_location": f"memory://{DC1}", "type": "table"},
            },
        ],
    }


def _fake_load(workflow_id, data_collection_id, metadata=None, init_data=None, **kwargs):
    df = BASE_DF
    for f in metadata or []:
        column = f.get("column_name")
        value = f.get("value")
        values = value if isinstance(value, list) else [value]
        if column in df.columns:
            df = df.filter(pl.col(column).is_in([str(v) for v in values]))
    select_columns = kwargs.get("select_columns")
    if select_columns:
        df = df.select([c for c in select_columns if c in df.columns])
    return df


def _filter(index: str, column: str, value) -> dict:
    return {
        "index": index,
        "value": value,
        "column_name": column,
        "interactive_component_type": "MultiSelect",
        "metadata": {"dc_id": DC1, "column_name": column},
    }


@pytest.fixture
def patched_env():
    client = mongomock.MongoClient()
    db = client.test_db
    db.dashboards.insert_one(_dashboard_doc())
    db.projects.insert_one({"_id": PROJECT_ID, "workflows": []})

    routes_mod = "depictio.api.v1.endpoints.dashboards_endpoints.routes"
    with (
        patch(f"{routes_mod}.dashboards_collection", db.dashboards),
        patch(f"{routes_mod}.projects_collection", db.projects),
        patch(f"{routes_mod}.check_project_permission", lambda *a, **k: True),
        patch(
            f"{routes_mod}._resolve_link_filters_cached",
            lambda **kw: list(kw["filters"]),
        ),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", _fake_load),
    ):
        yield
        client.close()


def _call(filters, target_indexes, include_stages=False):
    return funnel_values_endpoint(
        dashboard_id=DASHBOARD_ID,  # type: ignore[arg-type]
        request={
            "filters": filters,
            "target_indexes": target_indexes,
            "include_stages": include_stages,
        },
        current_user=object(),  # permission check is patched out
        access_token=None,
    )


def test_own_selection_is_excluded(patched_env):
    """comp-habitat's availability reflects only the depth filter — its own
    habitat selection must not restrict itself."""
    filters = [
        _filter("comp-habitat", "habitat", ["Groundwater"]),
        _filter("comp-depth", "depth", ["3"]),
    ]
    result = _call(filters, ["comp-habitat"])
    target = result["targets"]["comp-habitat"]
    assert target["status"] == "ok"
    # depth == 3 → only the Riverwater row survives, even though the user's
    # own habitat selection is Groundwater.
    assert target["values"] == ["Riverwater"]


def test_other_component_sees_narrowed_values(patched_env):
    filters = [
        _filter("comp-habitat", "habitat", ["Groundwater"]),
        _filter("comp-depth", "depth", ["3"]),
    ]
    result = _call(filters, ["comp-depth"])
    target = result["targets"]["comp-depth"]
    assert target["status"] == "ok"
    assert target["values"] == ["1", "2"]


def test_unrestricted_when_no_other_filter(patched_env):
    """With only its own filter active, a component is unrestricted."""
    filters = [_filter("comp-habitat", "habitat", ["Groundwater"])]
    result = _call(filters, ["comp-habitat"])
    assert result["targets"]["comp-habitat"]["status"] == "unrestricted"


def test_unknown_target_is_unsupported(patched_env):
    result = _call([], ["nope"])
    assert result["targets"]["nope"]["status"] == "unsupported"


def test_stages_report_cumulative_counts(patched_env):
    filters = [
        _filter("comp-habitat", "habitat", ["Groundwater"]),
        _filter("comp-depth", "depth", ["3"]),
    ]
    result = _call(filters, [], include_stages=True)
    assert result["initial_rows_by_dc"] == {DC1: 3}
    stages = result["stages"]
    assert len(stages) == 2
    assert stages[0]["rows_by_dc"] == {DC1: 2}  # habitat=Groundwater
    assert stages[1]["rows_by_dc"] == {DC1: 0}  # + depth=3 → nothing left
    assert result["filter_count"] == 2


def test_inactive_filters_are_ignored(patched_env):
    filters = [
        _filter("comp-habitat", "habitat", []),
        _filter("comp-depth", "depth", ["3"]),
    ]
    result = _call(filters, [], include_stages=True)
    assert result["filter_count"] == 1
    assert len(result["stages"]) == 1
