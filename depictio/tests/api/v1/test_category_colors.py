"""A dashboard's colour per category reaches the figures that colour by it.

`category_colors` (``{column: {value: colour}}``) is set on a dashboard's main
tab. `effective_category_colors` resolves it for any tab of the family, and
`merge_category_colors` turns it into the `color_discrete_map` of a UI-mode
figure whose colour column has an entry.
"""

from unittest.mock import patch

import mongomock
import plotly.express as px
import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import core_functions
from depictio.api.v1.services.figure.figure_builder import (
    create_figure_from_data,
    merge_category_colors,
    merge_dashboard_brand_theme,
)

CITIES = {"Athens": "#1a4f8f", "Barcelona": "#f5a11b", "Naples": "#00a550"}
COLORS = {"locality": CITIES, "season": {"Spring": "#40c057", "Summer": "#fab005"}}


# ---------------------------------------------------------------------------
# merge_category_colors


def test_colour_column_with_an_entry_gets_the_map():
    merged = merge_category_colors(COLORS, {"x": "a", "y": "b", "color": "locality"})
    assert merged["color_discrete_map"] == CITIES


def test_input_kwargs_are_not_mutated():
    kwargs = {"color": "locality"}
    merge_category_colors(COLORS, kwargs)
    assert kwargs == {"color": "locality"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"x": "a", "y": "b"},  # no colour column
        {"color": "depth"},  # a column without an entry
        {"color": ["locality"]},  # not a column name
    ],
)
def test_no_entry_leaves_the_kwargs_alone(kwargs):
    assert merge_category_colors(COLORS, kwargs) is kwargs


@pytest.mark.parametrize("colors", [None, {}, "locality", {"locality": "#fff"}, {"locality": {}}])
def test_missing_or_malformed_colours_are_ignored(colors):
    kwargs = {"color": "locality"}
    assert merge_category_colors(colors, kwargs) is kwargs


def test_the_components_own_map_wins_value_by_value():
    kwargs = {"color": "locality", "color_discrete_map": {"Athens": "#000000"}}
    merged = merge_category_colors(COLORS, kwargs)
    assert merged["color_discrete_map"] == {**CITIES, "Athens": "#000000"}


def test_a_json_string_map_is_parsed_before_merging():
    kwargs = {"color": "locality", "color_discrete_map": '{"Naples": "#123456"}'}
    merged = merge_category_colors(COLORS, kwargs)
    assert merged["color_discrete_map"] == {**CITIES, "Naples": "#123456"}


def test_brand_colorway_still_fills_values_the_map_does_not_name():
    brand = {"plots": {"colorway": ["#111111", "#222222"]}}
    kwargs = merge_category_colors(
        COLORS, merge_dashboard_brand_theme(brand, {"color": "locality"})
    )
    assert kwargs["color_discrete_map"] == CITIES
    assert kwargs["color_discrete_sequence"] == ["#111111", "#222222"]


def test_figure_traces_take_the_category_colours():
    df = pl.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 3.0, 2.0, 4.0]}).with_columns(
        pl.Series("locality", ["Naples", "Athens", "Barcelona", "Other"])
    )
    kwargs = merge_category_colors(COLORS, {"x": "a", "y": "b", "color": "locality"})
    with patch(
        "depictio.api.v1.services.figure.mantine_templates.ensure_mantine_templates",
        lambda: _vanilla_templates(),
    ):
        fig = create_figure_from_data(df, "scatter", kwargs)
    colours = {trace.name: trace.marker.color for trace in fig.data}
    assert {k: colours[k] for k in CITIES} == CITIES
    assert colours["Other"] not in CITIES.values()


def _vanilla_templates():
    from depictio.cli.cli.utils.mantine_templates import ensure_mantine_templates

    ensure_mantine_templates()


def test_px_accepts_the_merged_kwargs_for_box_and_bar():
    import pandas as pd

    frame = pd.DataFrame({"locality": list(CITIES), "v": [1, 2, 3]})
    for build in (px.box, px.bar):
        kwargs = merge_category_colors(COLORS, {"x": "locality", "y": "v", "color": "locality"})
        fig = build(frame, **kwargs)
        assert {t.name: t.marker.color for t in fig.data} == CITIES


# ---------------------------------------------------------------------------
# effective_category_colors


@pytest.fixture
def dashboards():
    db = mongomock.MongoClient()["depictio_test"]
    with patch.object(core_functions, "dashboards_collection", db["dashboards"]):
        yield db["dashboards"]


def _main(coll, category_colors=None):
    oid = ObjectId()
    doc = {"_id": oid, "dashboard_id": oid, "is_main_tab": True}
    if category_colors is not None:
        doc["category_colors"] = category_colors
    coll.insert_one(doc)
    return oid


def _child(parent_id, category_colors=None):
    doc = {"dashboard_id": ObjectId(), "is_main_tab": False, "parent_dashboard_id": parent_id}
    if category_colors is not None:
        doc["category_colors"] = category_colors
    return doc


class TestEffectiveCategoryColors:
    """What a figure is drawn in: the main tab's map, the tab's own over it."""

    def test_child_takes_the_main_tabs(self, dashboards):
        parent = _main(dashboards, COLORS)
        assert core_functions.effective_category_colors(_child(parent)) == COLORS

    def test_child_override_wins_per_value(self, dashboards):
        parent = _main(dashboards, COLORS)
        own = {"locality": {"Athens": "#000000"}}
        expected = {**COLORS, "locality": {**COLORS.get("locality", {}), "Athens": "#000000"}}
        assert core_functions.effective_category_colors(_child(parent, own)) == expected

    def test_main_tab_keeps_its_own(self, dashboards):
        parent = _main(dashboards, COLORS)
        doc = dashboards.find_one({"_id": parent})
        assert core_functions.effective_category_colors(doc) == COLORS

    def test_an_empty_own_map_inherits(self, dashboards):
        parent = _main(dashboards, COLORS)
        assert core_functions.effective_category_colors(_child(parent, {})) == COLORS

    def test_family_without_colours(self, dashboards):
        parent = _main(dashboards)
        assert core_functions.effective_category_colors(_child(parent)) is None
        assert core_functions.effective_category_colors(_child(str(parent))) is None

    def test_missing_parent(self, dashboards):
        assert core_functions.effective_category_colors(_child(ObjectId())) is None
