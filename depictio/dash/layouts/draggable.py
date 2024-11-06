import copy
import json
from bson import ObjectId
from dash import html, Input, Output, State, ALL, MATCH, ctx, dcc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import dash_draggable
import dash
import httpx
from depictio.dash.layouts.draggable_scenarios.add_component import add_new_component
from depictio.dash.layouts.edit import edit_component

from depictio.api.v1.configs.config import API_BASE_URL, logger

from depictio.dash.layouts.draggable_scenarios.interactive_component_update import update_interactive_component
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import render_dashboard


# Depictio layout imports for stepper

# Depictio layout imports for header
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.dash.utils import generate_unique_index, get_columns_from_data_collection, get_component_data, return_dc_tag_from_id, return_mongoid, return_wf_tag_from_id


# Mapping of component types to their respective dimensions (width and height)
component_dimensions = {"card-component": {"w": 2, "h": 5}, "interactive-component": {"w": 5, "h": 3}, "graph-component": {"w": 6, "h": 13}}
required_breakpoints = ["xl", "lg", "sm", "md", "xs", "xxs"]


def calculate_new_layout_position(child_type, existing_layouts, child_id, n):
    """Calculate position for new layout item based on existing ones and type."""
    # Get the default dimensions from the type
    dimensions = component_dimensions.get(child_type, {"w": 6, "h": 5})  # Default if type not found

    # Simple positioning logic: place items in rows based on their index
    columns_per_row = 12  # Assuming a 12-column layout grid
    row = n // (columns_per_row // dimensions["w"])  # Integer division to find row based on how many fit per row
    col_position = (n % (columns_per_row // dimensions["w"])) * dimensions["w"]  # Modulo for column position

    return {
        "x": col_position,
        "y": row * dimensions["h"],  # Stacking rows based on height of each component
        "w": dimensions["w"],
        "h": dimensions["h"],
        "i": child_id,
    }


# Update any nested component IDs within the duplicated component
def update_nested_ids(component, old_index, new_index):
    if isinstance(component, dict):
        for key, value in component.items():
            if key == "id" and isinstance(value, dict):
                if value.get("index") == old_index:
                    value["index"] = new_index
            elif isinstance(value, dict):
                update_nested_ids(value, old_index, new_index)
            elif isinstance(value, list):
                for item in value:
                    update_nested_ids(item, old_index, new_index)
    elif isinstance(component, list):
        for item in component:
            update_nested_ids(item, old_index, new_index)


def remove_duplicates_by_index(components):
    unique_components = {}
    for component in components:
        index = component["index"]
        if index not in unique_components:
            unique_components[index] = component
    return list(unique_components.values())


def register_callbacks_draggable(app):
    from dash import callback_context

    @app.callback(
        Output("local-store-components-metadata", "data"),
        [
            Input({"type": "workflow-selection-label", "index": ALL}, "value"),
            Input({"type": "datacollection-selection-label", "index": ALL}, "value"),
            Input("url", "pathname"),
        ],
        [
            State("local-store", "data"),  # Contains 'access_token'
            State("local-store-components-metadata", "data"),  # Existing components' data
            State({"type": "workflow-selection-label", "index": ALL}, "id"),
            State({"type": "datacollection-selection-label", "index": ALL}, "id"),
        ],
        prevent_initial_call=True,
    )
    def store_wf_dc_selection(wf_values, dc_values, pathname, local_store, components_store, wf_ids, dc_ids):
        """
        Callback to store all components' workflow and data collection data in a centralized store.
        Updates the store whenever any workflow or data collection dropdown changes.

        Args:
            wf_values (list): List of selected workflow values from all dropdowns.
            dc_values (list): List of selected data collection values from all dropdowns.
            pathname (str): Current URL pathname.
            local_store (dict): Data from 'local-store', expected to contain 'access_token'.
            components_store (dict): Existing components' wf/dc data.
            wf_ids (list): List of IDs for workflow dropdowns.
            dc_ids (list): List of IDs for datacollection dropdowns.

        Returns:
            dict: Updated components' wf/dc data.
        """
        logger.info("Entering store_wf_dc_selection callback")
        logger.debug(f"Workflow values: {wf_values}")
        logger.debug(f"Data collection values: {dc_values}")
        logger.debug(f"URL pathname: {pathname}")
        logger.debug(f"Local store data: {local_store}")
        logger.debug(f"Components store data before update: {components_store}")

        # Validate access token
        if not local_store or "access_token" not in local_store:
            logger.error("Local data or access_token is missing.")
            return components_store  # No update

        TOKEN = local_store["access_token"]

        # Initialize components_store if empty
        if not components_store:
            components_store = {}

        # Process workflow selections
        for wf_val, wf_id in zip(wf_values, wf_ids):
            # Parse the ID safely
            try:
                trigger_id = wf_id
            # except json.JSONDecodeError as e:
            #     logger.error(f"Error parsing workflow ID '{wf_id}': {e}")
            #     continue  # Skip this iteration
            except Exception as e:
                logger.error(f"Error parsing workflow ID '{wf_id}': {e}")
                continue

            trigger_index = str(trigger_id.get("index"))
            if not trigger_index:
                logger.error(f"Invalid workflow ID: {trigger_id}")
                continue  # Skip this iteration

            # Update workflow tag
            components_store.setdefault(trigger_index, {})
            components_store[trigger_index]["wf_tag"] = wf_val

            # Fetch corresponding wf_id and dc_id
            dc_tag = components_store[trigger_index].get("dc_tag", "")
            try:
                wf_id_fetched, dc_id_fetched = return_mongoid(workflow_tag=wf_val, data_collection_tag=dc_tag, TOKEN=TOKEN)
                components_store[trigger_index]["wf_id"] = wf_id_fetched
                components_store[trigger_index]["dc_id"] = dc_id_fetched
                logger.debug(f"Updated component '{trigger_index}' with wf_id: {wf_id_fetched}, dc_id: {dc_id_fetched}")
            except Exception as e:
                logger.error(f"Error retrieving IDs for component '{trigger_index}': {e}")
                components_store[trigger_index]["wf_id"] = ""
                components_store[trigger_index]["dc_id"] = ""

        # Process datacollection selections
        for dc_val, dc_id in zip(dc_values, dc_ids):
            # Parse the ID safely
            try:
                trigger_id = dc_id
            # except json.JSONDecodeError as e:
            #     logger.error(f"Error parsing datacollection ID '{dc_id}': {e}")
            #     continue  # Skip this iteration
            except Exception as e:
                logger.error(f"Error parsing datacollection ID '{dc_id}': {e}")
                continue  # Skip this iteration

            trigger_index = str(trigger_id.get("index"))
            if not trigger_index:
                logger.error(f"Invalid datacollection ID: {trigger_id}")
                continue  # Skip this iteration

            # Update datacollection tag
            components_store.setdefault(trigger_index, {})
            components_store[trigger_index]["dc_tag"] = dc_val

            # Fetch corresponding wf_id and dc_id
            wf_tag = components_store[trigger_index].get("wf_tag", "")
            try:
                wf_id_fetched, dc_id_fetched = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_val, TOKEN=TOKEN)
                components_store[trigger_index]["wf_id"] = wf_id_fetched
                components_store[trigger_index]["dc_id"] = dc_id_fetched
                logger.debug(f"Updated component '{trigger_index}' with wf_id: {wf_id_fetched}, dc_id: {dc_id_fetched}")
            except Exception as e:
                logger.error(f"Error retrieving IDs for component '{trigger_index}': {e}")
                components_store[trigger_index]["wf_id"] = ""
                components_store[trigger_index]["dc_id"] = ""

        logger.debug(f"Components store data after update: {components_store}")
        return components_store

    import uuid
    import logging

    # Initialize logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    def process_click_data(dict_graph_data, interactive_components_dict, TOKEN):
        """
        Process clickData from a Plotly graph and update the interactive_components_dict with new filters.

        Parameters:
        - dict_graph_data (dict): Contains the clicked point data and metadata.
        - interactive_components_dict (dict): Existing interactive components to be updated.

        Returns:
        - dict: Updated interactive_components_dict with new filter entries.
        """

        # Extract clicked point data
        point = dict_graph_data.get("value", {})
        metadata = dict_graph_data.get("metadata", {})

        logger.info(f"Processing click data: {point}")
        logger.info(f"Metadata: {metadata}")

        # Extract dict_kwargs from metadata to identify the columns mapped to x and y
        dict_kwargs = metadata.get("dict_kwargs", {})
        x_column = dict_kwargs.get("x")
        y_column = dict_kwargs.get("y")

        logger.info(f"Processing click data for columns: x={x_column}, y={y_column}")

        # Extract the x and y values from click data
        x_value = point.get("x")
        y_value = point.get("y")

        logger.info(f"Clicked point values: x={x_value}, y={y_value}")

        # Extract columns_description from metadata to determine column types
        columns_description = metadata.get("dc_config", {}).get("columns_description", {})

        wf_tag = return_wf_tag_from_id(metadata.get("wf_id"), TOKEN=TOKEN)
        dc_tag = return_dc_tag_from_id(metadata.get("wf_id"), metadata.get("dc_id"), TOKEN=TOKEN)
        cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
        logger.info(f"Columns JSON: {cols_json}")

        # Get column types; default to 'object' (categorical) if not specified
        x_col_type = cols_json.get(x_column, {}).get("type", "object")
        y_col_type = cols_json.get(y_column, {}).get("type", "object")

        logger.info(f"Column types: {x_column}={x_col_type}, {y_column}={y_col_type}")

        # Initialize a dictionary to hold new filter entries
        new_filters = {}

        # Function to generate unique keys for new filters
        def generate_filter_key(column_name):
            return f"filter_{column_name}_{uuid.uuid4()}"

        # Process x_value
        if x_value is not None and x_column:
            if x_col_type in ["int64", "float64"]:
                # Numerical column, use Slider for exact match
                new_key = generate_filter_key(x_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "Slider",
                        "column_name": x_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": x_value,
                }
                logger.info(f"Added numerical filter for {x_column}: {x_value}")
            else:
                # Categorical column, use Select for is_in filter
                new_key = generate_filter_key(x_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "Select",
                        "column_name": x_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": [x_value],  # is_in expects a list
                }
                logger.info(f"Added categorical filter for {x_column}: {x_value}")

        # Process y_value
        if y_value is not None and y_column:
            if y_col_type in ["int64", "float64"]:
                # Numerical column, use Slider for exact match
                new_key = generate_filter_key(y_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "Slider",
                        "column_name": y_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": y_value,
                }
                logger.info(f"Added numerical filter for {y_column}: {y_value}")
            else:
                # Categorical column, use Select for is_in filter
                new_key = generate_filter_key(y_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "Select",
                        "column_name": y_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": [y_value],  # is_in expects a list
                }
                logger.info(f"Added categorical filter for {y_column}: {y_value}")

        # Update the interactive_components_dict with new filters
        interactive_components_dict.update(new_filters)

        logger.info(f"Updated interactive_components_dict: {interactive_components_dict}")

        return interactive_components_dict


    def process_selected_data(dict_graph_data, interactive_components_dict, TOKEN):
        """
        Process selectedData from a Plotly graph and update the interactive_components_dict with new filters.

        Parameters:
        - dict_graph_data (dict): Contains the list of selected points data and metadata.
        - interactive_components_dict (dict): Existing interactive components to be updated.
        - TOKEN (str): Access token for authentication (if needed).

        Returns:
        - dict: Updated interactive_components_dict with new filter entries.
        """

        # Extract selected points data
        points = dict_graph_data.get("value", [])
        metadata = dict_graph_data.get("metadata", {})

        logger.info(f"Processing selected data with {len(points)} points.")
        logger.info(f"Metadata: {metadata}")

        # Extract dict_kwargs from metadata to identify the columns mapped to x and y
        dict_kwargs = metadata.get("dict_kwargs", {})
        x_column = dict_kwargs.get("x")
        y_column = dict_kwargs.get("y")

        logger.info(f"Processing selected data for columns: x={x_column}, y={y_column}")

        # Extract unique x and y values from selected points
        x_values = set(point.get("x") for point in points if "x" in point)
        y_values = set(point.get("y") for point in points if "y" in point)

        logger.info(f"Unique selected x values: {x_values}")
        logger.info(f"Unique selected y values: {y_values}")

        # Extract columns_description from metadata to determine column types
        columns_description = metadata.get("dc_config", {}).get("columns_description", {})

        # Fetch column types from data collection (assuming helper functions exist)
        wf_tag = return_wf_tag_from_id(metadata.get("wf_id"), TOKEN=TOKEN)
        dc_tag = return_dc_tag_from_id(metadata.get("wf_id"), metadata.get("dc_id"), TOKEN=TOKEN)
        cols_json = get_columns_from_data_collection(wf_tag, dc_tag, TOKEN)
        logger.info(f"Columns JSON: {cols_json}")

        # Get column types; default to 'object' (categorical) if not specified
        x_col_type = cols_json.get(x_column, {}).get("type", "object")
        y_col_type = cols_json.get(y_column, {}).get("type", "object")

        logger.info(f"Column types: {x_column}={x_col_type}, {y_column}={y_col_type}")

        # Initialize a dictionary to hold new filter entries
        new_filters = {}

        # Function to generate unique keys for new filters
        def generate_filter_key(column_name):
            return f"filter_{column_name}_{uuid.uuid4()}"

        # Process x_values
        if x_values and x_column:
            if x_col_type in ["int64", "float64"]:
                # Numerical column, use RangeSlider to encompass selected values
                min_val = min(x_values)
                max_val = max(x_values)
                new_key = generate_filter_key(x_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "RangeSlider",
                        "column_name": x_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": [min_val, max_val],
                }
                logger.info(f"Added RangeSlider filter for {x_column}: [{min_val}, {max_val}]")
            else:
                # Categorical column, use Select for is_in filter
                new_key = generate_filter_key(x_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "Select",
                        "column_name": x_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": list(x_values),  # is_in expects a list
                }
                logger.info(f"Added Select filter for {x_column}: {list(x_values)}")

        # Process y_values
        if y_values and y_column:
            if y_col_type in ["int64", "float64"]:
                # Numerical column, use RangeSlider to encompass selected values
                min_val = min(y_values)
                max_val = max(y_values)
                new_key = generate_filter_key(y_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "RangeSlider",
                        "column_name": y_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": [min_val, max_val],
                }
                logger.info(f"Added RangeSlider filter for {y_column}: [{min_val}, {max_val}]")
            else:
                # Categorical column, use Select for is_in filter
                new_key = generate_filter_key(y_column)
                new_filters[new_key] = {
                    "metadata": {
                        "interactive_component_type": "Select",
                        "column_name": y_column,
                        "wf_id": metadata.get("wf_id"),
                        "dc_id": metadata.get("dc_id"),
                    },
                    "value": list(y_values),  # is_in expects a list
                }
                logger.info(f"Added Select filter for {y_column}: {list(y_values)}")

        # Update the interactive_components_dict with new filters
        interactive_components_dict.update(new_filters)

        logger.info(f"Updated interactive_components_dict: {interactive_components_dict}")

        return interactive_components_dict

    @app.callback(
        Output("draggable", "children"),
        Output("draggable", "layouts"),
        Output("stored-draggable-children", "data"),
        Output("stored-draggable-layouts", "data"),
        Output("current-edit-parent-index", "data"),  # Add this Output
        # Output("stored-add-button", "data"),
        Input(
            {
                "type": "btn-done",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {
                "type": "btn-done-edit",
                "index": ALL,
            },
            "n_clicks",
        ),
        State(
            {
                "type": "interactive-component-value",
                "index": ALL,
            },
            "id",
        ),
        Input(
            {
                "type": "interactive-component-value",
                "index": ALL,
            },
            "value",
        ),
        Input(
            {
                "type": "graph",
                "index": ALL,
            },
            "selectedData",
        ),
        Input(
            {
                "type": "graph",
                "index": ALL,
            },
            "clickData",
        ),
        Input(
            {
                "type": "graph",
                "index": ALL,
            },
            "relayoutData",
        ),
        State(
            {
                "type": "graph",
                "index": ALL,
            },
            "id",
        ),
        State("stored-add-button", "data"),
        State(
            {
                "type": "stored-metadata-component",
                "index": ALL,
            },
            "data",
        ),
        State(
            {
                "type": "component-container",
                "index": ALL,
            },
            "children",
        ),
        State("draggable", "children"),
        State("draggable", "layouts"),
        Input("draggable", "layouts"),
        State("stored-draggable-children", "data"),
        State("stored-draggable-layouts", "data"),
        Input("stored-draggable-children", "data"),
        Input("stored-draggable-layouts", "data"),
        Input(
            {"type": "remove-box-button", "index": ALL},
            "n_clicks",
        ),
        Input(
            {
                "type": "edit-box-button",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {
                "type": "tmp-edit-component-metadata",
                "index": ALL,
            },
            "data",
        ),
        Input(
            {
                "type": "duplicate-box-button",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {
                "type": "reset-selection-graph-button",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input("remove-all-components-button", "n_clicks"),
        State("toggle-interactivity-button", "checked"),
        State("edit-dashboard-mode-button", "checked"),
        Input("edit-dashboard-mode-button", "checked"),
        State("edit-components-mode-button", "checked"),
        Input("edit-components-mode-button", "checked"),
        State("url", "pathname"),
        State("local-store", "data"),
        # Input("height-store", "data"),
        prevent_initial_call=True,
    )
    def populate_draggable(
        btn_done_clicks,
        btn_done_edit_clicks,
        interactive_component_ids,
        interactive_component_values,
        graph_selected_data,
        graph_click_data,
        graph_relayout_data,
        graph_ids,
        stored_add_button,
        stored_metadata,
        test_container,
        draggable_children,
        draggable_layouts,
        input_draggable_layouts,
        state_stored_draggable_children,
        state_stored_draggable_layouts,
        input_stored_draggable_children,
        input_stored_draggable_layouts,
        remove_box_button_values,
        edit_box_button_values,
        tmp_edit_component_metadata_values,
        duplicate_box_button_values,
        reset_selection_graph_button_values,
        remove_all_components_button,
        toggle_interactivity_button,
        edit_dashboard_mode_button,
        input_edit_dashboard_mode_button,
        edit_components_mode_button,
        input_edit_components_mode_button,
        pathname,
        local_data,
        # height_store,
    ):
        if not local_data:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not state_stored_draggable_layouts:
            state_stored_draggable_layouts = {}
        if not state_stored_draggable_children:
            state_stored_draggable_children = {}

        TOKEN = local_data["access_token"]

        # logger.info("btn_done_clicks: {}".format(btn_done_clicks))
        # logger.info("stored_add_button: {}".format(stored_add_button))

        ctx = dash.callback_context

        # logger.info("CTX: {}".format(ctx))
        # logger.info("CTX triggered: {}".format(ctx.triggered))
        # logger.info("CTX triggered_id: {}".format(ctx.triggered_id))
        # logger.info("TYPE CTX triggered_id: {}".format(type(ctx.triggered_id)))
        # logger.info("CTX triggered_props_id: {}".format(ctx.triggered_prop_ids))
        # logger.info("CTX args_grouping: {}".format(ctx.args_grouping))
        # logger.info("CTX inputs: {}".format(ctx.inputs))
        # logger.info("CTX inputs_list: {}".format(ctx.inputs_list))
        # logger.debug("CTX states: {}".format(ctx.states))
        # logger.debug("CTX states_list: {}".format(ctx.states_list))

        if isinstance(ctx.triggered_id, dict):
            triggered_input = ctx.triggered_id["type"]
            triggered_input_dict = ctx.triggered_id
        elif isinstance(ctx.triggered_id, str):
            triggered_input = ctx.triggered_id
            triggered_input_dict = None

        else:
            triggered_input = None
            triggered_input_dict = None

        # logger.info("triggered_input : {}".format(triggered_input))
        # logger.info("type of triggered_input: {}".format(type(triggered_input)))

        # logger.info(f"toggle_interactivity_button: {toggle_interactivity_button}")

        # Check if the value of the interactive component is not None
        check_value = False
        # remove duplicate of stored_metadata based on index
        index_list = []

        # FIXME: Remove duplicates from stored_metadata
        # Remove duplicates from stored_metadata
        # logger.info("Stored metadata: {}".format(stored_metadata))
        # logger.info(f"Length of stored metadata: {len(stored_metadata)}")
        stored_metadata = remove_duplicates_by_index(stored_metadata)
        # logger.info("CLEANED Stored metadata: {}".format(stored_metadata))
        # logger.info(f"Length of cleaned stored metadata: {len(stored_metadata)}")
        # logger.info(f"URL PATHNAME: {pathname}")
        dashboard_id = pathname.split("/")[-1]
        stored_metadata_interactive = [e for e in stored_metadata if e["component_type"] == "interactive"]

        # logger.info("Interactive component values: {}".format(interactive_component_values))
        # logger.info("Interactive component ids: {}".format(interactive_component_ids))
        # logger.info("Stored metadata interactive: {}".format(stored_metadata_interactive))

        interactive_components_dict = {
            id["index"]: {"value": value, "metadata": metadata}
            for (id, value, metadata) in zip(
                interactive_component_ids,
                interactive_component_values,
                stored_metadata_interactive,
            )
        }
        # logger.info(f"Interactive components dict: {interactive_components_dict}")

        if triggered_input:
            if "graph" in triggered_input:
                ctx_triggered = ctx.triggered
                ctx_triggered = ctx_triggered[0]
                ctx_triggered_prop_id = ctx_triggered["prop_id"]
                logger.info(f"triggered_input: {triggered_input}")
                logger.info(f"CTX triggered: {ctx_triggered}")
                logger.info(f"CTX triggered type : {type(ctx_triggered)}")
                logger.info(f"CTX triggered prop_id: {ctx_triggered_prop_id}")
                ctx_triggered_prop_id_index = eval(ctx_triggered_prop_id.split(".")[0])["index"]
                logger.info(f"CTX triggered prop_id index: {ctx_triggered_prop_id_index}")
                tests__ = ["selectedData" in ctx_triggered_prop_id, "clickData" in ctx_triggered_prop_id, "relayoutData" in ctx_triggered_prop_id]
                tests__ = ["clickData" in ctx_triggered_prop_id]

                logger.info(f"{tests__}")
                if any(tests__):
                    logger.info(f"Graph triggered input: {triggered_input}")
                    logger.info(f"Graph click data: {graph_click_data}")
                    logger.info(f"Graph ids: {graph_ids}")
                    logger.info(f"Interactive components dict: {interactive_components_dict}")

                    clickData = graph_click_data[0]

                    if clickData and "points" in clickData and len(clickData["points"]) > 0:
                        # Extract the first clicked point
                        clicked_point = clickData["points"][0]
                        logger.info(f"Clicked point data: {clicked_point}")

                        # Construct dict_graph_data as per the process_click_data function
                        dict_graph_data = {"value": clicked_point, "metadata": [e for e in stored_metadata if e["index"] == ctx_triggered_prop_id_index][0]}

                        # Update interactive_components_dict using the process_click_data function
                        updated_interactive_components = process_click_data(dict_graph_data, interactive_components_dict, TOKEN)

                        # Prepare selected_point data to store
                        selected_point = {"x": clicked_point.get("x"), "y": clicked_point.get("y"), "text": clicked_point.get("text", "")}

                        logger.info(f"Selected point: {selected_point}")

                        logger.info(f"Updated interactive components: {updated_interactive_components}")

                        for metadata in stored_metadata:
                            if metadata["index"] == ctx_triggered_prop_id_index:
                                metadata["filter_applied"] = True
                        logger.info(f"TMP Stored metadata: {stored_metadata}")

                        new_children = update_interactive_component(
                            stored_metadata, updated_interactive_components, draggable_children, switch_state=edit_components_mode_button, TOKEN=TOKEN, dashboard_id=dashboard_id
                        )
                        # state_stored_draggable_children[dashboard_id] = new_children

                        return new_children, dash.no_update, dash.no_update, dash.no_update, dash.no_update

                elif "selectedData" in ctx_triggered_prop_id:
                    selectedData = graph_selected_data[0]
                    logger.info(f"Selected data: {selectedData}")
    
                    if selectedData and "points" in selectedData and len(selectedData["points"]) > 0:
                        selected_points = selectedData["points"]
                        logger.info(f"Selected points data: {selected_points}")
    
                        # Construct dict_graph_data for multiple points
                        dict_graph_data = {
                            "value": selected_points,
                            "metadata": next(
                                (e for e in stored_metadata if e["index"] == ctx_triggered_prop_id_index), 
                                None
                            )
                        }
    
                        if dict_graph_data["metadata"] is None:
                            logger.error("Metadata not found for the triggered graph.")
                            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
                        # Update interactive_components_dict using the process_selected_data function
                        updated_interactive_components = process_selected_data(dict_graph_data, interactive_components_dict, TOKEN)
    
                        logger.info(f"Updated interactive components: {updated_interactive_components}")
    

                        for metadata in stored_metadata:
                            if metadata["index"] == ctx_triggered_prop_id_index:
                                metadata["filter_applied"] = True

                        new_children = update_interactive_component(
                            stored_metadata, 
                            updated_interactive_components, 
                            draggable_children, 
                            switch_state=edit_components_mode_button, 
                            TOKEN=TOKEN, 
                            dashboard_id=dashboard_id
                        )

                        logger.info(f"New children len : {len(new_children)}")
                        # state_stored_draggable_children[dashboard_id] = new_children
    
                        return new_children, dash.no_update, dash.no_update, dash.no_update, dash.no_update
                    elif "relayoutData" in ctx_triggered_prop_id:
                        return draggable_children, dash.no_update, dash.no_update, dash.no_update, dash.no_update
                    else:
                        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
                elif "relayoutData" in ctx_triggered_prop_id:
                    logger.info(f"Relayout data: {graph_relayout_data}")
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

                elif "reset-selection-graph-button" in triggered_input:
                    logger.info(f"Reset selection graph triggered input: {triggered_input}")

                    logger.info("Interactive component triggered")
                    logger.info("Interactive component values: {}".format(interactive_component_values))

                    for metadata in stored_metadata:
                        if metadata["index"] == ctx_triggered_prop_id_index:
                            metadata["filter_applied"] = False
                    logger.info(f"TMP Stored metadata: {stored_metadata}")

                    new_children = update_interactive_component(
                        stored_metadata, interactive_components_dict, draggable_children, switch_state=edit_components_mode_button, TOKEN=TOKEN, dashboard_id=dashboard_id
                    )
                    # state_stored_draggable_children[dashboard_id] = new_children

                    return new_children, dash.no_update, dash.no_update, dash.no_update, dash.no_update
                    # return new_childr

                    # return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
                else:
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
            # else:
            #     logger.info(f"Triggered input: {triggered_input}")
            #     logger.info(f"Triggered input dict: {triggered_input_dict}")
            #     return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

            if triggered_input == "interactive-component":
                if interactive_components_dict:
                    logger.info(f"Interactive component triggered input: {triggered_input}")
                    logger.info(f"Interactive components dict: {interactive_components_dict}")
                    triggered_input_eval_index = int(triggered_input_dict["index"])
                    logger.info(f"Triggered input eval index: {triggered_input_eval_index}")
                    if triggered_input_eval_index in interactive_components_dict:
                        value = interactive_components_dict[triggered_input_eval_index]["value"]
                        logger.info(f"Value: {value}")
                        # Handle the case of the TextInput component
                        if interactive_components_dict[triggered_input_eval_index]["metadata"]["interactive_component_type"] != "TextInput":
                            check_value = True if value is not None else False
                        else:
                            check_value = True if value is not "" else False
                        logger.info(f"Check value: {check_value}")

            # # if triggered_input["type"] == "btn-done":
            if triggered_input == "btn-done":
                # if btn_done_clicks:
                #     if btn_done_clicks[-1] > 0:
                logger.info("\n\n")
                logger.info("Populate draggable")

                logger.info("stored_metadata: {}".format(stored_metadata))
                # logger.info("stored_children: {}".format(test_container))
                # logger.info("draggable_children: {}".format(draggable_children))
                logger.info("draggable_layouts: {}".format(draggable_layouts))

                existing_ids = {str(child["props"]["id"]) for child in draggable_children}
                n = len(draggable_children)

                logger.info(f"Existing ids: {existing_ids}")
                logger.info(f"n: {n}")

                # Ensure all necessary breakpoints are initialized
                for bp in required_breakpoints:
                    if bp not in draggable_layouts:
                        draggable_layouts[bp] = []

                for child in test_container:
                    # logger.info(f"Child: {child}")
                    child_index = str(child["props"]["id"]["index"])

                    child_type = child["props"]["id"]["type"]

                    logger.info(f"Child type: {child_type}")

                    if child_type == "interactive-component":
                        logger.info(f"Interactive component found: {child}")
                        # WARNING: This is a temporary fix to remove the '-tmp' suffix from the id
                        if child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"].endswith("-tmp"):
                            child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"] = child["props"]["children"]["props"]["children"][
                                "props"
                            ]["children"][1]["props"]["id"]["type"].replace("-tmp", "")

                    logger.info(f"Child index: {child_index}")
                    logger.info(f"Child type: {child_type}")
                    # child types: card-component (w:3,h:4), interactive-component (w:6,h:6), graph-component (w:9,h:8)
                    if child_index not in existing_ids:
                        child = enable_box_edit_mode(child, edit_components_mode_button, dashboard_id=dashboard_id, fresh=False, TOKEN=TOKEN)
                        draggable_children.append(child)
                        child_id = f"box-{str(child_index)}"

                        # Calculate layout item position and size based on type
                        new_layout_item = calculate_new_layout_position(child_type, draggable_layouts, child_id, n)

                        # Update necessary breakpoints, this example only updates 'lg' for simplicity
                        # draggable_layouts["lg"].append(new_layout_item)

                        # new_layout_item = {
                        #     "i": child_id,
                        #     "x": 10 * (n % 2),
                        #     "y": n * 10,
                        #     "w": 6,
                        #     "h": 5,
                        # }

                        for key in required_breakpoints:
                            draggable_layouts[key].append(new_layout_item)
                        n += 1

                # logger.info(f"Updated draggable children: {draggable_children}")
                logger.info(f"Updated draggable layouts: {draggable_layouts}")
                state_stored_draggable_children[dashboard_id] = draggable_children
                state_stored_draggable_layouts[dashboard_id] = draggable_layouts
                return draggable_children, draggable_layouts, dash.no_update, state_stored_draggable_layouts, dash.no_update
                # return draggable_children, draggable_layouts, state_stored_draggable_children, state_stored_draggable_layouts
            #     else:
            #         return dash.no_update, dash.no_update, dash.no_update, dash.no_update
            # # elif triggered_input == "draggable":
            # #     return draggable_children, draggable_layouts

            elif triggered_input == "draggable":
                ctx_triggered_props_id = ctx.triggered_prop_ids
                if "draggable.layouts" in ctx_triggered_props_id:
                    new_layouts = input_draggable_layouts
                    # logger.info(f"state_stored_draggable_layouts: {state_stored_draggable_layouts}")
                    # logger.info(f"state_stored_draggable_children: {state_stored_draggable_children}")
                    logger.info(f"dashboard_id: {dashboard_id}")
                    state_stored_draggable_children[dashboard_id] = draggable_children
                    state_stored_draggable_layouts[dashboard_id] = new_layouts

                    return draggable_children, new_layouts, dash.no_update, state_stored_draggable_layouts, dash.no_update
                    # return draggable_children, new_layouts, state_stored_draggable_children, state_stored_draggable_layouts
                else:
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

            elif "interactive-component" in triggered_input and toggle_interactivity_button:
                logger.info("Interactive component triggered")
                logger.info("Interactive component values: {}".format(interactive_component_values))

                new_children = update_interactive_component(
                    stored_metadata, interactive_components_dict, draggable_children, switch_state=edit_components_mode_button, TOKEN=TOKEN, dashboard_id=dashboard_id
                )
                state_stored_draggable_children[dashboard_id] = new_children

                return new_children, dash.no_update, dash.no_update, dash.no_update, dash.no_update
                # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

            elif "edit-components-mode-button" in triggered_input:
                logger.info(f"Edit components mode button triggered: {edit_components_mode_button}")
                new_children = list()
                # logger.info("Current draggable children: {}".format(draggable_children))
                logger.info("Len Current draggable children: {}".format(len(draggable_children)))
                for child in draggable_children:
                    logger.info("Child: {}".format(child))
                    logger.info("Child props: {}".format(child["props"]))
                    logger.info("Child props children: {}".format(child["props"]["children"]))
                    if type(child["props"]["children"]) is dict:
                        child = enable_box_edit_mode(child["props"]["children"]["props"]["children"][-1], edit_components_mode_button)
                    elif type(child["props"]["children"]) is list:
                        child = enable_box_edit_mode(child["props"]["children"][-1], edit_components_mode_button)
                    new_children.append(child)
                    state_stored_draggable_children[dashboard_id] = new_children

                return new_children, dash.no_update, dash.no_update, dash.no_update, dash.no_update
                # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

            # elif triggered_input == "height-store":
            #     if not height_store:
            #         return draggable_layouts

            #     # Copy the existing layout to modify
            #     new_layouts = draggable_layouts.copy()

            #     # Iterate over each breakpoint (e.g., 'default', 'lg', etc.)
            #     for breakpoint in new_layouts:
            #         for item in new_layouts[breakpoint]:
            #             item_id = item['i']
            #             if item_id in height_store:
            #                 # Convert pixel height to grid units
            #                 row_height = 30  # Must match the rowHeight prop
            #                 new_h = max(1, height_store[item_id] // row_height)
            #                 item['h'] = new_h

            #     return draggable_children, new_layouts, dash.no_update, new_layouts

            elif triggered_input == "stored-draggable-layouts":
                logger.info("Stored draggable layouts triggered")
                logger.info("Input draggable layouts: {}".format(input_draggable_layouts))
                logger.info("State stored draggable layouts: {}".format(state_stored_draggable_layouts))

                if state_stored_draggable_layouts:
                    if dashboard_id in state_stored_draggable_layouts:
                        children = render_dashboard(stored_metadata, edit_components_mode_button, dashboard_id, TOKEN)

                        return children, state_stored_draggable_layouts[dashboard_id], dash.no_update, state_stored_draggable_layouts, dash.no_update
                    else:
                        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

                else:
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

            elif triggered_input == "remove-box-button":
                logger.info("Remove box button clicked")
                input_id = ctx.triggered_id["index"]
                logger.info("Input ID: {}".format(input_id))

                # Use list comprehension to filter
                # logger.info("Current draggable children: {}".format(draggable_children))
                updated_children = [child for child in draggable_children if child["props"]["id"] != f"box-{input_id}"]

                # state_stored_draggable_children[dashboard_id] = updated_children
                state_stored_draggable_layouts[dashboard_id] = draggable_layouts

                # logger.info("Updated draggable children: {}".format(updated_children))

                return updated_children, draggable_layouts, dash.no_update, state_stored_draggable_layouts, dash.no_update
                # return updated_children, draggable_layouts, state_stored_draggable_children, state_stored_draggable_layouts

            elif triggered_input == "edit-box-button":
                logger.warning("Edit box button clicked")

                input_id = ctx.triggered_id["index"]
                logger.info("Input ID: {}".format(input_id))

                component_data = get_component_data(input_id=input_id, dashboard_id=dashboard_id, TOKEN=TOKEN)
                logger.info(f"Component data: {component_data}")

                if component_data:
                    component_data["parent_index"] = input_id
                else:
                    component_data = {"parent_index": input_id}

                logger.info(f"Component data: {component_data}")

                # Create the modal for editing
                new_id = generate_unique_index()
                logger.info(f"New ID: {new_id}")
                edited_modal = edit_component(new_id, parent_id=input_id, active=1, component_data=component_data, TOKEN=TOKEN)
                logger.info(f"Edited modal: {edited_modal}")
                # edited_modal = edit_component(str(input_id), active=1, component_data=component_data, TOKEN=TOKEN)

                updated_children = []
                # logger.info(f"Draggable children: {draggable_children}")
                for child in draggable_children:
                    logger.info(f"Child props id: {child['props']['id']}")
                    if child["props"]["id"] == f"box-{input_id}":
                        logger.info("Found child to edit")
                        # Ensure that children is a list. If not, convert it to a list.
                        # existing_children = child["props"]["children"]
                        # if not isinstance(existing_children, list):
                        #     existing_children = [existing_children]
                        # # Append the modal to the existing children
                        # child["props"]["children"] = existing_children + [edited_modal]
                        child["props"]["children"] = edited_modal

                        # child["props"]["id"] = f"box-{input_id}-tmp"
                    updated_children.append(child)

                return updated_children, draggable_layouts, dash.no_update, dash.no_update, input_id

            elif triggered_input == "btn-done-edit":
                index = ctx.triggered_id["index"]

                edited_child = None
                parent_index = None

                for metadata in stored_metadata:
                    if str(metadata["index"]) == str(index):
                        logger.info(f"Metadata found: {metadata}")
                        parent_index = metadata["parent_index"]
                        logger.info(f"Parent index: {parent_index}")

                for child, metadata in zip(test_container, stored_metadata):
                    child_index = str(child["props"]["id"]["index"])

                    if str(child_index) == str(index):
                        child_type = child["props"]["id"]["type"]

                        logger.info(f"Child type: {child_type}")

                        if child_type == "interactive-component":
                            logger.info(f"Interactive component found: {child}")
                            # WARNING: This is a temporary fix to remove the '-tmp' suffix from the id
                            if child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"].endswith("-tmp"):
                                child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"] = child["props"]["children"]["props"]["children"][
                                    "props"
                                ]["children"][1]["props"]["id"]["type"].replace("-tmp", "")

                        edited_child = enable_box_edit_mode(child, edit_components_mode_button, dashboard_id=dashboard_id, fresh=False, TOKEN=TOKEN)

                        # logger.info(f"Edited child: {edited_child}")
                if parent_index:
                    updated_children = list()
                    for child in draggable_children:
                        if child["props"]["id"] == f"box-{parent_index}":
                            # logger.info("Found child to edit")
                            updated_children.append(edited_child)  # Replace the entire child
                        else:
                            updated_children.append(child)
                        # logger.info(f"AFTER UPDATE - child id: {child['props']['id']}")

                    for bp in required_breakpoints:
                        for layout in draggable_layouts[bp]:
                            if layout["i"] == f"box-{parent_index}":
                                layout["i"] = f"box-{index}"
                                break

                    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}", headers={"Authorization": f"Bearer {TOKEN}"})
                    if response.status_code == 200:
                        dashboard_data = response.json()
                        logger.info(f"AFTER UPDATE - Dashboard data: {dashboard_data}")
                        # dashboard_data["components"] = updated_children
                        # response = httpx.put(f"{API_BASE_URL}/depictio/api/v1/dashboards/update/{dashboard_id}", headers={"Authorization": f"Bearer {TOKEN}"}, json=dashboard_data)
                        # if response.status_code == 200:
                        #     logger.info(f"Dashboard updated successfully: {response.json()}")
                        # else:
                        #     logger.error(f"Error updating dashboard: {response.json()}")

                    logger.info(f"Edited component with new id 'box-{index}' and assigned layout {layout}")

                    # state_stored_draggable_children[dashboard_id] = updated_children
                    state_stored_draggable_layouts[dashboard_id] = draggable_layouts

                else:
                    updated_children = draggable_children

                return updated_children, draggable_layouts, dash.no_update, state_stored_draggable_layouts, ""

            elif triggered_input == "duplicate-box-button":
                triggered_index = ctx.triggered_id["index"]

                logger.info(f"Duplicating component with index: {triggered_index}")
                # Duplicate the component
                component_to_duplicate = None
                for child in draggable_children:
                    if child["props"]["id"] == f"box-{triggered_index}":
                        component_to_duplicate = child
                        break

                if component_to_duplicate is None:
                    logger.error(f"No component found with id 'box-{triggered_index}' to duplicate.")
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

                # Generate a new unique ID for the duplicated component
                new_index = generate_unique_index()
                # new_index = "200"
                child_id = f"box-{new_index}"

                # Create a deep copy of the component to duplicate
                duplicated_component = copy.deepcopy(component_to_duplicate)

                # Update the duplicated component's ID to the new ID
                duplicated_component["props"]["id"] = child_id

                # extract the metadata from the parent component
                metadata = None
                for metadata_child in stored_metadata:
                    if metadata_child["index"] == triggered_index:
                        metadata = metadata_child
                        logger.info(f"Metadata found: {metadata}")
                        break
                metadata["index"] = new_index
                new_store = dcc.Store(id={"type": "stored-metadata-component", "index": new_index}, data=metadata)
                logger.info(f"New store: {new_store}")
                logger.info(f"duplicated_component: {duplicated_component}")
                logger.info(f"duplicated_component children: {duplicated_component['props']['children']}")
                logger.info(f"duplicated_component children children: {duplicated_component['props']['children']['props']['children']}")
                if type(duplicated_component["props"]["children"]["props"]["children"]) == list:
                    duplicated_component["props"]["children"]["props"]["children"] += [new_store]
                elif type(duplicated_component["props"]["children"]["props"]["children"]) == dict:
                    duplicated_component["props"]["children"]["props"]["children"]["props"]["children"] += [new_store]

                update_nested_ids(duplicated_component, triggered_index, new_index)

                # Append the duplicated component to the updated children
                updated_children = list(draggable_children)
                updated_children.append(duplicated_component)

                # Calculate the new layout position
                # 'child_type' corresponds to the 'type' in the component's ID
                existing_layouts = draggable_layouts  # Current layouts before adding the new one
                n = len(updated_children)  # Position based on the number of components

                new_layout = calculate_new_layout_position("", existing_layouts, child_id, n)

                for key in required_breakpoints:
                    draggable_layouts[key].append(new_layout)

                logger.info(f"Duplicated component with new id 'box-{new_index}' and assigned layout {new_layout}")

                # state_stored_draggable_children[dashboard_id] = updated_children
                state_stored_draggable_layouts[dashboard_id] = draggable_layouts

                return updated_children, draggable_layouts, dash.no_update, state_stored_draggable_layouts, dash.no_update

            elif triggered_input == "remove-all-components-button":
                logger.info("Remove all components button clicked")
                state_stored_draggable_layouts[dashboard_id] = {}
                return [], {}, dash.no_update, state_stored_draggable_layouts, dash.no_update
                # return [], {}, {}, {}

        else:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # @app.callback(
    #     Output({"type": "last-button", "index": MATCH}, "data", allow_duplicate=True),
    #     Input({"type": "edit-box-button", "index": MATCH}, "n_clicks"),
    #     State({"type": "last-button", "index": MATCH}, "data"),
    #     prevent_initial_call=True,
    # )
    # def update_last_button_using_edit_box_button_value(edit_button_nclicks, last_button):
    #     logger.info(f"Edit button id: {edit_button_nclicks}")
    #     logger.info(f"Last button: {last_button}")
    #     return "Figure"

    # Callback to handle Add Button clicks
    @app.callback(
        Output("test-output", "children"),
        Output("stored-add-button", "data"),
        Output("initialized-add-button", "data"),
        # Output("initialized-edit-button", "data"),
        Input("add-button", "n_clicks"),
        # Input({"type": "edit-box-button", "index": ALL}, "n_clicks"),
        State("stored-add-button", "data"),
        State("initialized-add-button", "data"),
        # State("initialized-edit-button", "data"),
        prevent_initial_call=True,
    )
    def trigger_modal(
        add_button_nclicks,
        #   edit_button_nclicks,
        stored_add_button,
        initialized_add_button,
        # initialized_edit_button,
    ):
        logger.info("\n\nTrigger modal")
        logger.info(f"n_clicks: {add_button_nclicks}")
        logger.info(f"stored_add_button: {stored_add_button}")
        logger.info(f"initialized_add_button: {initialized_add_button}")
        # logger.info(f"edit_button_nclicks: {edit_button_nclicks}")
        # logger.info(f"initialized_edit_button: {initialized_edit_button}")

        from dash import ctx

        if not initialized_add_button:
            logger.info("Initializing add button")
            return dash.no_update, dash.no_update, True
            # return dash.no_update, dash.no_update, True, dash.no_update

        # if not initialized_edit_button:
        #     logger.info("Initializing edit button")
        #     return dash.no_update, dash.no_update, dash.no_update, True

        if add_button_nclicks is None:
            logger.info("No clicks detected")
            # return dash.no_update, dash.no_update, True, dash.no_update
            return dash.no_update, dash.no_update, True

        # if edit_button_nclicks is None:
        #     logger.info("No clicks detected")
        #     return dash.no_update, dash.no_update, dash.no_update, True

        triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"triggered_input: {triggered_input}")

        if triggered_input == "add-button":
            # Update the stored add button count
            logger.info(f"Updated stored_add_button: {stored_add_button}")
            # index = stored_add_button["count"]
            index = generate_unique_index()
            stored_add_button["id"] = index
            # stored_add_button["count"] += 1

            current_draggable_children = add_new_component(str(index))

            return current_draggable_children, stored_add_button, True
            # return current_draggable_children, stored_add_button, True, dash.no_update

        # elif "edit-box-button" in triggered_input:
        #     # Generate and return the new component
        #     index = str(eval(triggered_input)["index"])
        #     logger.info(f"Edit button clicked for index: {index}")
        #     current_draggable_children = edit_component(str(index), active=0)

        #     return current_draggable_children, stored_add_button, dash.no_update, True
        else:
            logger.warning(f"Unexpected triggered_input: {triggered_input}")
            return dash.no_update, dash.no_update, True, True

    @app.callback(
        Output("interactive-values-store", "data"),
        Input({"type": "interactive-component-value", "index": ALL}, "value"),
        State({"type": "interactive-component-value", "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def update_interactive_values_store(interactive_values, ids, stored_metadata, pathname):
        # logger.info("Callback 'update_interactive_values_store' triggered.")
        # logger.info(f"Interactive values: {interactive_values}")
        # logger.info(f"Interactive ids: {ids}")
        # logger.info(f"Stored metadata: {stored_metadata}")
        stored_metadata_interactive = [e for e in stored_metadata if e["component_type"] == "interactive"]
        # logger.info(f"Stored metadata interactive: {stored_metadata_interactive}")

        # Extract dashboard_id from the URL pathname
        try:
            dashboard_id = pathname.split("/")[-1]
            logger.debug(f"Dashboard ID: {dashboard_id}")
        except Exception as e:
            logger.error(f"Error extracting dashboard_id from pathname '{pathname}': {e}")
            raise dash.exceptions.PreventUpdate

        # Ensure that the lengths of interactive_values, ids, and stored_metadata match
        if not (len(interactive_values) == len(ids) == len(stored_metadata_interactive)):
            logger.error("Mismatch in lengths of interactive_values, ids, and stored_metadata.")
            raise dash.exceptions.PreventUpdate

        # Combine interactive_values with their corresponding metadata
        components = []
        for value, metadata in zip(interactive_values, stored_metadata_interactive):
            if metadata is None:
                logger.warning(f"Metadata is None for a component with value: {value}")
                continue
            components.append({"value": value, "metadata": metadata, "index": metadata["index"]})

        output_data = {"interactive_components_values": components}

        # logger.info(f"Output data: {output_data}")
        return output_data


def design_draggable(data, init_layout, init_children, local_data):
    # Generate core layout based on data availability

    TOKEN = local_data["access_token"]

    workflows = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    logger.info("Code: %s", workflows.status_code)

    workflows = workflows.json()

    logger.info(f"workflows {workflows}")

    if not workflows:
        # When there are no workflows, log information and prepare a message
        # logger.info(f"init_children {init_children}")
        logger.info(f"init_layout {init_layout}")
        # message = html.Div(["No workflows available."])
        message = html.Div(
            [
                html.Hr(),
                dmc.Center(
                    dmc.Group(
                        [
                            DashIconify(icon="feather:info", color="red", width=40),
                            dmc.Text(
                                "No data available.",
                                variant="gradient",
                                gradient={"from": "red", "to": "orange", "deg": 45},
                                style={"fontSize": 30, "textAlign": "center"},
                            ),
                        ]
                    )
                ),
                dmc.Text(
                    "Please first register workflows and data using Depictio CLI.",
                    variant="gradient",
                    gradient={"from": "red", "to": "orange", "deg": 45},
                    style={"fontSize": 25, "textAlign": "center"},
                ),
            ]
        )
        display_style = "none"  # Hide the draggable layout
        core_children = [message]
    else:
        display_style = "flex"  # Show the draggable layout
        core_children = []

    # Create the draggable layout outside of the if-else to keep it in the DOM
    draggable = dash_draggable.ResponsiveGridLayout(
        id="draggable",
        clearSavedLayout=True,
        layouts=init_layout,
        children=init_children,
        isDraggable=True,
        isResizable=True,
        # autoSize=True,
        # verticalCompact=True,  # Compacts items vertically to eliminate gaps
        # preventCollision=True,  # Prevents collisions between items
        # isDroppable=True,
        style={
            "display": display_style,
            "flex-grow": 1,
            "width": "100%",
            "height": "auto",
            # "height": "100%",
            # "overflowY": "auto",
        },
    )

    # Add draggable to the core children list whether it's visible or not
    core_children.append(draggable)

    # The core Div contains all elements, managing visibility as needed
    core = html.Div(core_children)

    return core
