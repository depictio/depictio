"""``content_width_default``: the page width a tab opens at on a first visit."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite


def test_default_is_full_and_absent_from_yaml():
    dash = DashboardDataLite(title="Test", components=[])
    assert dash.content_width_default == "full"
    assert "content_width_default" not in dash.to_yaml()


def test_comfortable_survives_yaml_and_full_round_trips():
    dash = DashboardDataLite(title="Test", components=[], content_width_default="comfortable")
    assert "content_width_default: comfortable" in dash.to_yaml()
    assert DashboardDataLite.from_yaml(dash.to_yaml()).content_width_default == "comfortable"
    full = dash.to_full()
    assert full["content_width_default"] == "comfortable"
    assert DashboardDataLite.from_full(full).content_width_default == "comfortable"


def test_unknown_value_rejected():
    with pytest.raises(ValidationError):
        DashboardDataLite(title="Test", components=[], content_width_default="narrow")


def test_compact_is_accepted():
    dash = DashboardDataLite(title="Test", components=[], content_width_default="compact")
    assert DashboardDataLite.from_yaml(dash.to_yaml()).content_width_default == "compact"
