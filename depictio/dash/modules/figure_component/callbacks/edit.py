"""
Figure Component - Edit Mode Save Callback

This module contains the save callback for editing existing figure components.
The callback reads State inputs from the design UI and uses the shared save helper
to persist changes to the dashboard.
"""

from datetime import datetime

from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger

from .save_utils import save_figure_to_dashboard


def register_figure_edit_callback(app):
    """Register edit mode save callback for figure component."""

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input({"type": "btn-save-edit-figure", "index": ALL}, "n_clicks"),
        State("edit-page-context", "data"),
        State("local-store", "data"),
        State("url", "pathname"),
        # Figure-specific States
        # NOTE: design_figure() uses "segmented-control-visu-graph" not "figure-visu-type-selector"
        State({"type": "segmented-control-visu-graph", "index": ALL}, "value"),
        # Parameter States (pattern-matched by parameter name)
        # These will capture all parameter inputs dynamically
        State({"type": "param-x", "index": ALL}, "value"),
        State({"type": "param-y", "index": ALL}, "value"),
        State({"type": "param-color", "index": ALL}, "value"),
        State({"type": "param-size", "index": ALL}, "value"),
        State({"type": "param-title", "index": ALL}, "value"),
        State({"type": "param-opacity", "index": ALL}, "value"),
        State({"type": "param-hover_name", "index": ALL}, "value"),
        State({"type": "param-hover_data", "index": ALL}, "value"),
        State({"type": "param-labels", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def save_figure_from_edit(
        btn_clicks,
        edit_context,
        local_store,
        current_pathname,
        visu_types,
        param_x,
        param_y,
        param_color,
        param_size,
        param_title,
        param_opacity,
        param_hover_name,
        param_hover_data,
        param_labels,
    ):
        """
        Save edited figure component.

        Reads values from design UI State inputs, builds complete component metadata
        with dict_kwargs, and uses the shared save_figure_to_dashboard() helper to
        persist changes.

        Args:
            btn_clicks: List of n_clicks from save buttons (pattern-matching)
            edit_context: Edit page context with dashboard_id, component_id, component_data
            local_store: Local storage with access token
            current_pathname: Current URL pathname (for app_prefix detection)
            visu_types: Visualization type from selector
            param_*: Parameter values from design UI (pattern-matched States)

        Returns:
            str: Redirect pathname to dashboard after save
        """
        logger.info("=" * 80)
        logger.info("🚀 FIGURE EDIT SAVE CALLBACK TRIGGERED")
        logger.info(f"   ctx.triggered_id: {ctx.triggered_id}")
        logger.info(f"   btn_clicks: {btn_clicks}")

        # GUARD: Validate trigger
        if not ctx.triggered_id or not any(btn_clicks):
            logger.warning("⚠️ FIGURE EDIT SAVE - No trigger or clicks, preventing update")
            raise PreventUpdate

        # Extract context
        dashboard_id = edit_context["dashboard_id"]
        component_id = edit_context["component_id"]
        component_data = edit_context["component_data"]

        logger.info(f"💾 FIGURE EDIT SAVE - Component: {component_id}")
        logger.info(f"   Dashboard: {dashboard_id}")
        logger.info(f"   Component type: {component_data.get('component_type')}")

        # Index for accessing State arrays (should be 0 for edit page with single component)
        idx = 0

        # Helper to safely extract value from State array
        def get_value(arr, idx, fallback=None):
            """Safely extract value from State array."""
            if arr and len(arr) > idx and arr[idx] is not None:
                return arr[idx]
            return fallback

        # Extract visualization type
        visu_type = get_value(visu_types, idx, component_data.get("visu_type", "scatter"))
        logger.info(f"   Visualization type: {visu_type}")

        # Build dict_kwargs from parameter States
        # Start with existing dict_kwargs and update with new values
        dict_kwargs = component_data.get("dict_kwargs", {}).copy()

        # Map parameter States to dict_kwargs keys
        param_mapping = {
            "x": get_value(param_x, idx),
            "y": get_value(param_y, idx),
            "color": get_value(param_color, idx),
            "size": get_value(param_size, idx),
            "title": get_value(param_title, idx),
            "opacity": get_value(param_opacity, idx),
            "hover_name": get_value(param_hover_name, idx),
            "hover_data": get_value(param_hover_data, idx),
            "labels": get_value(param_labels, idx),
        }

        # Update dict_kwargs with non-None values
        for key, value in param_mapping.items():
            if value is not None:
                if key == "labels" and isinstance(value, str) and value.strip():
                    # Parse labels if it's a JSON string
                    try:
                        import json

                        dict_kwargs[key] = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(f"   Failed to parse labels JSON: {value}")
                        dict_kwargs[key] = value
                else:
                    dict_kwargs[key] = value
            elif key in dict_kwargs and value is None:
                # Remove parameter if explicitly set to None
                del dict_kwargs[key]

        logger.info(f"   Updated dict_kwargs keys: {list(dict_kwargs.keys())}")
        logger.info(f"   Parameters: {dict_kwargs}")

        # Build complete component metadata
        updated_metadata = {
            **component_data,  # Preserve existing fields (wf_id, dc_id, layout, etc.)
            "index": component_id,  # Keep actual ID
            "visu_type": visu_type,
            "dict_kwargs": dict_kwargs,
            "last_updated": datetime.now().isoformat(),
        }

        logger.info(f"   Final metadata keys: {list(updated_metadata.keys())}")

        # Get access token
        TOKEN = local_store["access_token"]

        # Detect app prefix from current URL
        app_prefix = "dashboard"  # default to viewer
        if current_pathname and "/dashboard-edit/" in current_pathname:
            app_prefix = "dashboard-edit"

        # Use shared save helper
        redirect_url = save_figure_to_dashboard(dashboard_id, updated_metadata, TOKEN, app_prefix)

        return redirect_url

    logger.info("✅ Figure edit save callback registered")
