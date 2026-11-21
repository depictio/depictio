"""`annotations` (declared automatic figure marks) and `ReferenceLine.source`.

No block = every mark automatic by figure type; a given block draws only the
marks it turns on, so `{}` draws none. A reference line names where its value
comes from. Round-trip invariants:
- an unknown key in the block is refused (extra="forbid");
- both survive lite → full → lite;
- an explicitly empty block `{}` round-trips as itself (it turns every mark
  off), while unset stays absent.
"""

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.catalog import Render
from depictio.models.components.lite import FigureAnnotations, ReferenceLine
from depictio.models.models.dashboards import DashboardDataLite

FIGURE = {
    "tag": "bar-1",
    "component_type": "figure",
    "workflow_tag": "python/iris_workflow",
    "data_collection_tag": "iris_table",
    "visu_type": "bar",
}

ANNOTATIONS = {"bar_labels": "value", "group_n": True, "cell_values": None, "hidden_note": False}


def _lite_with_figure(**extra) -> DashboardDataLite:
    return DashboardDataLite(title="Test", components=[{**FIGURE, **extra}])


def _comp(dash: DashboardDataLite):
    comp = dash.components[0]
    return comp if isinstance(comp, dict) else comp.model_dump()


class TestFigureAnnotationsModel:
    def test_refuses_extra_key(self):
        with pytest.raises(ValidationError, match="bogus"):
            FigureAnnotations(bar_labels="value", bogus=True)

    def test_empty_block_sets_nothing_on(self):
        assert FigureAnnotations().model_dump() == FigureAnnotations.model_validate({}).model_dump()

    def test_reference_line_source(self):
        line = ReferenceLine(axis="y", value=0.05, source="MultiQC default")
        assert line.source == "MultiQC default"
        assert ReferenceLine(axis="y", value=1).source is None


class TestAnnotationsRoundTrip:
    def test_to_full_carries_annotations_and_source(self):
        dash = _lite_with_figure(
            annotations=ANNOTATIONS,
            reference_lines=[{"axis": "y", "value": 0.05, "source": "paper"}],
        )
        full = dash.to_full()["stored_metadata"][0]
        assert full["annotations"] == ANNOTATIONS
        assert full["reference_lines"][0]["source"] == "paper"

    def test_lite_full_lite_keeps_annotations_and_source(self):
        dash = _lite_with_figure(
            annotations=ANNOTATIONS,
            reference_lines=[{"axis": "y", "value": 0.05, "source": "paper"}],
        )
        full = dash.to_full()
        restored = DashboardDataLite.from_full({**full, "stored_layout_data": []})
        comp = _comp(restored)
        assert comp["annotations"] == ANNOTATIONS
        assert comp["reference_lines"][0]["source"] == "paper"

    def test_unset_stays_absent(self):
        full = _lite_with_figure().to_full()["stored_metadata"][0]
        assert full.get("annotations") is None
        restored = DashboardDataLite.from_full(
            {**_lite_with_figure().to_full(), "stored_layout_data": []}
        )
        assert _comp(restored).get("annotations") is None

    def test_explicit_empty_block_round_trips(self):
        dash = _lite_with_figure(annotations={})
        full = dash.to_full()["stored_metadata"][0]
        # The full dump fills the block's fields with their None defaults; the
        # block being *there* is what turns the automatic marks off.
        assert full["annotations"] == FigureAnnotations().model_dump()
        restored = DashboardDataLite.from_full({**dash.to_full(), "stored_layout_data": []})
        assert _comp(restored)["annotations"] == FigureAnnotations().model_dump()

    def test_annotations_only_on_ui_mode(self):
        with pytest.raises(ValidationError, match="UI-mode"):
            _lite_with_figure(mode="code", code_content="fig = px.scatter()", annotations={})


class TestCatalogRender:
    def test_figure_render_takes_annotations(self):
        render = Render(component="figure", visu_type="bar", annotations={"bar_labels": "percent"})
        assert render.annotations == FigureAnnotations(bar_labels="percent")

    def test_refuses_annotations_on_non_figure(self):
        with pytest.raises(ValidationError, match="figure fields"):
            Render(
                component="card",
                column="sepal.length",
                aggregation="average",
                annotations={"group_n": True},
            )

    def test_refuses_annotations_on_code_mode(self):
        with pytest.raises(ValidationError, match="UI-mode"):
            Render(component="figure", code="fig = px.scatter()", annotations={})
