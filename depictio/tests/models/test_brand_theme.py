"""Dashboard-level brand theme (#397): model shape, YAML round-trip, precedence.

`brand_theme` is an optional `BrandTheme` on both DashboardDataLite and
DashboardData — the same model the instance branding uses, so a dashboard
states only what it wants to differ. The key invariants:
- absent everywhere by default, so pre-feature dashboards (and the shipped
  `.db_seeds/*.json`) load unchanged;
- survives the lite YAML round-trip and the lite ↔ full conversions;
- instance-local logo uploads never leak into an export;
- the template sentinel rule (`mantine_light`/`mantine_dark` = "follow the UI
  theme") drives which template wins in the figure builder.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from depictio.models.models.branding import BrandPlots, BrandSurfaces, BrandTheme
from depictio.models.models.dashboards import DashboardData, DashboardDataLite

SEED_DIR = Path(__file__).parents[2] / "projects" / "init" / "iris" / ".db_seeds"


class TestBrandThemeShape:
    def test_defaults_are_empty(self):
        theme = BrandTheme()
        assert theme.is_empty
        assert theme.primary is None
        assert theme.plots is None
        # Deliberately unset rather than defaulted: `None` has to keep meaning
        # "inherit", and a defaulted value would export as noise.
        assert theme.tint_mode is None
        assert theme.logo_mode is None

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            BrandTheme(primary="#0ca678", font="Comic Sans")

    def test_colors_accept_hex_or_palette_name(self):
        assert BrandTheme(primary="#0CA678").primary == "#0ca678"
        assert BrandTheme(primary="teal").primary == "teal"
        with pytest.raises(ValidationError):
            BrandTheme(primary="rgb(1,2,3)")

    def test_surfaces_reject_palette_names(self):
        # A surface becomes a raw CSS value, so a Mantine palette name there
        # would silently render as an invalid color.
        assert BrandSurfaces(nav_bg="#ffffff").nav_bg == "#ffffff"
        with pytest.raises(ValidationError):
            BrandSurfaces(nav_bg="teal")

    def test_logo_url_must_be_absolute(self):
        assert BrandTheme(logo_url="/static/x.png").logo_url == "/static/x.png"
        assert BrandTheme(logo_url="https://x/y.png").logo_url == "https://x/y.png"
        with pytest.raises(ValidationError):
            BrandTheme(logo_url="x.png")

    def test_radius_is_a_mantine_token(self):
        assert BrandTheme(default_radius="lg").default_radius == "lg"
        with pytest.raises(ValidationError):
            BrandTheme(default_radius="12px")


class TestLiteRoundTrip:
    def test_default_is_none_and_absent_from_yaml(self):
        dash = DashboardDataLite(title="Test", components=[])
        assert dash.brand_theme is None
        assert "brand_theme" not in dash.to_yaml()

    def test_yaml_round_trip(self):
        dash = DashboardDataLite(
            title="Test",
            components=[],
            brand_theme=BrandTheme(
                primary="#0ca678",
                plots=BrandPlots(template="seaborn", colorway=["#0ca678", "#f76707"]),
            ),
        )
        yaml_str = dash.to_yaml()
        assert "brand_theme" in yaml_str

        restored = DashboardDataLite.from_yaml(yaml_str)
        assert restored.brand_theme is not None
        assert restored.brand_theme.primary == "#0ca678"
        assert restored.brand_theme.plots is not None
        assert restored.brand_theme.plots.template == "seaborn"
        assert restored.brand_theme.plots.colorway == ["#0ca678", "#f76707"]

    def test_to_full_carries_brand_theme(self):
        dash = DashboardDataLite(
            title="Test",
            components=[],
            brand_theme=BrandTheme(plots=BrandPlots(template="ggplot2")),
        )
        assert dash.to_full()["brand_theme"] == {"plots": {"template": "ggplot2"}}

    def test_to_full_without_brand_theme(self):
        assert DashboardDataLite(title="Test", components=[]).to_full()["brand_theme"] is None

    def test_from_full_restores_brand_theme(self):
        dash = DashboardDataLite(
            title="Test",
            components=[],
            brand_theme=BrandTheme(plots=BrandPlots(colorway=["#111111"])),
        )
        restored = DashboardDataLite.from_full(dash.to_full())
        assert restored.brand_theme is not None
        assert restored.brand_theme.plots is not None
        assert restored.brand_theme.plots.colorway == ["#111111"]


class TestExportSanitising:
    """Instance-local uploads must not travel with a YAML/seed."""

    def test_uploaded_logo_is_stripped(self):
        theme = DashboardDataLite._exportable_brand_theme(
            {"logo_mode": "custom", "logo_url": "/static/dashboard_logos/abc.png"}
        )
        # Nothing but a dead URL was set, so the whole block drops out.
        assert theme is None

    def test_uploaded_logo_stripped_but_colors_kept(self):
        theme = DashboardDataLite._exportable_brand_theme(
            {
                "logo_mode": "custom",
                "logo_url": "/static/dashboard_logos/abc.png",
                "primary": "#00a550",
            }
        )
        assert theme is not None
        assert theme.logo_url is None
        # "custom" without a URL would render a broken image on the importing
        # instance, so the mode falls back to inheriting.
        assert theme.logo_mode is None
        assert theme.primary == "#00a550"

    def test_external_logo_survives(self):
        theme = DashboardDataLite._exportable_brand_theme({"logo_url": "https://x/y.png"})
        assert theme is not None
        assert theme.logo_url == "https://x/y.png"

    def test_export_yaml_has_no_uploaded_logo(self):
        lite = DashboardDataLite.from_full(
            {
                "title": "Test",
                "brand_theme": {
                    "logo_mode": "custom",
                    "logo_url": "/static/dashboard_logos/6824cb3b89d2b72169309737.png?v=1754550000",
                },
            }
        )
        assert "logo_url" not in lite.to_yaml()

    def test_external_logo_survives_the_yaml_round_trip(self):
        url = "https://example.org/assets/facility-logo.png"
        lite = DashboardDataLite(title="Test", components=[], brand_theme=BrandTheme(logo_url=url))
        assert DashboardDataLite.from_yaml(lite.to_yaml()).brand_theme.logo_url == url

    def test_pre_feature_document_has_no_theme(self):
        # Documents saved before the feature don't carry the key at all.
        assert DashboardDataLite.from_full({"title": "Legacy"}).brand_theme is None


class TestSeedCompatibility:
    """Shipped seeds predate brand_theme — they must load with it defaulting off."""

    @pytest.mark.skipif(not SEED_DIR.exists(), reason="iris seeds not present")
    def test_existing_seed_parses_with_brand_theme_none(self):
        seed_files = sorted(SEED_DIR.glob("dashboard*.json"))
        assert seed_files, f"no dashboard seeds in {SEED_DIR}"
        seed = json.loads(seed_files[0].read_text())
        # Seeds are full-format dashboard dicts (DashboardData.mongo() shape);
        # from_full is the lite view over the same shape and must tolerate the
        # missing field.
        lite = DashboardDataLite.from_full(seed)
        assert lite.brand_theme is None


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

    def test_merge_dashboard_brand_theme(self):
        from depictio.api.v1.services.figure.figure_builder import merge_dashboard_brand_theme

        # No dashboard theme → kwargs untouched (same object, no copy).
        kwargs = {"x": "a", "template": "mantine_light"}
        assert merge_dashboard_brand_theme(None, kwargs) is kwargs

        # Dashboard template fills the sentinel slot…
        merged = merge_dashboard_brand_theme({"plots": {"template": "seaborn"}}, kwargs)
        assert merged["template"] == "seaborn"

        # …but never overrides an explicit component pick.
        merged = merge_dashboard_brand_theme(
            {"plots": {"template": "seaborn"}}, {"template": "plotly_dark"}
        )
        assert merged["template"] == "plotly_dark"

        # Colorway only fills when the component sets no colors of its own.
        merged = merge_dashboard_brand_theme({"plots": {"colorway": ["#111111"]}}, {})
        assert merged["color_discrete_sequence"] == ["#111111"]
        merged = merge_dashboard_brand_theme(
            {"plots": {"colorway": ["#111111"]}}, {"color_discrete_sequence": ["#eeeeee"]}
        )
        assert merged["color_discrete_sequence"] == ["#eeeeee"]
        merged = merge_dashboard_brand_theme(
            {"plots": {"colorway": ["#111111"]}}, {"color_discrete_map": {"A": "#eeeeee"}}
        )
        assert "color_discrete_sequence" not in merged

    def test_bare_palette_derives_a_colorway(self):
        """A dashboard that only picks a primary still tints its figures."""
        from depictio.api.v1.services.figure.figure_builder import merge_dashboard_brand_theme

        merged = merge_dashboard_brand_theme({"primary": "#00a550"}, {})
        assert merged["color_discrete_sequence"][0] == "#00a550"


class TestLegacyAppearanceFields:
    """`logo_url` and `plot_theme` predate `brand_theme` on a dashboard.

    The model forbids extras, so a document still carrying them would 500 the
    whole dashboard rather than merely lose its colours.
    """

    def test_logo_url_folds_in_as_a_custom_logo(self):
        folded = DashboardData._fold_legacy_appearance(
            {"logo_url": "/static/dashboard_logos/x.png"}
        )
        assert folded["brand_theme"] == {
            "logo_url": "/static/dashboard_logos/x.png",
            "logo_mode": "custom",
        }
        assert "logo_url" not in folded

    def test_plot_theme_folds_into_plots(self):
        folded = DashboardData._fold_legacy_appearance(
            {"plot_theme": {"template": "presentation", "colorway": ["#1b9e77"]}}
        )
        assert folded["brand_theme"]["plots"] == {
            "template": "presentation",
            "colorway": ["#1b9e77"],
        }
        assert "plot_theme" not in folded

    def test_a_stated_brand_theme_wins(self):
        folded = DashboardData._fold_legacy_appearance(
            {
                "logo_url": "/static/dashboard_logos/old.png",
                "brand_theme": {"logo_url": "/static/dashboard_logos/new.png"},
            }
        )
        assert folded["brand_theme"]["logo_url"] == "/static/dashboard_logos/new.png"

    def test_untouched_when_neither_field_is_present(self):
        data = {"title": "Iris"}
        assert DashboardData._fold_legacy_appearance(data) is data
