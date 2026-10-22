"""``open_with_defaults``: a tab that starts from its declared filter defaults on every visit."""

from depictio.models.models.dashboards import DashboardDataLite


def test_defaults_off_and_omitted_from_yaml():
    dash = DashboardDataLite(title="Test", components=[])
    assert dash.open_with_defaults is False
    assert "open_with_defaults" not in dash.to_yaml()


def test_survives_yaml_and_full_round_trips():
    dash = DashboardDataLite(title="Test", components=[], open_with_defaults=True)
    assert "open_with_defaults: true" in dash.to_yaml()
    assert DashboardDataLite.from_yaml(dash.to_yaml()).open_with_defaults is True
    full = dash.to_full()
    assert full["open_with_defaults"] is True
    assert DashboardDataLite.from_full(full).open_with_defaults is True


def test_a_document_saved_before_the_field_existed_reads_as_off():
    full = DashboardDataLite(title="Test", components=[]).to_full()
    full.pop("open_with_defaults")
    assert DashboardDataLite.from_full(full).open_with_defaults is False
