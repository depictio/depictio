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


def test_default_style_keeps_the_drawing():
    fig = _scatter()
    before = copy.deepcopy(fig)
    for style in ("default", None, "unknown"):
        assert apply_figure_style(fig, style) == fig
    assert fig == before


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


@pytest.mark.parametrize("symbol", ["line-ns", "cross-thin", "circle-open", "x-thin-open"])
def test_a_marker_drawn_by_its_outline_is_left_as_drawn(symbol):
    """A median tick or an open circle is its outline: zeroing it erases the mark."""
    marker = apply_figure_style(_scatter(symbol=symbol, size=30, line={"width": 3}), "minimal")[
        "data"
    ][0]["marker"]
    assert marker["size"] == 30
    assert marker["line"]["width"] == 3


def test_strip_points_are_sized_as_a_scatters():
    df = pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0], "city": ["A", "A", "B", "B"]})
    fig = json.loads(px.strip(df, x="v", y="city").to_json())
    trace = apply_figure_style(fig, "minimal")["data"][0]
    assert trace["marker"]["size"] == 12
    # The strip's box stays hidden: no outline drawn around its points.
    assert "width" not in (trace.get("line") or {})


def test_box_outliers_stay_small():
    df = pd.DataFrame({"v": [1.0, 2.0, 3.0, 40.0], "city": ["A"] * 4})
    fig = json.loads(px.box(df, x="city", y="v").to_json())
    assert apply_figure_style(fig, "minimal")["data"][0]["marker"]["size"] == 5


def _stacked_bars(**layout):
    df = pd.DataFrame(
        {"city": ["A", "A", "B", "B"], "taxon": ["x", "y", "x", "y"], "share": [0.6, 0.4, 0.3, 0.7]}
    )
    fig = json.loads(px.bar(df, x="share", y="city", color="taxon", orientation="h").to_json())
    fig["layout"].update(barmode="stack", **layout)
    return fig


@pytest.mark.parametrize("theme, surface", [("light", "#ffffff"), ("dark", "#242424")])
def test_stacked_segments_are_parted_by_a_gap_of_the_cards_colour(theme, surface):
    out = apply_figure_style(_stacked_bars(), "minimal", theme=theme)
    for trace in out["data"]:
        assert trace["marker"]["line"] == {"width": 1, "color": surface}


def test_bars_get_rounded_ends_unless_the_author_set_a_radius():
    assert apply_figure_style(_stacked_bars(), "minimal")["layout"]["barcornerradius"] == 4
    kept = apply_figure_style(_stacked_bars(barcornerradius=10), "minimal")
    assert kept["layout"]["barcornerradius"] == 10


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


def _bars(**layout):
    return {
        "data": [
            {
                "type": "bar",
                "orientation": "h",
                "x": [3, 5],
                "y": ["Athens", "Naples"],
                "text": ["3", "5"],
            }
        ],
        "layout": layout,
    }


def test_minimal_sets_inter_over_the_stock_font():
    from depictio.cli.cli.utils.mantine_templates import FONT_FAMILY

    plain = apply_figure_style(_bars(), "minimal")["layout"]
    assert plain["font"]["family"].startswith('"Inter Variable", Inter,')
    stock = _bars(template={"layout": {"font": {"family": FONT_FAMILY}}})
    assert apply_figure_style(stock, "minimal")["layout"]["font"]["family"].startswith(
        '"Inter Variable"'
    )


def test_minimal_keeps_a_brand_or_author_font():
    brand = _bars(template={"layout": {"font": {"family": "Lato, sans-serif"}}})
    assert "family" not in (apply_figure_style(brand, "minimal")["layout"].get("font") or {})
    own = _bars(font={"family": "Georgia, serif", "size": 13})
    assert apply_figure_style(own, "minimal")["layout"]["font"] == {
        "family": "Georgia, serif",
        "size": 13,
    }


def test_minimal_weights_category_names_and_bar_values():
    out = apply_figure_style(_bars(), "minimal")
    layout = out["layout"]
    # Horizontal bars: the cities are on y, the values on x.
    assert layout["yaxis"]["tickfont"]["weight"] == 500
    assert layout["yaxis"]["tickfont"]["color"] == "#495057"
    assert "weight" not in layout["xaxis"]["tickfont"]
    assert out["data"][0]["textfont"]["weight"] == 500
    go.Figure(out)


def test_minimal_leaves_an_authors_bar_text_weight():
    fig = _bars()
    fig["data"][0]["textfont"] = {"weight": 700}
    assert apply_figure_style(fig, "minimal")["data"][0]["textfont"]["weight"] == 700


# ---------------------------------------------------------------------------
# hover labels follow their series


def _bar(colour):
    return {
        "data": [
            {"type": "bar", "name": "HIGH", "x": ["a"], "y": [1], "marker": {"color": colour}}
        ],
        "layout": {},
    }


