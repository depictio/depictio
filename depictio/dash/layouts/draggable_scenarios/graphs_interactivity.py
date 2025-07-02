import uuid

import dash

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.draggable_scenarios.interactive_component_update import (
    update_interactive_component,
)
from depictio.dash.utils import get_columns_from_data_collection


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
    # columns_description = metadata.get("dc_config", {}).get("columns_description", {})

    cols_json = get_columns_from_data_collection(
        metadata.get("wf_id"), metadata.get("dc_id"), TOKEN
    )
    logger.info(f"Columns JSON: {cols_json}")

    # Get column types; default to 'object' (categorical) if not specified
    x_col_type = cols_json.get(x_column, {}).get("type", "object")
    y_col_type = cols_json.get(y_column, {}).get("type", "object")

    logger.info(f"Column types: {x_column}={x_col_type}, {y_column}={y_col_type}")

    # Initialize a dictionary to hold new filter entries
    new_filters = {}

    # Function to generate unique keys for new filters
    def generate_filter_key(column_name, component_id):
        return f"filter_{column_name}_{component_id}"

    # Process x_value
    if x_value is not None and x_column:
        if x_col_type in ["int64", "float64"]:
            # Numerical column, use Slider for exact match
            new_key = generate_filter_key(x_column, metadata["index"])
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
            new_key = generate_filter_key(x_column, metadata["index"])
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
            new_key = generate_filter_key(y_column, metadata["index"])
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
            new_key = generate_filter_key(y_column, metadata["index"])
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

    for k, v in interactive_components_dict.items():
        logger.info(f"Interactive components dict: {k} - {v}")
        v["component_type"] = "interactive"

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
    # columns_description = metadata.get("dc_config", {}).get("columns_description", {})

    # Fetch column types from data collection (assuming helper functions exist)
    cols_json = get_columns_from_data_collection(
        metadata.get("wf_id"), metadata.get("dc_id"), TOKEN
    )
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


def refresh_children_based_on_click_data(
    graph_click_data,
    graph_ids,
    ctx_triggered_prop_id_index,
    stored_metadata,
    interactive_components_dict,
    draggable_children,
    edit_components_mode_button,
    TOKEN,
    dashboard_id,
    theme="light",
):
    logger.info(f"Graph click data: {graph_click_data}")
    logger.info(f"Graph ids: {graph_ids}")
    logger.info(f"Interactive components dict: {interactive_components_dict}")

    # Iterate and find the clickData for the triggered graph
    clickData = [
        e
        for e, id in zip(graph_click_data, graph_ids)
        if id["index"] == ctx_triggered_prop_id_index
    ][0]

    logger.info(f"len(graph_click_data): {len(graph_click_data)}")
    logger.info(f"len(graph_ids): {len(graph_ids)}")
    for e, id in zip(graph_click_data, graph_ids):
        logger.info(f"Graph click data - {id['index']}: {e}")
        if e:
            if "points" in e:
                logger.info(f"id['index']: {id['index']}")
                logger.info(f"ctx_triggered_prop_id_index: {ctx_triggered_prop_id_index}")
                if id["index"] == ctx_triggered_prop_id_index:
                    logger.info(f"BINGO - Graph click data - {id['index']}: {e}")
                    clickData = e
                    break

    logger.info(f"Click data: {clickData}")
    logger.info(f"Click data type: {type(clickData)}")
    logger.info(f"len(clickData['points']): {len(clickData['points'])}")
    logger.info(f"Click data points check: {'points' in clickData}")

    # Check if clickData is not None and contains points
    if clickData and "points" in clickData and len(clickData["points"]) > 0:
        # Extract the first clicked point
        logger.info(f"Clicked data: {clickData}")
        clicked_point = clickData["points"][0]
        logger.info(f"Clicked point data: {clicked_point}")

        # Construct dict_graph_data as per the process_click_data function
        dict_graph_data = {
            "value": clicked_point,
            "metadata": [e for e in stored_metadata if e["index"] == ctx_triggered_prop_id_index][
                0
            ],
        }

        # Update interactive_components_dict using the process_click_data function
        updated_interactive_components = process_click_data(
            dict_graph_data, interactive_components_dict, TOKEN
        )

        # Prepare selected_point data to store
        selected_point = {
            "x": clicked_point.get("x"),
            "y": clicked_point.get("y"),
            "text": clicked_point.get("text", ""),
        }

        logger.info(f"Selected point: {selected_point}")

        logger.info(f"Updated interactive components: {updated_interactive_components}")

        for metadata in stored_metadata:
            if metadata["index"] == ctx_triggered_prop_id_index:
                metadata["filter_applied"] = True
        logger.info(f"TMP Stored metadata: {stored_metadata}")

        new_children = update_interactive_component(
            stored_metadata,
            updated_interactive_components,
            draggable_children,
            switch_state=edit_components_mode_button,
            TOKEN=TOKEN,
            dashboard_id=dashboard_id,
            theme=theme,
        )
        # state_stored_draggable_children[dashboard_id] = new_children

        return new_children


def refresh_children_based_on_selected_data(
    graph_selected_data,
    graph_ids,
    ctx_triggered_prop_id_index,
    stored_metadata,
    interactive_components_dict,
    draggable_children,
    edit_components_mode_button,
    TOKEN,
    dashboard_id,
    theme="light",
):
    selectedData = [
        e
        for e, id in zip(graph_selected_data, graph_ids)
        if id["index"] == ctx_triggered_prop_id_index
    ][0]
    logger.info(f"Selected data: {selectedData}")
    new_children = list()
    if selectedData and "points" in selectedData and len(selectedData["points"]) > 0:
        selected_points = selectedData["points"]
        logger.info(f"Selected points data: {selected_points}")

        # Construct dict_graph_data for multiple points
        dict_graph_data = {
            "value": selected_points,
            "metadata": next(
                (e for e in stored_metadata if e["index"] == ctx_triggered_prop_id_index),
                None,
            ),
        }
        logger.info(f"Dict graph data: {dict_graph_data}")

        if dict_graph_data["metadata"] is None:
            logger.error("Metadata not found for the triggered graph.")
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Update interactive_components_dict using the process_selected_data function
        updated_interactive_components = process_selected_data(
            dict_graph_data, interactive_components_dict, TOKEN
        )

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
            dashboard_id=dashboard_id,
            theme=theme,
        )

        logger.info(f"New children len : {len(new_children)}")
        # state_stored_draggable_children[dashboard_id] = new_children
    return new_children
