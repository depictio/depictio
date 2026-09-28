"""Data tools: component data, collection profile and sandboxed queries, through ``invoke``.

The Delta loaders are replaced by an in-memory frame that goes through the
real ``apply_runtime_filters``, so filters behave as in the viewer. The
sandbox is the in-process ``InlineSandbox``.
"""

import asyncio
import sys
import time
from unittest.mock import patch

import polars as pl
import pytest

from depictio.api.v1.agents.envelope import json_size
from depictio.api.v1.agents.registry import invoke
from depictio.api.v1.agents.tools import data
from depictio.api.v1.configs.config import settings
from depictio.api.v1.deltatables_utils import apply_runtime_filters
from depictio.api.v1.endpoints.ai_endpoints import context as ai_context
from depictio.api.v1.endpoints.ai_endpoints.executor import execute_polars
from depictio.api.v1.endpoints.ai_endpoints.sandbox import InlineSandbox
from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.tests.api.v1.agents.test_tools_discovery import (  # noqa: F401 - fixture
    call,
    ctx_for,
    world,
)

LONG_NOTE = "Collected by the field team after the storm, see the lab notebook page 12"

FRAME = pl.DataFrame(
    {
        "sepal_length": [5.1, 4.9, 4.7, 7.0, 6.4, 6.9, 6.3, 5.8, 7.1],
        "sepal_width": [3.5, 3.0, 3.2, 3.2, 3.2, 3.1, 3.3, 2.7, 3.0],
        "petal_length": [1.4, 1.4, 1.3, 4.7, 4.5, 4.9, 6.0, 5.1, 5.9],
        "species": ["setosa"] * 3 + ["versicolor"] * 3 + ["virginica"] * 3,
        "contact": ["ann@example.org"] + ["n/a"] * 8,
        "notes": [LONG_NOTE] + ["ok"] * 8,
    }
)


@pytest.fixture
def loads(world):  # noqa: F811 - pytest fixture injection
    """Patch the Delta layer; yields the list of load calls."""
    calls = []

    def fake_load(workflow_id, data_collection_id, metadata=None, select_columns=None, **kw):
        calls.append({"metadata": metadata, "select_columns": select_columns})
        df = apply_runtime_filters(FRAME, metadata)
        return df.select(select_columns) if select_columns else df

    init = {world.dc_id: {"delta_location": "s3://bucket/iris", "dc_type": "table"}}
    with (
        patch.object(data, "load_deltatable_lite", side_effect=fake_load),
        patch.object(data, "count_deltatable_lite", return_value=FRAME.height),
        patch.object(data, "init_data_for_dc", return_value=init),
        patch.object(ai_context, "load_deltatable_lite", side_effect=fake_load),
        patch.object(ai_context, "init_data_for_dc", return_value=init),
    ):
        yield calls


def component_data(world, user=None, **args):  # noqa: F811
    args.setdefault("dashboard_id", world.main)
    return call("get_component_data", user or world.owner, **args)


def test_figure_data_group_view_and_columns(world, loads):  # noqa: F811
    result = component_data(world, index="fig-1", max_rows=4)
    assert result.ok, result.error
    out = result.data
    assert out["row_count"] == 9 and "total_row_count" not in out
    assert out["component_columns"] == ["sepal_length", "sepal_width", "species"]
    assert [c["name"] for c in out["columns"]] == out["component_columns"]
    assert loads[-1]["select_columns"] == ["sepal_length", "sepal_width", "species"]
    assert len(out["rows"]) == 4
    figure = out["figure"]
    assert figure["roles"] == {"x": "sepal_length", "y": "sepal_width", "color": "species"}
    assert isinstance(figure["pearson_x_y"], float)
    assert figure["by_color"]["group_count"] == 3
    sepal = next(c for c in out["columns"] if c["name"] == "sepal_length")
    assert sepal["max"] == 7.1 and sepal["dtype"] == "Float64"


def test_filters_narrow_like_the_viewer(world, loads):  # noqa: F811
    result = component_data(
        world,
        index="fig-1",
        filters=[
            {"column": "species", "value": "virginica"},
            {"column": "sepal_length", "operator": "ge", "value": "6"},
        ],
    )
    assert result.ok, result.error
    out = result.data
    assert out["row_count"] == 2 and out["total_row_count"] == 9
    assert out["filters_applied"][0] == {
        "column": "species",
        "widget": "MultiSelect",
        "value": ["virginica"],
    }
    assert out["filters_applied"][1]["filter_expr"] == {"untrusted": "col('sepal_length') >= 6.0"}
    between = component_data(
        world,
        index="fig-1",
        filters=[{"column": "petal_length", "operator": "between", "value": [4.5, 5.0]}],
    )
    assert between.data["row_count"] == 3


