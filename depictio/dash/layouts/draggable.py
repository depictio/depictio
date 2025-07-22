import copy

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import httpx
from dash import ALL, Input, Output, State, ctx, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

# Import centralized component dimensions from metadata
from depictio.dash.component_metadata import get_component_dimensions_dict
from depictio.dash.layouts.draggable_scenarios.add_component import add_new_component
from depictio.dash.layouts.draggable_scenarios.graphs_interactivity import (
    refresh_children_based_on_click_data,
    refresh_children_based_on_selected_data,
)
from depictio.dash.layouts.draggable_scenarios.interactive_component_update import (
    render_raw_children,
    update_interactive_component,
)
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import render_dashboard

# Depictio layout imports for stepper
# Depictio layout imports for header
from depictio.dash.layouts.edit import edit_component, enable_box_edit_mode
from depictio.dash.utils import (
    generate_unique_index,
    get_component_data,
    return_dc_tag_from_id,
    return_wf_tag_from_id,
)

# Get component dimensions from centralized metadata
# Adjusted for 96-column grid with rowHeight=10 - default 14x14 for all components
component_dimensions = get_component_dimensions_dict()
# No longer using breakpoints - working with direct list format


def calculate_new_layout_position(child_type, existing_layouts, child_id, n):
    """Calculate position for new layout item based on existing ones and type."""
    # Get the default dimensions from the type
    logger.info(
        f"🔄 CALCULATE_NEW_LAYOUT_POSITION CALLED: {child_type} with {n} existing components"
    )
    dimensions = component_dimensions.get(
        child_type, {"w": 14, "h": 14}
    )  # Default 14x14 for 96-column grid
    logger.info(f"📐 Selected dimensions: {dimensions} for {child_type}")
    logger.info(f"📋 Existing layouts: {existing_layouts}")

    columns_per_row = 96
    components_per_row = columns_per_row // dimensions["w"]
    if components_per_row == 0:
        components_per_row = 1

    # Find the next available position by checking actual existing layouts
    if existing_layouts:
        # Find the maximum bottom position (y + height) of all existing components
        max_bottom = 0
        for layout in existing_layouts:
            if isinstance(layout, dict) and "y" in layout and "h" in layout:
                bottom = layout["y"] + layout["h"]
                max_bottom = max(max_bottom, bottom)

        logger.info(f"📏 Maximum bottom position of existing components: {max_bottom}")

        # Try different y positions starting from 0 to find the first available spot
        y_position = 0
        found_position = False

        # Check every possible y position, but limit attempts for performance
        max_attempts = min(max_bottom + dimensions["h"] + 10, 200)  # Cap at reasonable limit

        while y_position <= max_attempts and not found_position:
            # Check if we can fit the new component at this y position

            # For each possible x position in this row
            for x_position in range(0, columns_per_row - dimensions["w"] + 1):
                # Check if this position (x, y, w, h) overlaps with any existing component
                position_available = True
                new_x_range = set(range(x_position, x_position + dimensions["w"]))
                new_y_range = set(range(y_position, y_position + dimensions["h"]))

                for layout in existing_layouts:
                    if isinstance(layout, dict):
                        existing_x = layout.get("x", 0)
                        existing_y = layout.get("y", 0)
                        existing_w = layout.get("w", 14)
                        existing_h = layout.get("h", 14)

                        existing_x_range = set(range(existing_x, existing_x + existing_w))
                        existing_y_range = set(range(existing_y, existing_y + existing_h))

                        # Check for overlap
                        if new_x_range.intersection(existing_x_range) and new_y_range.intersection(
                            existing_y_range
                        ):
                            position_available = False
                            break

                if position_available:
                    col_position = x_position
                    found_position = True
                    logger.info(f"✅ Found available position: x={col_position}, y={y_position}")
                    break

            if not found_position:
                y_position += 1  # Try next row

        # If we still haven't found a position, place below everything
        if not found_position:
            col_position = 0
            y_position = max_bottom
            logger.info(f"⬇️ Fallback: placing below all components at y={y_position}")
    else:
        # No existing components, place at origin
        col_position = 0
        y_position = 0

    logger.info(f"📍 Calculated position: x={col_position}, y={y_position}")

    return {
        "x": col_position,
        "y": y_position,
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


def clean_stored_metadata(stored_metadata):
    # Remove duplicates from stored_metadata by checking parent_index and index
    stored_metadata = remove_duplicates_by_index(stored_metadata)
    parent_indexes = set(
        [
            e["parent_index"]
            for e in stored_metadata
            if "parent_index" in e and e["parent_index"] is not None
        ]
    )
    # remove parent indexes that are also child indexes
    stored_metadata = [e for e in stored_metadata if e["index"] not in parent_indexes]
    return stored_metadata


def register_callbacks_draggable(app):
    @app.callback(
        Output("local-store-components-metadata", "data"),
        [
            State({"type": "workflow-selection-label", "index": ALL}, "value"),
            State({"type": "datacollection-selection-label", "index": ALL}, "value"),
            Input("url", "pathname"),
            Input({"type": "btn-done", "index": ALL}, "n_clicks"),
            Input({"type": "btn-done-edit", "index": ALL}, "n_clicks"),
            Input({"type": "edit-box-button", "index": ALL}, "n_clicks"),
            Input({"type": "duplicate-box-button", "index": ALL}, "n_clicks"),
        ],
        [
            State("local-store", "data"),  # Contains 'access_token'
            State("local-store-components-metadata", "data"),  # Existing components' data
            State({"type": "workflow-selection-label", "index": ALL}, "id"),
            State({"type": "datacollection-selection-label", "index": ALL}, "id"),
            State("current-edit-parent-index", "data"),  # Retrieve parent_index
        ],
        prevent_initial_call=True,
    )
    def store_wf_dc_selection(
        wf_values,
        dc_values,
        pathname,
        btn_done_clicks,
        btn_done_edit_clicks,
        edit_box_button_clicks,
        duplicate_box_button_clicks,
        local_store,
        components_store,
        wf_ids,
        dc_ids,
        current_edit_parent_index,  # Retrieve parent_index from state
    ):
        """
        Callback to store all components' workflow and data collection data in a centralized store.
        Updates the store whenever any workflow or data collection dropdown changes.

        Args:
            wf_values (list): List of selected workflow IDs from all dropdowns.
            dc_values (list): List of selected data collection IDs from all dropdowns.
            pathname (str): Current URL pathname.
            local_store (dict): Data from 'local-store', expected to contain 'access_token'.
            components_store (dict): Existing components' wf/dc data.
            wf_ids (list): List of IDs for workflow dropdowns.
            dc_ids (list): List of IDs for datacollection dropdowns.

        Returns:
            dict: Updated components' wf/dc data.
        """
        logger.info("Storing workflow and data collection selections in components store.")
        logger.info(f"Workflow values (IDs): {wf_values}")
        logger.info(f"Data collection values (IDs): {dc_values}")
        logger.info(f"URL pathname: {pathname}")
        logger.info(f"Button done clicks: {btn_done_clicks}")
        logger.info(f"Button done edit clicks: {btn_done_edit_clicks}")
        logger.info(f"Edit box button clicks: {edit_box_button_clicks}")
        logger.info(f"Duplicate box button clicks: {duplicate_box_button_clicks}")
        # logger.info(f"Local store data: {local_store}")
        # logger.info(f"Components store data before update: {components_store}")
        logger.info(f"Workflow IDs: {wf_ids}")
        logger.info(f"Data collection IDs: {dc_ids}")
        logger.info(f"Current edit parent index: {current_edit_parent_index}")

        # Validate access token
        if not local_store or "access_token" not in local_store:
            logger.error("Local data or access_token is missing.")
            return components_store  # No update

        TOKEN = local_store["access_token"]

        # Initialize components_store if empty
        if not components_store:
            components_store = {}

        # Process workflow selections (now using IDs directly)
        for wf_id_value, wf_id_prop in zip(wf_values, wf_ids):
            # Parse the ID safely
            try:
                trigger_id = wf_id_prop
            except Exception as e:
                logger.error(f"Error parsing workflow ID prop '{wf_id_prop}': {e}")
                continue

            trigger_index = str(trigger_id.get("index"))
            if not trigger_index:
                logger.error(f"Invalid workflow ID prop: {trigger_id}")
                continue  # Skip this iteration

            # Update workflow ID directly
            components_store.setdefault(trigger_index, {})
            components_store[trigger_index]["wf_id"] = wf_id_value

            # Get component data if available
            component_data = None
            try:
                if wf_id_value is None or wf_id_value == "":
                    dashboard_id = pathname.split("/")[-1]
                    if current_edit_parent_index:
                        component_data = get_component_data(
                            input_id=current_edit_parent_index,
                            dashboard_id=dashboard_id,
                            TOKEN=TOKEN,
                        )
                        wf_id_value = component_data.get("wf_id", wf_id_value)
                        logger.info(
                            f"Component data retrieved for '{trigger_index}': {component_data}"
                        )
                        logger.info(f"Updated wf_id_value for '{trigger_index}': {wf_id_value}")

                        logger.info(f"Component data: {component_data}")
            except Exception as e:
                logger.warning(f"Failed to get component data: {e}")

            # Use comp

            # Get the workflow tag from the ID for reference/display purposes
            logger.info(f"Updating component '{trigger_index}' with wf_id: {wf_id_value}")
            try:
                wf_tag = return_wf_tag_from_id(workflow_id=wf_id_value, TOKEN=TOKEN)
                components_store[trigger_index]["wf_tag"] = wf_tag
                logger.debug(
                    f"Updated component '{trigger_index}' with wf_tag: {wf_tag} from wf_id: {wf_id_value}"
                )
            except Exception as e:
                logger.error(f"Error retrieving workflow tag for component '{trigger_index}': {e}")
                components_store[trigger_index]["wf_tag"] = ""

        # Process datacollection selections (now using IDs directly)
        for dc_id_value, dc_id_prop in zip(dc_values, dc_ids):
            # Parse the ID safely
            try:
                trigger_id = dc_id_prop
            except Exception as e:
                logger.error(f"Error parsing datacollection ID prop '{dc_id_prop}': {e}")
                continue  # Skip this iteration

            trigger_index = str(trigger_id.get("index"))
            if not trigger_index:
                logger.error(f"Invalid datacollection ID prop: {trigger_id}")
                continue  # Skip this iteration

            # Update datacollection ID directly
            components_store.setdefault(trigger_index, {})
            components_store[trigger_index]["dc_id"] = dc_id_value

            # Get the datacollection tag from the ID for reference/display purposes
            try:
                if dc_id_value is None or dc_id_value == "":
                    dashboard_id = pathname.split("/")[-1]
                    if current_edit_parent_index:
                        component_data = get_component_data(
                            input_id=current_edit_parent_index,
                            dashboard_id=dashboard_id,
                            TOKEN=TOKEN,
                        )
                        dc_id_value = component_data.get("dc_id", dc_id_value)
                        logger.info(
                            f"Component data retrieved for '{trigger_index}': {component_data}"
                        )
                        logger.info(f"Updated dc_id_value for '{trigger_index}': {dc_id_value}")
                dc_tag = return_dc_tag_from_id(data_collection_id=dc_id_value, TOKEN=TOKEN)
                components_store[trigger_index]["dc_tag"] = dc_tag
                logger.debug(
                    f"Updated component '{trigger_index}' with dc_tag: {dc_tag} from dc_id: {dc_id_value}"
                )
            except Exception as e:
                logger.error(
                    f"Error retrieving datacollection tag for component '{trigger_index}': {e}"
                )
                components_store[trigger_index]["dc_tag"] = ""

        logger.debug(f"Components store data after update: {components_store}")
        return components_store

    @app.callback(
        Output("draggable", "items"),
        Output("draggable", "currentLayout"),
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
        State("draggable", "items"),
        State("draggable", "currentLayout"),
        Input("draggable", "currentLayout"),
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
        Input("reset-all-filters-button", "n_clicks"),
        Input("remove-all-components-button", "n_clicks"),
        State("toggle-interactivity-button", "checked"),
        State("unified-edit-mode-button", "checked"),
        Input("unified-edit-mode-button", "checked"),
        State("url", "pathname"),
        State("local-store", "data"),
        State("theme-store", "data"),
        # Input("dashboard-title", "style"),  # Indirect trigger for theme changes
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
        reset_all_filters_button,
        remove_all_components_button,
        toggle_interactivity_button,
        unified_edit_mode_button,
        input_unified_edit_mode_button,
        pathname,
        local_data,
        theme_store,  # Now an Input parameter - triggers callback when theme changes
        # dashboard_title_style,  # Indirect trigger for theme changes
        # height_store,
    ):
        if not local_data:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not state_stored_draggable_layouts:
            state_stored_draggable_layouts = {}
        if not state_stored_draggable_children:
            state_stored_draggable_children = {}

        TOKEN = local_data["access_token"]

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

        # logger.info(f"Input draggable layouts: {input_draggable_layouts}")
        # logger.info(f"Draggable layout : {draggable_layouts}")
        # logger.info(f"Stored draggable layouts: {state_stored_draggable_layouts}")
        # logger.info(f"Stored draggable children: {state_stored_draggable_children}")
        # logger.info(f"Input stored draggable children: {input_stored_draggable_children}")

        # Extract dashboard_id from the pathname
        dashboard_id = pathname.split("/")[-1]

        # Ensure draggable_layouts is in list format
        if isinstance(draggable_layouts, dict):
            # Extract list from legacy dict format for backward compatibility
            draggable_layouts = draggable_layouts.get("lg", [])
        elif draggable_layouts is None:
            draggable_layouts = []

        # Initialize layouts from stored layouts if available
        if dashboard_id in state_stored_draggable_layouts:
            # Check if draggable_layouts is empty (list format only)
            is_empty = not draggable_layouts or len(draggable_layouts) == 0

            if is_empty:
                logger.info(
                    f"Initializing layouts from stored layouts for dashboard {dashboard_id}"
                )
                stored_layouts = state_stored_draggable_layouts[dashboard_id]
                # Ensure stored layouts are also in list format
                if isinstance(stored_layouts, dict):
                    draggable_layouts = stored_layouts.get("lg", [])
                else:
                    draggable_layouts = stored_layouts
                # logger.info(f"Updated draggable layouts: {draggable_layouts}")

        if isinstance(ctx.triggered_id, dict):
            triggered_input = ctx.triggered_id["type"]
            triggered_input_dict = ctx.triggered_id
        elif isinstance(ctx.triggered_id, str):
            triggered_input = ctx.triggered_id
            triggered_input_dict = None

        else:
            triggered_input = None
            triggered_input_dict = None

        logger.info(f"Triggered input: {triggered_input}")
        # logger.info(f"Theme store: {theme_store}")

        # Extract theme safely from theme store with improved fallback handling
        theme = "light"  # Default
        if theme_store:
            if isinstance(theme_store, dict):
                # Handle empty dict case
                if theme_store == {}:
                    theme = "light"
                else:
                    theme = theme_store.get("colorScheme", theme_store.get("theme", "light"))
            elif isinstance(theme_store, str) and theme_store in ["light", "dark"]:
                theme = theme_store
            else:
                logger.warning(
                    f"Invalid theme_store value: {theme_store}, using default light theme"
                )
                theme = "light"
        logger.info(f"Using theme: {theme}")
        logger.info(f"Dashboard callback triggered by: {triggered_input}")
        logger.info(f"Theme store value: {theme_store}")

        # FIXME: Remove duplicates from stored_metadata
        # Remove duplicates from stored_metadata
        stored_metadata = remove_duplicates_by_index(stored_metadata)

        dashboard_id = pathname.split("/")[-1]
        stored_metadata_interactive = [
            e for e in stored_metadata if e["component_type"] == "interactive"
        ]

        interactive_components_dict = {
            id["index"]: {"value": value, "metadata": metadata}
            for (id, value, metadata) in zip(
                interactive_component_ids,
                interactive_component_values,
                stored_metadata_interactive,
            )
        }

        # Can be "btn-done" or "btn-done-edit" or "graph" ..
        if triggered_input:
            # Handle scenarios where the user clicks on the "Done" button to add a new component
            if triggered_input == "btn-done":
                logger.info("Done button clicked")

                triggered_index = triggered_input_dict["index"]  # type: ignore[non-subscriptable]

                tmp_stored_metadata = [
                    e for e in stored_metadata if f"{e['index']}-tmp" == f"{triggered_index}"
                ]

                if not tmp_stored_metadata:
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                child_metadata = tmp_stored_metadata[0]
                child_index = child_metadata["index"]
                child_type = child_metadata["component_type"]

                children, indexes = render_raw_children(
                    tmp_stored_metadata[0],
                    switch_state=unified_edit_mode_button,
                    dashboard_id=dashboard_id,
                    TOKEN=TOKEN,
                    theme=theme,
                )
                child = children

                draggable_children.append(child)
                child_id = f"box-{str(indexes)}"
                logger.info(f"Child type: {child_type}")
                new_layout_item = calculate_new_layout_position(
                    child_type, draggable_layouts, child_id, len(draggable_children)
                )

                # Add new layout item to the list (no more breakpoint logic)
                draggable_layouts.append(new_layout_item)
                # logger.info(f"New layout item: {new_layout_item}")
                # logger.info(f"New draggable layouts: {draggable_layouts}")
                state_stored_draggable_layouts[dashboard_id] = draggable_layouts
                # logger.info(f"State stored draggable layouts: {state_stored_draggable_layouts}")

                # logger.info(f"New draggable children: {draggable_children}")
                return (
                    draggable_children,
                    draggable_layouts,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )

            # Handle scenarios where the user adjusts the layout of the draggable components
            elif triggered_input == "draggable":
                logger.info("Draggable callback triggered")
                ctx_triggered_props_id = ctx.triggered_prop_ids

                # logger.info(f"CTX triggered props id: {ctx_triggered_props_id}")
                # logger.info(f"Draggable layouts: {input_draggable_layouts}")
                # logger.info(f"State stored draggable layouts: {state_stored_draggable_layouts}")

                if "draggable.currentLayout" in ctx_triggered_props_id:
                    # dash-dynamic-grid-layout returns a single layout array - store it directly
                    state_stored_draggable_children[dashboard_id] = draggable_children
                    state_stored_draggable_layouts[dashboard_id] = input_draggable_layouts

                    return (
                        draggable_children,
                        input_draggable_layouts,  # Return the raw layout array
                        dash.no_update,
                        state_stored_draggable_layouts,
                        dash.no_update,
                    )
                else:
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

            # Handle scenarios where the user clicks/select on a graph
            elif "graph" in triggered_input:
                logger.info("Graph callback triggered")
                ctx_triggered = ctx.triggered
                ctx_triggered = ctx_triggered[0]
                ctx_triggered_prop_id = ctx_triggered["prop_id"]
                ctx_triggered_prop_id_index = eval(ctx_triggered_prop_id.split(".")[0])["index"]

                graph_metadata = [
                    e for e in stored_metadata if e["index"] == ctx_triggered_prop_id_index
                ]
                if graph_metadata:
                    graph_metadata = graph_metadata[0]
                else:
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

                # Restrict the callback to only scatter plots
                if graph_metadata["visu_type"].lower() == "scatter":
                    # Handle scenarios where the user clicks on a specific point on the graph
                    if "clickData" in ctx_triggered_prop_id:
                        logger.info("Click data triggered")
                        updated_children = refresh_children_based_on_click_data(
                            graph_click_data=graph_click_data,
                            graph_ids=graph_ids,
                            ctx_triggered_prop_id_index=ctx_triggered_prop_id_index,
                            stored_metadata=stored_metadata,
                            interactive_components_dict=interactive_components_dict,
                            draggable_children=draggable_children,
                            edit_components_mode_button=unified_edit_mode_button,
                            TOKEN=TOKEN,
                            dashboard_id=dashboard_id,
                        )
                        if updated_children:
                            return (
                                updated_children,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                            )
                        else:
                            return (
                                draggable_children,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                            )

                    # Handle scenarios where the user selects a range on the graph
                    elif "selectedData" in ctx_triggered_prop_id:
                        logger.info("Selected data triggered")
                        updated_children = refresh_children_based_on_selected_data(
                            graph_selected_data=graph_selected_data,
                            graph_ids=graph_ids,
                            ctx_triggered_prop_id_index=ctx_triggered_prop_id_index,
                            stored_metadata=stored_metadata,
                            interactive_components_dict=interactive_components_dict,
                            draggable_children=draggable_children,
                            edit_components_mode_button=unified_edit_mode_button,
                            TOKEN=TOKEN,
                            dashboard_id=dashboard_id,
                        )
                        if updated_children:
                            return (
                                updated_children,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                            )
                        else:
                            return (
                                draggable_children,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                            )

                    # Handle scenarios where the user relayouts the graph
                    # TODO: Implement this
                    elif "relayoutData" in ctx_triggered_prop_id:
                        logger.info("Relayout data triggered")
                        return (
                            draggable_children,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                        )

                    # Handle scenarios where the user resets the selection on the graph using a button
                    elif "reset-selection-graph-button" in triggered_input:
                        logger.info("Reset selection graph button triggered")
                        for metadata in stored_metadata:
                            if metadata["index"] == ctx_triggered_prop_id_index:
                                metadata["filter_applied"] = False
                        # logger.info(f"Stored metadata: {stored_metadata}")
                        # logger.info(f"Interactive components dict: {interactive_components_dict}")

                        new_children = update_interactive_component(
                            stored_metadata,
                            interactive_components_dict,
                            draggable_children,
                            switch_state=unified_edit_mode_button,
                            TOKEN=TOKEN,
                            dashboard_id=dashboard_id,
                            theme=theme,
                        )
                        return (
                            new_children,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                        )
                    else:
                        return (
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                        )
                else:
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

            elif (
                "interactive-component" in triggered_input
                and toggle_interactivity_button
                or triggered_input == "theme-store"
            ):
                if triggered_input == "theme-store":
                    logger.info("Theme store triggered - updating all components with new theme")
                else:
                    logger.info("Interactive component triggered")

                def clean_stored_metadata(stored_metadata):
                    # Remove duplicates from stored_metadata by checking parent_index and index
                    stored_metadata = remove_duplicates_by_index(stored_metadata)
                    parent_indexes = set(
                        [
                            e["parent_index"]
                            for e in stored_metadata
                            if "parent_index" in e and e["parent_index"] is not None
                        ]
                    )
                    # remove parent indexes that are also child indexes
                    stored_metadata = [
                        e for e in stored_metadata if e["index"] not in parent_indexes
                    ]
                    return stored_metadata

                stored_metadata = clean_stored_metadata(stored_metadata)

                logger.info(f"Updating components with theme: {theme}")

                new_children = update_interactive_component(
                    stored_metadata,
                    interactive_components_dict,
                    draggable_children,
                    switch_state=unified_edit_mode_button,
                    TOKEN=TOKEN,
                    dashboard_id=dashboard_id,
                    theme=theme,
                )
                state_stored_draggable_children[dashboard_id] = new_children

                if new_children:
                    return (
                        new_children,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                else:
                    return (
                        draggable_children,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

                # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

            elif triggered_input == "stored-draggable-layouts":
                # logger.info("Stored draggable layouts triggered")
                # logger.info(f"Input draggable layouts: {input_draggable_layouts}")
                # logger.info(f"State stored draggable layouts: {state_stored_draggable_layouts}")

                if state_stored_draggable_layouts:
                    if dashboard_id in state_stored_draggable_layouts:
                        children = render_dashboard(
                            stored_metadata,
                            unified_edit_mode_button,
                            dashboard_id,
                            theme,
                            TOKEN,
                        )
                        logger.info(f"render_dashboard called with theme: {theme}")

                        # Ensure we're using the stored layouts
                        current_layouts = state_stored_draggable_layouts[dashboard_id]

                        # Ensure layouts are in list format
                        if isinstance(current_layouts, dict):
                            current_layouts = current_layouts.get("lg", [])

                        return (
                            children,
                            current_layouts,
                            dash.no_update,
                            state_stored_draggable_layouts,
                            dash.no_update,
                        )
                    else:
                        return (
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                        )

                else:
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

            elif triggered_input == "remove-box-button":
                logger.info("Remove box button clicked")
                input_id = ctx.triggered_id["index"]

                updated_children = [
                    child
                    for child in draggable_children
                    if child["props"]["id"] != f"box-{input_id}"
                ]
                state_stored_draggable_layouts[dashboard_id] = draggable_layouts

                return (
                    updated_children,
                    draggable_layouts,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )
                # return updated_children, draggable_layouts, state_stored_draggable_children, state_stored_draggable_layouts

            elif triggered_input == "edit-box-button":
                logger.info("Edit box button clicked")

                input_id = ctx.triggered_id["index"]
                logger.info(f"Input ID: {input_id}")

                component_data = get_component_data(
                    input_id=input_id, dashboard_id=dashboard_id, TOKEN=TOKEN
                )

                if component_data:
                    component_data["parent_index"] = input_id
                else:
                    component_data = {"parent_index": input_id}

                new_id = generate_unique_index()
                edited_modal = edit_component(
                    new_id,
                    parent_id=input_id,
                    active=1,
                    component_data=component_data,
                    TOKEN=TOKEN,
                )

                updated_children = []
                # logger.info(f"Draggable children: {draggable_children}")
                for child in draggable_children:
                    logger.info(f"Child props id: {child['props']['id']}")
                    if child["props"]["id"] == f"box-{input_id}":
                        child["props"]["children"] = edited_modal

                    updated_children.append(child)

                return (
                    updated_children,
                    draggable_layouts,
                    dash.no_update,
                    dash.no_update,
                    input_id,
                )

            elif triggered_input == "btn-done-edit":
                logger.info("Done edit button clicked")
                index = ctx.triggered_id["index"]

                edited_child = None
                parent_index = None
                logger.info(f"Index: {index}")
                # logger.info(f"Stored metadata: {stored_metadata}")
                logger.info(f"test_container: {test_container}")
                for metadata in stored_metadata:
                    if str(metadata["index"]) == str(index):
                        parent_index = metadata["parent_index"]
                        parent_metadata = metadata
                for child, metadata in zip(test_container, stored_metadata):
                    child_index = str(child["props"]["id"]["index"])
                    if str(child_index) == str(index):
                        logger.info(f"Found child with index: {child_index}")
                        logger.info(f"Index: {index}")
                        logger.info(f"Metadata: {metadata}")
                        edited_child = enable_box_edit_mode(
                            child,
                            unified_edit_mode_button,
                            dashboard_id=dashboard_id,
                            fresh=False,
                            component_data=parent_metadata,
                            TOKEN=TOKEN,
                        )

                if parent_index:
                    updated_children = list()
                    for child in draggable_children:
                        if child["props"]["id"] == f"box-{parent_index}":
                            updated_children.append(edited_child)  # Replace the entire child
                        else:
                            updated_children.append(child)

                    # Update the layout to use the parent_index (keep the component at the same position)
                    # The edited component should replace the original component in the same layout position
                    # Now working with list format directly
                    for layout in draggable_layouts:
                        # logger.info(f"Layout: {layout}")
                        if layout["i"] == f"box-{parent_index}":
                            # Keep the layout ID as parent_index (don't change to new index)
                            # This ensures the component stays in the same position
                            break

                    state_stored_draggable_layouts[dashboard_id] = draggable_layouts

                else:
                    updated_children = draggable_children

                return (
                    updated_children,
                    draggable_layouts,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    "",
                )

            elif triggered_input == "duplicate-box-button":
                logger.info("Duplicate box button clicked")
                triggered_index = ctx.triggered_id["index"]

                component_to_duplicate = None
                for child in draggable_children:
                    if child["props"]["id"] == f"box-{triggered_index}":
                        component_to_duplicate = child
                        break

                if component_to_duplicate is None:
                    logger.error(
                        f"No component found with id 'box-{triggered_index}' to duplicate."
                    )
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

                # Generate a new unique ID for the duplicated component
                new_index = generate_unique_index()
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

                if metadata is None:
                    logger.warning(f"No metadata found for index {triggered_index}")
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

                # metadata is guaranteed to be not None at this point
                assert metadata is not None
                metadata["index"] = new_index
                new_store = dcc.Store(
                    id={"type": "stored-metadata-component", "index": new_index},
                    data=metadata,
                )

                if type(duplicated_component["props"]["children"]["props"]["children"]) is list:
                    duplicated_component["props"]["children"]["props"]["children"] += [new_store]
                elif type(duplicated_component["props"]["children"]["props"]["children"]) is dict:
                    duplicated_component["props"]["children"]["props"]["children"]["props"][
                        "children"
                    ] += [new_store]

                update_nested_ids(duplicated_component, triggered_index, new_index)

                # Append the duplicated component to the updated children
                updated_children = list(draggable_children)
                updated_children.append(duplicated_component)

                # Calculate the new layout position
                # 'child_type' corresponds to the 'type' in the component's ID
                existing_layouts = draggable_layouts  # Current layouts before adding the new one
                n = len(updated_children)  # Position based on the number of components

                new_layout = calculate_new_layout_position(
                    f"{metadata['component_type']}-component",
                    existing_layouts,
                    child_id,
                    n,
                )

                # Add new layout item to the list (no more breakpoint logic)
                draggable_layouts.append(new_layout)
                # logger.info(f"New layout: {new_layout}")

                logger.info(
                    f"Duplicated component with new id 'box-{new_index}' and assigned layout {new_layout}"
                )

                # state_stored_draggable_children[dashboard_id] = updated_children
                state_stored_draggable_layouts[dashboard_id] = draggable_layouts

                return (
                    updated_children,
                    draggable_layouts,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )

            elif triggered_input == "remove-all-components-button":
                logger.info("Remove all components button clicked")
                state_stored_draggable_layouts[dashboard_id] = {}
                return (
                    [],
                    {},
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )
                # return [], {}, {}, {}
            elif triggered_input == "reset-all-filters-button":
                logger.info("Reset all filters button clicked")
                new_children = list()
                for metadata in stored_metadata:
                    metadata["filter_applied"] = False

                    new_child, index = render_raw_children(
                        metadata,
                        unified_edit_mode_button,
                        dashboard_id,
                        TOKEN=TOKEN,
                        theme=theme,
                    )
                    new_children.append(new_child)

                # state_stored_draggable_children[dashboard_id] = new_children

                return (
                    new_children,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )
            elif triggered_input == "unified-edit-mode-button":
                logger.info(f"Unified edit mode button clicked: {unified_edit_mode_button}")
                logger.info(f"Current draggable children count: {len(draggable_children)}")

                # For edit mode toggle, we should NOT recreate components
                # The showRemoveButton and showResizeHandles are handled by update_grid_edit_mode callback
                # The action buttons visibility should be controlled via CSS classes, not by recreating components

                # Just preserve the existing children and layouts - let CSS handle the button visibility
                logger.info("Preserving existing components for edit mode toggle")

                return (
                    draggable_children,  # Keep existing children unchanged
                    draggable_layouts,  # Keep existing layouts unchanged
                    dash.no_update,  # Don't update stored children
                    dash.no_update,  # Don't update stored layouts
                    dash.no_update,  # Don't update edit parent index
                )
                # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

            else:
                logger.warning(f"Unexpected triggered_input: {triggered_input}")
                return (
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

        else:
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

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
        # logger.info("\n\nTrigger modal")
        # logger.info(f"n_clicks: {add_button_nclicks}")
        # logger.info(f"stored_add_button: {stored_add_button}")
        # logger.info(f"initialized_add_button: {initialized_add_button}")
        # logger.info(f"edit_button_nclicks: {edit_button_nclicks}")
        # logger.info(f"initialized_edit_button: {initialized_edit_button}")

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
            index = f"{index}-tmp"
            stored_add_button["_id"] = index
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
        stored_metadata_interactive = [
            e for e in stored_metadata if e["component_type"] == "interactive"
        ]
        stored_metadata_interactive = remove_duplicates_by_index(stored_metadata_interactive)
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
            # logger.info(f"Interactive values: {interactive_values}")
            # logger.info(f"Interactive ids: {ids}")
            # logger.info(f"Stored metadata: {stored_metadata_interactive}")
            # logger.info(
            #     f"Lengths of interactive_values : {len(interactive_values)}, ids: {len(ids)}, stored_metadata: {len(stored_metadata_interactive)}"
            # )
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

    # Add callback to control grid edit mode like in the prototype
    @app.callback(
        [
            Output("draggable", "showRemoveButton", allow_duplicate=True),
            Output("draggable", "showResizeHandles", allow_duplicate=True),
            Output("draggable", "className", allow_duplicate=True),
        ],
        Input("unified-edit-mode-button", "checked"),
        prevent_initial_call=True,
    )
    def update_grid_edit_mode(edit_mode_enabled):
        """Update draggable grid edit mode based on edit dashboard button state"""
        logger.info(f"Grid edit mode toggled: {edit_mode_enabled}")

        if edit_mode_enabled:
            # Keep layout consistent - CSS handles button visibility, not DashGridLayout properties
            return False, False, "draggable-grid-container"
        else:
            # Keep layout consistent - CSS handles button visibility, not DashGridLayout properties
            return False, False, "draggable-grid-container drag-handles-hidden"


def design_draggable(
    init_layout: dict,
    init_children: list[dict],
    dashboard_id: str,
    local_data: dict,
    theme: str = "light",
    edit_dashboard_mode_button: bool = False,
):
    # logger.info("design_draggable - Initializing draggable layout")
    # logger.info(f"design_draggable - Dashboard ID: {dashboard_id}")
    # logger.info(f"design_draggable - Local data: {local_data}")
    # logger.info(f"design_draggable - Initial layout: {init_layout}")

    # Generate core layout based on data availability

    # TODO: if required, check if data was registered for the project
    TOKEN = local_data["access_token"]
    project = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{dashboard_id}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    # logger.info(f"design_draggable - Project: {project}")
    from depictio.models.models.projects import Project

    project = Project.from_mongo(project)
    # logger.info(f"design_draggable - Project: {project}")
    workflows = project.workflows
    delta_table_locations = []
    for wf in workflows:
        for dc in wf.data_collections:
            # print(dc)
            # Check if deltatable exists
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{str(dc.id)}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            if response.status_code == 200:
                delta_table_location = response.json()["delta_table_location"]
                logger.info(f"Delta table location: {delta_table_location}")
                delta_table_locations.append(delta_table_location)
            else:
                logger.error(
                    f"Error retrieving deltatable for data collection '{dc.id}': {response.text}"
                )
    # logger.info(f"Delta table locations: {delta_table_locations}")

    if len(delta_table_locations) == 0:
        # When there are no workflows, log information and prepare a message
        # logger.info(f"init_children {init_children}")
        # logger.info(f"init_layout {init_layout}")
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

    # logger.info(f"Init layout: {init_layout}")

    # Ensure init_layout has the required breakpoints
    # Ensure init_layout is in list format
    if init_layout:
        if isinstance(init_layout, dict):
            # Extract list from legacy dict format
            current_layout = init_layout.get("lg", [])
        else:
            current_layout = init_layout
    else:
        current_layout = []

    # Create the draggable layout using dash-dynamic-grid-layout
    # Since enable_box_edit_mode now returns DraggableWrapper components,
    # we can use them directly without additional wrapping
    draggable_items = init_children  # These are already DraggableWrapper components

    # dash-dynamic-grid-layout expects: [{"i": "id", "x": 0, "y": 0, "w": 4, "h": 4}, ...]
    # We now work directly with this format

    logger.info("Using list format for dash-dynamic-grid-layout")
    logger.info(f"Current layout: {current_layout}")

    # Ensure we have a valid layout array
    if not current_layout:
        current_layout = []

    draggable = dgl.DashGridLayout(
        id="draggable",
        items=draggable_items,
        itemLayout=current_layout,
        rowHeight=10,  # Larger row height for better component display
        cols={"lg": 96, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
        showRemoveButton=False,  # Keep consistent - CSS handles visibility
        showResizeHandles=False,  # Keep consistent - CSS handles visibility
        className="draggable-grid-container",  # CSS class for styling
        allowOverlap=False,
        style={
            "display": display_style,
            "flex-grow": 1,
            "width": "100%",
            "height": "auto",
        },
    )

    # Add draggable to the core children list whether it's visible or not
    core_children.append(draggable)

    # The core Div contains all elements, managing visibility as needed
    core = html.Div(core_children)

    return core
