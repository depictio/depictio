"""The opening filter state producer A freezes at: the Python twin of
``depictio-react-core``'s ``interactiveDefaults.ts``, pinned on the same cases
as its vitest suite (``interactiveDefaults.test.ts``)."""

from __future__ import annotations

from typing import Any

from depictio.models.models.analysis_state import AnalysisState
from depictio.serverless.interactive_defaults import (
    default_filter_value,
    default_filters,
    filters_for_state,
    grouping_columns,
    grouping_for_state,
    grouping_render_body,
)


def _control(index: str, kind: str, default_state: dict[str, Any] | None = None, **extra):
    return {
        "index": index,
        "component_type": "interactive",
        "interactive_component_type": kind,
        "column_name": f"col_{index}",
        "dc_id": "dc1",
        "default_state": default_state,
        **extra,
    }


def test_select_defaults_are_the_list_the_renderer_emits():
    assert default_filter_value(_control("a", "Select", {"default_value": "Q10"})) == ["Q10"]
    assert default_filter_value(_control("a", "MultiSelect", {"default_value": ["x", 2]})) == [
        "x",
        "2",
    ]


def test_a_rangeslider_range_is_numeric():
    assert default_filter_value(_control("r", "RangeSlider", {"default_range": [1, "5"]})) == [1, 5]
    assert default_filter_value(_control("r", "RangeSlider", {"default_range": [1]})) is None


def test_a_textinput_seeds_its_trimmed_pattern_unless_it_cannot_compile():
    assert default_filter_value(_control("t", "TextInput", {"default_value": " ^ACG "})) == "^ACG"
    assert default_filter_value(_control("t", "TextInput", {"default_value": "("})) is None
    assert default_filter_value(_control("t", "TextInput", {"default_value": "   "})) is None
    contains = _control("t", "TextInput", {"default_value": "("}, match_mode="contains")
    assert default_filter_value(contains) == "("


def test_slider_segmented_control_and_switch():
    assert default_filter_value(_control("s", "Slider", {"default_value": 3})) == 3
    assert default_filter_value(_control("g", "SegmentedControl", {"default_value": "s1"})) == "s1"
    assert default_filter_value(_control("w", "Switch", {"default_value": "true"})) is True


def test_controls_without_a_declared_default_add_nothing():
    assert default_filter_value(_control("n", "MultiSelect")) is None
    assert default_filter_value(_control("n", "MultiSelect", {"default_value": []})) is None
    # A RangeSlider's default_value is not its range.
    assert default_filter_value(_control("n", "RangeSlider", {"default_value": 3})) is None


def test_one_entry_per_declared_default_in_the_viewers_shape():
    out = default_filters(
        [
            _control("sel", "Select", {"default_value": "Q10"}, filter_expr="col('q') > 1"),
            _control("rng", "RangeSlider", {"default_range": [0, 1]}, slider_mode="gte"),
            _control("none", "MultiSelect"),
            _control("txt", "TextInput", {"default_value": "a"}, case_sensitive=True),
            {"index": "card", "component_type": "card", "dc_id": "dc1"},
        ]
    )
    assert [(f["index"], f["value"]) for f in out] == [
        ("sel", ["Q10"]),
        ("rng", [0, 1]),
        ("txt", "a"),
    ]
    assert out[0] == {
        "index": "sel",
        "value": ["Q10"],
        "column_name": "col_sel",
        "interactive_component_type": "Select",
        "filter_expr": "col('q') > 1",
        "metadata": {
            "dc_id": "dc1",
            "column_name": "col_sel",
            "interactive_component_type": "Select",
        },
    }
    assert out[1]["metadata"]["slider_mode"] == "gte"
    assert out[2]["metadata"]["case_sensitive"] is True


# ---------------------------------------------------------------------------
# Freezing at an exported analysis state
# ---------------------------------------------------------------------------


def _filter_entry(index: str, value: Any, **extra: Any) -> dict[str, Any]:
    return {
        "index": index,
        "value": value,
        "column_name": f"col_{index}",
        "interactive_component_type": "MultiSelect",
        "metadata": {"dc_id": "dc1", "column_name": f"col_{index}"},
        **extra,
    }


def _state(*filters: dict[str, Any]) -> AnalysisState:
    return AnalysisState.model_validate(
        {"filters": list(filters), "context": {"dashboard_id": "dash-1"}}
    )


def test_no_state_is_the_declared_defaults():
    components = [
        _control("a", "Select", {"default_value": "Q10"}),
        {"index": "b", "component_type": "card"},
    ]
    assert filters_for_state(components, None) == default_filters(components)


