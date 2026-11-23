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


def test_group_filter_projections_never_ride_along():
    group_projection = {
        **_filter_entry("a", ["v"]),
        "index": "__depictio_group__:dc1:col_a",
        "source": "group_filter",
    }
    state = _state(group_projection, _filter_entry("a", ["v"]))
    assert [f["index"] for f in filters_for_state([_control("a", "MultiSelect")], state)] == ["a"]


def test_a_state_entry_for_a_chart_selection_targets_that_tab():
    """A chart selection names its figure's index: it belongs to that tab's
    freeze, and the render endpoints apply it like any other filter."""
    state = _state(_filter_entry("fig", [3.5], source="scatter_selection"))
    out = filters_for_state([{"index": "fig", "component_type": "figure", "dc_id": "dc1"}], state)
    assert [f["index"] for f in out] == ["fig"]
