"""The `minimal` figure style: a pure overlay on a serialised figure.

`apply_figure_style` runs last on every render path (UI, code, aggregation),
on the figure dict, so these tests feed it figure dicts directly: hand-written
ones for the exact rules and real Plotly Express output for each chart type the
preset claims to handle.
"""

import copy
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytest

from depictio.api.v1.services.figure.style_presets import (
    DEFAULT_FIGURE_STYLE,
    FIGURE_STYLES,
    apply_figure_style,
    figure_style_payload,
    resolve_figure_style,
    section_figure_style,
)


def _scatter(n=3, **marker):
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "Athens",
                "x": list(range(n)),
                "y": list(range(n)),
                "marker": {"size": 9, "opacity": 0.8, "line": {"width": 1}, **marker},
            }
        ],
        "layout": {
            "title": {"text": "PCoA"},
            "xaxis": {"title": {"text": "PCo1"}, "zeroline": True, "showline": True},
            "yaxis": {"title": {"text": "PCo2"}},
            "legend": {"title": {"text": "City"}, "orientation": "v"},
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "paper_bgcolor": "white",
        },
    }


# ---------------------------------------------------------------------------
# resolution


def test_styles_are_default_and_minimal():
    assert FIGURE_STYLES == ("default", "minimal")
    assert DEFAULT_FIGURE_STYLE == "default"


def test_resolve_takes_the_first_known_style():
    assert resolve_figure_style(None, "minimal", "default") == "minimal"
    assert resolve_figure_style("default", "minimal") == "default"
    assert resolve_figure_style("fancy", None, "minimal") == "minimal"
    assert resolve_figure_style(None, "", 3) == "default"


def test_section_figure_style_reads_the_named_grid_section():
    dash = {
        "grid_sections": [
            {"name": "At a glance", "figure_style": "minimal"},
            {"name": "Tables"},
        ]
    }
    assert section_figure_style(dash, "At a glance") == "minimal"
    assert section_figure_style(dash, "Tables") is None
    assert section_figure_style(dash, "Elsewhere") is None
    assert section_figure_style(dash, None) is None
    assert section_figure_style(None, "At a glance") is None
    assert (
        section_figure_style({"grid_sections": [{"name": "x", "figure_style": "odd"}]}, "x") is None
    )


SECTIONED = {"grid_sections": [{"name": "At a glance", "figure_style": "minimal"}]}


def test_payload_takes_the_figures_own_style_over_its_sections():
    component = {"section": "At a glance", "figure_style": "default", "title": "PCoA"}
    assert figure_style_payload(component, SECTIONED)["figure_style"] == "default"


def test_payload_falls_back_to_the_section_then_the_default():
    assert figure_style_payload({"section": "At a glance"}, SECTIONED)["figure_style"] == "minimal"
    assert figure_style_payload({"section": "Other"}, SECTIONED)["figure_style"] == "default"
    assert figure_style_payload({}, None)["figure_style"] == "default"


def test_payload_override_wins_and_is_validated():
    component = {"figure_style": "default", "title": "", "hide_legend": True}
    payload = figure_style_payload(
        component, None, {"figure_style": "minimal", "header_title": True, "hide_legend": False}
    )
    assert payload == {"figure_style": "minimal", "header_title": True, "hide_legend": False}
    # Unknown names and non-booleans fall through to the component's own.
    payload = figure_style_payload(
        component, None, {"figure_style": "<script>", "header_title": "yes", "hide_legend": 1}
    )
    assert payload == {"figure_style": "default", "header_title": False, "hide_legend": True}
    assert figure_style_payload(component, None, "minimal")["figure_style"] == "default"


def test_payload_header_title_follows_the_components_title():
    assert figure_style_payload({"title": "PCoA"})["header_title"] is True
    assert figure_style_payload({"title": "  "})["header_title"] is False


# ---------------------------------------------------------------------------
# the overlay


def test_default_style_returns_the_figure_untouched():
    fig = _scatter()
    assert apply_figure_style(fig, "default") is fig
    assert apply_figure_style(fig, None) is fig
    assert apply_figure_style(fig, "unknown") is fig


def test_overlay_does_not_mutate_its_input():
    fig = _scatter()
    before = copy.deepcopy(fig)
    apply_figure_style(fig, "minimal", header_title=True)
    assert fig == before


