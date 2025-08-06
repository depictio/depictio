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
# Adjusted for 12-column grid with rowHeight=50 - optimized dimensions per component type
component_dimensions = get_component_dimensions_dict()
# No longer using breakpoints - working with direct list format


def calculate_new_layout_position(child_type, existing_layouts, child_id, n):
    """Calculate position for new layout item based on existing ones and type."""
    # Get the default dimensions from the type
    logger.info(
        f"🔄 CALCULATE_NEW_LAYOUT_POSITION CALLED: {child_type} with {n} existing components"
    )
    dimensions = component_dimensions.get(
        child_type, {"w": 6, "h": 8}
    )  # Default 6x8 for 12-column grid with rowHeight=50
    logger.info(f"📐 Selected dimensions: {dimensions} for {child_type}")
    logger.info(f"📋 Existing layouts: {existing_layouts}")

    columns_per_row = 12  # Updated for 12-column grid
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
                        existing_w = layout.get("w", 6)  # Use 12-column grid compatible default
                        existing_h = layout.get("h", 8)  # Use rowHeight=50 compatible default

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
        # "moved": False,
        # "static": False,
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


def fix_responsive_scaling(layout_data, metadata_list):
    """Fix responsive scaling by restoring proper dimensions based on component metadata."""
    if not layout_data or not metadata_list:
        return layout_data

    # Create a mapping of component IDs to their expected dimensions
    expected_dimensions = {}
    for meta in metadata_list:
        if meta.get("index") and meta.get("component_type"):
            comp_id = f"box-{meta['index']}"
            comp_type = meta["component_type"]
            expected_dims = component_dimensions.get(comp_type, {"w": 6, "h": 8})
            expected_dimensions[comp_id] = expected_dims

    fixed_layouts = []
    for layout in layout_data:
        if not isinstance(layout, dict):
            continue

        layout_copy = dict(layout)
        layout_id = layout.get("i", "")

        if layout_id in expected_dimensions:
            expected = expected_dimensions[layout_id]
            current_w = layout.get("w", 0)
            current_h = layout.get("h", 0)

            # Check if dimensions are halved (responsive scaling)
            if current_w == expected["w"] // 2 and current_h == expected["h"] // 2:
                logger.warning(
                    f"🔧 FIXING RESPONSIVE SCALING - {layout_id}: {current_w}x{current_h} → {expected['w']}x{expected['h']}"
                )
                layout_copy["w"] = expected["w"]
                layout_copy["h"] = expected["h"]
            # Check for other scaling ratios (md: 10/12, sm: 6/12, xs: 4/12)
            elif current_w * 12 // 10 == expected["w"] and current_h * 12 // 10 == expected["h"]:
                logger.warning(
                    f"🔧 FIXING MD SCALING - {layout_id}: {current_w}x{current_h} → {expected['w']}x{expected['h']}"
                )
                layout_copy["w"] = expected["w"]
                layout_copy["h"] = expected["h"]

        fixed_layouts.append(layout_copy)

    return fixed_layouts


def clean_layout_data(layouts):
    """Clean corrupted layout data by filtering out entries with invalid IDs, dimensions, or positions."""
    if not layouts:
        return []

    cleaned_layouts = []
    for layout in layouts:
        if isinstance(layout, dict) and "i" in layout:
            layout_id = layout["i"]

            # Check if this is a corrupted path-like ID
            if isinstance(layout_id, str) and (
                "props,children" in layout_id or len(layout_id.split(",")) > 3
            ):
                logger.warning(f"Filtering out corrupted layout entry (path-like ID): {layout_id}")
                continue

            # Check for invalid dimensions or positions (outside 12-column grid)
            x = layout.get("x", 0)
            w = layout.get("w", 0)

            # Filter out layouts that:
            # 1. Have x position >= 12 (outside grid)
            # 2. Have width > 12 (too wide for grid)
            # 3. Have x + width > 12 (extend beyond grid)
            if x >= 12 or w > 12 or (x + w > 12 and x > 0):
                logger.warning(
                    f"Filtering out layout entry with invalid position/size: ID={layout_id}, x={x}, w={w}"
                )
                continue

            cleaned_layouts.append(layout)
        else:
            # Keep non-dict entries or entries without 'i' key as they might be valid
            cleaned_layouts.append(layout)

    logger.info(f"Layout cleaning: {len(layouts)} -> {len(cleaned_layouts)} entries")
    return cleaned_layouts


def get_component_id(component):
    """Safely extract component ID from native Dash component or JSON representation."""
    try:
        # Check for direct id attribute
        if hasattr(component, "id") and component.id is not None:
            # Native Dash component
            return component.id

        # Check for JSON representation
        elif isinstance(component, dict) and "props" in component:
            # JSON representation
            return component["props"].get("id")

        # Check for DraggableWrapper or other wrapper components
        elif hasattr(component, "_namespace") and hasattr(component, "id"):
            # Component with namespace (like dash-dynamic-grid-layout)
            return component.id

        # Check if it's a more complex component structure
        elif hasattr(component, "__dict__"):
            comp_dict = component.__dict__
            if "id" in comp_dict:
                return comp_dict["id"]

        return None
    except (KeyError, AttributeError, TypeError):
        return None


