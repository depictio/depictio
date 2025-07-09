import copy

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import httpx
from dash import ALL, Input, Output, State, ctx, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
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
    initialize_component_id_counter,
    return_dc_tag_from_id,
    return_wf_tag_from_id,
)

# Mapping of component types to their respective dimensions (width and height)
# Heights are now more responsive and optimized for different component types
component_dimensions = {
    "card": {"w": 2, "h": 6},  # Slightly taller for better content display
    "interactive": {"w": 5, "h": 6},  # Consistent height with cards
    "figure": {"w": 6, "h": 16},  # Taller for better visualization display
    "table": {"w": 6, "h": 12},  # Shorter than figures but adequate for tables
}
# Enable multiple breakpoints for better responsive behavior
required_breakpoints = ["lg", "md", "sm", "xs", "xxs"]

# Responsive component dimensions for different breakpoints
responsive_component_dimensions = {
    "lg": {
        "card": {"w": 2, "h": 6},
        "interactive": {"w": 5, "h": 6},
        "figure": {"w": 6, "h": 16},
        "table": {"w": 6, "h": 12},
    },
    "md": {
        "card": {"w": 2, "h": 6},
        "interactive": {"w": 4, "h": 6},
        "figure": {"w": 5, "h": 14},
        "table": {"w": 5, "h": 10},
    },
    "sm": {
        "card": {"w": 2, "h": 5},
        "interactive": {"w": 3, "h": 5},
        "figure": {"w": 4, "h": 12},
        "table": {"w": 4, "h": 8},
    },
    "xs": {
        "card": {"w": 2, "h": 4},
        "interactive": {"w": 2, "h": 4},
        "figure": {"w": 3, "h": 10},
        "table": {"w": 3, "h": 6},
    },
    "xxs": {
        "card": {"w": 1, "h": 4},
        "interactive": {"w": 1, "h": 4},
        "figure": {"w": 2, "h": 8},
        "table": {"w": 2, "h": 6},
    },
}


