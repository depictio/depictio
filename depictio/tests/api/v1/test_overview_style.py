"""The overview look (default figure style) and the classic style that opts out.

Figures are hand-built dicts shaped like Plotly Express output, so each rule is
tested on its own; `apply_figure_style` is checked for what each style chooses.
"""

import copy

import pytest

from depictio.api.v1.services.figure.overview_style import (
    OTHER_LEGENDGROUP,
    apply_overview,
)
from depictio.api.v1.services.figure.style_presets import apply_figure_style
from depictio.models import palettes

PALETTE = palettes.categorical(None, "light")
CHROME = palettes.chrome("light")


def _bar_by_x(cats=("a", "b", "c"), horizontal=False):
    """px.bar(color=x): one trace per category, named after it."""
    data = []
    for i, cat in enumerate(cats):
        trace = {
            "type": "bar",
            "name": cat,
            "legendgroup": cat,
            "showlegend": True,
            "marker": {"color": PALETTE[i % len(PALETTE)]},
            "orientation": "h" if horizontal else "v",
        }
        trace["y" if horizontal else "x"] = [cat]
        trace["x" if horizontal else "y"] = [i + 1]
        data.append(trace)
    return {"data": data, "layout": {"xaxis": {"title": {"text": "x"}}, "yaxis": {}}}


def _bar_stack(names, values=None, horizontal=False):
    """px.bar(x=sample, color=group): same categories in every trace."""
    data = []
    for i, name in enumerate(names):
        height = values[i] if values else 1
        trace = {
            "type": "bar",
            "name": name,
            "showlegend": True,
            "marker": {"color": PALETTE[i % len(PALETTE)]},
            "orientation": "h" if horizontal else "v",
        }
        trace["y" if horizontal else "x"] = ["s1", "s2"]
        trace["x" if horizontal else "y"] = [height, height]
        data.append(trace)
    return {"data": data, "layout": {"barmode": "stack"}}


def _scatter(n, **marker):
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "pts",
                "x": list(range(n)),
                "y": list(range(n)),
                "marker": dict(marker),
            }
        ],
        "layout": {},
    }


def _names(fig):
    return [t.get("name") for t in fig["data"]]


# ---------------------------------------------------------------------------
# a. single hue


def test_colour_that_only_repeats_x_becomes_one_hue_without_legend():
    out = apply_overview(_bar_by_x(), theme="light")
    assert {t["marker"]["color"] for t in out["data"]} == {PALETTE[0]}
    assert all(t["showlegend"] is False for t in out["data"])


def test_one_hue_follows_the_layout_colorway():
    fig = _bar_by_x()
    fig["layout"]["colorway"] = ["#123456", "#abcdef"]
    out = apply_overview(fig, theme="light")
    assert {t["marker"]["color"] for t in out["data"]} == {"#123456"}


def test_one_hue_also_reaches_boxes_and_horizontal_bars():
    box = {
        "data": [
            {"type": "box", "name": c, "x": [c] * 3, "y": [1, 2, 3], "marker": {"color": col}}
            for c, col in (("a", "#111111"), ("b", "#222222"))
        ],
        "layout": {},
    }
    out = apply_overview(box, theme="light")
    assert {t["marker"]["color"] for t in out["data"]} == {PALETTE[0]}
    assert {t["line"]["color"] for t in out["data"]} == {PALETTE[0]}
    horizontal = apply_overview(_bar_by_x(horizontal=True), theme="light")
    assert {t["marker"]["color"] for t in horizontal["data"]} == {PALETTE[0]}


def test_a_real_grouping_keeps_its_colours_and_legend():
    out = apply_overview(_bar_stack(["g1", "g2", "g3"]), theme="light")
    assert [t["marker"]["color"] for t in out["data"]] == PALETTE[:3]
    assert all(t["showlegend"] is True for t in out["data"])


def test_a_trace_named_otherwise_than_its_x_is_not_a_repeat():
    fig = _bar_by_x()
    fig["data"][0]["name"] = "something else"
    out = apply_overview(fig, theme="light")
    assert out["data"][1]["marker"]["color"] == PALETTE[1]


# ---------------------------------------------------------------------------
# b. sorted bars


def test_vertical_string_bars_sort_by_total_descending():
    out = apply_overview(_bar_by_x(), theme="light")
    assert out["layout"]["xaxis"]["categoryorder"] == "total descending"
    assert "categoryorder" not in out["layout"]["yaxis"]


