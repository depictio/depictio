"""``filter_panel_default``: the filter panel's state on a first visit."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite


def test_default_is_open_and_absent_from_yaml():
    dash = DashboardDataLite(title="Test", components=[])
    assert dash.filter_panel_default == "open"
    assert "filter_panel_default" not in dash.to_yaml()


def test_collapsed_survives_yaml_and_full_round_trips():
    dash = DashboardDataLite(title="Test", components=[], filter_panel_default="collapsed")
    assert "filter_panel_default: collapsed" in dash.to_yaml()
    assert DashboardDataLite.from_yaml(dash.to_yaml()).filter_panel_default == "collapsed"
    full = dash.to_full()
    assert full["filter_panel_default"] == "collapsed"
    assert DashboardDataLite.from_full(full).filter_panel_default == "collapsed"


def test_pre_feature_document_reads_as_open():
    full = DashboardDataLite(title="Test", components=[]).to_full()
    full.pop("filter_panel_default")
    assert DashboardDataLite.from_full(full).filter_panel_default == "open"


def test_unknown_value_rejected():
    with pytest.raises(ValidationError):
        DashboardDataLite(title="Test", components=[], filter_panel_default="hidden")
