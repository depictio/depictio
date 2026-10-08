"""A code-mode figure that names no colours draws its categories in the
dashboard's, like a UI-mode figure does through ``color_discrete_map``."""

import pandas as pd
import plotly.express as px

from depictio.api.v1.services.figure.figure_builder import recolor_code_figure

CITIES = {"Athens": "#1a4f8f", "Barcelona": "#f5a11b", "Naples": "#00a550"}
COLORS = {"locality": CITIES, "season": {"Spring": "#40c057", "Summer": "#fab005"}}
DF = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6], "locality": ["Athens", "Barcelona", "Naples"] * 2})


def _colours(fig):
    return {t.name: t.marker.color for t in fig.data}


def test_histogram_takes_the_dashboard_colours():
    fig = px.histogram(DF, x="v", color="locality")
    assert recolor_code_figure(fig, COLORS, "fig = px.histogram(df, x='v', color='locality')")
    assert _colours(fig) == CITIES


def test_box_line_follows_the_marker():
    fig = px.box(DF, x="locality", y="v", color="locality")
    recolor_code_figure(fig, COLORS, "px.box(...)")
    assert {t.name: t.marker.color for t in fig.data} == CITIES


def test_code_with_its_own_map_is_left_alone():
    code = "px.histogram(df, x='v', color='locality', color_discrete_map={'Athens': 'red'})"
    fig = px.histogram(DF, x="v", color="locality", color_discrete_map={"Athens": "red"})
    before = _colours(fig)
    assert not recolor_code_figure(fig, COLORS, code)
    assert _colours(fig) == before


def test_traces_naming_unknown_values_are_left_alone():
    df = DF.assign(locality=["Athens", "Paris", "Naples"] * 2)
    fig = px.histogram(df, x="v", color="locality")
    before = _colours(fig)
    assert not recolor_code_figure(fig, COLORS, "")
    assert _colours(fig) == before


def test_other_does_not_block_recolouring():
    df = DF.assign(locality=["Athens", "Other", "Naples"] * 2)
    fig = px.histogram(df, x="v", color="locality")
    assert recolor_code_figure(fig, COLORS, "")
    assert _colours(fig)["Athens"] == CITIES["Athens"]
    assert _colours(fig)["Naples"] == CITIES["Naples"]


def test_no_dashboard_colours():
    fig = px.histogram(DF, x="v", color="locality")
    assert not recolor_code_figure(fig, None, "")
    assert not recolor_code_figure(fig, {}, "")


# The ampliseq templates' figures take their map from the analysis groups.
TEMPLATE_CODE = (
    "fig = px.box(df, x='_grp', y='value', color='_grp',\n"
    "    color_discrete_map=depictio_group_kwargs.get('color_discrete_map', {}),\n"
    ")"
)


def test_a_map_read_from_the_groups_is_no_colour_of_its_own_while_ungrouped():
    """No group set: the map is empty, Plotly's cycle drew the cities."""
    fig = px.box(DF, x="locality", y="v", color="locality")
    assert recolor_code_figure(fig, COLORS, TEMPLATE_CODE)
    assert _colours(fig) == CITIES


def test_a_map_read_from_the_groups_is_kept_while_grouped():
    fig = px.box(DF, x="locality", y="v", color="locality", color_discrete_map={"Athens": "red"})
    before = _colours(fig)
    assert not recolor_code_figure(fig, COLORS, TEMPLATE_CODE, grouped=True)
    assert _colours(fig) == before


def test_a_map_of_the_codes_own_beside_the_groups_one_still_counts():
    code = TEMPLATE_CODE + "\nfig.update_traces(marker_color='red')"
    fig = px.box(DF, x="locality", y="v", color="locality")
    assert not recolor_code_figure(fig, COLORS, code)