def test_horizontal_bars_sort_ascending_on_y_so_the_biggest_is_on_top():
    out = apply_overview(_bar_by_x(horizontal=True), theme="light")
    assert out["layout"]["yaxis"]["categoryorder"] == "total ascending"


def test_an_axis_with_an_order_is_never_touched():
    for key, value in (("categoryorder", "category ascending"), ("categoryarray", ["b", "a"])):
        fig = _bar_by_x()
        fig["layout"]["xaxis"][key] = value
        axis = apply_overview(fig, theme="light")["layout"]["xaxis"]
        assert axis[key] == value
        assert set(axis) - {"title", "showgrid", "ticks", "zerolinecolor"} == {key}


def test_numeric_and_date_looking_categories_keep_their_order():
    fig = _bar_by_x(cats=("2019", "2020", "2021"))
    assert "categoryorder" not in apply_overview(fig, theme="light")["layout"]["xaxis"]


@pytest.mark.parametrize(
    "cats",
    [
        ("chr1", "chr2", "chr10", "chrX", "chrM"),
        ("1", "2", "X", "Y", "MT"),
        ("0-10", "10-20", "20-50"),
        ("1 kb", "5 kb", "10 kb"),
        ("<1", "1-5", ">5"),
        ("Jan", "Feb", "Mar"),
        ("Q1", "Q2", "Q3", "Q4"),
    ],
)
def test_categories_with_an_order_of_their_own_are_not_sorted(cats):
    fig = _bar_by_x(cats=cats)
    assert "categoryorder" not in apply_overview(fig, theme="light")["layout"]["xaxis"]


def test_numeric_x_bars_are_not_sorted():
    fig = _bar_stack(["g1"])
    fig["data"][0]["x"] = [1, 2]
    assert "xaxis" not in apply_overview(fig, theme="light")["layout"] or (
        "categoryorder" not in apply_overview(fig, theme="light")["layout"]["xaxis"]
    )


# ---------------------------------------------------------------------------
# c. remainder last, colour folding


@pytest.mark.parametrize(
    ("name", "kind"), [("Other", "other"), ("unclassified", "unclassified"), ("NA", "na")]
)
def test_reserved_traces_go_last_in_their_grey(name, kind):
    fig = _bar_stack([name, "g1", "g2"])
    out = apply_overview(fig, theme="light")
    assert _names(out) == ["g1", "g2", name]
    assert out["data"][-1]["marker"]["color"] == palettes.semantic(kind, "light")


def test_remainder_order_is_other_then_unclassified_then_na():
    out = apply_overview(_bar_stack(["NA", "Unclassified", "g1", "Other"]), theme="light")
    assert _names(out) == ["g1", "Other", "Unclassified", "NA"]


def test_a_dark_theme_takes_the_dark_greys():
    out = apply_overview(_bar_stack(["Other", "g1"]), theme="dark")
    assert out["data"][-1]["marker"]["color"] == palettes.semantic("other", "dark")


def test_an_unnamed_trace_is_not_a_reserved_value():
    fig = _bar_stack(["g1", "g2"])
    del fig["data"][0]["name"]
    out = apply_overview(fig, theme="light")
    assert out["data"][0]["marker"]["color"] == PALETTE[0]


def test_more_than_eight_series_fold_the_smallest_into_one_grey_entry():
    names = [f"g{i}" for i in range(12)]
    # g0 .. g11 with heights 12 .. 1: the last four are the smallest.
    fig = _bar_stack(names, values=list(range(12, 0, -1)))
    before = [t["name"] for t in fig["data"]]
    out = apply_overview(fig, theme="light")
    grey = palettes.semantic("other", "light")
    kept = [t for t in out["data"] if t["marker"]["color"] != grey]
    folded = [t for t in out["data"] if t["marker"]["color"] == grey]
    assert [t["name"] for t in kept] == before[:8]
    assert len(out["data"]) == 12  # colour only: nothing is dropped
    assert all(t["legendgroup"] == OTHER_LEGENDGROUP for t in folded)
    assert [t.get("showlegend") for t in folded] == [True, False, False, False]
    assert folded[0]["name"] == "Other (4)"
    # Kept series keep their legend entries and their colours.
    assert all(t["showlegend"] is True for t in kept)
    assert [t["marker"]["color"] for t in kept] == PALETTE[:8]


