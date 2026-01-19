"""
Interactive Component - Design/Edit Mode Callbacks

This module contains callbacks that are only needed when editing or designing interactive components.
These callbacks are lazy-loaded when entering edit mode to reduce initial app startup time.

Callbacks:
- pre_populate_interactive_settings_for_edit: Pre-fill design form in edit mode
- update_aggregation_options: Populate method dropdown based on column selection
- toggle_slider_controls_visibility: Show/hide slider controls based on method selection
"""

from dash import MATCH, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import get_columns_from_data_collection


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

    # Populate method dropdown based on column selection
    @app.callback(
        Output({"type": "input-dropdown-method", "index": MATCH}, "data"),
        [
            Input({"type": "input-dropdown-column", "index": MATCH}, "value"),
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input("edit-page-context", "data"),
            State({"type": "input-dropdown-method", "index": MATCH}, "id"),
            State("local-store", "data"),
        ],
        prevent_initial_call=False,
    )
    def update_aggregation_options(
        column_value, workflow_id, data_collection_id, edit_context, id, local_data
    ):
        """
        Populate method dropdown based on selected column type.

        Restored from legacy code (commit 852b230e~1) - adapted for multi-app architecture.
        Uses edit-page-context for edit mode, stepper selections for add mode.
        """

        logger.info("=== UPDATE AGGREGATION OPTIONS CALLBACK START ===")
        logger.info(f"column_value: {column_value}")
        logger.info(f"workflow_id: {workflow_id}")
        logger.info(f"data_collection_id: {data_collection_id}")
        logger.info(f"edit_context: {edit_context is not None}")
        logger.info(f"id: {id}")
        logger.info(f"local_data available: {local_data is not None}")

        if not local_data:
            logger.error("No local_data available!")
            return []

        TOKEN = local_data["access_token"]

        # In edit mode, get workflow/dc IDs from edit context
        if edit_context and (not workflow_id or not data_collection_id):
            logger.info("Edit mode detected - using edit-page-context")
            component_data = edit_context.get("component_data", {})
            if component_data:
                workflow_id = component_data.get("wf_id")
                data_collection_id = component_data.get("dc_id")
                logger.info(
                    f"Retrieved from edit context - workflow_id: {workflow_id}, data_collection_id: {data_collection_id}"
                )

        # If any essential parameters are None, return empty list but allow case where column_value is None
        if not workflow_id or not data_collection_id:
            logger.error(
                f"Missing essential workflow/dc parameters - workflow_id: {workflow_id}, data_collection_id: {data_collection_id}"
            )
            return []

        # If column_value is None, return empty list (but still log the attempt)
        if not column_value:
            logger.info(
                "Column value is None - returning empty list (this is normal on initial load)"
            )
            return []

        logger.info("Fetching columns from data collection...")
        cols_json = get_columns_from_data_collection(workflow_id, data_collection_id, TOKEN)
        logger.info(f"cols_json keys: {list(cols_json.keys()) if cols_json else 'None'}")

        # Check if column exists in cols_json
        if column_value not in cols_json:
            logger.error(f"Column '{column_value}' not found in cols_json!")
            logger.error(f"Available columns: {list(cols_json.keys())}")
            return []

        # Get the type of the selected column
        column_type = cols_json[column_value]["type"]
        logger.info(f"Frontend: Column '{column_value}' has type '{column_type}'")

        # Import agg_functions inline (as done in legacy code)
        from depictio.dash.modules.interactive_component.utils import agg_functions

        logger.info(f"Frontend: Available agg_functions keys: {list(agg_functions.keys())}")

        # Get the number of unique values in the selected column if it is a categorical column
        if column_type in ["object", "category"]:
            nb_unique = cols_json[column_value]["specs"]["nunique"]
        else:
            nb_unique = 0

        # Get the aggregation functions available for the selected column type
        if str(column_type) not in agg_functions:
            logger.error(f"Frontend: Column type '{column_type}' not found in agg_functions!")
            logger.error(f"Frontend: Available types: {list(agg_functions.keys())}")
            return []

        agg_functions_tmp_methods = agg_functions[str(column_type)]["input_methods"]
        logger.info(f"agg_functions_tmp_methods: {agg_functions_tmp_methods}")

        # Create a list of options for the dropdown
        options = [{"label": k, "value": k} for k in agg_functions_tmp_methods.keys()]
        logger.info(f"Options before filtering: {options}")

        # Remove the aggregation methods that are not suitable for the selected column
        if nb_unique > 5:
            options = [e for e in options if e["label"] != "SegmentedControl"]
            logger.info(f"Options after filtering (nb_unique > 5): {options}")

        logger.info(f"Final options to return: {options}")
        logger.info("=== UPDATE AGGREGATION OPTIONS CALLBACK END ===")
        return options

    # Show/hide slider controls based on method selection
    @app.callback(
        Output({"type": "input-dropdown-scale", "index": MATCH}, "style"),
        Output({"type": "input-number-marks", "index": MATCH}, "style"),
        Input({"type": "input-dropdown-method", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def toggle_slider_controls_visibility(method_value):
        """
        Show the scale selector and marks number input only for Slider and RangeSlider components.

        Restored from legacy code (commit 852b230e~1) - was commented out during multi-app refactor.
        """
        if method_value in ["Slider", "RangeSlider"]:
            return {"display": "block"}, {"display": "block"}
        else:
            return {"display": "none"}, {"display": "none"}

    logger.info("✅ Interactive design callbacks registered")
