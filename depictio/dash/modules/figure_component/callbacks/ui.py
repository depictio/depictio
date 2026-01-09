"""
Figure Component - UI Callbacks

This module contains callbacks for building the parameter UI interface.
Restored from frontend_legacy.py as part of Phase 2A implementation.
"""

from datetime import datetime

import dash
import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.utils import get_columns_from_data_collection

from ..component_builder import AccordionBuilder, ComponentBuilder
from ..definitions import get_visualization_definition
from ..state_manager import state_manager


def register_ui_callbacks(app):
    """Register UI building callbacks for figure component."""

    @app.callback(
        Output({"type": "collapse", "index": MATCH}, "children"),
        [
            Input({"type": "edit-button", "index": MATCH}, "n_clicks"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        [
            State({"type": "workflow-selection-label", "index": MATCH}, "value"),
            State({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            State({"type": "edit-button", "index": MATCH}, "id"),
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State("local-store", "data"),
            State({"type": "figure-mode-store", "index": MATCH}, "data"),
        ],
        prevent_initial_call=False,
    )
    def build_parameter_interface(
        _n_clicks_edit,
        visu_type,
        workflow,
        data_collection,
        edit_button_id,
        current_dict_kwargs,
        local_data,
        current_mode,
    ):
        """Build parameter interface using the robust component builder system.

        This callback is triggered when:
        1. Visualization type changes in the dropdown
        2. Edit button is clicked (though unused in current implementation)

        It builds the parameter input UI (x, y, color, size dropdowns, etc.)
        based on the selected visualization type and available columns.
        """

        if not local_data:
            raise dash.exceptions.PreventUpdate

        # Don't build UI parameter interface if in code mode
        if current_mode == "code":
            logger.info("🚫 SKIPPING UI PARAMETER INTERFACE - Component is in code mode")
            return html.Div()  # Return empty div for code mode

        logger.info("=== BUILDING PARAMETER INTERFACE ===")
        logger.info(f"Visualization type: {visu_type}")
        logger.info(f"Component ID: {edit_button_id.get('index') if edit_button_id else 'unknown'}")

        TOKEN = local_data["access_token"]
        component_index = edit_button_id["index"] if edit_button_id else "unknown"

        logger.info(f"Component index: {component_index}")
        logger.info(f"Workflow: {workflow}")
        logger.info(f"Data collection: {data_collection}")

        logger.info("Fetching available columns for data collection...")
        logger.info(f"Workflow ID: {workflow}")
        logger.info(f"Data Collection ID: {data_collection}")

        # Get available columns
        try:
            columns_json = get_columns_from_data_collection(workflow, data_collection, TOKEN)
            columns = list(columns_json.keys())
            logger.info(f"✓ Loaded {len(columns)} columns from data collection")
        except Exception as e:
            logger.error(f"Failed to get columns: {e}")
            columns = []
            columns_json = {}
            return html.Div(
                dmc.Alert(
                    f"Failed to load columns: {str(e)}",
                    title="Column Loading Error",
                    color="red",
                )
            )

        # Determine visualization type from dropdown
        if visu_type:  # visu_type is now the name (lowercase) from dropdown
            # Since we now use viz.name.lower() as dropdown value, use it directly
            visu_type = visu_type.lower()
        else:
            visu_type = "scatter"  # Default fallback

        logger.info(f"Final visualization type: {visu_type}")

        try:
            # Get visualization definition
            viz_def = get_visualization_definition(visu_type)

            # Get or create component state
            state = state_manager.get_state(component_index)
            if not state:
                state = state_manager.create_state(
                    component_id=component_index,
                    visualization_type=visu_type,
                    data_collection_id=data_collection or "",
                    workflow_id=workflow or "",
                )
            else:
                # Update visualization type if changed
                if state.visualization_type != visu_type:
                    state_manager.change_visualization_type(component_index, visu_type)

            # Load existing parameters from current dict_kwargs (which contains preserved values)
            parameters_to_load = current_dict_kwargs or {}

            if parameters_to_load:
                logger.info(f"Loading parameters into state: {parameters_to_load}")
                for param_name, value in parameters_to_load.items():
                    state.set_parameter_value(param_name, value)

            # Build UI components
            component_builder = ComponentBuilder(component_index, columns, columns_json)
            accordion_builder = AccordionBuilder(component_builder)

            # Build the complete accordion interface
            accordion = accordion_builder.build_full_accordion(viz_def, state)

            logger.info("✅ Successfully built parameter interface")
            return accordion

        except Exception as e:
            logger.error(f"Error building parameter interface: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return html.Div(
                [
                    dmc.Alert(
                        f"Error loading parameters: {str(e)}",
                        title="Parameter Loading Error",
                        color="red",
                    )
                ]
            )

    # Callback to capture parameter changes dynamically
    @app.callback(
        Output({"type": "param-trigger", "index": MATCH}, "data"),
        [
            Input({"type": ALL, "index": MATCH}, "value"),
            Input({"type": ALL, "index": MATCH}, "checked"),  # For DMC Switch components
        ],
        [
            State({"type": "param-trigger", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def update_param_trigger_and_state(*args):
        """
        Dynamically capture parameter changes using callback context.

        This callback uses ctx.inputs_list to dynamically iterate over
        whatever parameter inputs exist for the current visualization type,
        avoiding hardcoded parameter lists.
        """
        import json
        import time

        from ..state_manager import state_manager

        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        # Get component index from state
        trigger_id = args[-1]  # Last arg is the State
        component_index = trigger_id["index"]

        # Check if any param-* input triggered this
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            triggered_id_dict = json.loads(triggered_id)
        except (json.JSONDecodeError, TypeError):
            raise dash.exceptions.PreventUpdate

        # Only process if it's a parameter input
        if not (
            isinstance(triggered_id_dict, dict)
            and triggered_id_dict.get("type", "").startswith("param-")
        ):
            raise dash.exceptions.PreventUpdate

        logger.info(f"📝 PARAMETER CHANGED for component {component_index}")
        logger.info(f"   Triggered by: {triggered_id_dict}")

        # Get state from state manager
        state = state_manager.get_state(component_index)
        if not state:
            logger.warning(
                f"No state found for component {component_index}, cannot update parameters"
            )
            return dash.no_update

        # Extract all parameter values from ctx.inputs_list
        for input_dict in ctx.inputs_list:
            for input_item in input_dict:
                input_id = input_item.get("id", {})
                if isinstance(input_id, dict) and input_id.get("type", "").startswith("param-"):
                    param_name = input_id["type"].replace("param-", "")

                    # Get value from input - try both 'value' and 'checked'
                    value = input_item.get("value")
                    checked = input_item.get("checked")

                    # Use checked for Switch components, value for others
                    actual_value = checked if checked is not None else value

                    # Update state with non-empty values
                    if actual_value is not None and actual_value != "" and actual_value != []:
                        state.set_parameter_value(param_name, actual_value)
                        logger.info(f"   {param_name}: {actual_value}")
                    elif isinstance(actual_value, bool):
                        # Include boolean False
                        state.set_parameter_value(param_name, actual_value)
                        logger.info(f"   {param_name}: {actual_value}")

        # Return updated trigger with timestamp
        return {"timestamp": time.time()}

    # Callback to collect parameter changes and update dict_kwargs
    # Uses ALLSMALLER pattern to handle any parameters that exist for the current viz type
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data"),
        [
            Input({"type": "param-trigger", "index": MATCH}, "data"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "collapse", "index": MATCH}, "children"),
            State({"type": "param-trigger", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def update_dict_kwargs_from_state_manager(
        trigger_data, current_kwargs, collapse_children, trigger_id
    ):
        """
        Update dict_kwargs using state manager to avoid missing parameter issues.

        This callback is triggered by state_manager changes and extracts
        parameter values safely without depending on specific parameter inputs.
        """
        from ..state_manager import state_manager

        component_index = trigger_id["index"]
        logger.info(f"📝 UPDATING dict_kwargs for component {component_index}")

        # Get state from state manager
        state = state_manager.get_state(component_index)
        if not state:
            logger.warning(f"No state found for component {component_index}")
            return current_kwargs or {}

        # Get all parameter values from state.parameters dictionary
        updated_kwargs = dict(state.parameters)  # Make a copy

        logger.info(f"📝 Updated dict_kwargs from state: {updated_kwargs}")

        return updated_kwargs

    # Callback to sync dict_kwargs into stored-metadata-component for saving
    @app.callback(
        Output({"type": "stored-metadata-component", "index": MATCH}, "data"),
        [
            Input({"type": "dict_kwargs", "index": MATCH}, "data"),
            Input({"type": "segmented-control-visu-graph", "index": MATCH}, "value"),
        ],
        [
            State({"type": "stored-metadata-component", "index": MATCH}, "data"),
        ],
        prevent_initial_call=True,
    )
    def sync_dict_kwargs_to_metadata(dict_kwargs, visu_type, current_metadata):
        """
        Sync dict_kwargs and visu_type to stored-metadata-component for saving.

        This ensures that when the component is saved to the dashboard,
        it includes the current parameter values selected by the user.
        """
        if not current_metadata:
            raise dash.exceptions.PreventUpdate

        logger.info(
            f"🔄 Syncing dict_kwargs to stored-metadata for component {current_metadata.get('index')}"
        )
        logger.info(f"   dict_kwargs: {dict_kwargs}")
        logger.info(f"   visu_type: {visu_type}")

        # Update the metadata with current values
        updated_metadata = current_metadata.copy()
        updated_metadata["dict_kwargs"] = dict_kwargs or {}
        updated_metadata["visu_type"] = (
            visu_type if visu_type else updated_metadata.get("visu_type", "scatter")
        )
        updated_metadata["last_updated"] = datetime.now().isoformat()

        logger.info(f"✅ Metadata updated: {updated_metadata}")

        return updated_metadata

    logger.info(
        "✅ Figure UI callbacks registered (parameter interface + state-based dict_kwargs updater + metadata sync)"
    )