def test_folding_ranks_horizontal_bars_by_their_x_and_other_types_by_points():
    horizontal = _bar_stack(
        [f"g{i}" for i in range(10)], values=list(range(1, 11)), horizontal=True
    )
    out = apply_overview(horizontal, theme="light")
    grey = palettes.semantic("other", "light")
    assert sorted(t["name"] for t in out["data"] if t["marker"]["color"] != grey) == sorted(
        f"g{i}" for i in range(2, 10)
    )

    lines = {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "name": f"s{i}",
                "x": list(range(i + 1)),
                "y": list(range(i + 1)),
                "line": {"color": PALETTE[i % 8]},
            }
            for i in range(10)
        ],
        "layout": {},
    }
    out = apply_overview(lines, theme="light")
    folded = [t for t in out["data"] if t["line"]["color"] == grey]
    assert sorted(t["x"][-1] for t in folded) == [0, 1]  # the two shortest series


def test_a_kept_colour_repeat_is_recoloured_from_the_figures_own_colorway():
    """The brand's colorway is the figure's palette: a re-colour after the fold
    hands out its hues, not the default palette's."""
    colorway = palettes.categorical("signature")[:6]
    fig = _bar_stack([f"g{i}" for i in range(12)], values=list(range(12, 0, -1)))
    # One hue everywhere: the kept eight would repeat it.
    for trace in fig["data"]:
        trace["marker"]["color"] = colorway[0]
    fig["layout"]["colorway"] = colorway
    out = apply_overview(fig, theme="light")
    grey = palettes.semantic("other", "light")
    kept = [t for t in out["data"] if t["marker"]["color"] != grey]
    assert [t["marker"]["color"] for t in kept] == [colorway[i % len(colorway)] for i in range(8)]


def test_eight_series_are_left_alone():
    fig = _bar_stack([f"g{i}" for i in range(8)])
    out = apply_overview(fig, theme="light")
    assert [t["marker"]["color"] for t in out["data"]] == PALETTE[:8]
    assert all("legendgroup" not in t for t in out["data"])


def test_a_cycled_palette_gives_the_kept_series_distinct_colours():
    fig = _bar_stack([f"g{i}" for i in range(10)], values=[10] * 10)
    fig["data"][8]["marker"]["color"] = PALETTE[0]  # px cycles past the 8 slots
    fig["data"][9]["marker"]["color"] = PALETTE[1]
    grey = palettes.semantic("other", "light")
    out = apply_overview(fig, theme="light")
    kept = [t["marker"]["color"] for t in out["data"] if t["marker"]["color"] != grey]
    assert len(kept) == 8 and len(set(kept)) == 8


# ---------------------------------------------------------------------------
# d. light chrome


def test_vertical_bars_keep_only_the_horizontal_grid():
    layout = apply_overview(_bar_stack(["g1", "g2"]), theme="light")["layout"]
    assert layout["xaxis"]["showgrid"] is False
    assert layout["yaxis"]["gridcolor"] == CHROME["grid"]
    assert "showgrid" not in layout["yaxis"]


def test_horizontal_bars_keep_only_the_vertical_grid():
    layout = apply_overview(_bar_stack(["g1", "g2"], horizontal=True), theme="light")["layout"]
    assert layout["yaxis"]["showgrid"] is False
    assert layout["xaxis"]["gridcolor"] == CHROME["grid"]


def test_scatter_keeps_both_grids_in_the_light_ink():
    layout = apply_overview(_scatter(10), theme="light")["layout"]
    for key in ("xaxis", "yaxis"):
        assert layout[key]["gridcolor"] == CHROME["grid"]
        assert "showgrid" not in layout[key]


def test_ticks_zero_line_font_and_hover_come_from_the_chrome():
    layout = apply_overview(_bar_stack(["g1"]), theme="light")["layout"]
    assert layout["yaxis"]["ticks"] == ""
    assert layout["yaxis"]["zerolinecolor"] == CHROME["zero"]
    assert layout["font"]["family"] == palettes.font_family()
    assert layout["hoverlabel"]["bgcolor"] == CHROME["hover_bg"]
    assert layout["hoverlabel"]["bordercolor"] == CHROME["hover_border"]
    assert layout["hoverlabel"]["font"]["color"] == CHROME["hover_text"]


def test_dark_theme_uses_the_dark_chrome():
    layout = apply_overview(_scatter(10), theme="dark")["layout"]
    assert layout["xaxis"]["gridcolor"] == palettes.chrome("dark")["grid"]


