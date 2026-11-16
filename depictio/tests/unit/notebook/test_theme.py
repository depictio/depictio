"""The report's Paper look on the Python side: glassPlotly + glassPlotlyDefaults."""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import pytest

from depictio.notebook import theme
from depictio.notebook.components import figure_bundle


@pytest.fixture(autouse=True)
def _restore():
    default, state = pio.templates.default, dict(theme._STATE)
    yield
    pio.templates.default = default
    theme._STATE.clear()
    theme._STATE.update(state)


def test_paper_layout_is_glass_plotly_light():
    layout = theme.paper_layout()
    sans = "'Inter Variable', Inter, " + theme.SYSTEM_SANS
    assert layout["font"] == {"family": sans, "color": "#212529"}
    assert layout["paper_bgcolor"] == layout["plot_bgcolor"] == "rgba(0, 0, 0, 0)"
    # A whisper of horizontal grid only, no axis lines, no ticks.
    assert layout["xaxis"]["showgrid"] is False and layout["yaxis"]["showgrid"] is True
    assert layout["yaxis"]["gridcolor"] == "rgba(33, 37, 41, 0.07)"
    assert layout["xaxis"]["zerolinecolor"] == "rgba(33, 37, 41, 0.16)"
    for axis in ("xaxis", "yaxis"):
        assert layout[axis]["showline"] is False and layout[axis]["ticks"] == ""
        assert layout[axis]["tickfont"]["color"] == "#868e96"
        assert layout[axis]["title"]["font"]["color"] == "#495057"
    # The hover label is a small white card with a hairline rim.
    assert layout["hoverlabel"]["bgcolor"] == "#ffffff"
    assert layout["hoverlabel"]["bordercolor"] == "rgba(33, 37, 41, 0.12)"
    assert layout["legend"]["borderwidth"] == 0 and layout["bargap"] == 0.3
    assert theme.paper_layout("Lato")["font"]["family"] == "'Inter Variable', Inter, Lato"


def test_colorway_leads_with_the_primary_then_glass_hues():
    assert theme.paper_colorway(None) == [
        "#228be6",
        "#12b886",
        "#fd7e14",
        "#be4bdb",
        "#15aabf",
        "#e64980",
        "#82c91e",
        "#4c6ef5",
        "#fab005",
        "#fa5252",
    ]
    # A primary that already is one of the hues is not listed twice.
    assert theme.paper_colorway("teal")[0] == "#12b886"
    assert len(theme.paper_colorway("teal")) == 9
    assert theme.paper_colorway("#123456")[0] == "#123456"


def test_primary_resolves_to_shade_6_and_its_ink_at_shade_7():
    assert theme.resolve_primary(None) == ("#228be6", "#1c7ed6")
    assert theme.resolve_primary("violet") == ("#7950f2", "#7048e8")
    six, seven = theme.resolve_primary("#00a550")
    assert six == "#00a550" and seven.startswith("#") and seven != six


def test_apply_theme_fills_unset_keys_and_overrides_the_patch():
    fig = {
        "data": [{"type": "bar", "x": [1], "y": [2]}],
        "layout": {
            "margin": {"l": 60},
            "font": {"family": "Arial", "size": 13},
            "xaxis2": {"title": {"text": "facet"}},
            "legend": {"orientation": "v", "x": 1.02},
            "colorway": ["#000000"],
        },
    }
    out = theme.apply_theme(fig, "paper")
    lay = out["layout"]
    # Defaults go under: the figure's own margin and colorway win...
    assert lay["margin"]["l"] == 60 and lay["margin"]["t"] == 8
    assert lay["colorway"] == ["#000000"]
    # ...and a legend the figure placed itself stays where it is.
    assert lay["legend"]["orientation"] == "v" and lay["legend"]["x"] == 1.02
    assert lay["legend"]["borderwidth"] == 0
    # The patch goes over: the font family is Paper's, the size the figure's.
    assert lay["font"]["family"].startswith("'Inter Variable'") and lay["font"]["size"] == 13
    # Every axis, facets included.
    assert lay["xaxis2"]["showgrid"] is False and lay["xaxis2"]["title"]["text"] == "facet"
    # The input is untouched, and classic changes nothing.
    assert fig["layout"]["font"]["family"] == "Arial"
    assert theme.apply_theme(fig, "classic") is fig


def test_an_unplaced_legend_runs_along_the_top_left():
    lay = theme.apply_theme({"data": [], "layout": {}}, "paper")["layout"]
    assert lay["legend"]["orientation"] == "h"
    assert (lay["legend"]["xref"], lay["legend"]["yref"]) == ("container", "container")


def test_a_titled_figure_gets_its_legend_at_the_bottom_left():
    # Paper puts the title at the top left: a legend there printed over it
    # (a map's "Sampling sites" under its colour key).
    for title in ("Sampling sites", {"text": "Sampling sites"}):
        lay = theme.apply_theme({"data": [], "layout": {"title": title}}, "paper")["layout"]
        assert (lay["legend"]["y"], lay["legend"]["yanchor"]) == (0, "bottom")
    untitled = theme.apply_theme({"data": [], "layout": {"title": {"text": " "}}}, "paper")
    assert untitled["layout"]["legend"]["yanchor"] == "top"


def test_use_theme_registers_the_template_and_embeds_inter():
    style = theme.use_theme("paper", primary="violet")
    assert style.startswith("<style>@font-face{font-family:'Inter Variable'")
    assert "data:font/woff2;base64," in style and "unicode-range" in style
    assert pio.templates.default == "plotly_white+depictio_paper"
    template = pio.templates[theme.TEMPLATE_NAME]
    assert template.layout.colorway[0] == "#7950f2"
    assert template.layout.plot_bgcolor == "rgba(0, 0, 0, 0)"
    # Every figure the document shows wears it, server-built ones included.
    bundle = figure_bundle(go.Figure(layout={"plot_bgcolor": "#e5ecf6"}))
    assert bundle["application/vnd.plotly.v1+json"]["layout"]["plot_bgcolor"] == "rgba(0, 0, 0, 0)"


def test_classic_leaves_plotly_alone():
    assert theme.use_theme("classic") == ""
    bundle = figure_bundle(go.Figure(layout={"plot_bgcolor": "#e5ecf6"}))
    assert bundle["application/vnd.plotly.v1+json"]["layout"]["plot_bgcolor"] == "#e5ecf6"
    with pytest.raises(ValueError):
        theme.use_theme("neon")
