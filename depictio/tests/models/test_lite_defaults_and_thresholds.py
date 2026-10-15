"""Lite-model contracts added for the wave-3 platform fixes.

* P9: interactive ``default_value`` / ``default_range`` are validated and reach
  the stored component as ``default_state`` (the viewer seeds filters from it).
* P17: a card ``threshold_warn`` on the passing side of ``threshold_value`` is
  a validation error instead of being dropped silently by the server.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.models.components.lite import CardLiteComponent, InteractiveLiteComponent
from depictio.models.models.dashboards import DashboardDataLite

BASE_CARD = {
    "tag": "c",
    "workflow_tag": "wf",
    "data_collection_tag": "dc",
    "aggregation": "count",
    "column_name": "q",
    "secondary_layout": "threshold",
}
BASE_FILTER = {"tag": "f", "workflow_tag": "wf", "data_collection_tag": "dc", "column_name": "q"}


class TestThresholdWarnSide:
    def test_min_direction_warn_below_threshold_is_valid(self):
        card = CardLiteComponent(**BASE_CARD, threshold_value=30, threshold_warn=20)
        assert card.threshold_warn == 20

    def test_max_direction_warn_above_threshold_is_valid(self):
        CardLiteComponent(
            **BASE_CARD, threshold_value=5, threshold_warn=10, threshold_direction="max"
        )

    @pytest.mark.parametrize(
        ("direction", "warn", "needle"),
        [("min", 40, "must be below"), ("min", 30, "must be below"), ("max", 1, "must be above")],
    )
    def test_warn_on_the_passing_side_is_rejected(self, direction, warn, needle):
        with pytest.raises(ValidationError, match=needle):
            CardLiteComponent(
                **BASE_CARD,
                threshold_value=30 if direction == "min" else 5,
                threshold_warn=warn,
                threshold_direction=direction,
            )

    def test_warn_without_threshold_is_rejected(self):
        with pytest.raises(ValidationError, match="requires threshold_value"):
            CardLiteComponent(**BASE_CARD, threshold_warn=3)


class TestInteractiveDefaults:
    def test_select_default_value_reaches_default_state(self):
        dash = DashboardDataLite(
            title="t",
            components=[
                {
                    **BASE_FILTER,
                    "component_type": "interactive",
                    "interactive_component_type": "Select",
                    "default_value": "Q10",
                },
                {
                    **BASE_FILTER,
                    "tag": "r",
                    "component_type": "interactive",
                    "interactive_component_type": "RangeSlider",
                    "column_type": "float64",
                    "default_range": [0, 1],
                },
                {
                    **BASE_FILTER,
                    "tag": "n",
                    "component_type": "interactive",
                    "interactive_component_type": "MultiSelect",
                },
            ],
        )
        stored = dash.to_full()["stored_metadata"]
        assert stored[0]["default_state"] == {"default_value": "Q10"}
        assert stored[1]["default_state"] == {"default_range": [0, 1]}
        assert stored[2]["default_state"] is None

        # Export round-trips the declared defaults.
        back = DashboardDataLite.from_full(dash.to_full())
        dumped = [c if isinstance(c, dict) else c.model_dump() for c in back.components]
        assert dumped[0]["default_value"] == "Q10"
        assert dumped[1]["default_range"] == [0, 1]

    @pytest.mark.parametrize(
        ("kind", "extra", "needle"),
        [
            ("RangeSlider", {"default_value": 3}, "takes default_range"),
            ("Select", {"default_range": [0, 1]}, "only valid for"),
            ("RangeSlider", {"default_range": [5, 1]}, "is above high"),
            ("RangeSlider", {"default_range": [1]}, r"must be \[low, high\]"),
            ("RangeSlider", {"default_range": ["a", "b"]}, "must be numbers"),
            ("Slider", {"default_value": "x"}, "must be a number"),
            ("SegmentedControl", {"default_value": ["a"]}, "list default_value"),
        ],
    )
    def test_misplaced_defaults_are_rejected(self, kind, extra, needle):
        with pytest.raises(ValidationError, match=needle):
            InteractiveLiteComponent(**BASE_FILTER, interactive_component_type=kind, **extra)

    def test_multiselect_accepts_a_list(self):
        c = InteractiveLiteComponent(
            **BASE_FILTER, interactive_component_type="MultiSelect", default_value=["a", "b"]
        )
        assert c.default_state_payload() == {"default_value": ["a", "b"]}


class TestMainRequestedFields:
    def test_slider_mode_reaches_stored_metadata_and_round_trips(self):
        dash = DashboardDataLite(
            title="t",
            components=[
                {
                    **BASE_FILTER,
                    "component_type": "interactive",
                    "interactive_component_type": "Slider",
                    "column_type": "float64",
                    "slider_mode": "lte",
                }
            ],
        )
        assert dash.to_full()["stored_metadata"][0]["slider_mode"] == "lte"
        back = DashboardDataLite.from_full(dash.to_full())
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump()
        assert comp["slider_mode"] == "lte"

    def test_slider_mode_rejects_unknown_values(self):
        with pytest.raises(ValidationError):
            InteractiveLiteComponent(
                **BASE_FILTER, interactive_component_type="Slider", slider_mode="between"
            )

    def test_text_title_size_defaults_to_none(self):
        from depictio.models.components.lite import TextLiteComponent

        assert TextLiteComponent(tag="t").title_size is None
        assert TextLiteComponent(tag="t", title_size="sm").title_size == "sm"


class TestCardFollowRegionFilter:
    """P13: a card opts into a locus navigator's region with ``follow_region_filter``."""

    def _card(self, **extra):
        return {
            **BASE_CARD,
            "component_type": "card",
            "secondary_layout": "vertical",
            **extra,
        }

    def test_defaults_to_false(self):
        assert CardLiteComponent(**BASE_CARD).follow_region_filter is False

    @pytest.mark.parametrize("follow", [True, False])
    def test_reaches_stored_metadata_and_round_trips(self, follow):
        # How the API reads the flag (`region_scope.follows_region`) is covered in
        # tests/unit: this module runs on the CLI base install, without the server.
        dash = DashboardDataLite(title="t", components=[self._card(follow_region_filter=follow)])
        stored = dash.to_full()["stored_metadata"][0]
        assert stored["follow_region_filter"] is follow

        back = DashboardDataLite.from_full(dash.to_full())
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump()
        assert comp.get("follow_region_filter", False) is follow


