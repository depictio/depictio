"""
Figure Component - UI Callbacks

This module contains callbacks for building the parameter UI interface.
Restored from frontend_legacy.py as part of Phase 2A implementation.
"""

import dash
import dash_mantine_components as dmc
from dash import MATCH, Input, Output, State, html

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

    # Callback to update dict_kwargs when parameter values change
    @app.callback(
        Output({"type": "dict_kwargs", "index": MATCH}, "data"),
        [
            Input({"type": "param-x", "index": MATCH}, "value"),
            Input({"type": "param-y", "index": MATCH}, "value"),
            Input({"type": "param-color", "index": MATCH}, "value"),
            Input({"type": "param-size", "index": MATCH}, "value"),
            Input({"type": "param-title", "index": MATCH}, "value"),
            Input({"type": "param-opacity", "index": MATCH}, "value"),
            Input({"type": "param-hover_name", "index": MATCH}, "value"),
            Input({"type": "param-hover_data", "index": MATCH}, "value"),
            Input({"type": "param-labels", "index": MATCH}, "value"),
        ],
        [
            State({"type": "dict_kwargs", "index": MATCH}, "data"),
            State({"type": "param-x", "index": MATCH}, "id"),
        ],
        prevent_initial_call=True,
    )
    def update_dict_kwargs(
        x, y, color, size, title, opacity, hover_name, hover_data, labels, current_kwargs, param_id
    ):
        """
        Update dict_kwargs store when parameter values change.

        This callback fires when any parameter input changes and updates
        the dict_kwargs store, which then triggers the figure preview to update.
        """
        # Get the component index from the ID
        component_index = param_id["index"]

        logger.info(f"📝 PARAMS CHANGED for component {component_index}")

        # Build updated dict_kwargs
        updated_kwargs = current_kwargs or {}

        # Update parameters (only include non-None values)
        params = {
            "x": x,
            "y": y,
            "color": color,
            "size": size,
            "title": title,
            "opacity": opacity,
            "hover_name": hover_name,
            "hover_data": hover_data,
            "labels": labels,
        }

        for key, value in params.items():
            if value is not None:
                updated_kwargs[key] = value
            elif key in updated_kwargs:
                # Remove key if value is None and key exists
                del updated_kwargs[key]

        logger.info(f"📝 Updated dict_kwargs: {updated_kwargs}")

        return updated_kwargs

    logger.info("✅ Figure UI callbacks registered (parameter interface + dict_kwargs updater)")
