"""
Interactive Component - Design/Edit Mode Callbacks

This module contains callbacks that are only needed when editing or designing interactive components.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Callbacks:
- pre_populate_interactive_settings_for_edit: Pre-fill design form in edit mode
"""

from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


def register_interactive_design_callbacks(app):
    """Register design/edit mode callbacks for interactive component."""

    # Pre-populate interactive settings in edit mode (edit page, not stepper)
    @app.callback(
        Output({"type": "input-title", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-column", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-method", "index": MATCH}, "value"),
        Output({"type": "input-dropdown-scale", "index": MATCH}, "value"),
        Output({"type": "input-color-picker", "index": MATCH}, "value"),
        Output({"type": "input-icon-selector", "index": MATCH}, "value"),
        Output({"type": "input-title-size", "index": MATCH}, "value"),
        Output({"type": "input-number-marks", "index": MATCH}, "value"),
        Input("edit-page-context", "data"),
        State({"type": "input-title", "index": MATCH}, "id"),
        prevent_initial_call="initial_duplicate",
    )
    def pre_populate_interactive_settings_for_edit(edit_context, input_id):
        """
        Pre-populate interactive design settings when in edit mode.

        Uses actual component ID (no -tmp suffix). Only populates when
        the input_id matches the component being edited in the edit page.

        Args:
            edit_context: Edit page context with component data
            input_id: Interactive component ID from the design form

        Returns:
            Tuple of pre-populated values for all interactive settings
        """
        import dash

        if not edit_context:
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        component_data = edit_context.get("component_data")
        if not component_data or component_data.get("component_type") != "interactive":
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Match component ID (actual ID, no -tmp)
        if str(input_id["index"]) != str(edit_context.get("component_id")):
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        logger.info(f"🎨 PRE-POPULATING interactive settings for component {input_id['index']}")
        logger.info(f"   Title: {component_data.get('title')}")
        logger.info(f"   Column: {component_data.get('column_name')}")
        logger.info(f"   Method: {component_data.get('interactive_component_type')}")
        logger.info(f"   Scale: {component_data.get('scale')}")

        # Ensure ColorInput components get empty string instead of None to avoid trim() errors
        return (
            component_data.get("title") or "",  # TextInput needs string
            component_data.get("column_name"),  # Select accepts None
            component_data.get("interactive_component_type"),  # Select accepts None
            component_data.get("scale") or "linear",  # Select needs value
            component_data.get("custom_color") or "",  # ColorInput needs empty string, not None
            component_data.get("icon_name") or "bx:slider-alt",  # Select needs value
            component_data.get("title_size") or "md",  # Select needs value
            component_data.get("marks_number") or 2,  # NumberInput needs value
        )

    logger.info("✅ Interactive design callbacks registered")
