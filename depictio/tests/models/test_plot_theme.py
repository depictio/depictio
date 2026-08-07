"""Dashboard-level plot theme (#397): model shape, YAML round-trip, precedence.

`plot_theme` is an optional `DashboardThemeSpec` on both DashboardDataLite and
DashboardData. The key invariants:
- absent everywhere by default, so pre-feature dashboards (and the shipped
  `.db_seeds/*.json`) load unchanged;
- survives the lite YAML round-trip and the lite ↔ full conversions;
- the template sentinel rule (`mantine_light`/`mantine_dark` = "follow the UI
  theme") drives which template wins in the figure builder.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboards import DashboardDataLite, DashboardThemeSpec

SEED_DIR = Path(__file__).parents[2] / "projects" / "init" / "iris" / ".db_seeds"


class TestDashboardThemeSpec:
    def test_defaults_are_empty(self):
        spec = DashboardThemeSpec()
        assert spec.template is None
        assert spec.colorway is None
        assert spec.is_empty

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            DashboardThemeSpec(template="seaborn", font="Comic Sans")

    def test_populated(self):
        spec = DashboardThemeSpec(template="seaborn", colorway=["#111111", "#222222"])
        assert not spec.is_empty


class TestLiteRoundTrip:
    def test_default_is_none_and_absent_from_yaml(self):
        dash = DashboardDataLite(title="Test", components=[])
        assert dash.plot_theme is None
        assert "plot_theme" not in dash.to_yaml()

    def test_yaml_round_trip(self):
        dash = DashboardDataLite(
            title="Test",
            components=[],
            plot_theme=DashboardThemeSpec(template="seaborn", colorway=["#0ca678", "#f76707"]),
        )
        yaml_str = dash.to_yaml()
        assert "plot_theme" in yaml_str

        restored = DashboardDataLite.from_yaml(yaml_str)
        assert restored.plot_theme is not None
        assert restored.plot_theme.template == "seaborn"
        assert restored.plot_theme.colorway == ["#0ca678", "#f76707"]

    def test_to_full_carries_plot_theme(self):
        dash = DashboardDataLite(
            title="Test",
            components=[],
            plot_theme=DashboardThemeSpec(template="ggplot2"),
        )
        full = dash.to_full()
        assert full["plot_theme"] == {"template": "ggplot2", "colorway": None}

    def test_to_full_without_plot_theme(self):
        full = DashboardDataLite(title="Test", components=[]).to_full()
        assert full["plot_theme"] is None

    def test_from_full_restores_plot_theme(self):
        dash = DashboardDataLite(
            title="Test",
            components=[],
            plot_theme=DashboardThemeSpec(colorway=["#111111"]),
        )
        full = dash.to_full()
        restored = DashboardDataLite.from_full(full)
        assert restored.plot_theme is not None
        assert restored.plot_theme.colorway == ["#111111"]


class TestSeedCompatibility:
    """Shipped seeds predate plot_theme — they must load with it defaulting off."""

    @pytest.mark.skipif(not SEED_DIR.exists(), reason="iris seeds not present")
    def test_existing_seed_parses_with_plot_theme_none(self):
        seed_files = sorted(SEED_DIR.glob("dashboard*.json"))
        assert seed_files, f"no dashboard seeds in {SEED_DIR}"
        seed = json.loads(seed_files[0].read_text())
        # Seeds are full-format dashboard dicts (DashboardData.mongo() shape);
        # from_full is the lite view over the same shape and must tolerate the
        # missing field.
        lite = DashboardDataLite.from_full(seed)
        assert lite.plot_theme is None


class TestTemplatePrecedence:
    """The sentinel rule shared by the render endpoint, px path and agg path."""

    def test_resolve_template_override(self):
        from depictio.api.v1.services.figure.figure_builder import resolve_template_override

        assert resolve_template_override(None) is None
        assert resolve_template_override("") is None
        # Stamped legacy defaults mean "follow the UI theme".
        assert resolve_template_override("mantine_light") is None
        assert resolve_template_override("mantine_dark") is None
        # An explicit pick wins.
        assert resolve_template_override("seaborn") == "seaborn"

    def test_merge_dashboard_plot_theme(self):
        from depictio.api.v1.services.figure.figure_builder import merge_dashboard_plot_theme

        # No dashboard theme → kwargs untouched (same object, no copy).
        kwargs = {"x": "a", "template": "mantine_light"}
        assert merge_dashboard_plot_theme(None, kwargs) is kwargs

        # Dashboard template fills the sentinel slot…
        merged = merge_dashboard_plot_theme({"template": "seaborn"}, kwargs)
        assert merged["template"] == "seaborn"

        # …but never overrides an explicit component pick.
        merged = merge_dashboard_plot_theme({"template": "seaborn"}, {"template": "plotly_dark"})
        assert merged["template"] == "plotly_dark"

        # Colorway only fills when the component sets no colors of its own.
        merged = merge_dashboard_plot_theme({"colorway": ["#111111"]}, {})
        assert merged["color_discrete_sequence"] == ["#111111"]
        merged = merge_dashboard_plot_theme(
            {"colorway": ["#111111"]}, {"color_discrete_sequence": ["#eeeeee"]}
        )
        assert merged["color_discrete_sequence"] == ["#eeeeee"]
        merged = merge_dashboard_plot_theme(
            {"colorway": ["#111111"]}, {"color_discrete_map": {"A": "#eeeeee"}}
        )
        assert "color_discrete_sequence" not in merged