def test_minimal_layout():
    out = apply_figure_style(_scatter(), "minimal", header_title=True)
    layout = out["layout"]
    assert layout["paper_bgcolor"] == layout["plot_bgcolor"] == "rgba(0,0,0,0)"
    assert layout["title"] == {"text": ""}
    assert layout["margin"] == {"l": 8, "r": 8, "t": 8, "b": 8, "pad": 0}
    legend = layout["legend"]
    assert legend["orientation"] == "h"
    assert (legend["x"], legend["xanchor"]) == (0.5, "center")
    assert (legend["y"], legend["yref"], legend["yanchor"]) == (0, "container", "bottom")
    assert legend["title"] == {"text": ""}
    assert legend["itemsizing"] == "constant"
    assert layout["hoverlabel"]["bgcolor"] == "#ffffff"
    assert layout["modebar"]["bgcolor"] == "rgba(0,0,0,0)"
    for key in ("xaxis", "yaxis"):
        axis = layout[key]
        assert axis["showline"] is False
        assert axis["zeroline"] is False
        assert axis["showgrid"] is True
        assert axis["griddash"]
        assert axis["tickfont"]["size"] == 11
        assert axis["automargin"] is True
    assert layout["xaxis"]["title"]["text"] == "PCo1"


def test_title_kept_when_the_header_does_not_show_it():
    out = apply_figure_style(_scatter(), "minimal", header_title=False)
    assert out["layout"]["title"]["text"] == "PCoA"
    assert out["layout"]["title"]["xanchor"] == "left"
    assert out["layout"]["margin"]["t"] > 8


def test_dark_theme_colours():
    light = apply_figure_style(_scatter(), "minimal")["layout"]
    dark = apply_figure_style(_scatter(), "minimal", theme="dark")["layout"]
    assert light["xaxis"]["gridcolor"] != dark["xaxis"]["gridcolor"]
    assert dark["hoverlabel"]["bgcolor"] != "#ffffff"


def test_scatter_markers_are_large_and_unoutlined():
    marker = apply_figure_style(_scatter(), "minimal")["data"][0]["marker"]
    assert marker["size"] == 12
    assert marker["opacity"] == 0.9
    assert marker["line"]["width"] == 0


def test_many_points_get_smaller_markers():
    marker = apply_figure_style(_scatter(n=5000), "minimal")["data"][0]["marker"]
    assert marker["size"] < 12


