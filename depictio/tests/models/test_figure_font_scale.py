"""Per-figure font-size multiplier (`font_scale`): YAML round-trip.

Stored on the figure component's metadata; the React FigureRenderer multiplies
it into the Plotly layout font (axis labels, ticks, legend). Round-trip
invariants:
- absent by default (pre-feature components and seeds load unchanged);
- survives lite YAML ↔ full conversions;
- values equal to 1 are not exported (they're the default rendering).
"""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite

FIGURE = {
    "tag": "scatter-1",
    "component_type": "figure",
    "workflow_tag": "python/iris_workflow",
    "data_collection_tag": "iris_table",
    "visu_type": "scatter",
}


def _lite_with_figure(**extra) -> DashboardDataLite:
    return DashboardDataLite(title="Test", components=[{**FIGURE, **extra}])


class TestFontScaleRoundTrip:
    def test_default_absent(self):
        dash = _lite_with_figure()
        assert "font_scale" not in dash.to_yaml()
        assert dash.to_full()["stored_metadata"][0].get("font_scale") is None

    def test_to_full_carries_font_scale(self):
        dash = _lite_with_figure(font_scale=1.5)
        assert dash.to_full()["stored_metadata"][0]["font_scale"] == 1.5

    def test_yaml_round_trip(self):
        dash = _lite_with_figure(font_scale=1.3)
        yaml_str = dash.to_yaml()
        assert "font_scale" in yaml_str
        restored = DashboardDataLite.from_yaml(yaml_str)
        comp = restored.components[0]
        font_scale = comp["font_scale"] if isinstance(comp, dict) else comp.font_scale
        assert font_scale == 1.3

    def test_from_full_exports_only_non_default(self):
        full_scaled = _lite_with_figure(font_scale=1.5).to_full()
        lite = DashboardDataLite.from_full(
            {**full_scaled, "title": "Test", "stored_layout_data": []}
        )
        comp = lite.components[0]
        assert (comp["font_scale"] if isinstance(comp, dict) else comp.font_scale) == 1.5

        full_default = _lite_with_figure().to_full()
        lite_default = DashboardDataLite.from_full(
            {**full_default, "title": "Test", "stored_layout_data": []}
        )
        comp_default = lite_default.components[0]
        comp_dict = comp_default if isinstance(comp_default, dict) else comp_default.model_dump()
        assert "font_scale" not in comp_dict or comp_dict["font_scale"] is None

    def test_rejects_non_positive(self):
        with pytest.raises(ValidationError):
            _lite_with_figure(font_scale=0)
