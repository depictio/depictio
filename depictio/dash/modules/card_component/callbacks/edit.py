"""
Card Component - Edit Mode Save Callback

This module contains the save callback for editing existing card components.
The callback reads State inputs from the design UI and uses the shared save helper
to persist changes to the dashboard.
"""

from datetime import datetime

from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger

from .save_utils import save_card_to_dashboard


def register_card_edit_callback(app):
    """Register edit mode save callback for card component."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "btn-save-edit-card", "index": ALL}, "n_clicks"),
        State("edit-page-context", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        State({"type": "card-input", "index": ALL}, "value"),
        State({"type": "card-dropdown-column", "index": ALL}, "value"),
        State({"type": "card-dropdown-aggregation", "index": ALL}, "value"),
        State({"type": "card-color-background", "index": ALL}, "value"),
        State({"type": "card-color-title", "index": ALL}, "value"),
        State({"type": "card-icon-selector", "index": ALL}, "value"),
        State({"type": "card-title-font-size", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def save_card_from_edit(
        btn_clicks,
        edit_context,
        local_store,
        current_pathname,
        card_titles,
        card_columns,
        card_aggregations,
        card_bg_colors,
        card_title_colors,
        card_icons,
        card_font_sizes,
    ):
        """
        Save edited card component.

        Reads values from design UI State inputs, builds complete component metadata,
        and uses the shared save_card_to_dashboard() helper to persist changes.

        Args:
            btn_clicks: List of n_clicks from save buttons (pattern-matching)
            edit_context: Edit page context with dashboard_id, component_id, component_data
            local_store: Local storage with access token
            current_pathname: Current URL pathname (for app_prefix detection)
            card_titles: Card title values from design UI
            card_columns: Card column values from design UI
            card_aggregations: Card aggregation values from design UI
            card_bg_colors: Card background color values from design UI
            card_title_colors: Card title color values from design UI
            card_icons: Card icon values from design UI
            card_font_sizes: Card font size values from design UI

        Returns:
            str: Redirect pathname to dashboard after save
        """
        logger.info("=" * 80)
        logger.info("🚀 CARD EDIT SAVE CALLBACK TRIGGERED")
        logger.info(f"   ctx.triggered_id: {ctx.triggered_id}")
        logger.info(f"   btn_clicks: {btn_clicks}")

        # GUARD: Validate trigger
        if not ctx.triggered_id or not any(btn_clicks):
            logger.warning("⚠️ CARD EDIT SAVE - No trigger or clicks, preventing update")
            raise PreventUpdate

        # Extract context
        dashboard_id = edit_context["dashboard_id"]
        component_id = edit_context["component_id"]
        component_data = edit_context["component_data"]

        logger.info(f"💾 CARD EDIT SAVE - Component: {component_id}")
        logger.info(f"   Dashboard: {dashboard_id}")
        logger.info(f"   Component type: {component_data.get('component_type')}")
        logger.info(
            f"   Received States - titles: {card_titles}, columns: {card_columns}, aggregations: {card_aggregations}"
        )

        # Index for accessing State arrays (should be 0 for edit page with single component)
        idx = 0

        # Helper to safely extract value from State array with fallback
        def get_value(arr, idx, fallback_key, default=""):
            """Safely extract value from State array with fallback to component_data."""
            if arr and len(arr) > idx and arr[idx] is not None:
                return arr[idx]
            return component_data.get(fallback_key, default)

        # Build complete component metadata
        updated_metadata = {
            **component_data,  # Preserve existing fields (wf_id, dc_id, etc.)
            "index": component_id,  # Keep actual ID
            "title": get_value(card_titles, idx, "title", ""),
            "column_name": get_value(card_columns, idx, "column_name", None),
            "aggregation": get_value(card_aggregations, idx, "aggregation", None),
            "background_color": get_value(card_bg_colors, idx, "background_color", ""),
            "title_color": get_value(card_title_colors, idx, "title_color", ""),
            "icon_name": get_value(card_icons, idx, "icon_name", "mdi:chart-line"),
            "title_font_size": get_value(card_font_sizes, idx, "title_font_size", "md"),
            "last_updated": datetime.now().isoformat(),
        }

        logger.info(f"   Updated title: {updated_metadata['title']}")
        logger.info(f"   Updated column: {updated_metadata['column_name']}")
        logger.info(f"   Updated aggregation: {updated_metadata['aggregation']}")
        logger.info(f"   Updated background_color: {updated_metadata['background_color']}")
        logger.info(f"   Updated title_color: {updated_metadata['title_color']}")
        logger.info(f"   Updated icon: {updated_metadata['icon_name']}")
        logger.info(f"   Updated font_size: {updated_metadata['title_font_size']}")

        # Get access token
        TOKEN = local_store["access_token"]

        # Detect app prefix from current URL
        app_prefix = "dashboard"  # default to viewer
        if current_pathname and "/dashboard-edit/" in current_pathname:
            app_prefix = "dashboard-edit"

        # Use shared save helper
        redirect_url = save_card_to_dashboard(dashboard_id, updated_metadata, TOKEN, app_prefix)

        return redirect_url

    logger.info("✅ Card edit save callback registered")
