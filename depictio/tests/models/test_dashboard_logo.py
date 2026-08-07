"""Per-dashboard logo (`logo_url`): model shape and YAML round-trip.

`logo_url` is an optional string on both DashboardDataLite and DashboardData,
stamped by the /dashboards/upload_logo endpoint and rendered by the viewer
header. Invariants:
- absent everywhere by default, so pre-feature dashboards (and the shipped
  `.db_seeds/*.json`) load unchanged;
- external URLs survive the lite YAML round-trip and the lite ↔ full
  conversions;
- uploaded URLs (under the instance-local /static/dashboard_logos/ mount) are
  dropped on export — the file never ships and imports re-mint the
  dashboard_id the filename is keyed on, so carrying the URL would seed a
  silently broken image on any other deployment.
"""

import json
from pathlib import Path

from depictio.models.models.dashboards import DashboardDataLite

SEED_DIR = Path(__file__).parents[2] / "projects" / "init" / "iris" / ".db_seeds"

EXTERNAL_LOGO_URL = "https://example.org/assets/facility-logo.png"
UPLOADED_LOGO_URL = "/static/dashboard_logos/6824cb3b89d2b72169309737.png?v=1754550000"


class TestLiteRoundTrip:
    def test_default_is_none_and_absent_from_yaml(self):
        dash = DashboardDataLite(title="Test", components=[])
        assert dash.logo_url is None
        assert "logo_url" not in dash.to_yaml()

    def test_yaml_round_trip_external_url(self):
        dash = DashboardDataLite(title="Test", components=[], logo_url=EXTERNAL_LOGO_URL)
        yaml_str = dash.to_yaml()
        assert "logo_url" in yaml_str

        restored = DashboardDataLite.from_yaml(yaml_str)
        assert restored.logo_url == EXTERNAL_LOGO_URL

    def test_to_full_carries_logo_url(self):
        dash = DashboardDataLite(title="Test", components=[], logo_url=EXTERNAL_LOGO_URL)
        assert dash.to_full()["logo_url"] == EXTERNAL_LOGO_URL

    def test_to_full_defaults_to_none(self):
        dash = DashboardDataLite(title="Test", components=[])
        assert dash.to_full()["logo_url"] is None

    def test_from_full_restores_external_logo_url(self):
        full = DashboardDataLite(title="Test", components=[], logo_url=EXTERNAL_LOGO_URL).to_full()
        restored = DashboardDataLite.from_full(full)
        assert restored.logo_url == EXTERNAL_LOGO_URL

    def test_from_full_without_field_is_none(self):
        # Pre-feature documents don't carry the key at all.
        restored = DashboardDataLite.from_full({"title": "Legacy"})
        assert restored.logo_url is None


class TestUploadedLogoIsInstanceLocal:
    def test_from_full_drops_uploaded_logo_url(self):
        restored = DashboardDataLite.from_full({"title": "Test", "logo_url": UPLOADED_LOGO_URL})
        assert restored.logo_url is None

    def test_export_yaml_has_no_uploaded_logo(self):
        lite = DashboardDataLite.from_full({"title": "Test", "logo_url": UPLOADED_LOGO_URL})
        assert "logo_url" not in lite.to_yaml()


class TestSeedCompatibility:
    def test_shipped_seeds_have_no_logo(self):
        # The reference seeds predate the feature; they must load with the
        # default (no logo) rather than requiring a regeneration.
        for seed in SEED_DIR.glob("*.json"):
            data = json.loads(seed.read_text())
            assert data.get("logo_url") is None