def test_author_axis_settings_font_and_hover_win():
    fig = _bar_stack(["g1"])
    fig["layout"] = {
        "yaxis": {"gridcolor": "#ff0000", "ticks": "outside", "zerolinecolor": "#00ff00"},
        "xaxis": {"showgrid": True},
        "font": {"family": "Georgia"},
        "hoverlabel": {"bgcolor": "#000000", "font": {"color": "#fafafa"}},
    }
    layout = apply_overview(fig, theme="light")["layout"]
    assert layout["yaxis"]["gridcolor"] == "#ff0000"
    assert layout["yaxis"]["ticks"] == "outside"
    assert layout["yaxis"]["zerolinecolor"] == "#00ff00"
    assert layout["xaxis"]["showgrid"] is True
    assert layout["font"]["family"] == "Georgia"
    assert layout["hoverlabel"]["bgcolor"] == "#000000"
    assert layout["hoverlabel"]["font"]["color"] == "#fafafa"
    assert layout["hoverlabel"]["bordercolor"] == CHROME["hover_border"]


def test_a_template_level_value_counts_as_unset():
    fig = _scatter(10)
    fig["layout"]["template"] = {
        "layout": {"xaxis": {"gridcolor": "#abcdef"}, "font": {"family": "Arial"}}
    }
    out = apply_overview(fig, theme="light")
    assert out["layout"]["xaxis"]["gridcolor"] == CHROME["grid"]
    assert out["layout"]["template"] == fig["layout"]["template"]


def test_a_non_cartesian_figure_gets_no_axes():
    pie = {"data": [{"type": "pie", "labels": ["a"], "values": [1]}], "layout": {}}
    layout = apply_overview(pie, theme="light")["layout"]
    assert "xaxis" not in layout and "yaxis" not in layout
    assert layout["font"]["family"] == palettes.font_family()


# ---------------------------------------------------------------------------
# e. rounded bars


def test_bars_get_the_corner_radius_unless_the_author_set_one():
    assert apply_overview(_bar_stack(["g1"]), theme="light")["layout"]["barcornerradius"] == 4
    fig = _bar_stack(["g1"])
    fig["layout"]["barcornerradius"] = 0
    assert apply_overview(fig, theme="light")["layout"]["barcornerradius"] == 0
    assert "barcornerradius" not in apply_overview(_scatter(5), theme="light")["layout"]


# ---------------------------------------------------------------------------
# f. scatter markers by point count


@pytest.mark.parametrize("n", [30, 200, 3000, 20000])
def test_markers_follow_the_bucket_of_the_point_count(n):
    bucket = palettes.scatter_marker(n)
    marker = apply_overview(_scatter(n), theme="light")["data"][0]["marker"]
    assert marker["size"] == bucket["size"]
    assert marker["opacity"] == bucket["opacity"]
    if bucket["outline"]:
        assert marker["line"] == {"width": 0.5, "color": CHROME["surface"]}
    else:
        assert "line" not in marker


def test_the_count_is_over_all_marker_traces_of_the_figure():
    fig = _scatter(30)
    second = copy.deepcopy(fig["data"][0])
    second["name"] = "more"
    second["x"] = second["y"] = list(range(30))
    fig["data"].append(second)
    # 60 points: the 500 bucket, not the 50 one.
    assert apply_overview(fig, theme="light")["data"][0]["marker"]["size"] == 7


def test_explicit_marker_size_opacity_and_outline_win():
    fig = _scatter(30, size=15, opacity=0.3, line={"width": 2, "color": "#000000"})
    marker = apply_overview(fig, theme="light")["data"][0]["marker"]
    assert marker["size"] == 15
    assert marker["opacity"] == 0.3
    assert marker["line"] == {"width": 2, "color": "#000000"}


def test_a_size_column_is_data_and_stays():
    fig = _scatter(3, size=[5, 10, 20])
    assert apply_overview(fig, theme="light")["data"][0]["marker"]["size"] == [5, 10, 20]


def test_line_traces_and_line_symbols_are_left_alone():
    lines = _scatter(30)
    lines["data"][0]["mode"] = "lines+markers"
    assert "size" not in apply_overview(lines, theme="light")["data"][0]["marker"]
    ticks = _scatter(30, symbol="line-ns")
    assert "size" not in apply_overview(ticks, theme="light")["data"][0]["marker"]


