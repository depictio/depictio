"""
Graph interactivity handlers for Plotly click and selection data.

This module processes click and selection events from Plotly graphs and
translates them into filter updates for interactive components. It supports
both single-click filtering and multi-point selection (lasso/box select).

Key Functions:
    process_click_data: Process single point click data into filters
    process_selected_data: Process multiple selected points into filters
    refresh_children_based_on_click_data: Handle click events on graphs
    refresh_children_based_on_selected_data: Handle selection events on graphs
"""

import uuid

import dash

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.layouts.draggable_scenarios.interactive_component_update import (
    update_interactive_component_sync,
)
from depictio.dash.utils import get_columns_from_data_collection

# Numerical column types that use Slider/RangeSlider filters
NUMERICAL_COLUMN_TYPES = {"int64", "float64"}


def _create_filter_entry(
    column_name: str,
    column_type: str,
    value,
    metadata: dict,
    component_id: str,
    is_range: bool = False,
) -> dict:
    """
    Create a filter entry for an interactive component.

    Args:
        column_name: Name of the column to filter on.
        column_type: Data type of the column (e.g., 'int64', 'object').
        value: Filter value (single value or list for ranges/multiselect).
        metadata: Graph metadata containing wf_id and dc_id.
        component_id: Unique identifier for the filter component.
        is_range: Whether to create a RangeSlider (True) or Slider (False) for numerical.

    Returns:
        Dictionary with filter metadata and value.
    """
    is_numerical = column_type in NUMERICAL_COLUMN_TYPES

    if is_numerical:
        component_type = "RangeSlider" if is_range else "Slider"
        filter_value = value
    else:
        component_type = "Select"
        filter_value = value if isinstance(value, list) else [value]

    return {
        "metadata": {
            "interactive_component_type": component_type,
            "column_name": column_name,
            "wf_id": metadata.get("wf_id"),
            "dc_id": metadata.get("dc_id"),
        },
        "value": filter_value,
    }


def process_click_data(dict_graph_data, interactive_components_dict, TOKEN):
    """
    Process clickData from a Plotly graph and update filters.

    Extracts clicked point values and creates appropriate filter entries
    based on column types (numerical uses Slider, categorical uses Select).

    Args:
        dict_graph_data: Contains the clicked point data and metadata.
        interactive_components_dict: Existing interactive components to update.
        TOKEN: Authentication token for API calls.

    Returns:
        Updated interactive_components_dict with new filter entries.
    """
    point = dict_graph_data.get("value", {})
    metadata = dict_graph_data.get("metadata", {})
    dict_kwargs = metadata.get("dict_kwargs", {})

    x_column = dict_kwargs.get("x")
    y_column = dict_kwargs.get("y")
    x_value = point.get("x")
    y_value = point.get("y")

    logger.debug(f"Processing click data for columns: x={x_column}, y={y_column}")
    logger.info(f"Clicked point values: x={x_value}, y={y_value}")

    cols_json = get_columns_from_data_collection(
        metadata.get("wf_id"), metadata.get("dc_id"), TOKEN
    )

    x_col_type = cols_json.get(x_column, {}).get("type", "object")
    y_col_type = cols_json.get(y_column, {}).get("type", "object")

    new_filters = {}
    component_id = metadata["index"]

    if x_value is not None and x_column:
        filter_key = f"filter_{x_column}_{component_id}"
        new_filters[filter_key] = _create_filter_entry(
            x_column, x_col_type, x_value, metadata, component_id
        )
        logger.debug(f"Added filter for {x_column}: {x_value}")

    if y_value is not None and y_column:
        filter_key = f"filter_{y_column}_{component_id}"
        new_filters[filter_key] = _create_filter_entry(
            y_column, y_col_type, y_value, metadata, component_id
        )
        logger.debug(f"Added filter for {y_column}: {y_value}")

    interactive_components_dict.update(new_filters)

    for v in interactive_components_dict.values():
        v["component_type"] = "interactive"

    logger.debug(f"Updated interactive_components_dict: {interactive_components_dict}")
    return interactive_components_dict