class TestAlwaysSelected:
    """A Select that always holds a value: the first option of its own list."""

    def _select(self, **extra):
        return {
            **BASE_FILTER,
            "component_type": "interactive",
            "interactive_component_type": "Select",
            **extra,
        }

    def test_defaults_to_false_and_stays_out_of_stored_metadata(self):
        assert InteractiveLiteComponent(**self._select()).always_selected is False
        dash = DashboardDataLite(title="t", components=[self._select()])
        assert "always_selected" not in dash.to_full()["stored_metadata"][0]
        back = DashboardDataLite.from_full(dash.to_full())
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump(exclude_defaults=True)
        assert "always_selected" not in comp

    def test_select_flag_reaches_stored_metadata_and_round_trips(self):
        dash = DashboardDataLite(title="t", components=[self._select(always_selected=True)])
        assert dash.to_full()["stored_metadata"][0]["always_selected"] is True
        back = DashboardDataLite.from_full(dash.to_full())
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump()
        assert comp["always_selected"] is True

    @pytest.mark.parametrize(
        ("kind", "column_type"),
        [("MultiSelect", None), ("SegmentedControl", None), ("RangeSlider", "float64")],
    )
    def test_rejected_on_anything_but_a_select(self, kind, column_type):
        with pytest.raises(ValidationError, match="only valid for a Select"):
            InteractiveLiteComponent(
                **BASE_FILTER,
                interactive_component_type=kind,
                column_type=column_type,
                always_selected=True,
            )

    def test_default_by_round_trips_and_stays_out_when_unset(self):
        plain = DashboardDataLite(title="t", components=[self._select(always_selected=True)])
        stored = plain.to_full()["stored_metadata"][0]
        assert "default_by" not in stored and "default_order" not in stored
        ranked = DashboardDataLite(
            title="t",
            components=[self._select(always_selected=True, default_by="size")],
        )
        stored = ranked.to_full()["stored_metadata"][0]
        assert stored["default_by"] == "size" and "default_order" not in stored
        back = DashboardDataLite.from_full(ranked.to_full()).components[0]
        back = back if isinstance(back, dict) else back.model_dump()
        assert back["default_by"] == "size"
        asc = DashboardDataLite(
            title="t",
            components=[self._select(always_selected=True, default_by="size", default_order="asc")],
        )
        assert asc.to_full()["stored_metadata"][0]["default_order"] == "asc"

    def test_default_by_needs_always_selected(self):
        with pytest.raises(ValueError, match="always_selected"):
            InteractiveLiteComponent(**self._select(default_by="size"))

    def test_banner_facts_round_trip_with_and_without_a_format(self):
        facts = [
            {"column": "size", "label": "Members", "format": "integer", "icon": "tabler:users"},
            {"column": "note", "label": "Note"},
        ]
        dash = DashboardDataLite(
            title="t", components=[self._select(always_selected=True, banner_facts=facts)]
        )
        full = dash.to_full()
        # A fact without a format stores no `format` key at all.
        assert full["stored_metadata"][0]["banner_facts"] == facts
        back = DashboardDataLite.from_full(full)
        comp = back.components[0]
        comp = comp if isinstance(comp, dict) else comp.model_dump()
        assert [
            {k: v for k, v in f.items() if v is not None} for f in comp["banner_facts"]
        ] == facts
        assert back.to_full()["stored_metadata"][0]["banner_facts"] == facts

    def test_banner_facts_stay_out_of_stored_metadata_when_unset_or_empty(self):
        for extra in ({}, {"banner_facts": None}, {"banner_facts": []}):
            dash = DashboardDataLite(
                title="t", components=[self._select(always_selected=True, **extra)]
            )
            assert "banner_facts" not in dash.to_full()["stored_metadata"][0]
        empty = InteractiveLiteComponent(**self._select(always_selected=True, banner_facts=[]))
        assert empty.banner_facts is None

    def test_banner_facts_need_always_selected(self):
        facts = [{"column": "size", "label": "Members"}]
        with pytest.raises(ValidationError, match="always_selected"):
            InteractiveLiteComponent(**self._select(banner_facts=facts))

    @pytest.mark.parametrize("bad", ["bogus", "decimals:9", "decimals", ""])
    def test_a_banner_fact_format_outside_the_shared_vocabulary_is_rejected(self, bad):
        fact = {"column": "size", "label": "Members", "format": bad}
        with pytest.raises(ValidationError, match="is not one of"):
            InteractiveLiteComponent(**self._select(always_selected=True, banner_facts=[fact]))

    def test_a_banner_fact_needs_a_column_and_a_label_and_nothing_else(self):
        for fact in (
            {"label": "Members"},
            {"column": "size"},
            {"column": "", "label": "Members"},
            {"column": "size", "label": "Members", "unit": "x"},
        ):
            with pytest.raises(ValidationError):
                InteractiveLiteComponent(**self._select(always_selected=True, banner_facts=[fact]))

    def test_a_default_value_names_the_one_value_it_starts_on(self):
        one = InteractiveLiteComponent(**self._select(always_selected=True, default_value=["a"]))
        assert one.default_value == ["a"]
        with pytest.raises(ValidationError, match="holds exactly one value"):
            InteractiveLiteComponent(**self._select(always_selected=True, default_value=["a", "b"]))