def test_a_series_hover_label_wears_the_series_colour():
    out = apply_figure_style(_bar("#e03131"), "minimal")
    label = out["data"][0]["hoverlabel"]
    assert label["bgcolor"] == "#e03131"
    assert label["bordercolor"] == "#ffffff"
    # Dark red: white ink.
    assert label["font"]["color"] == "#ffffff"


def test_a_light_series_gets_dark_ink_on_its_hover_label():
    label = apply_figure_style(_bar("#fab005"), "minimal")["data"][0]["hoverlabel"]
    assert label["font"]["color"] == "#212529"


def test_rgb_colours_count_as_colours():
    label = apply_figure_style(_bar("rgb(34, 139, 230)"), "minimal")["data"][0]["hoverlabel"]
    assert label["bgcolor"] == "rgb(34, 139, 230)"


def test_stacked_segments_each_answer_in_their_own_colour():
    out = apply_figure_style(_stacked_bars(), "minimal")
    colours = [t["marker"]["color"] for t in out["data"]]
    assert len(set(colours)) == 2
    assert [t["hoverlabel"]["bgcolor"] for t in out["data"]] == colours


def test_per_point_colours_give_per_point_hover_colours():
    fig = _bar(["#e03131", "#fab005"])
    fig["data"][0].update(x=["a", "b"], y=[1, 2])
    label = apply_figure_style(fig, "minimal")["data"][0]["hoverlabel"]
    assert label["bgcolor"] == ["#e03131", "#fab005"]
    assert label["font"]["color"] == ["#ffffff", "#212529"]


@pytest.mark.parametrize("colour", [[0.1, 0.9], "tomato", "hsl(10, 50%, 50%)", None])
def test_a_scale_a_name_or_no_colour_keeps_the_neutral_hover_label(colour):
    out = apply_figure_style(_bar(colour), "minimal")
    assert "hoverlabel" not in out["data"][0]
    assert out["layout"]["hoverlabel"]["bgcolor"] == "#ffffff"


def test_a_line_only_scatter_takes_its_line_colour():
    fig = {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "x": [0, 1],
                "y": [0, 1],
                "line": {"color": "#1c7ed6"},
            }
        ],
        "layout": {},
    }
    assert apply_figure_style(fig, "minimal")["data"][0]["hoverlabel"]["bgcolor"] == "#1c7ed6"


def test_the_default_style_colours_hover_labels_too():
    fig = _bar("#e03131")
    before = copy.deepcopy(fig)
    out = apply_figure_style(fig, "default")
    assert out["data"][0]["hoverlabel"]["bgcolor"] == "#e03131"
    assert out["layout"] == fig["layout"]
    assert fig == before


def test_a_hover_line_without_a_name_is_dropped():
    fig = _bar("#e03131")
    fig["data"][0]["hovertemplate"] = "Impact class=HIGH<br>=%{x}<br>Share (%)=%{y}<extra></extra>"
    out = apply_figure_style(fig, "minimal")
    assert out["data"][0]["hovertemplate"] == "Impact class=HIGH<br>Share (%)=%{y}<extra></extra>"
    # A figure that never had the line is left alone.
    fig["data"][0]["hovertemplate"] = "a=%{x}<br>b=%{y}<extra></extra>"
    assert (
        apply_figure_style(fig, "minimal")["data"][0]["hovertemplate"]
        == fig["data"][0]["hovertemplate"]
    )


def test_the_unnamed_line_can_be_the_last_one_without_losing_the_extra_tail():
    fig = _bar("#e03131")
    fig["data"][0]["hovertemplate"] = "Impact class=HIGH<br>count=%{x}<br>=%{y}<extra></extra>"
    out = apply_figure_style(fig, "minimal")
    assert out["data"][0]["hovertemplate"] == "Impact class=HIGH<br>count=%{x}<extra></extra>"
    # The only value line is never dropped.
    fig["data"][0]["hovertemplate"] = "=%{y}<extra></extra>"
    assert apply_figure_style(fig, "minimal")["data"][0]["hovertemplate"] == "=%{y}<extra></extra>"


def test_a_translucent_series_colour_keeps_the_neutral_hover_label():
    for colour in ("rgba(99,110,250,0.25)", "rgba(99, 110, 250, 0.5)"):
        out = apply_figure_style(_bar(colour), "minimal")
        assert "bgcolor" not in out["data"][0].get("hoverlabel", {})
    # An almost opaque one still colours the label.
    out = apply_figure_style(_bar("rgba(224,49,49,0.95)"), "minimal")
    assert out["data"][0]["hoverlabel"]["bgcolor"] == "rgba(224,49,49,0.95)"


def test_a_hover_label_the_figure_chose_is_kept():
    fig = _bar("#e03131")
    fig["data"][0]["hoverlabel"] = {"bgcolor": "#000000", "font": {"color": "#ffffff"}}
    out = apply_figure_style(fig, "minimal")
    assert out["data"][0]["hoverlabel"] == {"bgcolor": "#000000", "font": {"color": "#ffffff"}}