def test_typed_array_points_are_counted():
    fig = _scatter()
    # 4000 float64 values as Plotly 6 serialises them.
    fig["data"][0]["x"] = {"dtype": "f8", "bdata": "A" * (4000 * 8 * 4 // 3)}
    marker = apply_figure_style(fig, "minimal")["data"][0]["marker"]
    assert marker["size"] < 12


def test_a_size_mapped_to_a_column_is_kept():
    marker = apply_figure_style(_scatter(size=[4, 8, 16]), "minimal")["data"][0]["marker"]
    assert marker["size"] == [4, 8, 16]


def test_bars_lose_their_outline_and_the_category_axis_its_grid():
    fig = {
        "data": [
            {"type": "bar", "x": ["a", "b"], "y": [1, 2], "marker": {"line": {"width": 1}}},
        ],
        "layout": {"xaxis": {}, "yaxis": {}},
    }
    out = apply_figure_style(fig, "minimal")
    assert out["data"][0]["marker"]["line"]["width"] == 0
    assert out["layout"]["bargap"] == pytest.approx(0.22)
    assert out["layout"]["xaxis"]["showgrid"] is False
    assert out["layout"]["yaxis"]["showgrid"] is True


def test_horizontal_bars_put_the_categories_on_y():
    fig = {
        "data": [{"type": "bar", "orientation": "h", "x": [1, 2], "y": ["a", "b"]}],
        "layout": {"xaxis": {}, "yaxis": {}},
    }
    layout = apply_figure_style(fig, "minimal")["layout"]
    assert layout["xaxis"]["showgrid"] is True
    assert layout["yaxis"]["showgrid"] is False


def test_hide_legend_in_any_style():
    for style in ("default", "minimal"):
        out = apply_figure_style(_scatter(), style, hide_legend=True)
        assert out["layout"]["showlegend"] is False


def test_an_author_hidden_legend_stays_hidden():
    fig = _scatter()
    fig["layout"]["showlegend"] = False
    assert apply_figure_style(fig, "minimal")["layout"]["showlegend"] is False


def test_facet_titles_above_the_plot_get_room():
    fig = _scatter()
    fig["layout"]["annotations"] = [
        {"text": "Athens", "x": 0.5, "y": 1.0, "xref": "paper", "yref": "paper",
         "showarrow": False, "yanchor": "bottom"},
    ]  # fmt: skip
    out = apply_figure_style(fig, "minimal", header_title=True)
    assert out["layout"]["margin"]["t"] > 8
    assert out["layout"]["annotations"][0]["font"]["size"] == 12


# ---------------------------------------------------------------------------
# grouped bars

HABITATS = {"Groundwater": "#5bb5c8", "Soil": "#e8a04f"}


def _grouped_bars(shared_categories=False):
    rows = []
    for habitat in HABITATS:
        for i in range(3):
            sample = f"s{i}" if shared_categories else f"{habitat}-{i}"
            for phylum, share in (("Proteobacteria", 0.6), ("Other", 0.4)):
                rows.append(
                    {"sample": sample, "habitat": habitat, "Phylum": phylum, "share": share}
                )
    fig = px.bar(pd.DataFrame(rows), x="sample", y="share", color="Phylum", facet_col="habitat")
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    return json.loads(fig.to_json())


def test_grouped_bars_get_an_underline_per_group():
    out = apply_figure_style(
        _grouped_bars(), "minimal", category_colors={"habitat": HABITATS}, header_title=True
    )
    layout = out["layout"]
    underlines = [s for s in layout["shapes"] if s.get("ysizemode") == "pixel"]
    assert [s["fillcolor"] for s in underlines] == list(HABITATS.values())
    labels = [a["text"] for a in layout["annotations"]]
    assert labels == list(HABITATS)
    # Under the plot, not over the panels.
    assert all(a["y"] == 0 and a["yshift"] < 0 for a in layout["annotations"])
    for key in ("xaxis", "xaxis2"):
        assert layout[key]["matches"] is None
        assert layout[key]["showticklabels"] is False
    assert layout["margin"]["b"] >= 36
    # The legend moves to the right, in stacking order.
    assert layout["legend"]["orientation"] == "v"
    assert layout["legend"]["traceorder"] == "reversed"


def test_group_colour_falls_back_to_a_trace_of_that_name_then_neutral():
    out = apply_figure_style(_grouped_bars(), "minimal")
    colours = [s["fillcolor"] for s in out["layout"]["shapes"]]
    assert len(colours) == 2 and len(set(colours)) == 1  # neutral for both


def test_facets_that_repeat_categories_are_not_groups():
    out = apply_figure_style(_grouped_bars(shared_categories=True), "minimal")
    assert not out["layout"].get("shapes")
    assert [a["text"] for a in out["layout"]["annotations"]] == list(HABITATS)


# ---------------------------------------------------------------------------
# every chart type the preset claims


TIPS = px.data.tips()
IRIS = px.data.iris()


@pytest.mark.parametrize(
    "build",
    [
        lambda: px.scatter(IRIS, x="sepal_width", y="sepal_length", color="species"),
        lambda: px.bar(TIPS, x="day", y="total_bill", color="sex", barmode="group"),
        lambda: px.box(TIPS, x="day", y="total_bill", color="smoker", points="all"),
        lambda: px.violin(TIPS, x="day", y="tip", color="sex"),
        lambda: px.line(TIPS.sort_values("total_bill"), x="total_bill", y="tip", color="sex"),
        lambda: px.histogram(TIPS, x="total_bill", color="sex"),
        lambda: px.density_heatmap(TIPS, x="total_bill", y="tip"),
        lambda: px.imshow([[1, 2], [3, 4]]),
    ],
    ids=["scatter", "bar", "box", "violin", "line", "histogram", "density_heatmap", "heatmap"],
)
def test_minimal_is_a_valid_figure_for_each_type(build):
    fig = json.loads(build().to_json())
    out = apply_figure_style(fig, "minimal", header_title=True)
    # Plotly validates every property on construction: a misspelt key or a
    # wrong value type raises here.
    go.Figure(out)
    assert out["layout"]["plot_bgcolor"] == "rgba(0,0,0,0)"


def test_heatmap_axes_have_no_grid():
    fig = json.loads(px.imshow([[1, 2], [3, 4]]).to_json())
    layout = apply_figure_style(fig, "minimal")["layout"]
    assert layout["xaxis"]["showgrid"] is False
    assert layout["yaxis"]["showgrid"] is False
