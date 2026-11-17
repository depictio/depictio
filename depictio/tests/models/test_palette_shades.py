"""Colour fields take a Mantine palette name with an optional shade (`orange.4`)."""

from __future__ import annotations

import pytest

from depictio.models.models.dashboards import DashboardDataLite


@pytest.mark.parametrize("color", ["orange", "orange.4", "orange-4", "#12b886", "brandPrimary"])
def test_icon_and_tab_colors_accept_palette_spellings(color):
    dash = DashboardDataLite(title="t", icon_color=color, tab_icon_color=color, components=[])
    assert dash.icon_color == color
    assert dash.tab_icon_color == color
    full = dash.to_full()
    assert full["tab_icon_color"] == color
    assert DashboardDataLite.from_full(full).tab_icon_color == color
