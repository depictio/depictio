"""
Figure Component - Design/Edit Mode Callbacks

This module contains callbacks that are only needed when editing or designing figures.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Callbacks:
- pre_populate_figure_settings_for_edit: Pre-fill design form in edit mode
- design_figure_preview: Live preview of figure with design changes (added in Phase 2B)
"""

from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger


def register_design_callbacks(app):
    """Register design/edit mode callbacks for figure component."""

    # Pre-populate figure settings in edit mode (edit page, not stepper)
    @app.callback(
        # Visualization type selector
        Output({"type": "figure-visu-type-selector", "index": MATCH}, "value"),
        # Common parameters (exist across multiple viz types)
        Output({"type": "param-x", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-y", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-color", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-size", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-title", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-opacity", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-hover_name", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-hover_data", "index": MATCH}, "value", allow_duplicate=True),
        Output({"type": "param-labels", "index": MATCH}, "value", allow_duplicate=True),
        Input("edit-page-context", "data"),
        State({"type": "figure-visu-type-selector", "index": MATCH}, "id"),
        prevent_initial_call="initial_duplicate",
    )
    def pre_populate_figure_settings_for_edit(edit_context, figure_id):
        """
        Pre-populate figure design settings when in edit mode.

        Uses actual component ID (no -tmp suffix). Only populates when
        the figure_id matches the component being edited in the edit page.

        Args:
            edit_context: Edit page context with component data
            figure_id: Figure component ID from the design form

        Returns:
            Tuple of pre-populated values for all figure settings:
            - visu_type
            - x, y, color, size
            - title, opacity
            - hover_name, hover_data
            - labels
        """
        import dash

        if not edit_context:
            return tuple([dash.no_update] * 10)

        component_data = edit_context.get("component_data")
        if not component_data or component_data.get("component_type") != "figure":
            return tuple([dash.no_update] * 10)

        # Match component ID (actual ID, no -tmp)
        if str(figure_id["index"]) != str(edit_context.get("component_id")):
            return tuple([dash.no_update] * 10)

        logger.info(f"🎨 PRE-POPULATING figure settings for component {figure_id['index']}")

        # Extract visualization type
        visu_type = component_data.get("visu_type", "scatter")
        logger.info(f"   Visualization type: {visu_type}")

        # Extract dict_kwargs (parameters)
        dict_kwargs = component_data.get("dict_kwargs", {})
        logger.info(f"   Parameters: {list(dict_kwargs.keys())}")

        # Helper to extract parameter with None fallback
        def get_param(key, default=None):
            value = dict_kwargs.get(key, default)
            logger.info(f"   {key}: {value}")
            return value

        # Extract all common parameters
        x = get_param("x")
        y = get_param("y")
        color = get_param("color")
        size = get_param("size")
        title = get_param("title")
        opacity = get_param("opacity")
        hover_name = get_param("hover_name")
        hover_data = get_param("hover_data")

        # Handle labels (convert dict to JSON string for text input)
        labels = get_param("labels")
        if labels and isinstance(labels, dict):
            import json

            labels = json.dumps(labels)

        logger.info("✓ Pre-population complete")

        return (
            visu_type,
            x,
            y,
            color,
            size,
            title,
            opacity,
            hover_name,
            hover_data,
            labels,
        )

    logger.info("✅ Figure design callbacks registered (pre-populate)")


# Note: Live preview callback will be added in Phase 2B after testing pre-populate