def test_saved_and_viewer_filters(world, loads):  # noqa: F811
    saved = component_data(world, index="fig-1", use_saved_filters=True)
    assert saved.data["row_count"] == 3  # the tab's Species widget is saved on virginica

    viewer = component_data(
        world,
        index="fig-1",
        viewer_filters=[
            {
                "index": "x",
                "column_name": "species",
                "interactive_component_type": "MultiSelect",
                "value": ["setosa"],
            },
            {"column_name": "habitat", "interactive_component_type": "MultiSelect", "value": ["a"]},
        ],
    )
    assert viewer.ok and viewer.data["row_count"] == 3
    assert viewer.data["filters_ignored"] == [
        {"column": "habitat", "reason": "not a column of this data collection"}
    ]


def test_unknown_filter_column_and_bad_values(world, loads):  # noqa: F811
    unknown = component_data(world, index="fig-1", filters=[{"column": "nope", "value": 1}])
    assert not unknown.ok and "Unknown column(s) nope" in unknown.error
    bad = component_data(
        world, index="fig-1", filters=[{"column": "species", "operator": "between", "value": 1}]
    )
    assert not bad.ok and bad.error.startswith("Invalid arguments")
    refused = component_data(
        world, index="fig-1", filters=[{"column": "species", "operator": "ne", "value": "import x"}]
    )
    assert not refused.ok and "refused" in refused.error
    unknown_col = component_data(world, index="fig-1", columns=["missing"])
    assert not unknown_col.ok and "missing" in unknown_col.error


def test_card_value_comes_from_the_card_route(world, loads):  # noqa: F811
    seen = {}

    def fake_cards(dashboard_id, request, current_user, access_token=None):
        seen.update(request=request, user=current_user, dashboard_id=dashboard_id)
        return {"values": {"card-1": 5.3}, "secondary_values": {"card-1": {"max": 6.0}}}

    with patch.object(dash_routes, "bulk_compute_cards", side_effect=fake_cards):
        result = component_data(
            world, index="card-1", filters=[{"column": "species", "value": "virginica"}]
        )
    assert result.ok, result.error
    card = result.data["card"]
    assert card == {
        "aggregation": "mean",
        "column": "petal_length",
        "value": 5.3,
        "secondary_values": {"max": 6.0},
    }
    assert seen["request"]["component_ids"] == ["card-1"]
    assert seen["request"]["filters"][0]["column_name"] == "species"
    assert seen["user"] is world.owner and str(seen["dashboard_id"]) == world.main


def test_interactive_options_and_text_component(world, loads):  # noqa: F811
    options = component_data(world, index="filter-1")
    assert options.ok and options.data["options"]["group_count"] == 3
    text = component_data(world, index="text-1")
    assert not text.ok and "has no data" in text.error


def test_rows_are_redacted_and_long_text_wrapped(world, loads):  # noqa: F811
    result = component_data(world, index="fig-1", columns=["contact", "notes"], max_rows=2)
    assert result.ok
    first = result.data["rows"][0]
    assert first["contact"] == "<email>"
    assert first["notes"] == {"untrusted": LONG_NOTE}
    assert result.data["rows"][1]["notes"] == "ok"


def test_ingest_bookkeeping_columns_are_left_out(world, loads, monkeypatch):  # noqa: F811
    stamped = FRAME.with_columns(
        pl.lit("2026-09-28 22:01:23").alias("aggregation_time"),
        pl.lit("run-1").alias("depictio_run_id"),
    )
    monkeypatch.setattr(sys.modules[__name__], "FRAME", stamped)
    result = component_data(world, index="fig-1", max_rows=1)
    assert result.ok
    names = {c["name"] for c in result.data["columns"]}
    assert not names & {"aggregation_time", "depictio_run_id"}
    assert "aggregation_time" not in result.data["rows"][0]


def test_permission_denied(world, loads):  # noqa: F811
    result = component_data(world, user=world.stranger, index="fig-1")
    assert not result.ok and "permission" in result.error
    assert loads == []


def test_timeout(world, loads):  # noqa: F811
    def slow(*a, **kw):
        time.sleep(0.5)
        return FRAME

    with (
        patch.object(data, "load_deltatable_lite", side_effect=slow),
        patch.object(settings.mcp, "query_timeout_s", 0.05),
    ):
        result = component_data(world, index="fig-1")
    assert not result.ok and "Timed out" in result.error


def test_budget_is_respected(world, loads):  # noqa: F811
    wide = pl.concat([FRAME] * 60)
    with patch.object(data, "load_deltatable_lite", return_value=wide):
        result = component_data(world, index="fig-1", columns=list(FRAME.columns), max_rows=500)
    assert result.ok and result.truncated
    assert json_size(result.data) <= settings.mcp.max_output_chars
    assert result.data["row_count"] == wide.height and result.data["rows"]


