"""Figure styles: a figure's own `figure_style` and card header, and a grid
section's `figure_style`, through YAML import and export."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite, FilterSectionSpec

PCOA = {
    "component_type": "figure",
    "tag": "ov-pcoa",
    "workflow_tag": "nf-core/ampliseq",
    "data_collection_tag": "embedding_pcoa",
    "visu_type": "scatter",
    "dict_kwargs": {"x": "dim_1", "y": "dim_2", "color": "locality"},
    "title": "PCoA",
    "section": "At a glance",
    "layout": {"x": 0, "y": 0, "w": 4, "h": 5},
}

HEADER = {
    "figure_style": "minimal",
    "subtitle": "Bray-Curtis",
    "icon_name": "mdi:chart-scatter-plot",
    "icon_color": "pink",
    "hide_legend": True,
}


def _dash(*components, grid_sections=None):
    return DashboardDataLite(
        title="Landing", components=list(components), grid_sections=grid_sections or []
    )


def test_figure_style_and_header_round_trip():
    full = _dash({**PCOA, **HEADER}).to_full()["stored_metadata"][0]
    assert {k: full[k] for k in HEADER} == HEADER
    figure = DashboardDataLite.from_full(_dash({**PCOA, **HEADER}).to_full()).components[0]
    assert {k: getattr(figure, k) for k in HEADER} == HEADER
    yaml_text = _dash({**PCOA, **HEADER}).to_yaml()
    for key in HEADER:
        assert f"{key}:" in yaml_text


def test_unset_style_and_header_are_left_out():
    full = _dash(PCOA).to_full()["stored_metadata"][0]
    for key in ("figure_style", "subtitle", "icon_name", "icon_color"):
        assert not full.get(key)
    yaml_text = _dash(PCOA).to_yaml()
    for key in HEADER:
        assert f"{key}:" not in yaml_text


def test_figure_style_rejects_an_unknown_style():
    with pytest.raises(ValidationError):
        _dash({**PCOA, "figure_style": "fancy"})


def test_section_figure_style():
    assert FilterSectionSpec(name="x").figure_style is None
    assert FilterSectionSpec(name="x", figure_style="minimal").figure_style == "minimal"
    with pytest.raises(ValidationError):
        FilterSectionSpec(name="x", figure_style="fancy")


def test_section_figure_style_round_trips():
    sections = [{"name": "At a glance", "figure_style": "minimal", "appearance": "plain"}]
    full = _dash(PCOA, grid_sections=sections).to_full()
    assert full["grid_sections"][0]["figure_style"] == "minimal"
    back = DashboardDataLite.from_full(full)
    assert back.grid_sections[0].figure_style == "minimal"
