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


def test_card_link_round_trip():
    kpi = {**KPI, "display": {**KPI["display"], "link": "tab:Sampling Campaign"}}
    assert _dash(kpi).to_full()["stored_metadata"][0]["link"] == "tab:Sampling Campaign"
    card = DashboardDataLite.from_full(_dash(kpi).to_full()).components[0]
    assert card.display["link"] == "tab:Sampling Campaign"


def test_persistent_section_exclude_tabs():
    from depictio.models.models.dashboards import FilterSectionSpec

    spec = FilterSectionSpec(name="Samples", persistent=True, exclude_tabs=["Overview"])
    assert spec.exclude_tabs == ["Overview"]
    assert FilterSectionSpec(name="x").exclude_tabs is None


def test_section_appearance_defaults_to_box():
    from depictio.models.models.dashboards import FilterSectionSpec

    assert FilterSectionSpec(name="x").appearance == "box"
    assert FilterSectionSpec(name="x", appearance="plain").appearance == "plain"


def test_card_decimals_round_trip():
    kpi = {**KPI, "display": {**KPI["display"], "decimals": 2}}
    assert _dash(kpi).to_full()["stored_metadata"][0]["decimals"] == 2
    card = DashboardDataLite.from_full(_dash(kpi).to_full()).components[0]
    assert card.display["decimals"] == 2


def test_show_tab_header_defaults_on_and_survives_round_trip():
    dash = DashboardDataLite(title="T", components=[])
    assert dash.show_tab_header is True
    assert "show_tab_header" not in dash.to_yaml()
    off = DashboardDataLite(title="T", components=[], show_tab_header=False)
    assert "show_tab_header: false" in off.to_yaml()
    assert DashboardDataLite.from_yaml(off.to_yaml()).show_tab_header is False
    assert DashboardDataLite.from_full(off.to_full()).show_tab_header is False
