"""Card styles: a card's own `variant`."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite

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


def _dash(*components):
    return DashboardDataLite(title="Landing", components=list(components))


@pytest.mark.parametrize("variant", ["default", "headline", "compact", "minimal"])
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