def test_describe_data_collection(world, loads):  # noqa: F811
    result = call("describe_data_collection", world.owner, dc_id=world.dc_id, sample_rows=2)
    assert result.ok, result.error
    out = result.data
    assert out["dc_tag"] == "iris_table" and out["row_count"] == 9
    assert out["project_name"] == {"untrusted": "Iris project"}
    assert len(out["sample_rows"]) == 2 and out["sample_rows"][0]["contact"] == "<email>"
    assert {c["name"] for c in out["columns"]} == set(FRAME.columns)

    denied = call("describe_data_collection", world.stranger, dc_id=world.dc_id)
    assert not denied.ok and "not found or access denied" in denied.error


# ---------------------------------------------------------------------------
# query_data
# ---------------------------------------------------------------------------
def inline_factory(specs):
    spec = specs[0]
    return InlineSandbox(
        frames={spec.tag: apply_runtime_filters(FRAME, spec.filters)}, default_tag=spec.tag
    )


class SlowSandbox(InlineSandbox):
    closed = 0

    def run(self, code, *, dc_tag="", deadline_s=0.0):
        time.sleep(0.4)
        return super().run(code, dc_tag=dc_tag, deadline_s=deadline_s)

    def close(self):
        SlowSandbox.closed += 1


def slow_factory(specs):
    return SlowSandbox(frames={specs[0].tag: FRAME}, default_tag=specs[0].tag)


@pytest.fixture
def sandbox(world, loads):  # noqa: F811
    with patch.object(data, "_sandbox_factory", side_effect=inline_factory):
        yield


def test_query_data_by_dc_with_filters(world, sandbox):  # noqa: F811
    code = "df.group_by('species').agg(pl.col('petal_length').mean()).sort('species')"
    result = call(
        "query_data",
        world.owner,
        dc_id=world.dc_id,
        code=code,
        filters=[{"column": "species", "operator": "in", "value": ["setosa", "virginica"]}],
    )
    assert result.ok, result.error
    out = result.data
    assert out["code"] == code and out["dc_tag"] == "iris_table"
    assert out["rows_in"] == 6 and out["rows_out"] == 2
    assert (
        "virginica" in out["output"]["untrusted"] and "versicolor" not in out["output"]["untrusted"]
    )


def test_query_data_by_component_and_policy(world, sandbox):  # noqa: F811
    result = call(
        "query_data", world.owner, dashboard_id=world.main, index="fig-1", code="df.height"
    )
    assert result.ok and result.data["output"] == {"untrusted": "9"}

    blocked = call("query_data", world.owner, dc_id=world.dc_id, code="__import__('os')")
    assert not blocked.ok and blocked.error.startswith("Query failed")
    assert "Allowed form: one expression rooted at df or pl" in blocked.error

    assigned = call("query_data", world.owner, dc_id=world.dc_id, code="x = df\nx")
    assert not assigned.ok and "Assign" in assigned.error and "Allowed form" in assigned.error

    both = call(
        "query_data", world.owner, dc_id=world.dc_id, dashboard_id=world.main, code="df.height"
    )
    assert not both.ok and "either dc_id" in both.error

    denied = call("query_data", world.stranger, dc_id=world.dc_id, code="df.height")
    assert not denied.ok and "access denied" in denied.error


def test_query_data_documented_examples_pass_the_policy():
    """Every example the tool advertises must run under the executor's allowlist."""
    frame = pl.DataFrame({"g": ["a", "a", "a", "b", "b"], "x": [1.0, 2.0, 30.0, 4.0, 5.0]})
    examples = data._CODE_DESCRIPTION.split("Examples: ", 1)[1].split(" | ")
    hint = data._POLICY_HINT.split("e.g. ", 1)[1].split("; ", 1)[0]
    assert len(examples) == 3
    for code in [*examples, hint]:
        step = execute_polars(code, frame)
        assert step.status == "success", (code, step.output)


def test_query_data_timeout_closes_the_sandbox(world, loads):  # noqa: F811
    SlowSandbox.closed = 0
    with (
        patch.object(data, "_sandbox_factory", side_effect=slow_factory),
        patch.object(settings.mcp, "query_timeout_s", 0.05),
        patch.object(data, "SANDBOX_START_ALLOWANCE_S", 0.0),
    ):
        result = call("query_data", world.owner, dc_id=world.dc_id, code="df.height")
    assert not result.ok and "Timed out" in result.error
    assert SlowSandbox.closed >= 1
    assert data._active_queries == {}


def test_query_data_concurrency_cap(world, loads):  # noqa: F811
    ctx = ctx_for(world.owner)

    async def three():
        return await asyncio.gather(
            *(
                invoke("query_data", ctx, {"dc_id": world.dc_id, "code": "df.height"})
                for _ in range(3)
            )
        )

    with patch.object(data, "_sandbox_factory", side_effect=slow_factory):
        results = asyncio.run(three())
    assert sum(r.ok for r in results) == 2
    refused = [r for r in results if not r.ok]
    assert len(refused) == 1 and "At most 2" in refused[0].error
    assert data._active_queries == {}
