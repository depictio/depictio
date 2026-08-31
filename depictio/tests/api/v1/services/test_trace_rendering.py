"""The export trace policy: an exported spec never carries a GPU trace."""

from __future__ import annotations

from depictio.api.v1.services.export.plotly_export import _prefer_svg_traces
from depictio.api.v1.services.trace_rendering import (
    EXPORT_SCATTER_TYPE,
    svg_equivalent,
)


class TestSvgEquivalent:
    def test_maps_the_gl_types_that_have_one(self):
        assert svg_equivalent("scattergl") == "scatter"
        assert svg_equivalent("scatterpolargl") == "scatterpolar"

    def test_returns_none_for_a_type_with_no_svg_form(self):
        # Downgrading these would mean dropping the trace, not redrawing it.
        assert svg_equivalent("scatter3d") is None
        assert svg_equivalent("surface") is None

    def test_returns_none_for_a_type_that_is_already_svg(self):
        assert svg_equivalent("scatter") is None
        assert svg_equivalent("bar") is None

    def test_the_exported_scatter_type_is_svg(self):
        assert EXPORT_SCATTER_TYPE == "scatter"


class TestPreferSvgTraces:
    def test_downgrades_a_gl_trace(self):
        spec = {"data": [{"type": "scattergl", "x": [1, 2], "y": [3, 4]}]}
        assert _prefer_svg_traces(spec)["data"][0]["type"] == "scatter"

    def test_downgrades_regardless_of_size(self):
        # There is no threshold: the host page's WebGL budget is not ours to
        # know, so a small gl trace is as unwelcome as a large one.
        spec = {"data": [{"type": "scattergl", "x": [1], "y": [1]}]}
        assert _prefer_svg_traces(spec)["data"][0]["type"] == "scatter"

    def test_leaves_a_trace_with_no_svg_form_alone(self):
        spec = {"data": [{"type": "scatter3d", "x": [1], "y": [1], "z": [1]}]}
        assert _prefer_svg_traces(spec)["data"][0]["type"] == "scatter3d"

    def test_leaves_other_traces_untouched(self):
        spec = {"data": [{"type": "bar", "x": ["a"], "y": [1]}, {"type": "heatmap"}]}
        types = [t["type"] for t in _prefer_svg_traces(spec)["data"]]
        assert types == ["bar", "heatmap"]

    def test_tolerates_a_trace_with_no_type(self):
        # Plotly defaults an untyped trace to scatter; it is already SVG.
        spec = {"data": [{"x": [1], "y": [1]}]}
        assert "type" not in _prefer_svg_traces(spec)["data"][0]

    def test_tolerates_an_empty_or_absent_data_list(self):
        assert _prefer_svg_traces({"data": []}) == {"data": []}
        assert _prefer_svg_traces({}) == {}