def calculate_responsive_layout_positions(child_type, existing_layouts, child_id, n):
    """Calculate layout positions for all breakpoints."""
    logger.info(
        f"Calculating responsive layout positions for {child_type} with {n} existing components"
    )

    # Grid columns for different breakpoints
    grid_columns = {"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2}

    # Create layout items for all breakpoints
    layout_items = {}

    for breakpoint in required_breakpoints:
        # Get dimensions for this breakpoint
        dimensions = responsive_component_dimensions.get(breakpoint, {}).get(
            child_type, component_dimensions.get(child_type, {"w": 6, "h": 5})
        )

        columns_per_row = grid_columns[breakpoint]
        existing_items = existing_layouts.get(breakpoint, [])

        # Create a grid to track occupied spaces
        max_rows = 50  # Reasonable maximum for grid calculation
        occupied_grid = [[False for _ in range(columns_per_row)] for _ in range(max_rows)]

        # Mark occupied spaces from existing items
        for item in existing_items:
            x, y, w, h = item["x"], item["y"], item["w"], item["h"]
            for row in range(y, min(y + h, max_rows)):
                for col in range(x, min(x + w, columns_per_row)):
                    occupied_grid[row][col] = True

        # Find the first available position that can fit the new component
        target_w, target_h = min(dimensions["w"], columns_per_row), dimensions["h"]

        position_found = False
        for row in range(max_rows - target_h + 1):
            for col in range(columns_per_row - target_w + 1):
                # Check if the area is available
                can_place = True
                for r in range(row, row + target_h):
                    for c in range(col, col + target_w):
                        if occupied_grid[r][c]:
                            can_place = False
                            break
                    if not can_place:
                        break

                if can_place:
                    layout_items[breakpoint] = {
                        "x": col,
                        "y": row,
                        "w": target_w,
                        "h": target_h,
                        "i": child_id,
                    }
                    position_found = True
                    break
            if position_found:
                break

        # Fallback: place at the bottom if no space found
        if not position_found:
            max_y = max([item["y"] + item["h"] for item in existing_items], default=0)
            layout_items[breakpoint] = {
                "x": 0,
                "y": max_y,
                "w": target_w,
                "h": target_h,
                "i": child_id,
            }

    logger.info(f"Calculated responsive positions for {child_type}: {layout_items}")
    return layout_items


def calculate_new_layout_position(child_type, existing_layouts, child_id, n):
    """Calculate position for new layout item based on existing ones and type."""
    logger.info(f"Calculating new layout position for {child_type} with {n} existing components")

    # Grid columns for different breakpoints
    grid_columns = {"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2}

    # Create layout items for all breakpoints
    layout_items = {}

    for breakpoint in required_breakpoints:
        # Get dimensions for this breakpoint
        dimensions = responsive_component_dimensions.get(breakpoint, {}).get(
            child_type, component_dimensions.get(child_type, {"w": 6, "h": 5})
        )

        columns_per_row = grid_columns[breakpoint]
        existing_items = existing_layouts.get(breakpoint, [])

        # Create a grid to track occupied spaces
        max_rows = 50  # Reasonable maximum for grid calculation
        occupied_grid = [[False for _ in range(columns_per_row)] for _ in range(max_rows)]

        # Mark occupied spaces from existing items
        for item in existing_items:
            x, y, w, h = item["x"], item["y"], item["w"], item["h"]
            for row in range(y, min(y + h, max_rows)):
                for col in range(x, min(x + w, columns_per_row)):
                    occupied_grid[row][col] = True

        # Find the first available position that can fit the new component
        target_w, target_h = min(dimensions["w"], columns_per_row), dimensions["h"]

        position_found = False
        for row in range(max_rows - target_h + 1):
            for col in range(columns_per_row - target_w + 1):
                # Check if the area is available
                can_place = True
                for r in range(row, row + target_h):
                    for c in range(col, col + target_w):
                        if occupied_grid[r][c]:
                            can_place = False
                            break
                    if not can_place:
                        break

                if can_place:
                    layout_items[breakpoint] = {
                        "x": col,
                        "y": row,
                        "w": target_w,
                        "h": target_h,
                        "i": child_id,
                    }
                    position_found = True
                    break
            if position_found:
                break

        # Fallback: place at the bottom if no space found
        if not position_found:
            max_y = max([item["y"] + item["h"] for item in existing_items], default=0)
            layout_items[breakpoint] = {
                "x": 0,
                "y": max_y,
                "w": target_w,
                "h": target_h,
                "i": child_id,
            }

    # Return the layout item for the primary breakpoint (lg)
    primary_layout = layout_items.get("lg", layout_items[list(layout_items.keys())[0]])
    logger.info(f"Calculated positions for {child_type}: {layout_items}")
    logger.info(f"Primary layout (lg): {primary_layout}")

    return primary_layout


# Update any nested component IDs within the duplicated component
def update_nested_ids(component, old_index, new_index):
    """Update nested component IDs when duplicating components.

    Args:
        component: The component structure to update
        old_index: The original component index (can be int or str)
        new_index: The new component index (can be int or str)
    """
    # Convert to strings for comparison since IDs can be mixed types
    old_index_str = str(old_index)
    new_index_str = str(new_index)

    if isinstance(component, dict):
        for key, value in component.items():
            if key == "id" and isinstance(value, dict):
                if str(value.get("index")) == old_index_str:
                    # Keep the new index as the same type as the old index
                    if isinstance(value.get("index"), int):
                        value["index"] = int(new_index_str)
                    else:
                        value["index"] = new_index_str
                    logger.debug(f"Updated nested ID from {old_index_str} to {new_index_str}")
            elif isinstance(value, dict):
                update_nested_ids(value, old_index, new_index)
            elif isinstance(value, list):
                for item in value:
                    update_nested_ids(item, old_index, new_index)
    elif isinstance(component, list):
        for item in component:
            update_nested_ids(item, old_index, new_index)


def remove_duplicates_by_index(components):
    """Remove duplicate components based on their index.

    Args:
        components: List of component metadata dictionaries

    Returns:
        List of unique components
    """
    unique_components = {}
    for component in components:
        index = str(component["index"])  # Convert to string for consistent comparison
        if index not in unique_components:
            unique_components[index] = component

    result = list(unique_components.values())
    logger.debug(f"Removed {len(components) - len(result)} duplicate components")
    return result


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
    # Add CSS injection clientside callback for resize border highlighting only
    # app.clientside_callback(
    #     """
    #     function(_) {
    #         // Inject minimal CSS for resize border highlighting
    #         const style = document.createElement('style');
    #         style.textContent = `
    #             .react-grid-item {
    #                 display: flex !important;
    #                 flex-direction: column !important;
    #             }
    #             .react-grid-item > div {
    #                 height: 100% !important;
    #                 width: 100% !important;
    #                 display: flex !important;
    #                 flex-direction: column !important;
    #             }
    #             .js-plotly-plot {
    #                 flex-grow: 1 !important;
    #                 height: 100% !important;
    #             }
    #             .react-resizable-handle {
    #                 background-color: rgba(255, 0, 0, 0.3) !important;
    #             }
    #             .react-grid-item.resizing {
    #                 border: 2px solid red !important;
    #                 opacity: 0.8 !important;
    #             }
    #         `;
    #         document.head.appendChild(style);
    #         return window.dash_clientside.no_update;
    #     }
    #     """,
    #     Output("css-store", "data", allow_duplicate=True),
    #     Input("draggable", "id"),
    #     prevent_initial_call="initial_duplicate",
    # )

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
    def store_wf_dc_selection(
        wf_values, dc_values, pathname, local_store, components_store, wf_ids, dc_ids
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
        # logger.info(f"Workflow values (IDs): {wf_values}")
        # logger.info(f"Data collection values (IDs): {dc_values}")
        # logger.info(f"URL pathname: {pathname}")
        # logger.info(f"Local store data: {local_store}")
        # logger.info(f"Components store data before update: {components_store}")

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

            # Get the workflow tag from the ID for reference/display purposes
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
        Output("draggable", "itemLayout"),
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
        State("draggable", "itemLayout"),
        Input("draggable", "itemLayout"),
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
        draggable_items,
        draggable_item_layout,
        input_draggable_item_layout,
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

        # Initialize layouts from stored layouts if available
        if dashboard_id in state_stored_draggable_layouts:
            # Check if draggable_item_layout is empty
            is_empty = not draggable_item_layout or len(draggable_item_layout) == 0

            if is_empty:
                logger.info(
                    f"Initializing layouts from stored layouts for dashboard {dashboard_id}"
                )
                # Use the lg breakpoint from stored layouts as the primary layout
                stored_layouts = state_stored_draggable_layouts[dashboard_id]
                draggable_item_layout = stored_layouts.get("lg", [])
                # logger.info(f"Updated draggable item layout: {draggable_item_layout}")

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

        # Extract theme safely from multiple sources
        theme = "light"  # Default
        # if theme_relay_data:
        #     theme = theme_relay_data.get("theme", "light")
        # elif theme_store:
        #     theme = theme_store
        logger.info(f"Using theme: {theme}")

        # FIXME: Remove duplicates from stored_metadata
        # Remove duplicates from stored_metadata
        stored_metadata = remove_duplicates_by_index(stored_metadata)

        # Initialize component ID counter based on existing metadata
        initialize_component_id_counter(stored_metadata)

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

                # Initialize component ID counter to ensure proper sequencing
                initialize_component_id_counter(stored_metadata)

                child, index = render_raw_children(
                    tmp_stored_metadata[0],
                    switch_state=edit_components_mode_button,
                    dashboard_id=dashboard_id,
                    TOKEN=TOKEN,
                    theme=theme,
                )

                # Wrap the component with enable_box_edit_mode using draggable wrapper
                child_id = str(index)
                wrapped_child = enable_box_edit_mode(
                    child,
                    switch_state=edit_components_mode_button,
                    dashboard_id=dashboard_id,
                    TOKEN=TOKEN,
                    use_draggable_wrapper=True,
                    component_type=child_type,
                )
                draggable_items.append(wrapped_child)

                logger.info(f"Child type: {child_type}")
                logger.info(f"Adding new component with ID: {child_id}")

                # Calculate layout position for the new component
                layout_item = calculate_new_layout_position(
                    child_type, {"lg": draggable_item_layout}, child_id, len(draggable_items)
                )

                # Add to the primary layout
                draggable_item_layout.append(layout_item)
                logger.info(f"Added layout item: {layout_item}")

                # Store the updated layouts (maintaining backward compatibility)
                responsive_layouts = calculate_responsive_layout_positions(
                    child_type, {"lg": draggable_item_layout}, child_id, len(draggable_items)
                )
                state_stored_draggable_layouts[dashboard_id] = responsive_layouts

                return (
                    draggable_items,
                    draggable_item_layout,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )

            # Handle scenarios where the user adjusts the layout of the draggable components
            elif triggered_input == "draggable":
                logger.info("Draggable callback triggered")
                ctx_triggered_props_id = ctx.triggered_prop_ids

                # logger.info(f"CTX triggered props id: {ctx_triggered_props_id}")
                # logger.info(f"Draggable item layout: {input_draggable_item_layout}")
                # logger.info(f"State stored draggable layouts: {state_stored_draggable_layouts}")

                if "draggable.itemLayout" in ctx_triggered_props_id:
                    new_item_layout = input_draggable_item_layout
                    state_stored_draggable_children[dashboard_id] = draggable_items

                    # Convert back to responsive layout format for storage
                    responsive_layouts = {"lg": new_item_layout}
                    state_stored_draggable_layouts[dashboard_id] = responsive_layouts

                    return (
                        draggable_items,
                        new_item_layout,
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
                            draggable_children=[
                                item.children
                                for item in draggable_items
                                if hasattr(item, "children")
                            ],
                            edit_components_mode_button=edit_components_mode_button,
                            TOKEN=TOKEN,
                            dashboard_id=dashboard_id,
                        )
                        if updated_children:
                            # Need to wrap updated children in DraggableWrapper
                            wrapped_children = []
                            for child in updated_children:
                                if hasattr(child, "get") and child.get("props", {}).get("id"):
                                    child_id = child["props"]["id"]
                                    if isinstance(child_id, str) and child_id.startswith("box-"):
                                        wrapped_child = enable_box_edit_mode(
                                            child,
                                            switch_state=True,
                                            use_draggable_wrapper=True,
                                            component_type="component",
                                        )
                                        wrapped_children.append(wrapped_child)
                                    else:
                                        wrapped_children.append(child)
                                else:
                                    wrapped_children.append(child)
                            return (
                                wrapped_children,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                            )
                        else:
                            return (
                                draggable_items,
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
                            draggable_children=[
                                item.children
                                for item in draggable_items
                                if hasattr(item, "children")
                            ],
                            edit_components_mode_button=edit_components_mode_button,
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
                                draggable_items,
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
                            draggable_items,
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
                            [
                                item.children
                                for item in draggable_items
                                if hasattr(item, "children")
                            ],
                            switch_state=edit_components_mode_button,
                            TOKEN=TOKEN,
                            dashboard_id=dashboard_id,
                            theme=theme,
                        )

                        # Wrap the updated components in DraggableWrapper
                        if new_children:
                            wrapped_children = []
                            for i, child in enumerate(new_children):
                                if hasattr(child, "props") and child.props.get("id"):
                                    child_id = child.props["id"]
                                    if isinstance(child_id, str) and child_id.startswith("box-"):
                                        component_type = (
                                            stored_metadata[i].get("component_type", "component")
                                            if i < len(stored_metadata)
                                            else "component"
                                        )
                                        wrapped_child = enable_box_edit_mode(
                                            child,
                                            switch_state=True,
                                            use_draggable_wrapper=True,
                                            component_type=component_type,
                                        )
                                        wrapped_children.append(wrapped_child)
                                    else:
                                        wrapped_children.append(child)
                                else:
                                    wrapped_children.append(child)

                            return (
                                wrapped_children,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                                dash.no_update,
                            )
                        else:
                            return (
                                draggable_items,
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
                or triggered_input == "theme-relay-store"
            ):
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
                    [item.children for item in draggable_items if hasattr(item, "children")],
                    switch_state=edit_components_mode_button,
                    TOKEN=TOKEN,
                    dashboard_id=dashboard_id,
                    theme=theme,
                )

                # Wrap the updated components in DraggableWrapper
                if new_children:
                    wrapped_children = []
                    for i, child in enumerate(new_children):
                        if hasattr(child, "props") and child.props.get("id"):
                            child_id = child.props["id"]
                            if isinstance(child_id, str) and child_id.startswith("box-"):
                                component_type = (
                                    stored_metadata[i].get("component_type", "component")
                                    if i < len(stored_metadata)
                                    else "component"
                                )
                                wrapped_child = enable_box_edit_mode(
                                    child,
                                    switch_state=True,
                                    use_draggable_wrapper=True,
                                    component_type=component_type,
                                )
                                wrapped_children.append(wrapped_child)
                            else:
                                wrapped_children.append(child)
                        else:
                            wrapped_children.append(child)

                    state_stored_draggable_children[dashboard_id] = wrapped_children

                    return (
                        wrapped_children,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                else:
                    return (
                        draggable_items,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

            elif "edit-components-mode-button" in triggered_input:
                logger.info(f"Edit components mode button triggered: {edit_components_mode_button}")
                new_children = list()
                # logger.info("Current draggable children: {}".format(draggable_children))
                logger.info(f"Len Current draggable children: {len(draggable_items)}")
                for child, child_metadata in zip(draggable_items, stored_metadata):
                    # logger.info(f"Child: {child}")
                    # logger.info("Child props: {}".format(child["props"]))
                    # logger.info("Child props children: {}".format(child["props"]["children"]))
                    if type(child["props"]["children"]) is dict:
                        child = enable_box_edit_mode(
                            child["props"]["children"]["props"]["children"][-1],
                            edit_components_mode_button,
                            component_data=child_metadata,
                        )
                    elif type(child["props"]["children"]) is list:
                        child = enable_box_edit_mode(
                            child["props"]["children"][-1],
                            edit_components_mode_button,
                            component_data=child_metadata,
                        )

                    # Wrap the child with enable_box_edit_mode using draggable wrapper
                    child_id = str(child_metadata.get("index", "unknown"))
                    component_type = child_metadata.get("component_type", "component")
                    wrapped_child = enable_box_edit_mode(
                        child,
                        switch_state=edit_components_mode_button,
                        use_draggable_wrapper=True,
                        component_type=component_type,
                    )
                    new_children.append(wrapped_child)

                state_stored_draggable_children[dashboard_id] = new_children

                return (
                    new_children,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )
                # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

            elif triggered_input == "stored-draggable-layouts":
                # logger.info("Stored draggable layouts triggered")
                # logger.info(f"Input draggable layouts: {input_draggable_layouts}")
                # logger.info(f"State stored draggable layouts: {state_stored_draggable_layouts}")

                if state_stored_draggable_layouts:
                    if dashboard_id in state_stored_draggable_layouts:
                        # Initialize component ID counter when restoring dashboard
                        initialize_component_id_counter(stored_metadata)

                        children = render_dashboard(
                            stored_metadata,
                            edit_components_mode_button,
                            dashboard_id,
                            theme,
                            TOKEN,
                        )

                        # Wrap restored components in DraggableWrapper
                        wrapped_children = []
                        for i, child in enumerate(children):
                            if hasattr(child, "props") and child.props.get("id"):
                                child_id = child.props["id"]
                                if isinstance(child_id, str) and child_id.startswith("box-"):
                                    component_type = (
                                        stored_metadata[i].get("component_type", "component")
                                        if i < len(stored_metadata)
                                        else "component"
                                    )
                                    wrapped_child = enable_box_edit_mode(
                                        child,
                                        switch_state=True,
                                        use_draggable_wrapper=True,
                                        component_type=component_type,
                                    )
                                    wrapped_children.append(wrapped_child)
                                else:
                                    wrapped_children.append(child)
                            else:
                                wrapped_children.append(child)

                        # Ensure we're using the stored layouts
                        current_layouts = state_stored_draggable_layouts[dashboard_id]
                        # Use lg breakpoint as primary layout
                        primary_layout = current_layouts.get("lg", [])

                        return (
                            wrapped_children,
                            primary_layout,
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
                    child for child in draggable_items if child["props"]["id"] != f"{input_id}"
                ]
                state_stored_draggable_layouts[dashboard_id] = {"lg": draggable_item_layout}

                return (
                    updated_children,
                    draggable_item_layout,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )
                # return updated_children, draggable_layouts, state_stored_draggable_children, state_stored_draggable_layouts

            elif triggered_input == "edit-box-button":
                logger.info("Edit box button clicked")

                input_id = ctx.triggered_id["index"]

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
                # logger.info(f"Draggable children: {draggable_items}")
                for child in draggable_items:
                    logger.info(f"Child props id: {child['props']['id']}")
                    if child["props"]["id"] == f"box-{input_id}":
                        child["props"]["children"] = edited_modal

                    updated_children.append(child)

                return (
                    updated_children,
                    draggable_item_layout,
                    dash.no_update,
                    dash.no_update,
                    input_id,
                )

            elif triggered_input == "btn-done-edit":
                logger.info("Done edit button clicked")
                index = ctx.triggered_id["index"]

                edited_child = None
                parent_index = None

                for metadata in stored_metadata:
                    if str(metadata["index"]) == str(index):
                        parent_index = metadata["parent_index"]
                        parent_metadata = metadata
                for child, metadata in zip(test_container, stored_metadata):
                    child_index = str(child["props"]["id"]["index"])
                    if str(child_index) == str(index):
                        edited_child = enable_box_edit_mode(
                            child,
                            edit_components_mode_button,
                            dashboard_id=dashboard_id,
                            fresh=False,
                            component_data=parent_metadata,
                            TOKEN=TOKEN,
                        )

                if parent_index:
                    updated_children = list()
                    for child in draggable_items:
                        if child["props"]["id"] == f"box-{parent_index}":
                            updated_children.append(edited_child)  # Replace the entire child
                        else:
                            updated_children.append(child)

                    for bp in required_breakpoints:
                        # logger.info(f"BP: {bp}")
                        for layout in state_stored_draggable_layouts[dashboard_id].get(bp, []):
                            # logger.info(f"Layout: {layout}")
                            if layout["i"] == f"box-{parent_index}":
                                layout["i"] = f"box-{index}"
                                break

                    # State already updated above

                else:
                    updated_children = draggable_items

                return (
                    updated_children,
                    draggable_item_layout,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    "",
                )

            elif triggered_input == "duplicate-box-button":
                logger.info("Duplicate box button clicked")
                triggered_index = ctx.triggered_id["index"]

                component_to_duplicate = None
                for child in draggable_items:
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

                # Find the original component's metadata
                original_metadata = None
                for metadata_child in stored_metadata:
                    if metadata_child["index"] == triggered_index:
                        original_metadata = metadata_child
                        logger.info(f"Original metadata found: {original_metadata}")
                        break

                if original_metadata is None:
                    logger.warning(f"No metadata found for index {triggered_index}")
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

                # Generate a new unique ID for the duplicated component
                new_index = generate_unique_index()
                child_id = f"{new_index}"

                logger.info(
                    f"Generated new component ID: {new_index} for duplication of {triggered_index}"
                )

                # Create a deep copy of the component to duplicate
                duplicated_component = copy.deepcopy(component_to_duplicate)

                # Update the duplicated component's ID to the new ID
                duplicated_component["props"]["id"] = child_id

                # Create new metadata by copying the original and updating the index
                metadata = copy.deepcopy(original_metadata)
                metadata["index"] = new_index

                # Remove any parent_index to avoid conflicts
                if "parent_index" in metadata:
                    del metadata["parent_index"]

                logger.info(f"Created new metadata with index {new_index}: {metadata}")
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

                # Update all nested IDs within the duplicated component
                update_nested_ids(duplicated_component, triggered_index, new_index)
                logger.info(f"Updated nested IDs from {triggered_index} to {new_index}")

                # Append the duplicated component to the updated children
                updated_children = list(draggable_items)
                updated_children.append(duplicated_component)

                # Calculate the new layout position
                # 'child_type' corresponds to the 'type' in the component's ID
                existing_layouts = state_stored_draggable_layouts.get(
                    dashboard_id, {}
                )  # Current layouts before adding the new one
                n = len(updated_children)  # Position based on the number of components

                # Calculate responsive layout positions for all breakpoints
                responsive_layouts = calculate_responsive_layout_positions(
                    metadata["component_type"],
                    existing_layouts,
                    child_id,
                    n,
                )

                for breakpoint in required_breakpoints:
                    layout_item = responsive_layouts.get(breakpoint)
                    if layout_item:
                        # Ensure the layout item ID matches component ID
                        layout_item["i"] = child_id
                        state_stored_draggable_layouts[dashboard_id][breakpoint].append(layout_item)
                        logger.info(f"Added duplicated layout item for {breakpoint}: {layout_item}")

                logger.info(
                    f"Successfully duplicated component from index {triggered_index} to new index {new_index}"
                )
                logger.info(f"Component ID: {child_id}")
                logger.info("Responsive layouts assigned for all breakpoints")

                # state_stored_draggable_children[dashboard_id] = updated_children
                # State already updated above

                return (
                    updated_children,
                    draggable_item_layout,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )

            elif triggered_input == "remove-all-components-button":
                logger.info("Remove all components button clicked")
                state_stored_draggable_layouts[dashboard_id] = {}
                # Reset the component ID counter when removing all components
                initialize_component_id_counter([])
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
                        edit_components_mode_button,
                        dashboard_id,
                        TOKEN=TOKEN,
                        theme=theme,
                    )

                    # Wrap the component with enable_box_edit_mode using draggable wrapper
                    child_id = str(index)
                    component_type = metadata.get("component_type", "component")
                    wrapped_child = enable_box_edit_mode(
                        new_child,
                        switch_state=edit_components_mode_button,
                        dashboard_id=dashboard_id,
                        TOKEN=TOKEN,
                        use_draggable_wrapper=True,
                        component_type=component_type,
                    )
                    new_children.append(wrapped_child)

                # state_stored_draggable_children[dashboard_id] = new_children

                return (
                    new_children,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )
            elif triggered_input == "edit-dashboard-mode-button":
                logger.info(f"Edit dashboard mode button clicked: {edit_dashboard_mode_button}")
                # new_children = list()
                # for child, child_metadata in zip(draggable_children, stored_metadata):
                #     if type(child["props"]["children"]) is dict:
                #         child = enable_box_edit_mode(child["props"]["children"]["props"]["children"][-1], edit_dashboard_mode_button, component_data=child_metadata)
                #     elif type(child["props"]["children"]) is list:
                #         child = enable_box_edit_mode(child["props"]["children"][-1], edit_dashboard_mode_button, component_data=child_metadata)
                #     new_children.append(child)
                #     state_stored_draggable_children[dashboard_id] = new_children

                return (
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
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


def design_draggable(
    init_layout: dict, init_children: list[dict], dashboard_id: str, local_data: dict
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
        # display_style = "none"  # Hide the draggable layout
        core_children = [message]
    else:
        # display_style = "flex"  # Show the draggable layout
        core_children = []

    # logger.info(f"Init layout: {init_layout}")

    # Ensure init_layout has the required breakpoints
    # If init_layout is empty or None, initialize it with proper structure
    if not init_layout:
        init_layout = {}

    for key in required_breakpoints:
        if key not in init_layout:
            init_layout[key] = []
    # logger.info(f"Initialized layout with required breakpoints: {init_layout}")

    # Create the draggable layout outside of the if-else to keep it in the DOM
    draggable = html.Div(
        [
            # CSS injection for proper vertical growth
            dcc.Store(id="css-store"),
            dgl.DashGridLayout(
                id="draggable",
                items=init_children,
                itemLayout=init_layout.get("lg", []),  # Use lg breakpoint as primary
                # rowHeight=10,  # Flexible row height
                # cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                # style={
                #     "display": display_style,
                #     "minHeight": "400px",
                #     "width": "100%",
                # },
                # compactType="vertical",
                showRemoveButton=True,  # Will be controlled by edit mode - should never be displayed
                showResizeHandles=True,
                # margin=[10, 10],
                # autoSize=True,
                # allowOverlap=False,  # Enable resize visual feedback
                className="depictio-grid-layout",
            ),
        ]
    )

    # Add draggable to the core children list whether it's visible or not
    core_children.append(draggable)

    # The core Div contains all elements, managing visibility as needed
    core = html.Div(core_children)

    return core
