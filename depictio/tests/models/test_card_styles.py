"""Card styles: a card's own `variant` and a grid section's `card_variant`."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite, FilterSectionSpec

STYLES = ["default", "headline", "compact", "minimal", "accent", "split"]

KPI = {
    "component_type": "card",
    "tag": "kpi-samples",
    "workflow_tag": "nf-core/ampliseq",
    "data_collection_tag": "metadata",
    "aggregation": "nunique",
    "column_name": "ID",
    "column_type": "object",
    "title": "Samples",
    "section": "Key figures",
    "layout": {"x": 0, "y": 0, "w": 2, "h": 2},
}


def _dash(*components, grid_sections=None):
    return DashboardDataLite(
        title="Landing",
        components=list(components),
        grid_sections=grid_sections or [],
    )


@pytest.mark.parametrize("variant", STYLES)
def test_card_variant_round_trips(variant):
    kpi = {**KPI, "display": {"variant": variant}}
    assert _dash(kpi).to_full()["stored_metadata"][0]["variant"] == variant
    card = DashboardDataLite.from_full(_dash(kpi).to_full()).components[0]
    assert card.display["variant"] == variant


def test_card_variant_rejects_an_unknown_style():
    with pytest.raises(ValidationError):
        _dash({**KPI, "variant": "fancy"})


def test_card_variant_unset_is_left_out():
    full = _dash(KPI).to_full()["stored_metadata"][0]
    assert not full.get("variant")
    card = DashboardDataLite.from_full(_dash(KPI).to_full()).components[0]
    assert "variant" not in (getattr(card, "display", None) or {})
    assert "variant" not in _dash(KPI).to_yaml()


def test_section_card_variant_defaults_to_unset():
    assert FilterSectionSpec(name="x").card_variant is None


@pytest.mark.parametrize("variant", STYLES)
def test_section_card_variant_accepts_each_style(variant):
    assert FilterSectionSpec(name="x", card_variant=variant).card_variant == variant


def test_section_card_variant_rejects_an_unknown_style():
    with pytest.raises(ValidationError):
        FilterSectionSpec(name="x", card_variant="fancy")


def test_section_card_variant_round_trips_through_yaml_and_full():
    dash = _dash(KPI, grid_sections=[{"name": "Key figures", "card_variant": "headline"}])
    assert dash.to_full()["grid_sections"][0]["card_variant"] == "headline"

    from_yaml = DashboardDataLite.from_yaml(dash.to_yaml())
    assert from_yaml.grid_sections[0].card_variant == "headline"

    from_full = DashboardDataLite.from_full(dash.to_full())
    assert from_full.grid_sections[0].card_variant == "headline"


def test_section_card_variant_unset_is_not_exported():
    dash = _dash(KPI, grid_sections=[{"name": "Key figures"}])
    assert "card_variant" not in dash.to_yaml()
    exported = DashboardDataLite.from_full(dash.to_full())
    assert "card_variant" not in exported.to_yaml()


def test_section_card_variant_does_not_write_into_its_cards():
    # The section's style is resolved when the grid draws, not copied onto the
    # cards: a card without its own variant keeps following the section.
    dash = _dash(KPI, grid_sections=[{"name": "Key figures", "card_variant": "compact"}])
    assert not dash.to_full()["stored_metadata"][0].get("variant")


def test_card_variant_enum_lists_every_style():
    from typing import get_args

    from depictio.models.components.types import CardVariant

    assert list(get_args(CardVariant)) == STYLES