def process_selected_data(dict_graph_data, interactive_components_dict, TOKEN):
    """
    Process selectedData from a Plotly graph and update filters.

    Handles multiple selected points from lasso or box selection tools.
    Creates RangeSlider filters for numerical columns (using min/max range)
    and Select filters for categorical columns (using unique values).

    Args:
        dict_graph_data: Contains the list of selected points and metadata.
        interactive_components_dict: Existing interactive components to update.
        TOKEN: Access token for API authentication.

    Returns:
        Updated interactive_components_dict with new filter entries.
    """
    points = dict_graph_data.get("value", [])
    metadata = dict_graph_data.get("metadata", {})
    dict_kwargs = metadata.get("dict_kwargs", {})

    x_column = dict_kwargs.get("x")
    y_column = dict_kwargs.get("y")

    logger.debug(f"Processing selected data with {len(points)} points.")
    logger.debug(f"Processing selected data for columns: x={x_column}, y={y_column}")

    x_values = {point.get("x") for point in points if "x" in point}
    y_values = {point.get("y") for point in points if "y" in point}

    cols_json = get_columns_from_data_collection(
        metadata.get("wf_id"), metadata.get("dc_id"), TOKEN
    )

    x_col_type = cols_json.get(x_column, {}).get("type", "object")
    y_col_type = cols_json.get(y_column, {}).get("type", "object")

    new_filters = {}

    if x_values and x_column:
        filter_key = f"filter_{x_column}_{uuid.uuid4()}"
        is_numerical = x_col_type in NUMERICAL_COLUMN_TYPES
        value = [min(x_values), max(x_values)] if is_numerical else list(x_values)
        new_filters[filter_key] = _create_filter_entry(
            x_column, x_col_type, value, metadata, filter_key, is_range=is_numerical
        )
        logger.debug(f"Added filter for {x_column}: {value}")

    if y_values and y_column:
        filter_key = f"filter_{y_column}_{uuid.uuid4()}"
        is_numerical = y_col_type in NUMERICAL_COLUMN_TYPES
        value = [min(y_values), max(y_values)] if is_numerical else list(y_values)
        new_filters[filter_key] = _create_filter_entry(
            y_column, y_col_type, value, metadata, filter_key, is_range=is_numerical
        )
        logger.debug(f"Added filter for {y_column}: {value}")

    interactive_components_dict.update(new_filters)
    logger.debug(f"Updated interactive_components_dict: {interactive_components_dict}")
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
):
    """
    Handle click events on graphs and update interactive components.

    Finds the clicked graph from the list of graphs, extracts click data,
    and processes it into filter updates. Uses pattern-matching architecture
    where components handle their own filter updates.

    Args:
        graph_click_data: List of click data from all graphs.
        graph_ids: List of graph component IDs.
        ctx_triggered_prop_id_index: Index of the triggered graph.
        stored_metadata: Metadata for all components.
        interactive_components_dict: Current interactive component filters.
        draggable_children: Current draggable layout children.
        edit_components_mode_button: Edit mode switch state.
        TOKEN: Authentication token.
        dashboard_id: Current dashboard identifier.

    Returns:
        Tuple of (draggable_children, updated_interactive_components).
    """
    logger.info(f"Graph click data: {graph_click_data}")
    logger.info(f"Graph ids: {graph_ids}")
    logger.info(f"Interactive components dict: {interactive_components_dict}")

    # Initialize the variable
    updated_interactive_components = {}

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

        logger.debug(f"Updated interactive components: {updated_interactive_components}")

        for metadata in stored_metadata:
            if metadata["index"] == ctx_triggered_prop_id_index:
                metadata["filter_applied"] = True
        logger.info(f"TMP Stored metadata: {stored_metadata}")

        # PATTERN-MATCHING ARCHITECTURE: Components handle their own filter updates
        # updated_interactive_components triggers interactive-values-store update
        # Pattern-matching callbacks (cards, figures, tables) listen and update themselves
        # No need to rebuild children - return unchanged and let callbacks handle updates

        return draggable_children, updated_interactive_components


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
):
    """
    Handle selection events on graphs and update interactive components.

    Processes multi-point selection (lasso/box select) from graphs and
    updates the interactive component filters accordingly. Rebuilds
    component children to reflect the new filter state.

    Args:
        graph_selected_data: List of selection data from all graphs.
        graph_ids: List of graph component IDs.
        ctx_triggered_prop_id_index: Index of the triggered graph.
        stored_metadata: Metadata for all components.
        interactive_components_dict: Current interactive component filters.
        draggable_children: Current draggable layout children.
        edit_components_mode_button: Edit mode switch state.
        TOKEN: Authentication token.
        dashboard_id: Current dashboard identifier.

    Returns:
        Tuple of (new_children, updated_interactive_components).
    """
    selectedData = [
        e
        for e, id in zip(graph_selected_data, graph_ids)
        if id["index"] == ctx_triggered_prop_id_index
    ][0]
    logger.info(f"Selected data: {selectedData}")
    new_children = list()
    updated_interactive_components = {}  # Initialize the variable

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

        logger.debug(f"Updated interactive components: {updated_interactive_components}")

        for metadata in stored_metadata:
            if metadata["index"] == ctx_triggered_prop_id_index:
                metadata["filter_applied"] = True

        new_children = update_interactive_component_sync(
            stored_metadata,
            updated_interactive_components,
            draggable_children,
            switch_state=edit_components_mode_button,
            TOKEN=TOKEN,
            dashboard_id=dashboard_id,
            theme="light",  # TODO: Get theme from store
        )

        logger.info(f"New children len : {len(new_children)}")
        # state_stored_draggable_children[dashboard_id] = new_children
    return new_children, updated_interactive_components
