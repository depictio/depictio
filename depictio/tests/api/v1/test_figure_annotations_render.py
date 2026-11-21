"""The automatic marks a figure draws on itself (``FigureAnnotations``).

Figures are built with plotly express, styled as a tile is
(``apply_figure_style``), then marked with ``apply_annotations`` -- the exact
order of the two hook points (API worker, catalog preview).
"""

import copy
import json

import pandas as pd
import plotly.express as px

from depictio.api.v1.services.figure.annotations import apply_annotations
from depictio.api.v1.services.figure.style_presets import apply_figure_style
from depictio.models import palettes
from depictio.models.palettes.cvd import contrast_ratio


def _styled(fig, style="default"):
    figure = json.loads(fig.to_json())
    return apply_figure_style(figure, style)


# ---------------------------------------------------------------------------
# bar labels


def test_automatic_bar_labels_on_few_unstacked_bars():
    fig = px.bar(
        pd.DataFrame({"cat": list("abc"), "v": [3, 2, 1]}), x="cat", y="v", barmode="group"
    )
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    trace = out["data"][0]
    assert trace["texttemplate"] == "%{y:,.0f}"
    assert trace["textposition"] == "outside"
    assert trace["cliponaxis"] is False
    assert trace["textfont"]["color"] == palettes.chrome("light")["text"]


def test_automatic_bar_labels_on_coloured_bars():
    # One trace per group (px color=g), grouped: 3 bars in total.
    df = pd.DataFrame({"cat": list("abc"), "g": ["x", "y", "z"], "v": [3, 2, 1]})
    fig = px.bar(df, x="cat", y="v", color="g", barmode="group")
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    assert all(t["texttemplate"] == "%{y:,.0f}" for t in out["data"])


def test_automatic_bar_labels_on_a_default_px_bar():
    # px sets barmode="relative" on every bar chart; one series is not a stack.
    fig = px.bar(pd.DataFrame({"cat": list("abc"), "v": [0.5, 1.25, 2.0]}), x="cat", y="v")
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    assert out["data"][0]["texttemplate"] == "%{y:,.2~f}"


def test_no_automatic_bar_labels_on_thirteen_bars():
    fig = px.bar(
        pd.DataFrame({"cat": [f"c{i}" for i in range(13)], "v": list(range(13))}),
        x="cat",
        y="v",
        barmode="group",
    )
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    assert all("texttemplate" not in t for t in out["data"])


def test_no_automatic_bar_labels_on_a_stack():
    df = pd.DataFrame({"s": ["s1", "s1", "s2", "s2"], "g": ["x", "y", "x", "y"], "v": [1, 2, 3, 4]})
    fig = px.bar(df, x="s", y="v", color="g", barmode="stack")
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    assert all("texttemplate" not in t for t in out["data"])


def test_declared_percent_bar_labels_carry_the_share_in_customdata():
    fig = px.bar(pd.DataFrame({"cat": list("abc"), "v": [1, 1, 2]}), x="cat", y="v")
    out = apply_annotations(
        _styled(fig), {"bar_labels": "percent"}, figure_style="default", theme="light"
    )
    trace = out["data"][0]
    assert trace["texttemplate"] == "%{customdata:.0%}"
    assert trace["customdata"] == [0.25, 0.25, 0.5]


# ---------------------------------------------------------------------------
# an empty block, and classic


def _fold_figure():
    """A real grouping of 10 series: the overview look folds the smallest 2."""
    df = pd.DataFrame(
        {
            "s": ["s1", "s2"] * 10,
            "g": [f"g{i}" for i in range(10) for _ in range(2)],
            "v": [v for i in range(10, 0, -1) for v in [i, i]],
        }
    )
    return px.bar(df, x="s", y="v", color="g")


def test_an_empty_block_draws_nothing_not_even_the_fold_note():
    styled = _styled(_fold_figure())
    assert styled["layout"]["meta"]["depictio_folded"] == 2  # the fold did happen
    out = apply_annotations(styled, {}, figure_style="default", theme="light")
    assert all("texttemplate" not in t for t in out["data"])
    assert out["layout"].get("annotations") == styled["layout"].get("annotations")
    assert out == styled


