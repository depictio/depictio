"""Text-tile surfaces and card badges: what a landing tab is built from."""

from depictio.models.models.dashboards import DashboardDataLite


def _dash(*components):
    return DashboardDataLite(title="Landing", components=list(components))


FINDING = {
    "component_type": "text",
    "tag": "finding-1",
    "title": "Locality drives the community",
    "order": 4,
    "body": "# 41%\nof between-sample variation",
    "surface": "card",
    "accent": "tab:Ordination & Clustering",
    "layout": {"x": 0, "y": 0, "w": 3, "h": 3},
}

KPI = {
    "component_type": "card",
    "tag": "kpi-samples",
    "workflow_tag": "nf-core/ampliseq",
    "data_collection_tag": "metadata",
    "aggregation": "nunique",
    "column_name": "ID",
    "column_type": "object",
    "title": "Samples",
    "display": {"icon_name": "mdi:water", "icon_style": "badge", "caption": "AML 52 · TARA 33"},
    "layout": {"x": 0, "y": 0, "w": 2, "h": 2},
}


def test_text_surface_defaults_to_bare_prose():
    tile = _dash({"component_type": "text", "tag": "t", "body": "x"}).components[0]
    assert tile.surface == "none"
    assert tile.accent is None


def test_text_surface_and_accent_reach_the_stored_component():
    full = _dash(FINDING).to_full()["stored_metadata"][0]
    assert full["surface"] == "card"
    assert full["accent"] == "tab:Ordination & Clustering"


def test_text_tile_survives_export():
    lite = DashboardDataLite.from_full(_dash(FINDING).to_full())
    tile = lite.components[0]
    assert tile.surface == "card"
    assert tile.accent == "tab:Ordination & Clustering"
    assert tile.body.startswith("# 41%")
    assert tile.order == 4


def test_card_badge_and_caption_round_trip():
    full = _dash(KPI).to_full()["stored_metadata"][0]
    assert full["icon_style"] == "badge"
    assert full["caption"] == "AML 52 · TARA 33"
    card = DashboardDataLite.from_full(_dash(KPI).to_full()).components[0]
    assert card.display["icon_style"] == "badge"
    assert card.display["caption"] == "AML 52 · TARA 33"


def test_card_headline_variant_round_trip():
    kpi = {**KPI, "display": {**KPI["display"], "variant": "headline"}}
    assert _dash(kpi).to_full()["stored_metadata"][0]["variant"] == "headline"
    card = DashboardDataLite.from_full(_dash(kpi).to_full()).components[0]
    assert card.display["variant"] == "headline"