def test_state_entries_win_and_the_rest_keeps_its_default():
    components = [
        _control("a", "Select", {"default_value": "Q10"}),
        _control("b", "Select", {"default_value": "Q20"}),
        {"index": "fig", "component_type": "figure", "dc_id": "dc1"},
    ]
    state = _state(_filter_entry("a", ["custom"]))
    out = filters_for_state(components, state)
    # The state's value for the control it mentions, the declared default for
    # the one it does not, and nothing else (the entry naming no interactive
    # component here is dropped with the card).
    assert [(f["index"], f["value"]) for f in out] == [("a", ["custom"]), ("b", ["Q20"])]
    # The state's entry travels whole, in the viewer's wire shape.
    assert out[0] == _filter_entry("a", ["custom"])


def test_a_state_entry_for_another_tab_does_not_reach_this_tab():
    state = _state(_filter_entry("elsewhere", ["x"]))
    assert filters_for_state([_control("a", "Select", {"default_value": "Q10"})], state) == (
        default_filters([_control("a", "Select", {"default_value": "Q10"})])
    )


def test_group_filter_projections_ride_along_on_every_tab():
    """The runtime derives the same filters from the groups it opens with, so a
    frozen tile is computed under them, like the live ones beside it."""
    group_projection = {
        **_filter_entry("a", ["v"]),
        "index": "__depictio_group__:dc1:col_a",
        "source": "group_filter",
    }
    state = _state(group_projection, _filter_entry("a", ["v"]))
    out = filters_for_state([_control("a", "MultiSelect")], state)
    assert [f["index"] for f in out] == ["__depictio_group__:dc1:col_a", "a"]
    # even on a tab that holds none of the control it is made on
    other = filters_for_state([_control("z", "MultiSelect")], state)
    assert [f["index"] for f in other] == ["__depictio_group__:dc1:col_a"]


def _grouped_state(**extra: Any) -> AnalysisState:
    return AnalysisState.model_validate(
        {
            "groups": [
                {
                    "id": "g1",
                    "name": "North",
                    "color": "#e03131",
                    "dc_id": "dc1",
                    "column_name": "sample",
                    "values": ["s1", "s2"],
                    "filter_active": True,
                },
                {
                    "id": "g2",
                    "name": "Empty",
                    "color": "#1971c2",
                    "column_name": "other",
                    "values": [],
                },
            ],
            "context": {"dashboard_id": "d1"},
            **extra,
        }
    )


def test_a_state_without_groups_or_colouring_opens_ungrouped():
    assert grouping_for_state(None) is None
    plain = AnalysisState.model_validate({"context": {"dashboard_id": "d1"}})
    assert grouping_for_state(plain) is None
    assert grouping_columns(plain) == set()
    assert grouping_render_body(plain) == {}


def test_the_groups_and_colour_by_are_carried_as_the_state_holds_them():
    state = _grouped_state(
        color_by={"kind": "groups"}, display_mode="facet", show_other=False, show_overall=False
    )
    grouping = grouping_for_state(state)
    assert grouping is not None
    assert [g.name for g in grouping.groups] == ["North", "Empty"]
    assert grouping.color_by.kind == "groups"
    assert (grouping.display_mode, grouping.show_other, grouping.show_overall) == (
        "facet",
        False,
        False,
    )
    # a saved group alone, nothing coloured, is still carried
    assert grouping_for_state(_grouped_state()) is not None


def test_the_columns_to_keep_are_every_groups_and_the_colour_by_column():
    assert grouping_columns(_grouped_state()) == {"sample", "other"}
    by_column = _grouped_state(color_by={"kind": "column", "column_name": "species"})
    assert grouping_columns(by_column) == {"sample", "other", "species"}


def test_a_frozen_figure_is_asked_for_the_colouring_the_viewer_would():
    groups = grouping_render_body(_grouped_state(color_by={"kind": "groups"}))
    # a group without values is not a group (the server would drop it too)
    assert [g["name"] for g in groups["groups"]] == ["North"]
    assert groups["groups"][0]["dc_id"] == "dc1"
    assert groups["color_by_group"] is True
    assert "include_other" not in groups and "grouping_display" not in groups
    split = grouping_render_body(
        _grouped_state(color_by={"kind": "groups"}, display_mode="facet", show_other=False)
    )
    assert split["include_other"] is False and split["grouping_display"] == "facet"
    column = grouping_render_body(_grouped_state(color_by={"kind": "column", "column_name": "sp"}))
    assert column == {"color_by_column": {"column_name": "sp"}}
    # colour-by off: groups that only filter colour nothing
    assert grouping_render_body(_grouped_state()) == {}


def test_a_state_entry_for_a_chart_selection_targets_that_tab():
    """A chart selection names its figure's index: it belongs to that tab's
    freeze, and the render endpoints apply it like any other filter."""
    state = _state(_filter_entry("fig", [3.5], source="scatter_selection"))
    out = filters_for_state([{"index": "fig", "component_type": "figure", "dc_id": "dc1"}], state)
    assert [f["index"] for f in out] == ["fig"]