def test_classic_draws_nothing():
    fig = px.bar(pd.DataFrame({"cat": list("abc"), "v": [3, 2, 1]}), x="cat", y="v")
    figure = json.loads(fig.to_json())
    out = apply_annotations(figure, None, figure_style="classic", theme="light")
    assert out == figure
    assert "texttemplate" not in out["data"][0]


# ---------------------------------------------------------------------------
# group n


def test_group_n_appends_the_count_to_each_category_tick():
    df = pd.DataFrame({"cat": ["a"] * 4 + ["b"] * 2, "v": [1, 2, 3, 4, 5, 6]})
    fig = px.box(df, x="cat", y="v")
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    axis = out["layout"]["xaxis"]
    assert axis["tickvals"] == ["a", "b"]
    assert axis["ticktext"] == ["a (n=4)", "b (n=2)"]


def test_group_n_in_legend_names_when_traces_share_categories():
    df = pd.DataFrame({"cat": ["a", "a", "b", "b"], "g": ["x", "y", "x", "y"], "v": [1, 2, 3, 4]})
    fig = px.box(df, x="cat", y="v", color="g")
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    assert [t["name"] for t in out["data"]] == ["x (n=2)", "y (n=2)"]
    assert "ticktext" not in out["layout"]["xaxis"]


# ---------------------------------------------------------------------------
# cell values


def test_cell_values_print_the_cell_and_pick_the_readable_ink():
    fig = px.imshow([[1.0, 2, 3], [4, 5, 6]])
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    trace = out["data"][0]
    assert trace["texttemplate"] == "%{z:.2~f}"
    stops = [stop[1] for stop in out["layout"]["coloraxis"]["colorscale"]]
    candidates = (palettes.chrome("light")["text"], "#ffffff")
    expected = max(candidates, key=lambda c: min(contrast_ratio(c, s) for s in stops))
    assert trace["textfont"]["color"] == expected
    assert trace["textfont"]["color"] in candidates


def test_declared_cell_values_ignore_the_cell_budget():
    z = [[float(i * j) for j in range(25)] for i in range(25)]  # 625 cells
    fig = px.imshow(z)
    out = apply_annotations(
        _styled(fig), {"cell_values": True}, figure_style="default", theme="light"
    )
    assert out["data"][0]["texttemplate"] == "%{z:.2~f}"


def test_automatic_cell_values_stay_off_a_big_heatmap():
    z = [[float(i * j) for j in range(25)] for i in range(25)]  # 625 cells
    fig = px.imshow(z)
    out = apply_annotations(_styled(fig), None, figure_style="default", theme="light")
    assert "texttemplate" not in out["data"][0]


# ---------------------------------------------------------------------------
# hidden note


def test_hidden_note_after_the_style_folds_the_tail():
    out = apply_annotations(_styled(_fold_figure()), None, figure_style="default", theme="light")
    notes = [a for a in out["layout"]["annotations"] if "not shown" in str(a.get("text"))]
    assert len(notes) == 1
    note = notes[0]
    assert note["text"] == "2 more not shown"
    assert note["xanchor"] == "right" and note["yanchor"] == "bottom"
    assert note["showarrow"] is False
    assert note["font"]["size"] == 11
    assert note["font"]["color"] == palettes.annotation_ink("light")


def test_hidden_note_follows_the_dark_ink():
    out = apply_annotations(_styled(_fold_figure()), None, figure_style="default", theme="dark")
    note = next(a for a in out["layout"]["annotations"] if "not shown" in str(a.get("text")))
    assert note["font"]["color"] == palettes.annotation_ink("dark")


# ---------------------------------------------------------------------------
# a mark declares itself only once


def test_a_declared_block_draws_only_the_marks_it_turns_on():
    fig = px.bar(
        pd.DataFrame({"cat": list("abc"), "v": [3, 2, 1]}), x="cat", y="v", barmode="group"
    )
    out = apply_annotations(_styled(fig), {"group_n": True}, figure_style="default", theme="light")
    assert all("texttemplate" not in t for t in out["data"])  # no bar labels
    assert "annotations" not in out["layout"]  # no hidden note


def test_apply_annotations_never_mutates_its_input():
    fig = px.bar(pd.DataFrame({"cat": list("abc"), "v": [3, 2, 1]}), x="cat", y="v")
    figure = _styled(fig)
    before = copy.deepcopy(figure)
    out = apply_annotations(figure, None, figure_style="default", theme="light")
    assert figure == before
    assert out is not figure
