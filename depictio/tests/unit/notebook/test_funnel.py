"""The funnel the document computes from ``depictio_state`` when it runs."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1 import deltatables_utils as server
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.notebook import funnel, predicates

FRAME = pl.DataFrame({"s": ["a", "b", "c", "d"], "x": [1, 2, 3, 4], "k": ["p", "q", "p", "q"]})
DC = "dc1"


def _f(index, column, value, itype="MultiSelect", dc=DC):
    return {
        "index": index,
        "column_name": column,
        "interactive_component_type": itype,
        "value": value,
        "metadata": {"dc_id": dc},
    }


def test_the_mirrored_server_helpers_have_not_drifted():
    """The notebook carries copies (it cannot import the server); pin them."""
    assert predicates.SLIDER_MODES == server.SLIDER_MODES
    assert predicates.DEFAULT_SLIDER_MODE == server.DEFAULT_SLIDER_MODE
    assert predicates.LINK_NO_MATCH == server.LINK_NO_MATCH
    assert predicates.MAX_TEXT_PATTERN_LENGTH == server.MAX_TEXT_PATTERN_LENGTH
    assert funnel.FUNNEL_MAX_STAGES == routes.FUNNEL_MAX_STAGES
    for args in [
        ("a.c", None, None),
        ("a.c", True, "contains"),
        ("A", False, "contains"),
        ("(", None, None),
        ("  ", None, None),
        ("x" * 600, None, None),
    ]:
        assert predicates.text_filter_pattern(*args) == server.text_filter_pattern(*args), args
    for raw in [
        "2024-01-01",
        "2024-01-01T08:00:00",
        "2024-01-01 08:00:00",
        "2024-01-01T08:00:00.5",
        "2024-01-01T08:00:00Z",
    ]:
        assert predicates.parse_iso_datetime(raw) == server.parse_iso_datetime(raw), raw


@pytest.mark.parametrize(
    "f",
    [
        {"value": None},
        {"value": ""},
        {"value": [None, None]},
        {"value": 0},
        {"value": [0, 1]},
        {"value": False},
    ],
)
def test_active_means_what_the_funnel_endpoint_means(f):
    assert funnel._is_active(f) == routes._funnel_filter_is_active(f)


def test_stages_follow_the_state_order_and_its_cap():
    state = {
        "filters": [_f("a", "s", ["a"]), _f("b", "x", [1, 3], "RangeSlider"), _f("c", "s", [])],
        "funnel": {"stage_order": ["b"]},
    }
    assert [f["index"] for f in funnel.active_filters(state)] == ["b", "a"]
    many = {"filters": [_f(str(i), "s", ["a"]) for i in range(20)]}
    assert len(funnel.active_filters(many)) == funnel.FUNNEL_MAX_STAGES


def test_a_stage_filters_its_own_collection_only_and_skips_a_missing_column():
    state = {
        "filters": [
            _f("a", "s", ["a", "c"]),
            _f("b", "nope", ["z"]),
            _f("c", "s", ["a"], dc="other"),
        ]
    }
    assert funnel.funnel_stage(FRAME, state, 1, dc_id=DC)["s"].to_list() == ["a", "c"]
    assert funnel.funnel_stage(FRAME, state, 2, dc_id=DC).height == 4
    assert funnel.funnel_stage(FRAME, state, 3, dc_id=DC).height == 4
    assert funnel.funnel_stage(FRAME, state, 9, dc_id=DC).height == 4


def test_rest_applies_what_the_state_gained_since_export():
    state = {"filters": [_f("a", "s", ["a", "b", "c"]), _f("b", "x", [2, 4], "RangeSlider")]}
    assert funnel.funnel_rest(FRAME, state, 1, dc_id=DC)["x"].to_list() == [2, 3, 4]


def test_a_link_resolution_is_applied_only_for_the_filter_it_was_resolved_for():
    links = [{"interactive_component_type": "MultiSelect", "column_name": "k", "value": ["p"]}]
    resolved_for = {"index": "a", "value": ["x"]}
    state = {"filters": [_f("a", "missing_here", ["x"], dc="other")]}
    out = funnel.funnel_stage(FRAME, state, 1, dc_id=DC, links=links, resolved_for=resolved_for)
    assert out["k"].to_list() == ["p", "p"]
    changed = {"filters": [_f("a", "missing_here", ["y"], dc="other")]}
    with pytest.warns(UserWarning, match="resolved by the server for the old value"):
        out = funnel.funnel_stage(
            FRAME, changed, 1, dc_id=DC, links=links, resolved_for=resolved_for
        )
    assert out.height == 4
