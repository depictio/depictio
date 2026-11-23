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


# ---------------------------------------------------------------------------
# a. colour against the reference


def _with_reference(fig, value, axis="y", label="median of this table"):
    fig["layout"]["meta"] = {"depictio_reference": [{"axis": axis, "value": value, "label": label}]}
    return fig


def _keys(fig):
    return [t for t in fig["data"] if str(t.get("legendgroup") or "").startswith("__reference__")]


def test_bars_that_repeat_their_axis_take_their_side_of_the_reference():
    fig = apply_overview(_with_reference(_bar_by_x(), 1.5))
    bars = [t for t in fig["data"] if t["type"] == "bar"]
    above, below = PALETTE[0], fig["layout"]["meta"]["depictio_reference_sides"]["below"]
    assert [t["marker"]["color"] for t in bars] == [below, above, above]
    assert all(t["showlegend"] is False for t in bars)
    assert [k["name"] for k in _keys(fig)] == [
        "Above the median of this table",
        "At or below the median of this table",
    ]
    assert above.lower() != below.lower()


def test_a_single_series_is_coloured_point_by_point():
    fig = _scatter(4)
    fig = apply_overview(_with_reference(fig, 1, label="y = 1"))
    colours = fig["data"][0]["marker"]["color"]
    assert colours[2] == colours[3] == PALETTE[0]
    assert colours[0] == colours[1] != PALETTE[0]
    assert [k["name"] for k in _keys(fig)] == ["Above y = 1", "At or below y = 1"]


def test_only_the_sides_present_get_a_legend_entry():
    fig = apply_overview(_with_reference(_bar_by_x(), 0))
    assert [k["name"] for k in _keys(fig)] == ["Above the median of this table"]


def test_a_reference_across_the_category_axis_colours_nothing():
    fig = apply_overview(_with_reference(_bar_by_x(), 1.5, axis="x"))
    # no colour against the line: one hue, as before
    assert {t["marker"]["color"] for t in fig["data"]} == {PALETTE[0]}
    assert not _keys(fig)


def test_a_real_grouping_keeps_its_colours_against_a_reference():
    fig = apply_overview(_with_reference(_bar_stack(["g1", "g2"]), 0.5))
    assert [t["marker"]["color"] for t in fig["data"]] == PALETTE[:2]
    assert not _keys(fig)


def test_pinned_categories_keep_their_colours_against_a_reference():
    fig = apply_overview(
        _with_reference(_bar_by_x(), 1.5),
        category_colors={"sample": {"a": "#111111", "b": "#222222", "c": "#333333"}},
    )
    assert not _keys(fig)


def test_the_legend_keys_change_no_axis_chrome():
    fig = apply_overview(_with_reference(_bar_by_x(), 1.5))
    assert fig["layout"]["xaxis"]["showgrid"] is False


def test_facets_keep_the_colour_that_ties_a_category_across_panels():
    fig = _bar_by_x()
    extra = copy.deepcopy(fig["data"])
    for trace in extra:
        trace.update(xaxis="x2", yaxis="y2", showlegend=False)
    fig["data"] += extra
    out = apply_overview(fig)
    assert [t["marker"]["color"] for t in out["data"][:3]] == PALETTE[:3]
    assert any(t.get("showlegend") is not False for t in out["data"])


def test_the_order_px_writes_for_colour_by_x_does_not_stop_the_sort():
    fig = _with_reference(_bar_by_x(("a", "b", "c")), 1.5)
    fig["layout"]["xaxis"].update(categoryorder="array", categoryarray=["a", "b", "c"])
    fig["layout"]["legend"] = {"title": {"text": "sample"}}
    out = apply_overview(fig)
    assert out["layout"]["xaxis"]["categoryorder"] == "total descending"
    assert out["layout"]["legend"]["title"]["text"] == ""


def test_an_order_the_author_gave_survives_colour_by_x():
    fig = _bar_by_x(("a", "b", "c"))
    fig["layout"]["xaxis"].update(categoryorder="array", categoryarray=["c", "a", "b"])
    out = apply_overview(fig)
    assert out["layout"]["xaxis"]["categoryarray"] == ["c", "a", "b"]


def test_a_legend_key_sits_on_a_category_so_the_bar_axis_stays_categorical():
    fig = {
        "data": [
            {
                "type": "bar",
                "name": "",
                "x": ["a", "b"],
                "y": [1, 3],
                "marker": {"color": PALETTE[0]},
            }
        ],
        "layout": {},
    }
    out = apply_overview(_with_reference(fig, 2))
    assert all(k["x"] == ["a"] and k["y"] == [None] for k in _keys(out))


# --- g. lines -------------------------------------------------------------


def _lines(n_series, n_points, **trace):
    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "name": f"s{i}",
                "x": list(range(n_points)),
                "y": [i + j for j in range(n_points)],
                **trace,
            }
            for i in range(n_series)
        ],
        "layout": {},
    }


def test_lines_are_drawn_bold_with_a_dot_on_each_point_of_a_short_series():
    out = apply_overview(_lines(2, 24))
    spec = palettes.style()["line_style"]
    for t in out["data"]:
        assert t["line"]["width"] == spec["width"]
        assert t["mode"] == "lines+markers"
        assert t["marker"]["size"] == palettes.line_marker_size(spec["width"])
    assert out["layout"]["hovermode"] == "x unified"


def test_a_long_series_stays_a_bare_curve():
    out = apply_overview(_lines(1, 500))
    assert out["data"][0]["mode"] == "lines"
    assert "hovermode" not in out["layout"]


def test_many_lines_thin_out_and_keep_their_own_hover():
    spec = palettes.style()["line_style"]
    out = apply_overview(_lines(spec["many_series"] + 1, 10))
    assert {t["line"]["width"] for t in out["data"]} == {spec["width_many"]}
    assert "hovermode" not in out["layout"]


def test_the_authors_line_width_mode_and_area_fill_survive():
    fig = _lines(2, 10, line={"width": 1})
    fig["data"][1]["fill"] = "tozeroy"
    fig["layout"]["hovermode"] = "closest"
    out = apply_overview(fig)
    assert [t["line"]["width"] for t in out["data"]] == [1, 1]
    assert out["data"][1]["mode"] == "lines"
    assert out["layout"]["hovermode"] == "closest"


def test_a_px_series_without_a_colour_column_is_not_a_missing_value():
    fig = {
        "data": [
            {
                "type": "scatter",
                "mode": "markers",
                "name": "",
                "showlegend": False,
                "x": [1, 2],
                "y": [3, 4],
            }
        ],
        "layout": {},
    }
    out = apply_overview(fig)
    assert out["data"][0].get("marker", {}).get("color") != palettes.semantic("na", "light")