def test_typed_array_points_are_counted():
    fig = _scatter(0)
    fig["data"][0]["x"] = {"dtype": "i4", "bdata": "AAAAAAEAAAA="}  # two int32 points
    assert apply_overview(fig, theme="light")["data"][0]["marker"]["size"] == 9


# ---------------------------------------------------------------------------
# purity and styles


def test_apply_overview_never_mutates_its_input_and_shares_the_data():
    fig = _bar_stack([f"g{i}" for i in range(10)])
    fig["layout"]["template"] = {"layout": {"colorway": ["#111111"]}}
    before = copy.deepcopy(fig)
    out = apply_overview(fig, theme="light")
    assert fig == before
    assert out["data"][0]["x"] is fig["data"][0]["x"]
    assert out["layout"]["template"] is fig["layout"]["template"]


def test_classic_leaves_the_drawing_alone():
    fig = _bar_by_x()
    fig["data"][0]["marker"]["color"] = "#e03131"
    before = copy.deepcopy(fig)
    out = apply_figure_style(fig, "classic")
    assert fig == before
    assert out["layout"] == fig["layout"]
    for new, old in zip(out["data"], fig["data"], strict=True):
        assert new["marker"] == old["marker"]
        assert new["showlegend"] == old["showlegend"]
    # Its tooltips still follow the series colour, like the default's.
    assert out["data"][0]["hoverlabel"]["bgcolor"] == "#e03131"


def test_classic_still_hides_the_legend_on_request():
    out = apply_figure_style(_bar_stack(["g1", "g2"]), "classic", hide_legend=True)
    assert out["layout"]["showlegend"] is False


def test_default_is_the_overview_look_with_series_coloured_tooltips():
    fig = _bar_by_x()
    out = apply_figure_style(fig, "default")
    assert out["layout"]["xaxis"]["categoryorder"] == "total descending"
    assert out["data"][0]["marker"]["color"] == PALETTE[0]
    assert out["data"][0]["hoverlabel"]["bgcolor"] == PALETTE[0]
    assert apply_figure_style(fig, None) == out
    assert apply_figure_style(fig, "unknown") == out


def test_default_hides_the_legend_on_request():
    out = apply_figure_style(_bar_stack(["g1", "g2"]), "default", hide_legend=True)
    assert out["layout"]["showlegend"] is False


def test_minimal_is_the_overview_look_plus_the_showcase_overlay():
    fig = _bar_stack([f"g{i}" for i in range(10)], values=list(range(10, 0, -1)))
    out = apply_figure_style(fig, "minimal")
    grey = palettes.semantic("other", "light")
    assert sum(t["marker"]["color"] == grey for t in out["data"]) == 2
    assert out["layout"]["plot_bgcolor"] == "rgba(0,0,0,0)"  # the minimal overlay
    one_hue = apply_figure_style(_bar_by_x(), "minimal")
    assert {t["marker"]["color"] for t in one_hue["data"]} == {PALETTE[0]}
    assert one_hue["layout"]["xaxis"]["categoryorder"] == "total descending"


@pytest.mark.parametrize("style", ["default", "minimal", "classic"])
def test_no_style_mutates_its_input(style):
    fig = _bar_by_x()
    before = copy.deepcopy(fig)
    apply_figure_style(fig, style, header_title=True)
    assert fig == before


def test_single_hue_keeps_dashboard_category_colours():
    from depictio.api.v1.services.figure.overview_style import apply_overview

    fig = {
        "data": [
            {"type": "box", "name": n, "x": [n, n], "y": [1, 2], "marker": {"color": c}}
            for n, c in (("Soil", "#111111"), ("Sediment", "#222222"))
        ],
        "layout": {},
    }
    out = apply_overview(
        fig, category_colors={"habitat": {"Soil": "#111111", "Sediment": "#222222"}}
    )
    assert [t["marker"]["color"] for t in out["data"]] == ["#111111", "#222222"]


def test_full_stack_is_not_resorted():
    from depictio.api.v1.services.figure.overview_style import apply_overview

    fig = {
        "data": [
            {"type": "bar", "orientation": "h", "name": "a", "y": ["Soil", "Water"], "x": [60, 30]},
            {"type": "bar", "orientation": "h", "name": "b", "y": ["Soil", "Water"], "x": [40, 70]},
        ],
        "layout": {"barmode": "stack"},
    }
    out = apply_overview(fig)
    assert "categoryorder" not in (out["layout"].get("yaxis") or {})