def remove_duplicates_by_index(components):
    unique_components = {}
    for component in components:
        index = component["index"]
        if index not in unique_components:
            # First occurrence of this index
            unique_components[index] = component
        else:
            # Duplicate found - prefer the one with non-None parent_index
            existing = unique_components[index]
            current_parent = component.get("parent_index")
            existing_parent = existing.get("parent_index")

            # If current has parent_index but existing doesn't, prefer current
            if current_parent is not None and existing_parent is None:
                logger.debug(f"DEDUP: Replacing {index} (parent_index: None -> {current_parent})")
                unique_components[index] = component
            # If existing has parent_index but current doesn't, keep existing (do nothing)
            elif existing_parent is not None and current_parent is None:
                logger.debug(
                    f"DEDUP: Keeping {index} (parent_index: {existing_parent}, rejecting None)"
                )
                continue
            # If both have same parent_index status, prefer the one with more recent last_updated
            else:
                current_updated = component.get("last_updated")
                existing_updated = existing.get("last_updated")
                if current_updated and existing_updated:
                    if current_updated > existing_updated:
                        logger.debug(
                            f"DEDUP: Replacing {index} based on timestamp ({existing_updated} -> {current_updated})"
                        )
                        unique_components[index] = component
                # If last_updated is not available, keep existing (first occurrence)
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
                        # logger.info(
                        #     f"Component data retrieved for '{trigger_index}': {component_data}"
                        # )
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

        # logger.debug(f"Components store data after update: {components_store}")
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

        logger.info("\n===== DRAGGABLE CALLBACK TRIGGERED =====\n")

        logger.info("CTX: {}".format(ctx))
        logger.info("CTX triggered: {}".format(ctx.triggered))
        logger.info("CTX triggered_id: {}".format(ctx.triggered_id))
        logger.info("TYPE CTX triggered_id: {}".format(type(ctx.triggered_id)))
        logger.info("CTX triggered_props_id: {}".format(ctx.triggered_prop_ids))
        # logger.info("CTX args_grouping: {}".format(ctx.args_grouping))
        logger.info("CTX inputs: {}".format(ctx.inputs))
        logger.info("CTX inputs_list: {}".format(ctx.inputs_list))
        # logger.debug("CTX states: {}".format(ctx.states))
        # logger.debug("CTX states_list: {}".format(ctx.states_list))

        # logger.info(f"Input draggable layouts: {input_draggable_layouts}")
        # logger.info(f"Draggable layout : {draggable_layouts}")
        # logger.info(f"Stored draggable layouts: {state_stored_draggable_layouts}")
        # logger.info(f"Stored draggable children: {state_stored_draggable_children}")
        # logger.info(f"Input stored draggable children: {input_stored_draggable_children}")
        logger.info(f"Stored metadata: {stored_metadata}")
        logger.info("\n")

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
                    raw_layouts = stored_layouts.get("lg", [])
                else:
                    raw_layouts = stored_layouts

                # Clean any corrupted layouts and normalize properties
                cleaned_layouts = clean_layout_data(raw_layouts)
                logger.info(f"Cleaned layouts: {cleaned_layouts}")

                # CRITICAL: Remove orphaned layouts that don't have corresponding components
                if draggable_children:
                    component_ids = set()
                    for child in draggable_children:
                        # logger.info(f"Processing child: {child}")
                        child_id = get_component_id(child)
                        if child_id:
                            component_ids.add(child_id)

                    # Filter layouts to only include those with matching components
                    matched_layouts = []
                    for layout in cleaned_layouts:
                        layout_id = layout.get("i", "")
                        if layout_id in component_ids:
                            matched_layouts.append(layout)
                        else:
                            logger.warning(
                                f"🗑️ Removing orphaned layout: {layout_id} (no matching component)"
                            )

                    draggable_layouts = matched_layouts

                    logger.info(
                        f"Matched layouts after cleaning: {len(matched_layouts)} from {len(cleaned_layouts)}"
                    )
                else:
                    draggable_layouts = cleaned_layouts
                    logger.info(
                        f"Cleaned and normalized layouts loaded from storage: {len(raw_layouts)} -> {len(draggable_layouts)}"
                    )
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

        # Add comprehensive callback tracking
        callback_id = id(ctx) if ctx else "NO_CTX"
        logger.info(f"🚀 CALLBACK START - ID: {callback_id}")
        logger.info(f"Triggered input: {triggered_input}")
        logger.debug(f"🚀 CALLBACK DEBUG - ctx.triggered: {ctx.triggered if ctx else 'NO_CTX'}")
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

                child, index_returned = render_raw_children(
                    tmp_stored_metadata[0],
                    switch_state=unified_edit_mode_button,
                    dashboard_id=dashboard_id,
                    TOKEN=TOKEN,
                    theme=theme,
                )

                draggable_children.append(child)
                # Use the clean child_index from metadata instead of the potentially corrupted return value
                child_id = f"box-{str(child_index)}"
                logger.debug(f"🔍 DRAG DEBUG - child_index: {child_index}")
                logger.debug(f"🔍 DRAG DEBUG - index_returned: {index_returned}")
                logger.debug(f"🔍 DRAG DEBUG - child_id: {child_id}")
                logger.info(f"Child type: {child_type}")
                # Clean existing layouts before calculating new position
                clean_draggable_layouts = clean_layout_data(draggable_layouts)
                new_layout_item = calculate_new_layout_position(
                    child_type, clean_draggable_layouts, child_id, len(draggable_children)
                )

                # Add new layout item to the cleaned list
                clean_draggable_layouts.append(new_layout_item)
                draggable_layouts = clean_draggable_layouts  # Use cleaned layouts
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
                    logger.info("🔄 LAYOUT UPDATE - DashGridLayout currentLayout changed")
                    logger.info(
                        f"🔄 LAYOUT UPDATE - New layout received: {input_draggable_layouts}"
                    )

                    # Check if any dimensions were changed by responsive grid
                    if dashboard_id in state_stored_draggable_layouts:
                        stored_layouts = state_stored_draggable_layouts[dashboard_id]
                        for new_layout in input_draggable_layouts:
                            for stored_layout in stored_layouts:
                                if new_layout.get("i") == stored_layout.get("i"):
                                    if new_layout.get("w") != stored_layout.get(
                                        "w"
                                    ) or new_layout.get("h") != stored_layout.get("h"):
                                        logger.info(
                                            f"📏 DIMENSIONS CHANGED - {new_layout.get('i')}: {stored_layout.get('w')}x{stored_layout.get('h')} → {new_layout.get('w')}x{new_layout.get('h')}"
                                        )
                                        # Check if this looks like responsive scaling (halving)
                                        if new_layout.get("w", 0) * 2 == stored_layout.get(
                                            "w", 0
                                        ) and new_layout.get("h", 0) * 2 == stored_layout.get(
                                            "h", 0
                                        ):
                                            logger.warning(
                                                "⚠️ RESPONSIVE SCALING DETECTED - Dimensions halved (likely xs breakpoint)"
                                            )
                                        elif (
                                            new_layout.get("w", 0) * 3
                                            == stored_layout.get("w", 0) * 2
                                        ):
                                            logger.warning(
                                                "⚠️ RESPONSIVE SCALING DETECTED - Dimensions scaled by 2/3 (likely md breakpoint)"
                                            )
                                        logger.debug(
                                            f"📱 SCALE DEBUG - Width ratio: {new_layout.get('w', 0) / max(stored_layout.get('w', 1), 1):.2f}"
                                        )
                                        logger.debug(
                                            f"📱 SCALE DEBUG - Height ratio: {new_layout.get('h', 0) / max(stored_layout.get('h', 1), 1):.2f}"
                                        )

                    # dash-dynamic-grid-layout returns a single layout array - normalize and store it
                    state_stored_draggable_children[dashboard_id] = draggable_children
                    # Fix responsive scaling issues before normalizing
                    logger.info(
                        "🔧 RESPONSIVE FIX - Applying fixes to currentLayout before storing"
                    )
                    fixed_layouts = fix_responsive_scaling(input_draggable_layouts, stored_metadata)
                    # Normalize layout data to ensure consistent moved/static properties
                    state_stored_draggable_layouts[dashboard_id] = fixed_layouts

                    logger.info("🔄 LAYOUT UPDATE - Final stored layouts:")
                    for i, layout in enumerate(fixed_layouts):
                        logger.info(
                            f"  Stored Layout {i}: {layout.get('i')} -> {layout.get('w')}x{layout.get('h')} at ({layout.get('x')},{layout.get('y')})"
                        )

                    return (
                        draggable_children,
                        fixed_layouts,  # Return the normalized layout array
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

            # Handle scenarios where the user resets a component using the reset button
            elif "reset-selection-graph-button" in triggered_input:
                logger.info("Reset selection button triggered")

                # Find the component being reset
                reset_component_metadata = None
                ctx_triggered = ctx.triggered[0]
                ctx_triggered_prop_id = ctx_triggered["prop_id"]
                ctx_triggered_prop_id_index = eval(ctx_triggered_prop_id.split(".")[0])["index"]

                for metadata in stored_metadata:
                    if metadata["index"] == ctx_triggered_prop_id_index:
                        metadata["filter_applied"] = False
                        reset_component_metadata = metadata
                        break

                # Handle specific reset logic based on component type
                if reset_component_metadata:
                    component_type = reset_component_metadata.get("component_type")
                    logger.info(
                        f"Resetting {component_type} component: {ctx_triggered_prop_id_index}"
                    )

                    # For interactive components, clear their values in the interactive_components_dict
                    if component_type == "interactive":
                        if ctx_triggered_prop_id_index in interactive_components_dict:
                            # Clear the value for this interactive component
                            interactive_components_dict[ctx_triggered_prop_id_index]["value"] = None
                            logger.info(
                                f"Cleared value for interactive component: {ctx_triggered_prop_id_index}"
                            )

                    # For scatter plots, the filter_applied = False is sufficient
                    elif component_type == "figure":
                        visu_type = reset_component_metadata.get("visu_type", "")
                        if visu_type.lower() == "scatter":
                            logger.info(f"Reset scatter plot: {ctx_triggered_prop_id_index}")

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
                if graph_metadata.get("visu_type", "").lower() == "scatter":
                    # Handle scenarios where the user clicks on a specific point on the graph
                    if "clickData" in ctx_triggered_prop_id:
                        logger.info("Click data triggered")
                        result = refresh_children_based_on_click_data(
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
                        # Handle tuple return (new_children, updated_interactive_components)
                        if isinstance(result, tuple):
                            updated_children, _ = result
                        else:
                            updated_children = result

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
                        result = refresh_children_based_on_selected_data(
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
                        # Handle tuple return (new_children, updated_interactive_components)
                        if isinstance(result, tuple):
                            updated_children, _ = result
                        else:
                            updated_children = result

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
                component_id_to_remove = f"box-{input_id}"

                logger.debug(f"🗑️ REMOVE DEBUG - Removing component: {component_id_to_remove}")
                logger.debug(f"🗑️ REMOVE DEBUG - Current children count: {len(draggable_children)}")
                logger.debug(f"🗑️ REMOVE DEBUG - Current layouts count: {len(draggable_layouts)}")

                # Remove the component from children
                updated_children = [
                    child
                    for child in draggable_children
                    if get_component_id(child) != component_id_to_remove
                ]

                # Remove the corresponding layout entry
                updated_layouts = [
                    layout
                    for layout in draggable_layouts
                    if layout.get("i") != component_id_to_remove
                ]

                logger.debug(
                    f"🗑️ REMOVE DEBUG - After removal - children: {len(updated_children)}, layouts: {len(updated_layouts)}"
                )

                # Update the stored layouts
                state_stored_draggable_layouts[dashboard_id] = updated_layouts

                return (
                    updated_children,
                    updated_layouts,
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
                    child_id = get_component_id(child)
                    logger.info(f"Child ID: {child_id}")
                    if child_id == f"box-{input_id}":
                        # Handle both native Dash components and JSON representations
                        if hasattr(child, "children") and hasattr(child, "id"):
                            # Native Dash component - create new component with updated children
                            child = type(child)(id=child.id, children=edited_modal)
                        elif isinstance(child, dict) and "props" in child:
                            # JSON representation
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
                logger.info("=== BTN-DONE-EDIT TRIGGERED ===")
                logger.info("Re-rendering dashboard with updated component parameters")
                logger.info(f"Stored metadata: {stored_metadata}")

                index = ctx.triggered_id["index"]

                edited_child = None
                parent_index = None
                logger.info(f"Index: {index}")
                # logger.info(f"Stored metadata: {stored_metadata}")
                # logger.info(f"test_container: {test_container}")
                logger.info(f"Looking for metadata with index: {index}")
                logger.info(f"Available metadata entries for index {index}:")
                for i, metadata in enumerate(stored_metadata):
                    if str(metadata["index"]) == str(index):
                        logger.info(
                            f"  Entry {i}: parent_index={metadata.get('parent_index')}, last_updated={metadata.get('last_updated')}"
                        )
                # Find metadata for the edited component, prioritizing entries with non-None parent_index
                parent_index = None
                parent_metadata = None
                for metadata in stored_metadata:
                    if str(metadata["index"]) == str(index):
                        # If this is our first match or if this has a non-None parent_index
                        # while our current match has None, prefer this one
                        if parent_metadata is None or (
                            parent_index is None and metadata.get("parent_index") is not None
                        ):
                            parent_index = metadata["parent_index"]
                            parent_metadata = metadata
                        # If we already have a non-None parent_index, don't overwrite it with None
                        elif parent_index is not None and metadata.get("parent_index") is None:
                            continue
                        else:
                            # Update with this metadata (both have same parent_index status)
                            parent_index = metadata["parent_index"]
                            parent_metadata = metadata

                logger.info(f"Selected parent_index: {parent_index} for index: {index}")
                for child, metadata in zip(test_container, stored_metadata):
                    # Extract child index safely
                    child_index = None
                    try:
                        if hasattr(child, "id") and isinstance(child.id, dict):
                            # Native Dash component with dict ID
                            child_index = str(child.id.get("index", ""))
                        elif isinstance(child, dict) and "props" in child:
                            # JSON representation
                            child_id = child["props"].get("id")
                            if isinstance(child_id, dict):
                                child_index = str(child_id.get("index", ""))
                            else:
                                child_index = str(child_id) if child_id else ""

                        if not child_index:
                            continue

                    except (KeyError, AttributeError, TypeError) as e:
                        logger.warning(f"Error extracting child index: {e}")
                        continue

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
                    temp_parent_box_id = f"box-{parent_index}-tmp"
                    parent_box_id = f"box-{parent_index}"

                    for child in draggable_children:
                        child_id = get_component_id(child)
                        if child_id == parent_box_id:
                            updated_children.append(edited_child)  # Replace the original component
                            logger.info(f"Replaced component with box ID: {parent_box_id}")
                        elif child_id == temp_parent_box_id:
                            logger.info(f"Removed temp component with box ID: {temp_parent_box_id}")
                            # Skip adding the temp component (remove it)
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
                logger.info("=" * 80)
                logger.info("🚨 DUPLICATE CALLBACK EXECUTION START")
                logger.info("=" * 80)
                logger.debug(f"🔍 DUPLICATE DEBUG - ctx.triggered: {ctx.triggered}")
                logger.debug(f"🔍 DUPLICATE DEBUG - ctx.triggered_id: {ctx.triggered_id}")
                logger.debug(f"🔍 DUPLICATE DEBUG - Total triggered items: {len(ctx.triggered)}")

                # Check ALL triggered inputs to understand multiple triggers
                for i, triggered_item in enumerate(ctx.triggered):
                    logger.debug(f"🔍 DUPLICATE DEBUG - Triggered item {i}: {triggered_item}")

                # Log current dashboard state before duplication
                logger.debug(
                    f"🔍 DUPLICATE DEBUG - Current draggable_children count: {len(draggable_children) if draggable_children else 0}"
                )
                logger.debug(
                    f"🔍 DUPLICATE DEBUG - Current draggable_layouts count: {len(draggable_layouts) if draggable_layouts else 0}"
                )
                if draggable_layouts:
                    for i, layout in enumerate(draggable_layouts):
                        logger.debug(
                            f"🔍 DUPLICATE DEBUG - Existing layout {i}: {layout.get('i', 'NO_ID')} at ({layout.get('x', '?')},{layout.get('y', '?')})"
                        )

                # Check if this is actually a triggered button (non-zero clicks)
                triggered_button_clicks = ctx.triggered[0]["value"]
                if not triggered_button_clicks or triggered_button_clicks == 0:
                    logger.debug(
                        "🔍 DUPLICATE DEBUG - Button not actually clicked (0 clicks), skipping"
                    )
                    return (
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )

                # CRITICAL: Check if there are multiple triggers and only process the first one
                if len(ctx.triggered) > 1:
                    logger.debug(
                        f"🔍 DUPLICATE DEBUG - Multiple triggers detected ({len(ctx.triggered)}), processing only the first one"
                    )
                    # Only process if this is the first trigger or they're all the same
                    first_trigger_id = ctx.triggered[0]["prop_id"]
                    current_trigger_id = f'{{"index":"{ctx.triggered_id["index"]}","type":"duplicate-box-button"}}.n_clicks'
                    if first_trigger_id != current_trigger_id:
                        logger.debug(
                            f"🔍 DUPLICATE DEBUG - Skipping duplicate trigger: {current_trigger_id}"
                        )
                        return (
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                        )

                triggered_index = ctx.triggered_id["index"]

                logger.debug(f"🔍 DUPLICATE DEBUG - Looking for component: box-{triggered_index}")
                logger.debug(
                    f"🔍 DUPLICATE DEBUG - Number of draggable_children: {len(draggable_children)}"
                )
                logger.debug(f"🔍 DUPLICATE DEBUG - Current draggable_layouts: {draggable_layouts}")

                # Check if we're already processing a duplication for this component
                duplicate_target_id = f"box-{triggered_index}"
                existing_duplicates = [
                    layout
                    for layout in draggable_layouts
                    if layout.get("i", "").startswith("box-") and layout["i"] != duplicate_target_id
                ]
                logger.debug(
                    f"🔍 DUPLICATE DEBUG - Existing components count: {len(existing_duplicates) + 1}"
                )  # +1 for original

                # Debug: log all component IDs and structures
                for i, child in enumerate(draggable_children):
                    child_id = get_component_id(child)
                    logger.debug(f"🔍 DUPLICATE DEBUG - Child {i}: ID = {child_id}")
                    logger.debug(f"🔍 DUPLICATE DEBUG - Child {i}: type = {type(child)}")
                    logger.debug(
                        f"🔍 DUPLICATE DEBUG - Child {i}: hasattr(child, 'id') = {hasattr(child, 'id')}"
                    )
                    if hasattr(child, "id"):
                        logger.debug(f"🔍 DUPLICATE DEBUG - Child {i}: child.id = {child.id}")
                    if isinstance(child, dict):
                        logger.debug(
                            f"🔍 DUPLICATE DEBUG - Child {i}: dict keys = {list(child.keys())}"
                        )
                        if "props" in child:
                            logger.debug(
                                f"🔍 DUPLICATE DEBUG - Child {i}: props keys = {list(child['props'].keys())}"
                            )
                    # Show first 200 chars of the component structure
                    child_str = str(child)[:200] + "..." if len(str(child)) > 200 else str(child)
                    logger.debug(f"🔍 DUPLICATE DEBUG - Child {i}: structure = {child_str}")

                component_to_duplicate = None
                for child in draggable_children:
                    child_id = get_component_id(child)
                    if child_id == f"box-{triggered_index}":
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
                logger.debug(f"🔍 DUPLICATE DEBUG - Generated new component ID: {child_id}")
                logger.debug(
                    f"🔍 DUPLICATE DEBUG - About to create duplicate of: {duplicate_target_id}"
                )

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
                # Clean existing layouts to remove any corrupted entries
                existing_layouts = clean_layout_data(draggable_layouts)

                # Fix any responsive scaling issues in existing layouts
                logger.info(
                    "🔧 RESPONSIVE FIX - Applying responsive scaling corrections to existing layouts"
                )
                existing_layouts = fix_responsive_scaling(existing_layouts, stored_metadata)

                # DEBUG: Check for responsive scaling in existing layouts
                logger.debug("🔍 RESPONSIVE DEBUG - Checking existing layouts after fixes:")
                expected_dims = component_dimensions.get(
                    metadata["component_type"], {"w": 6, "h": 8}
                )
                logger.debug(
                    f"🔍 RESPONSIVE DEBUG - Expected dimensions for {metadata['component_type']}: {expected_dims}"
                )

                for i, layout in enumerate(existing_layouts):
                    actual_w = layout.get("w", 0)
                    actual_h = layout.get("h", 0)
                    if actual_w == expected_dims["w"] // 2 and actual_h == expected_dims["h"] // 2:
                        logger.warning(
                            f"⚠️ RESPONSIVE SCALING STILL DETECTED in layout {i}: {layout.get('i')} has w:{actual_w}, h:{actual_h} (expected w:{expected_dims['w']}, h:{expected_dims['h']})"
                        )
                    logger.debug(
                        f"🔍 RESPONSIVE DEBUG - Layout {i}: {layout.get('i')} -> w:{actual_w}, h:{actual_h}"
                    )

                n = len(updated_children)  # Position based on the number of components

                new_layout = calculate_new_layout_position(
                    metadata["component_type"],
                    existing_layouts,
                    child_id,
                    n,
                )

                logger.debug(f"🔍 DUPLICATE DEBUG - Component type: {metadata['component_type']}")
                logger.debug(f"🔍 DUPLICATE DEBUG - New layout created: {new_layout}")
                logger.debug(
                    f"🔍 DUPLICATE DEBUG - Expected dimensions for {metadata['component_type']}: {component_dimensions.get(metadata['component_type'], {'w': 6, 'h': 8})}"
                )

                # Add new layout item to the cleaned list
                existing_layouts.append(new_layout)
                draggable_layouts = existing_layouts  # Use cleaned layouts

                logger.info(
                    f"Duplicated component with new id 'box-{new_index}' and assigned layout {new_layout}"
                )

                # state_stored_draggable_children[dashboard_id] = updated_children
                state_stored_draggable_layouts[dashboard_id] = draggable_layouts

                logger.info("=" * 80)
                logger.info("🔚 DUPLICATE CALLBACK EXECUTION END")
                logger.debug(f"🔍 DUPLICATE DEBUG - Final children count: {len(updated_children)}")
                logger.debug(f"🔍 DUPLICATE DEBUG - Final layouts count: {len(draggable_layouts)}")
                logger.debug(f"🔍 DUPLICATE DEBUG - New component created: {child_id}")
                logger.debug("🔍 DUPLICATE DEBUG - Final layout data being returned:")
                for i, layout in enumerate(draggable_layouts):
                    logger.debug(
                        f"  Layout {i}: {layout.get('i')} -> {layout.get('w')}x{layout.get('h')} at ({layout.get('x')},{layout.get('y')})"
                    )
                logger.info("=" * 80)

                return (
                    updated_children,
                    draggable_layouts,
                    dash.no_update,
                    state_stored_draggable_layouts,
                    dash.no_update,
                )

            elif triggered_input == "remove-all-components-button":
                logger.info("Remove all components button clicked")
                logger.info("🗑️ REMOVE ALL - Clearing all components and layouts")

                # Clear all layouts - use empty list format (not dict)
                empty_layouts = []
                state_stored_draggable_layouts[dashboard_id] = empty_layouts

                logger.info(f"🗑️ REMOVE ALL - Cleared layouts for dashboard {dashboard_id}")

                return (
                    [],  # Empty children
                    empty_layouts,  # Empty layouts (list format)
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
        [
            Input({"type": "interactive-component-value", "index": ALL}, "value"),
            Input({"type": "graph", "index": ALL}, "clickData"),
            Input({"type": "graph", "index": ALL}, "selectedData"),
            Input({"type": "reset-selection-graph-button", "index": ALL}, "n_clicks"),
            Input("reset-all-filters-button", "n_clicks"),
        ],
        [
            State({"type": "interactive-component-value", "index": ALL}, "id"),
            State({"type": "stored-metadata-component", "index": ALL}, "data"),
            State({"type": "graph", "index": ALL}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
            State("interactive-values-store", "data"),  # Add current store state
        ],
        prevent_initial_call=True,
    )
    def update_interactive_values_store(
        interactive_values,
        graph_click_data,
        graph_selected_data,
        reset_button_clicks,
        reset_all_clicks,
        ids,
        stored_metadata,
        graph_ids,
        local_store,
        pathname,
        current_store_data,
    ):
        from depictio.dash.layouts.draggable_scenarios.graphs_interactivity import (
            process_click_data,
            process_selected_data,
        )

        logger.info("Callback 'update_interactive_values_store' triggered.")

        # Extract dashboard_id from the URL pathname
        try:
            dashboard_id = pathname.split("/")[-1]
            logger.debug(f"Dashboard ID: {dashboard_id}")
        except Exception as e:
            logger.error(f"Error extracting dashboard_id from pathname '{pathname}': {e}")
            raise dash.exceptions.PreventUpdate

        # Check what triggered the callback
        ctx = dash.callback_context
        triggered_prop_ids = [t["prop_id"] for t in ctx.triggered]
        logger.info(f"Triggered by: {triggered_prop_ids}")

        # Start with existing interactive components
        stored_metadata_interactive = [
            e for e in stored_metadata if e["component_type"] == "interactive"
        ]
        stored_metadata_interactive = remove_duplicates_by_index(stored_metadata_interactive)

        components = []
        scatter_plot_components = {}

        # Check trigger types
        graph_triggered = any("graph" in prop_id for prop_id in triggered_prop_ids)
        interactive_triggered = any(
            "interactive-component-value" in prop_id for prop_id in triggered_prop_ids
        )
        reset_triggered = any(
            "reset-selection-graph-button" in prop_id or "reset-all-filters-button" in prop_id
            for prop_id in triggered_prop_ids
        )

        logger.info(
            f"🎯 Trigger analysis: graph={graph_triggered}, interactive={interactive_triggered}, reset={reset_triggered}"
        )

        # Handle reset buttons first (they take priority)
        if reset_triggered:
            logger.info("🔄 Reset button detected in main store callback")

            # Check if this is actually a button click (not initialization)
            triggered_value = ctx.triggered[0]["value"]
            if not triggered_value or triggered_value == 0:
                logger.info(
                    f"🔄 Skipping reset - no actual button click (value: {triggered_value})"
                )
            else:
                triggered_prop_id = ctx.triggered[0]["prop_id"]
                logger.info(f"🔄 Processing reset: {triggered_prop_id}")

                # Start with current store data
                if not current_store_data:
                    current_store_data = {"interactive_components_values": []}

                current_components = current_store_data.get("interactive_components_values", [])

                if "reset-all-filters-button" in triggered_prop_id:
                    logger.info("🔄 Reset all filters in main callback")
                    # Remove all scatter plot filters and reset interactive components to defaults
                    filtered_components = []
                    for component in current_components:
                        component_id = component.get("index", "")
                        if component_id.startswith("filter_"):
                            logger.info(f"🔄 Removed scatter plot filter: {component_id}")
                        else:
                            # Reset interactive component to default
                            component_metadata = component.get("metadata", {})
                            default_state = component_metadata.get("default_state", {})

                            reset_component = component.copy()
                            if "default_range" in default_state:
                                reset_component["value"] = default_state["default_range"]
                            elif "default_value" in default_state:
                                reset_component["value"] = default_state["default_value"]
                            else:
                                reset_component["value"] = None

                            filtered_components.append(reset_component)
                            logger.info(f"🔄 Reset interactive component {component_id} to default")

                    output_data = {"interactive_components_values": filtered_components}
                    logger.info(f"🔄 Reset all completed: {len(filtered_components)} components")
                    return output_data

                elif "reset-selection-graph-button" in triggered_prop_id:
                    logger.info("🔄 Individual reset in main callback")
                    try:
                        component_index = eval(triggered_prop_id.split(".")[0])["index"]
                        logger.info(f"🔄 Resetting component: {component_index}")

                        # Find component metadata
                        component_metadata = None
                        for meta in stored_metadata:
                            if meta and meta.get("index") == component_index:
                                component_metadata = meta
                                break

                        if component_metadata:
                            component_type = component_metadata.get("component_type")

                            if (
                                component_type == "figure"
                                and component_metadata.get("visu_type", "").lower() == "scatter"
                            ):
                                # Remove scatter plot filters
                                filtered_components = [
                                    c
                                    for c in current_components
                                    if not (
                                        c.get("index", "").startswith("filter_")
                                        and component_index in c.get("index", "")
                                    )
                                ]
                                logger.info(
                                    f"🔄 Removed scatter plot filters for {component_index}"
                                )
                            elif component_type == "interactive":
                                # Reset interactive component
                                filtered_components = []
                                for component in current_components:
                                    if component.get("index") == component_index:
                                        default_state = component.get("metadata", {}).get(
                                            "default_state", {}
                                        )
                                        reset_component = component.copy()

                                        if "default_range" in default_state:
                                            reset_component["value"] = default_state[
                                                "default_range"
                                            ]
                                        elif "default_value" in default_state:
                                            reset_component["value"] = default_state[
                                                "default_value"
                                            ]
                                        else:
                                            reset_component["value"] = None

                                        filtered_components.append(reset_component)
                                        logger.info(
                                            f"🔄 Reset interactive component {component_index}"
                                        )
                                    else:
                                        filtered_components.append(component)
                            else:
                                filtered_components = current_components

                            output_data = {"interactive_components_values": filtered_components}
                            logger.info(
                                f"🔄 Individual reset completed: {len(filtered_components)} components"
                            )
                            return output_data

                    except Exception as e:
                        logger.error(f"Error processing individual reset: {e}")

            # If reset didn't process, continue with normal logic
            logger.info("🔄 Reset trigger detected but not processed, continuing with normal logic")
        logger.info(
            f"🎯 Current store has {len(current_store_data.get('interactive_components_values', [])) if current_store_data else 0} existing components"
        )

        # Check if we have any actual graph data to process (needed early for filter preservation logic)
        has_actual_graph_data = False
        if graph_triggered:
            if graph_click_data:
                has_actual_graph_data = any(
                    click_data and click_data.get("points") and len(click_data["points"]) > 0
                    for click_data in graph_click_data
                )

            if graph_selected_data and not has_actual_graph_data:
                has_actual_graph_data = any(
                    selected_data
                    and selected_data.get("points")
                    and len(selected_data["points"]) > 0
                    for selected_data in graph_selected_data
                )

            logger.info(f"🎯 Has actual graph data to process: {has_actual_graph_data}")

        # Handle regular interactive component updates
        if (
            interactive_values
            and ids
            and len(interactive_values) == len(ids) == len(stored_metadata_interactive)
        ):
            for value, metadata in zip(interactive_values, stored_metadata_interactive):
                if metadata is None:
                    logger.warning(f"Metadata is None for a component with value: {value}")
                    continue
                components.append(
                    {"value": value, "metadata": metadata, "index": metadata["index"]}
                )

        # Get the graph that was triggered (if any) to avoid duplicate filters
        triggered_graph_index = None
        if graph_triggered:
            for prop_id in triggered_prop_ids:
                if "graph" in prop_id:
                    try:
                        graph_id_str = prop_id.split(".")[0]
                        graph_id_dict = eval(graph_id_str)
                        triggered_graph_index = graph_id_dict["index"]
                        break
                    except Exception:
                        continue

        # Always preserve existing scatter plot filters unless we're specifically updating them
        if current_store_data and "interactive_components_values" in current_store_data:
            # Find existing scatter plot filters and preserve them (except for triggered graph)
            for existing_component in current_store_data["interactive_components_values"]:
                if isinstance(existing_component, dict):
                    component_index = existing_component.get("index", "")
                    # Check if this is a scatter plot generated filter (starts with "filter_")
                    if component_index.startswith("filter_"):
                        # Only remove if this is the same graph AND we have actual new data
                        should_replace = (
                            triggered_graph_index
                            and triggered_graph_index in component_index
                            and has_actual_graph_data
                        )

                        if not should_replace:
                            components.append(existing_component)
                            logger.info(
                                f"🎯 Preserved existing scatter plot filter: {component_index}"
                            )
                        else:
                            logger.info(
                                f"🎯 Removing old filter for triggered graph (will be replaced): {component_index}"
                            )

        # Handle scatter plot interactions
        if graph_triggered:
            logger.info("🎯 Graph interaction detected in store update")

            # Only process graph interactions if we have actual data
            # This prevents clearing filters when Dash sends empty data on subsequent triggers
            if has_actual_graph_data:
                # Find which graph was triggered
                for prop_id in triggered_prop_ids:
                    if "graph" in prop_id:
                        try:
                            # Parse the triggered graph index
                            graph_id_str = prop_id.split(".")[0]
                            graph_id_dict = eval(graph_id_str)
                            ctx_triggered_prop_id_index = graph_id_dict["index"]

                            # Get the corresponding graph metadata
                            graph_metadata = None
                            for meta in stored_metadata:
                                if meta.get("index") == ctx_triggered_prop_id_index:
                                    graph_metadata = meta
                                    break

                            if (
                                not graph_metadata
                                or graph_metadata.get("visu_type", "").lower() != "scatter"
                            ):
                                continue

                            logger.info(
                                f"🎯 Processing scatter plot interaction for {ctx_triggered_prop_id_index}"
                            )

                            # Get token from local store
                            TOKEN = None
                            if local_store and "access_token" in local_store:
                                TOKEN = local_store["access_token"]

                            if not TOKEN:
                                logger.warning(
                                    "No access token available for scatter plot processing"
                                )
                                continue

                            # Process click data
                            if "clickData" in prop_id and graph_click_data:
                                logger.info(f"🎯 Processing clickData: {graph_click_data}")
                                for i, click_data in enumerate(graph_click_data):
                                    logger.info(
                                        f"🎯 Checking click_data[{i}]: {click_data} for graph {graph_ids[i]['index'] if i < len(graph_ids) else 'N/A'}"
                                    )
                                    if (
                                        click_data
                                        and i < len(graph_ids)
                                        and graph_ids[i]["index"] == ctx_triggered_prop_id_index
                                    ):
                                        # Only process if there are actual clicked points
                                        if (
                                            click_data.get("points")
                                            and len(click_data["points"]) > 0
                                        ):
                                            dict_graph_data = {
                                                "value": click_data["points"][0],
                                                "metadata": graph_metadata,
                                            }
                                            scatter_plot_components = process_click_data(
                                                dict_graph_data, {}, TOKEN
                                            )
                                            logger.info(
                                                f"🎯 Click data processed: {len(scatter_plot_components)} components"
                                            )
                                        else:
                                            logger.info(
                                                f"🎯 No click points - click_data: {click_data}"
                                            )
                                        break

                            # Process selected data
                            elif "selectedData" in prop_id and graph_selected_data:
                                logger.info(f"🎯 Processing selectedData: {graph_selected_data}")
                                for i, selected_data in enumerate(graph_selected_data):
                                    logger.info(
                                        f"🎯 Checking selected_data[{i}]: {selected_data} for graph {graph_ids[i]['index'] if i < len(graph_ids) else 'N/A'}"
                                    )
                                    if (
                                        selected_data
                                        and i < len(graph_ids)
                                        and graph_ids[i]["index"] == ctx_triggered_prop_id_index
                                    ):
                                        # Only process if there are actual selected points
                                        if (
                                            selected_data.get("points")
                                            and len(selected_data["points"]) > 0
                                        ):
                                            dict_graph_data = {
                                                "value": selected_data["points"],
                                                "metadata": graph_metadata,
                                            }
                                            scatter_plot_components = process_selected_data(
                                                dict_graph_data, {}, TOKEN
                                            )
                                            logger.info(
                                                f"🎯 Selected data processed: {len(scatter_plot_components)} components"
                                            )
                                        else:
                                            logger.info(
                                                f"🎯 No selected points - selected_data: {selected_data}"
                                            )
                                        break

                        except Exception as e:
                            logger.error(f"Error processing graph interaction: {e}")
                            continue
            else:
                logger.info(
                    "🎯 No actual graph data - preserving existing filters and skipping graph processing"
                )

        # Add scatter plot generated components to the store
        if scatter_plot_components:
            for component_key, component_data in scatter_plot_components.items():
                if isinstance(component_data, dict) and component_data.get("metadata"):
                    # Enhance metadata to match expected format for table filtering
                    enhanced_metadata = component_data.get("metadata", {}).copy()
                    enhanced_metadata["component_type"] = (
                        "interactive"  # Critical for table filtering
                    )
                    enhanced_metadata["index"] = component_key  # Ensure proper index

                    _tmp_metadata = {
                        "value": component_data.get("value"),
                        "metadata": enhanced_metadata,
                        "index": component_key,
                    }
                    components.append(_tmp_metadata)
                    logger.info(
                        f"🎯 Added scatter plot component: {component_key} with enhanced metadata: {_tmp_metadata}"
                    )

        # Final check: prevent accidental loss of scatter plot filters
        scatter_filters_before = 0
        scatter_filters_after = 0

        if current_store_data and "interactive_components_values" in current_store_data:
            scatter_filters_before = len(
                [
                    c
                    for c in current_store_data["interactive_components_values"]
                    if c.get("index", "").startswith("filter_")
                ]
            )

        scatter_filters_after = len(
            [c for c in components if c.get("index", "").startswith("filter_")]
        )

        logger.info(
            f"🎯 Scatter filters: before={scatter_filters_before}, after={scatter_filters_after}"
        )

        # If we're losing scatter plot filters without a graph trigger, prevent the update
        if (
            scatter_filters_before > 0
            and scatter_filters_after == 0
            and not graph_triggered
            and current_store_data
        ):
            logger.warning(
                "🚨 Preventing accidental loss of scatter plot filters - keeping current store"
            )
            return current_store_data

        output_data = {"interactive_components_values": components}
        logger.info(f"🎯 Store updated with {len(components)} total components")
        logger.info(f"🎯 Final scatter filter count: {scatter_filters_after}")
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

    # Debug logging for grid configuration
    logger.debug("🔍 GRID DEBUG - Creating DashGridLayout with configuration:")
    logger.debug("🔍 GRID DEBUG - rowHeight: 50")
    logger.debug("🔍 GRID DEBUG - cols: {'lg': 12, 'md': 12, 'sm': 12, 'xs': 12, 'xxs': 12}")
    logger.debug(
        f"🔍 GRID DEBUG - current_layout items: {len(current_layout) if current_layout else 0}"
    )
    if current_layout:
        for i, layout_item in enumerate(current_layout):
            logger.debug(f"🔍 GRID DEBUG - layout item {i}: {layout_item}")

    draggable = dgl.DashGridLayout(
        id="draggable",
        items=draggable_items,
        itemLayout=current_layout,
        rowHeight=50,  # Larger row height for better component display
        cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
        showRemoveButton=False,  # Keep consistent - CSS handles visibility
        showResizeHandles=True,  # Enable resize functionality for vertical growing behavior
        className="draggable-grid-container",  # CSS class for styling
        allowOverlap=False,
        # Additional parameters to try to disable responsive scaling
        autoSize=True,  # Let grid auto-size instead of using responsive breakpoints
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
