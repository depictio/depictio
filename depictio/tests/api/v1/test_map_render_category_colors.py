"""``render_map`` draws a category in the colour the dashboard gives it.

The dashboard's ``category_colors`` (main tab's, with the tab's own laid over
them) colour every figure's categories; the map rendered without them, so
"Athens" was blue on the filter bar and in the PCoA and red on the map. The
component's own ``color_discrete_map`` still wins value by value, as it does
for figures (``merge_category_colors``).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px

from depictio.api.v1.services.map.render import render_map

DF = pd.DataFrame(
    {
        "lat": [37.9, 40.8, 41.9, 45.4],
        "lon": [23.7, 14.3, 12.5, 12.3],
        "city": ["Athens", "Naples", "Rome", "Venice"],
    }
)
SCATTER = {
    "map_type": "scatter_map",
    "lat_column": "lat",
    "lon_column": "lon",
    "color_column": "city",
}


def _trace_colours(fig) -> dict[str, str]:
    return {t.name: t.marker.color for t in fig.data}


def test_dashboard_colours_reach_the_map() -> None:
    fig, info = render_map(
        DF, SCATTER, category_colors={"city": {"Athens": "#1a4f8f", "Rome": "#e8590c"}}
    )
    colours = _trace_colours(fig)
    assert colours["Athens"] == "#1a4f8f"
    assert colours["Rome"] == "#e8590c"
    # A value the dashboard does not name keeps its palette slot.
    assert colours["Naples"] == px.colors.qualitative.Plotly[1]
    assert info["color_discrete_map"]["Athens"] == "#1a4f8f"


def test_component_map_wins_value_by_value() -> None:
    trigger = {**SCATTER, "color_discrete_map": {"Athens": "#000000"}}
    fig, _info = render_map(
        DF, trigger, category_colors={"city": {"Athens": "#1a4f8f", "Rome": "#e8590c"}}
    )
    colours = _trace_colours(fig)
    assert colours["Athens"] == "#000000"
    assert colours["Rome"] == "#e8590c"


def test_component_map_in_dict_kwargs_does_not_drop_the_dashboard_colours() -> None:
    # dict_kwargs are laid over the Plotly kwargs last; its partial map must not
    # replace the merged one.
    trigger = {**SCATTER, "dict_kwargs": {"color_discrete_map": '{"Venice": "#111111"}'}}
    fig, _info = render_map(DF, trigger, category_colors={"city": {"Athens": "#1a4f8f"}})
    colours = _trace_colours(fig)
    assert colours["Athens"] == "#1a4f8f"
    assert colours["Venice"] == "#111111"


def test_other_columns_and_the_auto_key_are_ignored() -> None:
    fig, info = render_map(
        DF,
        SCATTER,
        category_colors={"habitat": {"Soil": "#123456"}, "city": {"*": "auto"}},
    )
    palette = px.colors.qualitative.Plotly
    assert _trace_colours(fig) == {
        "Athens": palette[0],
        "Naples": palette[1],
        "Rome": palette[2],
        "Venice": palette[3],
    }
    assert "*" not in info["color_discrete_map"]


def test_without_dashboard_colours_the_map_is_unchanged() -> None:
    plain, plain_info = render_map(DF, SCATTER)
    none, none_info = render_map(DF, SCATTER, category_colors=None)
    assert _trace_colours(plain) == _trace_colours(none)
    assert plain_info["color_discrete_map"] == none_info["color_discrete_map"]


def test_choropleth_takes_the_dashboard_colours_for_a_categorical_column() -> None:
    square = [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "id": "A", "geometry": {"type": "Polygon", "coordinates": square}},
            {"type": "Feature", "id": "B", "geometry": {"type": "Polygon", "coordinates": square}},
        ],
    }
    df = pd.DataFrame({"region": ["A", "B"], "zone": ["north", "south"]})
    trigger = {
        "map_type": "choropleth_map",
        "locations_column": "region",
        "color_column": "zone",
        "geojson_data": geojson,
    }
    fig, _info = render_map(df, trigger, category_colors={"zone": {"north": "#2a78d6"}})
    # A discrete choropleth is one trace per category, coloured by a flat scale.
    colours = {t.name: t.colorscale[0][1] for t in fig.data}
    assert colours["north"] == "#2a78d6"
    assert colours["south"] == px.colors.qualitative.Plotly[1]
