"""Option order of a categorical filter: ``order_by`` and the duration default."""

from __future__ import annotations

import pytest

from depictio.models.components.lite import InteractiveLiteComponent
from depictio.models.components.value_order import order_values, parse_duration_hours
from depictio.models.models.dashboards import DashboardDataLite

FILTER = {
    "tag": "f",
    "workflow_tag": "wf",
    "data_collection_tag": "dc",
    "column_name": "time_point",
    "interactive_component_type": "MultiSelect",
}


class TestParseDurationHours:
    @pytest.mark.parametrize(
        ("label", "hours"),
        [("30min", 0.5), ("2h", 2.0), ("1d", 24.0), ("GM_12h", 12.0), ("1.5 hr", 1.5)],
    )
    def test_reads_the_trailing_duration(self, label, hours):
        assert parse_duration_hours(label) == hours

    @pytest.mark.parametrize("label", ["REP12", "Sample_2", "", None, "control"])
    def test_ids_that_merely_end_in_a_number_read_nothing(self, label):
        assert parse_duration_hours(label) is None


class TestOrderValues:
    def test_durations_follow_the_duration_not_the_alphabet(self):
        got = order_values(["18h", "1h", "30min", "2h", "0h", "1d"])
        assert got == ["0h", "30min", "1h", "2h", "18h", "1d"]

    def test_values_that_are_not_all_durations_keep_the_plain_sort(self):
        assert order_values(["b", "10", "2"]) == ["10", "2", "b"]
        assert order_values(["30min", "control", "1h"]) == ["1h", "30min", "control"]

    def test_companion_keys_order_the_values_numerically(self):
        keys = {"30min": 2, "18h": 10, "1h": 3, "0h": 1}
        assert order_values(["18h", "0h", "1h", "30min"], keys) == ["0h", "30min", "1h", "18h"]

    def test_companion_keys_read_as_text_are_ordered_naturally(self):
        keys = {"a": "step_10", "b": "step_2"}
        assert order_values(["a", "b"], keys) == ["b", "a"]

    def test_a_value_without_a_key_goes_last_and_ties_fall_back_on_the_value(self):
        keys = {"x": 1, "y": 1, "z": None}
        assert order_values(["z", "y", "x", "w"], keys) == ["x", "y", "w", "z"]

    def test_nulls_are_dropped_and_values_stringified(self):
        assert order_values([2, None, 10, 2]) == ["10", "2"]


class TestInteractiveOrderBy:
    def test_the_field_is_optional(self):
        assert InteractiveLiteComponent(**FILTER).order_by is None

    @pytest.mark.parametrize("kind", ["Select", "MultiSelect", "SegmentedControl"])
    def test_orders_the_controls_that_list_values(self, kind):
        comp = InteractiveLiteComponent(
            **{**FILTER, "interactive_component_type": kind}, order_by="time_order"
        )
        assert comp.order_by == "time_order"

    def test_a_slider_has_no_options_to_order(self):
        with pytest.raises(ValueError, match="order_by"):
            InteractiveLiteComponent(
                **{**FILTER, "interactive_component_type": "RangeSlider"}, order_by="time_order"
            )

    def test_round_trips_through_the_stored_dashboard(self):
        dash = DashboardDataLite(title="t", components=[{**FILTER, "order_by": "time_order"}])
        stored = dash.to_full()["stored_metadata"][0]
        assert stored["order_by"] == "time_order"
        back = DashboardDataLite.from_full(dash.to_full())
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump()
        assert comp["order_by"] == "time_order"
        assert back.to_full()["stored_metadata"][0]["order_by"] == "time_order"

    def test_unset_stores_no_key(self):
        dash = DashboardDataLite(title="t", components=[dict(FILTER)])
        assert "order_by" not in dash.to_full()["stored_metadata"][0]
