"""A highlight: another tab's figure shown again, through YAML import and export.

The tile binds to no data of its own, so it must come through both ways
without a workflow or a collection, and with where its figure lives.
"""

import pytest
from pydantic import ValidationError

from depictio.models.components.lite import HighlightLiteComponent
from depictio.models.components.union import ComponentMetadata
from depictio.models.models.dashboards import DashboardDataLite

HIGHLIGHT = {
    "component_type": "highlight",
    "title": "Faith PD per locality",
    "subtitle": "at the deepest rarefaction depth",
    "source_tab": "Alpha Diversity",
    "source_component": "trec-fig-alpha-plateau",
    "icon_name": "mdi:chart-scatter-plot",
    "icon_color": "teal",
    "hide_legend": True,
    "section": "At a glance",
    "layout": {"x": 0, "y": 0, "w": 6, "h": 7},
}


def _dash(*components):
    return DashboardDataLite(title="Landing", components=list(components))


def test_a_highlight_validates_as_its_own_type():
    component = _dash(HIGHLIGHT).components[0]
    assert isinstance(component, HighlightLiteComponent)
    assert component.source_tab == "Alpha Diversity"
    assert component.figure_style is None  # drawn minimal unless set


def test_round_trip_keeps_the_source_and_the_header():
    full = _dash(HIGHLIGHT).to_full()["stored_metadata"][0]
    assert full["component_type"] == "highlight"
    for key in ("source_tab", "source_component", "subtitle", "icon_name", "icon_color"):
        assert full[key] == HIGHLIGHT[key]
    assert full["hide_legend"] is True
    assert not full["workflow_tag"] and not full["data_collection_tag"]

    back = DashboardDataLite.from_full(_dash(HIGHLIGHT).to_full()).components[0]
    assert isinstance(back, HighlightLiteComponent)
    assert back.source_tab == "Alpha Diversity"
    assert back.source_component == "trec-fig-alpha-plateau"
    assert back.title == "Faith PD per locality"
    assert back.workflow_tag == "" and back.data_collection_tag == ""
    assert back.layout == HIGHLIGHT["layout"]


def test_export_writes_the_tab_name_rather_than_its_id():
    full = _dash({**HIGHLIGHT, "source_dashboard_id": "6ac39c1b0395845c79494761"}).to_full()
    assert full["stored_metadata"][0]["source_dashboard_id"] == "6ac39c1b0395845c79494761"
    yaml_text = DashboardDataLite.from_full(full).to_yaml()
    assert "source_tab: Alpha Diversity" in yaml_text
    assert "source_dashboard_id" not in yaml_text


def test_export_keeps_the_id_when_it_is_all_there_is():
    by_id = {k: v for k, v in HIGHLIGHT.items() if k != "source_tab"}
    by_id["source_dashboard_id"] = "6ac39c1b0395845c79494761"
    yaml_text = DashboardDataLite.from_full(_dash(by_id).to_full()).to_yaml()
    assert "source_dashboard_id: 6ac39c1b0395845c79494761" in yaml_text


def test_a_style_set_on_the_highlight_comes_through():
    full = _dash({**HIGHLIGHT, "figure_style": "default"}).to_full()["stored_metadata"][0]
    assert full["figure_style"] == "default"


@pytest.mark.parametrize(
    "broken",
    [
        {k: v for k, v in HIGHLIGHT.items() if k != "source_tab"},  # no tab
        {**HIGHLIGHT, "source_tab": "  "},
        {k: v for k, v in HIGHLIGHT.items() if k != "source_component"},  # no figure
        {**HIGHLIGHT, "source_component": ""},
        {**HIGHLIGHT, "figure_style": "fancy"},
    ],
)
def test_a_highlight_without_a_source_is_rejected(broken):
    with pytest.raises((ValidationError, ValueError)):
        _dash(broken)


def test_the_full_union_takes_a_highlight():
    from pydantic import TypeAdapter

    component = TypeAdapter(ComponentMetadata).validate_python(
        {k: v for k, v in HIGHLIGHT.items() if k != "layout"}
    )
    assert component.component_type == "highlight"
    assert component.index  # a runtime index is minted
