"""The UpSet figure of a notebook export or report fallback, in the dashboard's colours.

The dashboard recolours the server's plain figure in the browser
(``upsetFigure.ts``); ``upset_colors.py`` is the same pass for a figure that
never reaches that renderer. Both read one fixture, written from the TS side
(``upsetFigure.fixture.test.ts`` asserts it there).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from depictio.api.v1.services.export.compute import _upset_payload
from depictio.api.v1.services.export.upset_colors import (
    colour_upset_figure,
    colour_upset_sets,
    resolve_upset_set_colors,
    upset_set_names,
    with_upset_set_label_dots,
)

FIXTURE = (
    Path(__file__).resolve().parents[6]
    / "packages/depictio-react-core/src/components/advanced_viz/fixtures/upset-colouring.json"
)
_FIXTURE = json.loads(FIXTURE.read_text())
_LAYOUT = _FIXTURE["figure"]["layout"]
_DATA = _FIXTURE["figure"]["data"]


def _normalised(obj):
    """Through JSON, as the TS side's expectation was written."""
    return json.loads(json.dumps(obj))


@pytest.mark.parametrize("case", _FIXTURE["cases"], ids=lambda c: c["name"])
def test_the_recolouring_matches_the_dashboards(case):
    names = [name for _, name in sorted(upset_set_names(_LAYOUT).items())]
    colors = resolve_upset_set_colors(
        case["category_colors"], names, column=case["column"], overrides=case["overrides"]
    )
    if case["expected"] is None:
        assert colors is None
        return
    assert colors == case["expected"]["colors"]
    assert _normalised(colour_upset_sets(_DATA, _LAYOUT, colors)) == case["expected"]["data"]
    assert _normalised(with_upset_set_label_dots(_LAYOUT, colors)) == case["expected"]["layout"]


def test_the_figure_is_not_mutated_and_unpinned_sets_keep_the_plain_look():
    before = json.dumps(_FIXTURE["figure"], sort_keys=True)
    figure = {"data": _DATA, "layout": _LAYOUT}
    assert colour_upset_figure(figure, {"Phylum": {"Bacteria": "#fff"}}, {}) is figure
    out = colour_upset_figure(
        figure, {"habitat": {"Soil": "#eda100"}}, {"set_category_column": "habitat"}
    )
    assert out is not figure
    assert json.dumps(_FIXTURE["figure"], sort_keys=True) == before


def test_the_sets_take_the_dashboards_colours_everywhere_they_are_drawn():
    """The shape of the bug: grey bars and black dots, whatever the dashboard pinned."""
    case = _FIXTURE["cases"][0]
    out = colour_upset_figure(
        {"data": _DATA, "layout": _LAYOUT},
        case["category_colors"],
        {"set_category_column": "habitat"},
    )
    pinned = set(case["category_colors"]["habitat"].values())
    sizes = next(t for t in out["data"] if t.get("orientation") == "h")
    assert set(sizes["marker"]["color"]) == pinned
    filled = next(t for t in out["data"] if t.get("type") == "scatter" and t.get("hovertext"))
    assert set(filled["marker"]["color"]) <= pinned
    bars = next(t for t in out["data"] if t.get("name") == "Intersection Size")
    assert pinned <= set(bars["marker"]["color"])


def test_the_annotation_tracks_come_with_the_config_default_columns():
    config = {"default_annotation_cols": ["Phylum"], "show_set_sizes": True}
    base = {"wf_id": "w", "dc_id": "d", "filter_metadata": []}
    payload = _upset_payload(config, base)
    assert payload["annotation_cols"] == ["Phylum"]
    assert payload["show_set_sizes"] is True
    # The renderer's master switch drops the tracks and the size bars together.
    off = _upset_payload({**config, "show_annotations": False}, base)
    assert off["annotation_cols"] is None
    assert off["show_set_sizes"] is False
    assert _upset_payload({}, base)["annotation_cols"] is None


def test_a_long_static_legend_goes_under_the_figure():
    from depictio.api.v1.services.export.plotly_export import (
        UPSET_STATIC_LEGEND_MAX,
        _static_upset_legend,
    )

    legend = {"x": 0, "y": 1, "font": {"size": 10}}
    many = {
        "data": [
            {
                "name": f"Phylum: {i}",
                "legendgroup": "Phylum",
                "legendgrouptitle": {"text": "Phylum"},
            }
            for i in range(UPSET_STATIC_LEGEND_MAX + 1)
        ],
        "layout": {"legend": legend},
    }
    static = _static_upset_legend(many)
    # One group would stack in one column even laid out in a row.
    assert all("legendgroup" not in t for t in static["data"])
    out = static["layout"]["legend"]
    assert out["title"]["text"] == "Phylum"
    assert static["data"][0]["name"] == "0"
    assert out["orientation"] == "h" and out["yanchor"] == "top" and out["y"] < 0
    assert out["font"]["size"] == 9
    few = {"data": [{"name": "Soil"}], "layout": {"legend": legend}}
    assert _static_upset_legend(few) == few
