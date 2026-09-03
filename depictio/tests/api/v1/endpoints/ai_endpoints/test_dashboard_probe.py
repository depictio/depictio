"""Unit tests for the generated-dashboard render probe.

`probe_component` calls real render paths, all of which want a database and a
Delta table, so the paths themselves are out of scope here. What is testable
without either is the part that has to be right for the probe to be usable at
all: which probe a component type dispatches to, what payload that probe
builds, and the promise that nothing escapes as an exception.

Every probe imports its render path lazily, inside the function body, so a
stand-in module dropped into `sys.modules` is enough to exercise the real
probe body while nothing touches Mongo, Redis or S3.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from depictio.api.v1.endpoints.ai_endpoints import dashboard_probe
from depictio.api.v1.endpoints.ai_endpoints.context import ColumnSummary, DataContext
from depictio.api.v1.endpoints.ai_endpoints.dashboard_probe import (
    MAX_REASON_CHARS,
    NO_PROBE_TYPES,
    PROBE_ROW_LIMIT,
    probe_component,
)

WF_ID = "7" * 24
DC_ID = "6" * 24
USER = SimpleNamespace(id="u" * 24, email="probe@example.com")

PHYSICAL = {
    "individual_id": "String",
    "bill_length_mm": "Float64",
    "bill_depth_mm": "Float64",
    "body_mass_g": "Float64",
}


@pytest.fixture()
def ctx() -> DataContext:
    return DataContext(
        data_collection_id=DC_ID,
        workflow_id=WF_ID,
        project_name="Penguins",
        project_description=None,
        dc_name="physical_features",
        dc_description=None,
        columns=[
            ColumnSummary(name=name, dtype=dtype, null_pct=0.0, nunique=9)
            for name, dtype in PHYSICAL.items()
        ],
        sample_rows=[],
        row_count=344,
        workflow_tag="python/penguins",
        data_collection_tag="physical_features",
        dc_type="table",
    )


def _install(monkeypatch, name: str, **members: Any) -> ModuleType:
    """Put a stand-in module in `sys.modules` for the duration of one test."""
    module = ModuleType(name)
    for attr, value in members.items():
        setattr(module, attr, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _comp(component_type: str, **fields: Any) -> dict[str, Any]:
    return {"tag": "c", "component_type": component_type, **fields}


class TestDispatchByType:
    def test_figure_builds_the_preview_the_viewer_would_build(self, monkeypatch, ctx):
        seen: list[dict] = []
        _install(
            monkeypatch,
            "depictio.api.v1.celery_tasks",
            build_figure_preview=lambda payload: seen.append(payload) or {"figure": {}},
        )

        component = _comp(
            "figure",
            visu_type="box",
            dict_kwargs={"x": "individual_id", "y": "bill_depth_mm"},
        )
        assert probe_component(component, ctx, USER) is None

        metadata = seen[0]["metadata"]
        assert metadata["wf_id"] == WF_ID
        assert metadata["dc_id"] == DC_ID
        assert metadata["visu_type"] == "box"
        assert metadata["dict_kwargs"] == {"x": "individual_id", "y": "bill_depth_mm"}
        assert metadata["mode"] == "ui"
        assert seen[0]["filter_metadata"] == []

    def test_advanced_viz_sends_every_bound_role_column_duplicates_included(self, monkeypatch, ctx):
        seen: list[dict] = []

        def fetch(*, response, payload, current_user, access_token):
            seen.append(payload)
            response.headers["X-Total-Ms"] = "0"
            return {"columns": payload["columns"], "rows": {}}

        _install(
            monkeypatch,
            "depictio.api.v1.endpoints.advanced_viz_endpoints.routes",
            fetch_advanced_viz_data=fetch,
        )

        # The binding that produced the failing penguins dashboard: `depth` and
        # `metric` on the same float column. The probe must forward it as-is,
        # because that duplicate is exactly what the endpoint had to learn to
        # survive.
        component = _comp(
            "advanced_viz",
            viz_kind="rarefaction",
            config={
                "viz_kind": "rarefaction",
                "sample_id_col": "individual_id",
                "depth_col": "bill_depth_mm",
                "metric_col": "bill_depth_mm",
            },
        )
        assert probe_component(component, ctx, USER) is None

        payload = seen[0]
        assert payload["columns"] == ["individual_id", "bill_depth_mm", "bill_depth_mm"]
        assert payload["roles"] == {
            "sample_id": "individual_id",
            "depth": "bill_depth_mm",
            "metric": "bill_depth_mm",
        }
        assert payload["viz_kind"] == "rarefaction"
        assert payload["limit_rows"] == PROBE_ROW_LIMIT

    def test_advanced_viz_without_a_single_column_role_is_not_probed(self, monkeypatch, ctx):
        def fetch(**kwargs):
            raise AssertionError("upset_plot binds no single-column role")

        _install(
            monkeypatch,
            "depictio.api.v1.endpoints.advanced_viz_endpoints.routes",
            fetch_advanced_viz_data=fetch,
        )
        component = _comp("advanced_viz", viz_kind="upset_plot", config={"viz_kind": "upset_plot"})
        assert probe_component(component, ctx, USER) is None

    def test_table_reads_the_schema_then_pages_one_row(self, monkeypatch, ctx):
        pages: list[dict] = []
        _install(
            monkeypatch,
            "depictio.api.v1.deltatables_utils",
            schema_deltatable_lite=lambda *a, **k: dict(PHYSICAL),
            load_sorted_deltatable_lite=lambda **kwargs: pages.append(kwargs),
        )
        monkeypatch.setattr(
            "depictio.api.v1.endpoints.ai_endpoints.context.init_data_for_dc",
            lambda dc_id: {dc_id: {"delta_location": "s3://x", "dc_type": "table"}},
        )

        component = _comp("table", columns=["bill_depth_mm", "individual_id"])
        assert probe_component(component, ctx, USER) is None

        assert pages[0]["sort_by"] == "bill_depth_mm"
        assert pages[0]["select_columns"] == ["bill_depth_mm", "individual_id"]
        assert pages[0]["page"] == (0, PROBE_ROW_LIMIT)

    def test_table_reports_a_column_the_collection_does_not_have(self, monkeypatch, ctx):
        _install(
            monkeypatch,
            "depictio.api.v1.deltatables_utils",
            schema_deltatable_lite=lambda *a, **k: dict(PHYSICAL),
            load_sorted_deltatable_lite=lambda **kwargs: pytest.fail("must not load"),
        )
        monkeypatch.setattr(
            "depictio.api.v1.endpoints.ai_endpoints.context.init_data_for_dc",
            lambda dc_id: {},
        )

        reason = probe_component(_comp("table", columns=["nope"]), ctx, USER)
        assert reason is not None
        assert "nope" in reason

    def test_interactive_value_widget_lists_one_value(self, monkeypatch, ctx):
        seen: list[dict] = []

        async def get_unique_values(dc_id, *, column, limit, filter_expr, current_user):
            seen.append({"column": column, "limit": limit, "filter_expr": filter_expr})
            return {"column": column, "values": ["Adelie"]}

        _install(
            monkeypatch,
            "depictio.api.v1.endpoints.deltatables_endpoints.routes",
            get_unique_values=get_unique_values,
        )

        component = _comp(
            "interactive", interactive_component_type="MultiSelect", column_name="individual_id"
        )
        assert probe_component(component, ctx, USER) is None
        assert seen == [{"column": "individual_id", "limit": PROBE_ROW_LIMIT, "filter_expr": None}]

    @pytest.mark.parametrize("widget", ["Slider", "RangeSlider", "DateRangePicker"])
    def test_interactive_range_widget_reads_the_stored_specs(self, monkeypatch, ctx, widget):
        monkeypatch.setattr(
            dashboard_probe, "_column_specs", lambda dc_id, column: {"min": 0, "max": 10}
        )
        component = _comp(
            "interactive", interactive_component_type=widget, column_name="bill_depth_mm"
        )
        assert probe_component(component, ctx, USER) is None

    def test_interactive_range_widget_without_bounds_is_reported(self, monkeypatch, ctx):
        monkeypatch.setattr(dashboard_probe, "_column_specs", lambda dc_id, column: {"count": 344})
        component = _comp(
            "interactive", interactive_component_type="Slider", column_name="bill_depth_mm"
        )
        reason = probe_component(component, ctx, USER)
        assert reason is not None
        assert "min/max" in reason

    def test_interactive_widgets_that_fetch_nothing_are_not_probed(self, ctx):
        for widget in ("Checkbox", "Switch"):
            component = _comp(
                "interactive", interactive_component_type=widget, column_name="individual_id"
            )
            assert probe_component(component, ctx, USER) is None

    def test_card_uses_its_own_layout_when_the_endpoint_computes_it(self, monkeypatch, ctx):
        seen: list[dict] = []

        async def get_card_metric(dc_id, request, current_user):
            seen.append(request)
            return {"value": 1}

        _install(
            monkeypatch,
            "depictio.api.v1.endpoints.deltatables_endpoints.routes",
            get_card_metric=get_card_metric,
        )

        component = _comp(
            "card",
            aggregation="average",
            column_name="bill_depth_mm",
            secondary_layout="histogram",
        )
        assert probe_component(component, ctx, USER) is None
        assert seen[0] == {
            "layout": "histogram",
            "column": "bill_depth_mm",
            "aggregation": "average",
        }

    def test_card_falls_back_to_the_hero_pseudo_layout(self, monkeypatch, ctx):
        seen: list[dict] = []

        async def get_card_metric(dc_id, request, current_user):
            seen.append(request)
            return {"value": 1}

        _install(
            monkeypatch,
            "depictio.api.v1.endpoints.deltatables_endpoints.routes",
            get_card_metric=get_card_metric,
        )

        # `top_n` is a breakdown layout, not one `card_metric` computes.
        component = _comp(
            "card", aggregation="count", column_name="individual_id", secondary_layout="top_n"
        )
        assert probe_component(component, ctx, USER) is None
        assert seen[0]["layout"] == "hero"


class TestNothingToProbe:
    @pytest.mark.parametrize("component_type", sorted(NO_PROBE_TYPES))
    def test_types_without_a_cheap_probe_return_none(self, ctx, component_type):
        assert probe_component(_comp(component_type), ctx, USER) is None

    def test_unknown_type_returns_none(self, ctx):
        assert probe_component(_comp("hologram"), ctx, USER) is None
        assert probe_component({}, ctx, USER) is None

    def test_no_context_means_nothing_to_probe_against(self):
        assert probe_component(_comp("figure", visu_type="box"), None, USER) is None


class TestFailuresAreReturnedNotRaised:
    def test_an_exception_inside_a_probe_becomes_a_message(self, monkeypatch, ctx):
        def boom(payload):
            raise ValueError("Value of 'x' is not the name of a column in 'data_frame'")

        _install(monkeypatch, "depictio.api.v1.celery_tasks", build_figure_preview=boom)

        reason = probe_component(_comp("figure", dict_kwargs={"x": "nope"}), ctx, USER)
        assert reason is not None
        assert reason.startswith("figure did not render: ")
        assert "not the name of a column" in reason

    def test_an_http_error_reports_its_detail(self, monkeypatch, ctx):
        class FakeHTTPException(Exception):
            def __init__(self, status_code, detail):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        def fetch(**kwargs):
            raise FakeHTTPException(422, "Could not read this data collection: duplicate column")

        _install(
            monkeypatch,
            "depictio.api.v1.endpoints.advanced_viz_endpoints.routes",
            fetch_advanced_viz_data=fetch,
        )

        reason = probe_component(
            _comp(
                "advanced_viz",
                viz_kind="rarefaction",
                config={
                    "viz_kind": "rarefaction",
                    "sample_id_col": "individual_id",
                    "depth_col": "bill_depth_mm",
                    "metric_col": "bill_depth_mm",
                },
            ),
            ctx,
            USER,
        )
        assert reason == (
            "advanced_viz did not render: Could not read this data collection: duplicate column"
        )

    def test_a_long_reason_is_trimmed(self, monkeypatch, ctx):
        def boom(payload):
            raise RuntimeError("x" * (MAX_REASON_CHARS * 2))

        _install(monkeypatch, "depictio.api.v1.celery_tasks", build_figure_preview=boom)

        reason = probe_component(_comp("figure"), ctx, USER)
        assert reason is not None
        assert reason.endswith("...")
        assert len(reason) < MAX_REASON_CHARS + 40

    def test_an_import_failure_is_a_message_too(self, monkeypatch, ctx):
        # A stand-in module without the attribute the probe imports: the
        # ImportError has to come back as a reason like any other failure.
        _install(monkeypatch, "depictio.api.v1.celery_tasks")

        reason = probe_component(_comp("figure"), ctx, USER)
        assert reason is not None
        assert reason.startswith("figure did not render: ")
