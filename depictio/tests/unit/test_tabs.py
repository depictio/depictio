"""
Unit Tests for Tab Management Functionality.

Tests the core tab management features including URL parsing,
parent dashboard resolution, and tab model fields.
"""

from depictio.models.models.dashboards import DashboardDataLite

# ============================================================================
# Test URL Pathname Extraction
# ============================================================================


class TestExtractDashboardIdFromPathname:
    """Tests for _extract_dashboard_id_from_pathname helper."""

    def test_viewer_url(self):
        """Extract dashboard ID from viewer URL."""
        from depictio.dash.layouts.tab_callbacks import _extract_dashboard_id_from_pathname

        dashboard_id, is_edit = _extract_dashboard_id_from_pathname("/dashboard/abc123")
        assert dashboard_id == "abc123"
        assert is_edit is False

    def test_viewer_edit_url(self):
        """Extract dashboard ID from viewer edit URL."""
        from depictio.dash.layouts.tab_callbacks import _extract_dashboard_id_from_pathname

        dashboard_id, is_edit = _extract_dashboard_id_from_pathname("/dashboard/abc123/edit")
        assert dashboard_id == "abc123"
        assert is_edit is True

    def test_editor_url(self):
        """Extract dashboard ID from editor app URL."""
        from depictio.dash.layouts.tab_callbacks import _extract_dashboard_id_from_pathname

        dashboard_id, is_edit = _extract_dashboard_id_from_pathname("/dashboard-edit/xyz789")
        assert dashboard_id == "xyz789"
        assert is_edit is True

    def test_invalid_url(self):
        """Invalid URL returns None."""
        from depictio.dash.layouts.tab_callbacks import _extract_dashboard_id_from_pathname

        dashboard_id, is_edit = _extract_dashboard_id_from_pathname("/invalid/path")
        assert dashboard_id is None
        assert is_edit is False

    def test_none_pathname(self):
        """None pathname returns None."""
        from depictio.dash.layouts.tab_callbacks import _extract_dashboard_id_from_pathname

        dashboard_id, is_edit = _extract_dashboard_id_from_pathname(None)
        assert dashboard_id is None
        assert is_edit is False


# ============================================================================
# Test Parent Dashboard ID Resolution
# ============================================================================


class TestGetParentDashboardId:
    """Tests for _get_parent_dashboard_id helper."""

    def test_main_tab_returns_own_id(self):
        """Main tab returns its own dashboard_id as parent."""
        from depictio.dash.layouts.tab_callbacks import _get_parent_dashboard_id

        dashboard_data = {"is_main_tab": True, "dashboard_id": "main123"}
        parent_id = _get_parent_dashboard_id(dashboard_data, "main123")
        assert parent_id == "main123"

    def test_child_tab_returns_parent_id(self):
        """Child tab returns parent_dashboard_id."""
        from depictio.dash.layouts.tab_callbacks import _get_parent_dashboard_id

        dashboard_data = {"is_main_tab": False, "parent_dashboard_id": "parent456"}
        parent_id = _get_parent_dashboard_id(dashboard_data, "child789")
        assert parent_id == "parent456"

    def test_default_to_main_tab(self):
        """Missing is_main_tab defaults to True (main tab behavior)."""
        from depictio.dash.layouts.tab_callbacks import _get_parent_dashboard_id

        dashboard_data = {"dashboard_id": "some123"}
        parent_id = _get_parent_dashboard_id(dashboard_data, "some123")
        assert parent_id == "some123"


# ============================================================================
# Test DashboardDataLite Tab Fields
# ============================================================================


class TestDashboardDataLiteTabFields:
    """Tests for tab-related fields in DashboardDataLite."""

    def test_default_is_main_tab(self):
        """Default is_main_tab should be True."""
        lite = DashboardDataLite(title="Test")
        assert lite.is_main_tab is True

    def test_default_tab_order(self):
        """Default tab_order should be 0."""
        lite = DashboardDataLite(title="Test")
        assert lite.tab_order == 0

    def test_child_tab_fields(self):
        """Child tab fields should be set correctly."""
        lite = DashboardDataLite(
            title="Child Tab",
            is_main_tab=False,
            parent_dashboard_tag="Parent Dashboard",
            tab_order=1,
            tab_icon="mdi:chart-bar",
            tab_icon_color="blue",
        )
        assert lite.is_main_tab is False
        assert lite.parent_dashboard_tag == "Parent Dashboard"
        assert lite.tab_order == 1
        assert lite.tab_icon == "mdi:chart-bar"
        assert lite.tab_icon_color == "blue"

    def test_main_tab_name(self):
        """Main tab can have custom display name."""
        lite = DashboardDataLite(
            title="Dashboard Title",
            main_tab_name="Overview",
        )
        assert lite.main_tab_name == "Overview"

    def test_tab_fields_in_yaml_roundtrip(self):
        """Tab fields should survive YAML export/import."""
        original = DashboardDataLite(
            title="Tab Test",
            is_main_tab=False,
            parent_dashboard_tag="Parent",
            tab_order=2,
            tab_icon="mdi:table",
            tab_icon_color="green",
        )
        yaml_str = original.to_yaml()
        restored = DashboardDataLite.from_yaml(yaml_str)

        assert restored.is_main_tab == original.is_main_tab
        assert restored.tab_order == original.tab_order
        assert restored.tab_icon == original.tab_icon
        assert restored.tab_icon_color == original.tab_icon_color


# ============================================================================
# Test Tab Modal Constants
# ============================================================================


class TestTabModalConstants:
    """Tests for tab modal icon and color options."""

    def test_icon_options_exist(self):
        """TAB_ICON_OPTIONS should be defined and non-empty."""
        from depictio.dash.layouts.tab_modal import TAB_ICON_OPTIONS

        assert len(TAB_ICON_OPTIONS) > 0
        # Each option should have value and label
        for opt in TAB_ICON_OPTIONS:
            assert "value" in opt
            assert "label" in opt

    def test_color_options_exist(self):
        """TAB_COLOR_OPTIONS should be defined and non-empty."""
        from depictio.dash.layouts.tab_modal import TAB_COLOR_OPTIONS

        assert len(TAB_COLOR_OPTIONS) > 0
        # Each option should have value and label
        for opt in TAB_COLOR_OPTIONS:
            assert "value" in opt
            assert "label" in opt

    def test_default_icon_in_options(self):
        """Default icon should be in options."""
        from depictio.dash.layouts.tab_modal import TAB_ICON_OPTIONS

        values = [opt["value"] for opt in TAB_ICON_OPTIONS]
        assert "mdi:view-dashboard" in values

    def test_default_color_in_options(self):
        """Default color should be in options."""
        from depictio.dash.layouts.tab_modal import TAB_COLOR_OPTIONS

        values = [opt["value"] for opt in TAB_COLOR_OPTIONS]
        assert "orange" in values
