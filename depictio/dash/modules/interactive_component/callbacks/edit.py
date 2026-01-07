"""
Interactive Component - Edit Mode Save Callback

This module contains the save callback for editing existing interactive components.
The callback reads State inputs from the design UI and uses the shared save helper
to persist changes to the dashboard.
"""

from datetime import datetime

from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger

from .save_utils import save_interactive_to_dashboard


def register_interactive_edit_callback(app):
    """Register edit mode save callback for interactive component."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "btn-save-edit-interactive", "index": ALL}, "n_clicks"),
        State("edit-page-context", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        State({"type": "input-title", "index": ALL}, "value"),
        State({"type": "input-dropdown-column", "index": ALL}, "value"),
        State({"type": "input-dropdown-method", "index": ALL}, "value"),
        State({"type": "input-dropdown-scale", "index": ALL}, "value"),
        State({"type": "input-color-picker", "index": ALL}, "value"),
        State({"type": "input-icon-selector", "index": ALL}, "value"),
        State({"type": "input-title-size", "index": ALL}, "value"),
        State({"type": "input-number-marks", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def save_interactive_from_edit(
        btn_clicks,
        edit_context,
        local_store,
        current_pathname,
        titles,
        columns,
        methods,
        scales,
        colors,
        icons,
        title_sizes,
        marks_numbers,
    ):
        """
        Save edited interactive component.

        Reads values from design UI State inputs, builds complete component metadata,
        and uses the shared save_interactive_to_dashboard() helper to persist changes.

        Args:
            btn_clicks: List of n_clicks from save buttons (pattern-matching)
            edit_context: Edit page context with dashboard_id, component_id, component_data
            local_store: Local storage with access token
            current_pathname: Current URL pathname (for app_prefix detection)
            titles: Component title values from design UI
            columns: Column name values from design UI
            methods: Interactive component type values from design UI
            scales: Scale type values from design UI (linear/log10)
            colors: Custom color values from design UI
            icons: Icon values from design UI
            title_sizes: Title size values from design UI
            marks_numbers: Number of marks values from design UI

        Returns:
            str: Redirect pathname to dashboard after save
        """
        logger.info("=" * 80)
        logger.info("🚀 INTERACTIVE EDIT SAVE CALLBACK TRIGGERED")
        logger.info(f"   ctx.triggered_id: {ctx.triggered_id}")
        logger.info(f"   btn_clicks: {btn_clicks}")

        # GUARD: Validate trigger
        if not ctx.triggered_id or not any(btn_clicks):
            logger.warning("⚠️ INTERACTIVE EDIT SAVE - No trigger or clicks, preventing update")
            raise PreventUpdate

        # Extract context
        dashboard_id = edit_context["dashboard_id"]
        component_id = edit_context["component_id"]
        component_data = edit_context["component_data"]

        logger.info(f"💾 INTERACTIVE EDIT SAVE - Component: {component_id}")
        logger.info(f"   Dashboard: {dashboard_id}")
        logger.info(f"   Component type: {component_data.get('component_type')}")
        logger.info(
            f"   Received States - titles: {titles}, columns: {columns}, methods: {methods}"
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
            **component_data,  # Preserve existing fields (wf_id, dc_id, value, etc.)
            "index": component_id,  # Keep actual ID
            "title": get_value(titles, idx, "title", ""),
            "column_name": get_value(columns, idx, "column_name", None),
            "interactive_component_type": get_value(
                methods, idx, "interactive_component_type", None
            ),
            "scale": get_value(scales, idx, "scale", "linear"),
            "custom_color": get_value(colors, idx, "custom_color", ""),
            "icon_name": get_value(icons, idx, "icon_name", "bx:slider-alt"),
            "title_size": get_value(title_sizes, idx, "title_size", "md"),
            "marks_number": get_value(marks_numbers, idx, "marks_number", 2),
            "last_updated": datetime.now().isoformat(),
        }

        logger.info(f"   Updated title: {updated_metadata['title']}")
        logger.info(f"   Updated column: {updated_metadata['column_name']}")
        logger.info(f"   Updated method: {updated_metadata['interactive_component_type']}")
        logger.info(f"   Updated scale: {updated_metadata['scale']}")
        logger.info(f"   Updated color: {updated_metadata['custom_color']}")
        logger.info(f"   Updated icon: {updated_metadata['icon_name']}")
        logger.info(f"   Updated title_size: {updated_metadata['title_size']}")
        logger.info(f"   Updated marks: {updated_metadata['marks_number']}")

        # Get access token
        TOKEN = local_store["access_token"]

        # Detect app prefix from current URL
        app_prefix = "dashboard"  # default to viewer
        if current_pathname and "/dashboard-edit/" in current_pathname:
            app_prefix = "dashboard-edit"

        # Use shared save helper
        redirect_url = save_interactive_to_dashboard(
            dashboard_id, updated_metadata, TOKEN, app_prefix
        )

        return redirect_url

    logger.info("✅ Interactive edit save callback registered")
