import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import httpx
from dash import ALL, Input, Output, State, ctx, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.colors import colors

# Import centralized component dimensions from metadata
from depictio.dash.component_metadata import get_build_functions, get_component_dimensions_dict

# Depictio layout imports for stepper
# Depictio layout imports for header
from depictio.dash.utils import (
    get_component_data,
    return_dc_tag_from_id,
    return_wf_tag_from_id,
)

# Get component dimensions and build functions from centralized metadata
# Adjusted for 48-column grid with rowHeight=20 - ultra-fine precision for component placement
component_dimensions = get_component_dimensions_dict()
build_functions = get_build_functions()
# No longer using breakpoints - working with direct list format


# KEEPME - MODULARISE
def calculate_new_layout_position(child_type, existing_layouts, child_id, n):
    """Calculate position for new layout item based on existing ones and type."""
    # Get the default dimensions from the type
    logger.info(
        f"🔄 CALCULATE_NEW_LAYOUT_POSITION CALLED: {child_type} with {n} existing components"
    )
    dimensions = component_dimensions.get(
        child_type, {"w": 20, "h": 16}
    )  # Default 20x16 for 48-column grid with rowHeight=20
    logger.info(f"📐 Selected dimensions: {dimensions} for {child_type}")
    logger.info(f"📋 Existing layouts: {existing_layouts}")

    columns_per_row = 48  # Updated for 48-column grid
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
                        existing_w = layout.get("w", 24)  # Use 48-column grid compatible default
                        existing_h = layout.get("h", 20)  # Use rowHeight=20 compatible default

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


# KEEPME - MODULARISE
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


# KEEPME - MODULARISE - TO EVALUATE
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

            # If current has parent_index but existing doesn't, prefer current but preserve all fields
            if current_parent is not None and existing_parent is None:
                logger.debug(f"DEDUP: Replacing {index} (parent_index: None -> {current_parent})")
                # Merge: start with existing, update with current, preserving important fields
                merged_component = {**existing, **component}
                # Preserve code_content if it exists in either version
                if existing.get("code_content") and not component.get("code_content"):
                    merged_component["code_content"] = existing["code_content"]
                    logger.debug(f"DEDUP: Preserved code_content for component {index}")
                unique_components[index] = merged_component
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
                        # Merge: start with existing, update with current, preserving important fields
                        merged_component = {**existing, **component}
                        # Preserve code_content if it exists in existing but not in current
                        if existing.get("code_content") and not component.get("code_content"):
                            merged_component["code_content"] = existing["code_content"]
                            logger.debug(f"DEDUP: Preserved code_content for component {index}")
                        unique_components[index] = merged_component
                # If last_updated is not available, keep existing (first occurrence)
    return list(unique_components.values())


# KEEPME - MODULARISE
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


# KEEPME - TO EVALUATE
def find_component_by_type(component, target_type, target_index):
    """
    Recursively search for a component with specific type and index in the component tree.

    Args:
        component: The component to search within
        target_type: The type of component to find (e.g., "stored-metadata-component")
        target_index: The index to match

    Returns:
        List of matching components
    """
    matches = []

    # Check if this is the component we're looking for
    if hasattr(component, "id") and isinstance(component.id, dict):
        if component.id.get("type") == target_type and component.id.get("index") == target_index:
            # Extract the data from the Store component
            if hasattr(component, "data"):
                matches.append({"data": component.data})

    # Recursively search children
    if hasattr(component, "children"):
        children = component.children
        if children is not None:
            # Handle both single child and list of children
            if not isinstance(children, list):
                children = [children]

            for child in children:
                if child is not None:
                    matches.extend(find_component_by_type(child, target_type, target_index))

    return matches


def register_callbacks_draggable(app):
    # KEEPME - MODULARISE - TO EVALUATE
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

        PERFORMANCE OPTIMIZATION (Phase 3): Early return for URL-triggered callbacks.
        When this callback is triggered by URL pathname changes (dashboard navigation),
        we skip processing because metadata is already loaded by dashboard restore.
        This eliminates ~2359ms on page load for dashboards with 11 components.

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
        # PERFORMANCE OPTIMIZATION: Skip processing on URL-triggered callbacks
        # Dashboard restore already loads all component metadata from database
        # This callback only needs to run when users edit/duplicate components
        logger.info(f"[PERF] Metadata callback triggered by: {ctx.triggered_id}")
        if ctx.triggered_id == "url":
            logger.info(f"[PERF] Metadata callback SKIPPED for URL change: {pathname}")
            return components_store or dash.no_update

        logger.info(f"[PERF] Metadata callback PROCESSING (triggered by: {ctx.triggered_id})")
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

    # ============================================================================
    # CLEARME SECTION REMOVED
    # ============================================================================
    # The monolithic populate_draggable() callback (2,200+ lines) has been removed.
    #
    # ✅ ALREADY REPLACED - No action needed:
    #   - Add component → add_component_simple.py
    #   - Edit component → edit_component_simple.py, edit_page.py
    #   - Remove component → remove_component_simple.py
    #   - Layout changes → Active callback below (update_interactive_values_store)
    #   - Interactive filters → Pattern-matching with interactive-values-store
    #   - Edit mode toggle → Active callback below (update_grid_edit_mode)
    #   - Reset filters → Store pattern (update_interactive_values_store)
    #
    # 🔴 TODO - FUTURE RESTORATION REQUIRED:
    #   1. Graph Interactions (clickData/selectedData filtering)
    #      - Functions exist in draggable_scenarios/graphs_interactivity.py
    #      - Need callback to connect to interactive-values-store pattern
    #
    #   2. Duplicate Component (full component duplication)
    #      - Deep copy with layout collision avoidance
    #      - Metadata cloning with permission checks
    #
    # 📋 Complete implementation details: dev/draggable/CLEARME_DOCUMENTATION.md
    # ============================================================================

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
    # TEMPORARILY DISABLED: Old modal-based add-button system
    # Replaced by simple direct add callback in add_component_simple.py
    # @app.callback(
    #     Output("test-output", "children"),
    #     Output("stored-add-button", "data"),
    #     Output("initialized-add-button", "data"),
    #     Output("notes-footer-content", "className", allow_duplicate=True),
    #     Output("page-content", "className", allow_duplicate=True),
    #     # Output("initialized-edit-button", "data"),
    #     Input("add-button", "n_clicks"),
    #     # Input({"type": "edit-box-button", "index": ALL}, "n_clicks"),
    #     State("stored-add-button", "data"),
    #     State("initialized-add-button", "data"),
    #     State("notes-footer-content", "className"),
    #     State("page-content", "className"),
    #     # State("initialized-edit-button", "data"),
    #     prevent_initial_call=True,
    # )
    # def trigger_modal(
    #     add_button_nclicks,
    #     #   edit_button_nclicks,
    #     stored_add_button,
    #     initialized_add_button,
    #     current_footer_class,
    #     current_page_class,
    #     # initialized_edit_button,
    # ):
    #     # logger.info("\n\nTrigger modal")
    #     # logger.info(f"n_clicks: {add_button_nclicks}")
    #     # logger.info(f"stored_add_button: {stored_add_button}")
    #     # logger.info(f"initialized_add_button: {initialized_add_button}")
    #     # logger.info(f"edit_button_nclicks: {edit_button_nclicks}")
    #     # logger.info(f"initialized_edit_button: {initialized_edit_button}")

    #     if not initialized_add_button:
    #         logger.info("Initializing add button")
    #         return dash.no_update, dash.no_update, True, dash.no_update, dash.no_update
    #         # return dash.no_update, dash.no_update, True, dash.no_update

    #     # if not initialized_edit_button:
    #     #     logger.info("Initializing edit button")
    #     #     return dash.no_update, dash.no_update, dash.no_update, True

    #     if add_button_nclicks is None:
    #         logger.info("No clicks detected")
    #         # return dash.no_update, dash.no_update, True, dash.no_update
    #         return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    #     # if edit_button_nclicks is None:
    #     #     logger.info("No clicks detected")
    #     #     return dash.no_update, dash.no_update, dash.no_update, True

    #     triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    #     logger.info(f"triggered_input: {triggered_input}")

    #     if triggered_input == "add-button":
    #         # Update the stored add button count
    #         logger.info(f"Updated stored_add_button: {stored_add_button}")
    #         # index = stored_add_button["count"]
    #         index = generate_unique_index()
    #         index = f"{index}-tmp"
    #         stored_add_button["_id"] = index
    #         # stored_add_button["count"] += 1

    #         current_draggable_children = add_new_component(str(index))

    #         # Close notes footer when add-button is clicked
    #         # If footer is visible or fullscreen, hide it completely
    #         current_footer_class = current_footer_class or ""
    #         current_page_class = current_page_class or ""

    #         if (
    #             "footer-visible" in current_footer_class
    #             or "footer-fullscreen" in current_footer_class
    #         ):
    #             # Hide footer completely
    #             new_footer_class = ""
    #             new_page_class = current_page_class.replace("notes-fullscreen", "").strip()
    #             logger.info(
    #                 f"Closing notes footer when add-button clicked. Footer: '{new_footer_class}', Page: '{new_page_class}'"
    #             )
    #         else:
    #             # Footer already hidden, no change needed
    #             new_footer_class = current_footer_class
    #             new_page_class = current_page_class

    #         return (
    #             current_draggable_children,
    #             stored_add_button,
    #             True,
    #             new_footer_class,
    #             new_page_class,
    #         )
    #         # return current_draggable_children, stored_add_button, True, dash.no_update

    #     # elif "edit-box-button" in triggered_input:
    #     #     # Generate and return the new component
    #     #     index = str(eval(triggered_input)["index"])
    #     #     logger.info(f"Edit button clicked for index: {index}")
    #     #     current_draggable_children = edit_component(str(index), active=0)

    #     #     return current_draggable_children, stored_add_button, dash.no_update, True
    #     else:
    #         logger.warning(f"Unexpected triggered_input: {triggered_input}")
    #         return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # KEEPME - TO EVALUATE - REMOVE PENDING CHANGES LOGIC PART
    @app.callback(
        [
            Output("interactive-values-store", "data"),
            Output("pending-changes-store", "data", allow_duplicate=True),
        ],
        [
            Input({"type": "interactive-component-value", "index": ALL}, "value"),
            # TODO: Re-enable graph interactions later
            # Input({"type": "graph", "index": ALL}, "clickData"),
            # Input({"type": "graph", "index": ALL}, "selectedData"),
            Input({"type": "reset-selection-graph-button", "index": ALL}, "n_clicks"),
            Input("reset-all-filters-button", "n_clicks"),
        ],
        [
            State({"type": "interactive-component-value", "index": ALL}, "id"),
            State({"type": "stored-metadata-component", "index": ALL}, "data"),
            State({"type": "graph", "index": ALL}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
            State("interactive-values-store", "data"),
            State("live-interactivity-toggle", "checked"),
            State("pending-changes-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_interactive_values_store(
        interactive_values,
        # TODO: Re-enable graph interactions later
        # graph_click_data,
        # graph_selected_data,
        reset_button_clicks,
        reset_all_clicks,
        ids,
        stored_metadata,
        graph_ids,
        local_store,
        pathname,
        current_store_data,
        live_interactivity_on,
        pending_changes,
    ):
        # FIXME
        live_interactivity_on = True

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
        # scatter_plot_components = {}
        reset_action_performed = False  # Track if an individual reset was performed

        # Check trigger types
        # TODO: Re-enable graph interactions later
        # graph_triggered = any("graph" in prop_id for prop_id in triggered_prop_ids)
        graph_triggered = False  # Disabled for now
        interactive_triggered = any(
            "interactive-component-value" in prop_id for prop_id in triggered_prop_ids
        )
        reset_triggered = any(
            "reset-selection-graph-button" in prop_id or "reset-all-filters-button" in prop_id
            for prop_id in triggered_prop_ids
        )

        logger.info(
            f"🎯 Trigger analysis: graph={graph_triggered} (disabled), interactive={interactive_triggered}, reset={reset_triggered}"
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
                    # Reset always applies immediately regardless of live interactivity state
                    return output_data, {}

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

                            # CRITICAL FIX: Return immediately to bypass filter preservation logic
                            # Individual reset should work like reset-all with early return
                            output_data = {"interactive_components_values": filtered_components}
                            logger.info(
                                f"✅ Individual reset completed: {len(filtered_components)} components - returning immediately"
                            )
                            # Individual reset always applies immediately (like reset-all)
                            return output_data, {}

                    except Exception as e:
                        logger.error(f"Error processing individual reset: {e}")

            # If reset didn't process, continue with normal logic
            logger.info("🔄 Reset trigger detected but not processed, continuing with normal logic")
        logger.info(
            f"🎯 Current store has {len(current_store_data.get('interactive_components_values', [])) if current_store_data else 0} existing components"
        )

        # Guard clause: Prevent spurious updates on initialization
        # If no actual user interaction occurred (e.g., reset button with value 0, empty component lists)
        # Return no_update to prevent triggering save callback unnecessarily
        if not interactive_triggered and not reset_action_performed:
            # Check if we have any stored interactive metadata (i.e., interactive components exist)
            has_interactive_components = bool(stored_metadata_interactive)

            if not has_interactive_components:
                logger.info(
                    "🔴 GUARD: No interactive components - skipping store update to prevent spurious save"
                )
                return dash.no_update, dash.no_update

        # TODO: Re-enable graph interactions later
        # # Check if we have any actual graph data to process (needed early for filter preservation logic)
        # has_actual_graph_data = False
        # if graph_triggered:
        #     if graph_click_data:
        #         has_actual_graph_data = any(
        #             click_data and click_data.get("points") and len(click_data["points"]) > 0
        #             for click_data in graph_click_data
        #         )
        #
        #     if graph_selected_data and not has_actual_graph_data:
        #         has_actual_graph_data = any(
        #             selected_data
        #             and selected_data.get("points")
        #             and len(selected_data["points"]) > 0
        #             for selected_data in graph_selected_data
        #         )
        #
        #     logger.info(f"🎯 Has actual graph data to process: {has_actual_graph_data}")
        # has_actual_graph_data = False  # Disabled for now

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

        # TODO: Re-enable graph interactions later
        # # Get the graph that was triggered (if any) to avoid duplicate filters
        # triggered_graph_index = None
        # if graph_triggered:
        #     for prop_id in triggered_prop_ids:
        #         if "graph" in prop_id:
        #             try:
        #                 graph_id_str = prop_id.split(".")[0]
        #                 graph_id_dict = eval(graph_id_str)
        #                 triggered_graph_index = graph_id_dict["index"]
        #                 break
        #             except Exception:
        #                 continue
        #
        # # Always preserve existing scatter plot filters unless we're specifically updating them
        # if current_store_data and "interactive_components_values" in current_store_data:
        #     # Find existing scatter plot filters and preserve them (except for triggered graph)
        #     for existing_component in current_store_data["interactive_components_values"]:
        #         if isinstance(existing_component, dict):
        #             component_index = existing_component.get("index", "")
        #             # Check if this is a scatter plot generated filter (starts with "filter_")
        #             if component_index.startswith("filter_"):
        #                 # Only remove if this is the same graph AND we have actual new data
        #                 should_replace = (
        #                     triggered_graph_index
        #                     and triggered_graph_index in component_index
        #                     and has_actual_graph_data
        #                 )
        #
        #                 if not should_replace:
        #                     components.append(existing_component)
        #                     logger.info(
        #                         f"🎯 Preserved existing scatter plot filter: {component_index}"
        #                     )
        #                 else:
        #                     logger.info(
        #                         f"🎯 Removing old filter for triggered graph (will be replaced): {component_index}"
        #                     )

        # TODO: Re-enable graph interactions later
        # # Handle scatter plot interactions
        # if graph_triggered:
        #     logger.info("🎯 Graph interaction detected in store update")
        #
        #     # Only process graph interactions if we have actual data
        #     # This prevents clearing filters when Dash sends empty data on subsequent triggers
        #     if has_actual_graph_data:
        #         # Find which graph was triggered
        #         for prop_id in triggered_prop_ids:
        #             if "graph" in prop_id:
        #                 try:
        #                     # Parse the triggered graph index
        #                     graph_id_str = prop_id.split(".")[0]
        #                     graph_id_dict = eval(graph_id_str)
        #                     ctx_triggered_prop_id_index = graph_id_dict["index"]
        #
        #                     # Get the corresponding graph metadata
        #                     graph_metadata = None
        #                     for meta in stored_metadata:
        #                         if meta.get("index") == ctx_triggered_prop_id_index:
        #                             graph_metadata = meta
        #                             break
        #
        #                     if (
        #                         not graph_metadata
        #                         or graph_metadata.get("visu_type", "").lower() != "scatter"
        #                     ):
        #                         continue
        #
        #                     logger.info(
        #                         f"🎯 Processing scatter plot interaction for {ctx_triggered_prop_id_index}"
        #                     )
        #
        #                     # Get token from local store
        #                     TOKEN = None
        #                     if local_store and "access_token" in local_store:
        #                         TOKEN = local_store["access_token"]
        #
        #                     if not TOKEN:
        #                         logger.warning(
        #                             "No access token available for scatter plot processing"
        #                         )
        #                         continue
        #
        #                     # Process click data
        #                     if "clickData" in prop_id and graph_click_data:
        #                         logger.info(f"🎯 Processing clickData: {graph_click_data}")
        #                         for i, click_data in enumerate(graph_click_data):
        #                             logger.info(
        #                                 f"🎯 Checking click_data[{i}]: {click_data} for graph {graph_ids[i]['index'] if i < len(graph_ids) else 'N/A'}"
        #                             )
        #                             if (
        #                                 click_data
        #                                 and i < len(graph_ids)
        #                                 and graph_ids[i]["index"] == ctx_triggered_prop_id_index
        #                             ):
        #                                 # Only process if there are actual clicked points
        #                                 if (
        #                                     click_data.get("points")
        #                                     and len(click_data["points"]) > 0
        #                                 ):
        #                                     dict_graph_data = {
        #                                         "value": click_data["points"][0],
        #                                         "metadata": graph_metadata,
        #                                     }
        #                                     scatter_plot_components = process_click_data(
        #                                         dict_graph_data, {}, TOKEN
        #                                     )
        #                                     logger.info(
        #                                         f"🎯 Click data processed: {len(scatter_plot_components)} components"
        #                                     )
        #                                 else:
        #                                     logger.info(
        #                                         f"🎯 No click points - click_data: {click_data}"
        #                                     )
        #                                 break
        #
        #                     # Process selected data
        #                     elif "selectedData" in prop_id and graph_selected_data:
        #                         logger.info(f"🎯 Processing selectedData: {graph_selected_data}")
        #                         for i, selected_data in enumerate(graph_selected_data):
        #                             logger.info(
        #                                 f"🎯 Checking selected_data[{i}]: {selected_data} for graph {graph_ids[i]['index'] if i < len(graph_ids) else 'N/A'}"
        #                             )
        #                             if (
        #                                 selected_data
        #                                 and i < len(graph_ids)
        #                                 and graph_ids[i]["index"] == ctx_triggered_prop_id_index
        #                             ):
        #                                 # Only process if there are actual selected points
        #                                 if (
        #                                     selected_data.get("points")
        #                                     and len(selected_data["points"]) > 0
        #                                 ):
        #                                     dict_graph_data = {
        #                                         "value": selected_data["points"],
        #                                         "metadata": graph_metadata,
        #                                     }
        #                                     scatter_plot_components = process_selected_data(
        #                                         dict_graph_data, {}, TOKEN
        #                                     )
        #                                     logger.info(
        #                                         f"🎯 Selected data processed: {len(scatter_plot_components)} components"
        #                                     )
        #                                 else:
        #                                     logger.info(
        #                                         f"🎯 No selected points - selected_data: {selected_data}"
        #                                     )
        #                                 break
        #
        #                 except Exception as e:
        #                     logger.error(f"Error processing graph interaction: {e}")
        #                     continue
        #     else:
        #         logger.info(
        #             "🎯 No actual graph data - preserving existing filters and skipping graph processing"
        #         )
        #
        # # Add scatter plot generated components to the store
        # if scatter_plot_components:
        #     for component_key, component_data in scatter_plot_components.items():
        #         if isinstance(component_data, dict) and component_data.get("metadata"):
        #             # Enhance metadata to match expected format for table filtering
        #             enhanced_metadata = component_data.get("metadata", {}).copy()
        #             enhanced_metadata["component_type"] = (
        #                 "interactive"  # Critical for table filtering
        #             )
        #             enhanced_metadata["index"] = component_key  # Ensure proper index
        #
        #             _tmp_metadata = {
        #                 "value": component_data.get("value"),
        #                 "metadata": enhanced_metadata,
        #                 "index": component_key,
        #             }
        #             components.append(_tmp_metadata)
        #             logger.info(
        #                 f"🎯 Added scatter plot component: {component_key} with enhanced metadata: {_tmp_metadata}"
        #             )

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
            return current_store_data, dash.no_update

        output_data = {"interactive_components_values": components}

        # Check live interactivity state to decide filter application
        if live_interactivity_on:
            # Live mode: apply filters immediately
            logger.info(f"🔴 LIVE MODE: Applying {len(components)} filters immediately")
            return output_data, {}  # Empty pending changes
        else:
            # Non-live mode: store as pending changes, keep current store unchanged
            logger.info(
                f"⏸️ NON-LIVE MODE: Checking {len(components)} components for pending changes"
            )

            # Get current applied values for comparison
            current_applied_components = {}
            if current_store_data and "interactive_components_values" in current_store_data:
                for comp in current_store_data["interactive_components_values"]:
                    comp_index = comp.get("index")
                    if comp_index:
                        current_applied_components[comp_index] = comp.get("value")

            updated_pending = pending_changes.copy() if pending_changes else {}

            # Merge at component level to avoid overwriting existing pending changes
            if "interactive_components_values" in output_data:
                if "interactive_components_values" not in updated_pending:
                    updated_pending["interactive_components_values"] = []

                # Create a dict for quick lookup of existing pending components by index
                existing_pending = {
                    comp.get("index"): comp
                    for comp in updated_pending["interactive_components_values"]
                }

                # Update/add components from output_data only if they differ from current applied values
                components_with_changes = 0
                for component in output_data["interactive_components_values"]:
                    component_index = component.get("index")
                    if component_index:
                        current_value = component.get("value")
                        applied_value = current_applied_components.get(component_index)

                        # Add to pending if value differs OR if this was a reset action
                        if current_value != applied_value or reset_action_performed:
                            components_with_changes += 1
                            if reset_action_performed:
                                logger.info(
                                    f"⏸️ Found reset action pending: {component_index} = {current_value} (reset action forces pending)"
                                )
                            else:
                                logger.info(
                                    f"⏸️ Found pending change {component_index}: current={current_value}, applied={applied_value}"
                                )
                            existing_pending[component_index] = component
                        else:
                            logger.info(
                                f"⏸️ No change for {component_index}: current={current_value}, applied={applied_value}"
                            )
                            # Remove from pending if it was there before (values now match applied)
                            existing_pending.pop(component_index, None)

                # Convert back to list
                updated_pending["interactive_components_values"] = list(existing_pending.values())

            pending_count = len(updated_pending.get("interactive_components_values", []))
            logger.info(f"⏸️ Total pending components: {pending_count}")
            return dash.no_update, updated_pending

    # KEEPME
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
            # Keep handles in DOM, CSS controls visibility - showResizeHandles must be True for handles to exist
            return False, True, "draggable-grid-container"
        else:
            # Keep handles in DOM, CSS hides them via .drag-handles-hidden class
            return False, True, "draggable-grid-container drag-handles-hidden"

    # KEEPME - MODULARISE - IS SUPPOSED TO FILL PREDEFINED MESSAGE FOR USER (Activate EDIT ON / CREATE FIRST COMPONENT ...)
    # @app.callback(
    #     Output("draggable-wrapper", "children"),
    #     [
    #         Input("unified-edit-mode-button", "checked"),
    #     ],
    #     [
    #         State("local-store", "data"),
    #         State("draggable", "children"),
    #     ],
    #     prevent_initial_call=False,
    # )
    # def update_empty_dashboard_wrapper(edit_mode_enabled, local_data, current_draggable_items):
    #     """Update draggable wrapper to show empty state messages when dashboard is empty"""
    #     logger.info(f"🔄 update_empty_dashboard_wrapper triggered - Edit mode: {edit_mode_enabled}")
    #     logger.info(f"🔄 Trigger: {ctx.triggered_id}, Current items: {len(current_draggable_items) if current_draggable_items else 0}")
    #     return html.Div(id="draggable")

    #     # Guard clause: If dashboard has stored components, always keep the draggable (don't show empty state)
    #     # This prevents showing empty state during initial load when components are being populated
    #     stored_children_data = local_data.get("stored_children_data", []) if local_data else []
    #     stored_layout_data = local_data.get("stored_layout_data", []) if local_data else []

    #     if (stored_children_data and len(stored_children_data) > 0) or (
    #         stored_layout_data and len(stored_layout_data) > 0
    #     ):
    #         logger.info(
    #             f"Dashboard has stored components ({len(stored_children_data)} children, {len(stored_layout_data)} layouts) - keeping original draggable"
    #         )
    #         return dash.no_update

    #     # Also check current draggable items as secondary check
    #     if current_draggable_items and len(current_draggable_items) > 0:
    #         logger.info("Dashboard has current draggable items, keeping original draggable")
    #         return dash.no_update

    #     if not local_data:
    #         logger.info("No local data available, keeping original draggable")
    #         return dash.no_update

    #     logger.info(f"Truly empty dashboard - Edit mode: {edit_mode_enabled}")

    #     if not edit_mode_enabled:
    #         logger.info("🔵 Empty dashboard + Edit mode OFF - showing welcome message")
    #         # Welcome message (blue theme) - now clickable to enable edit mode
    #         welcome_message = html.Div(
    #             dmc.Center(
    #                 dmc.Paper(
    #                     dmc.Stack(
    #                         [
    #                             dmc.Center(
    #                                 DashIconify(
    #                                     icon="material-symbols:edit-outline",
    #                                     width=64,
    #                                     height=64,
    #                                     color=colors["blue"],
    #                                 )
    #                             ),
    #                             dmc.Text(
    #                                 "Your dashboard is empty",
    #                                 size="xl",
    #                                 fw="bold",
    #                                 ta="center",
    #                                 c=colors["blue"],
    #                                 style={"color": f"var(--app-text-color, {colors['blue']})"},
    #                             ),
    #                             dmc.Text(
    #                                 "Enable Edit Mode to start building your dashboard",
    #                                 size="md",
    #                                 ta="center",
    #                                 c="gray",
    #                                 style={"color": "var(--app-text-color, #666)"},
    #                             ),
    #                         ],
    #                         gap="md",
    #                         align="center",
    #                     ),
    #                     p="xl",
    #                     radius="lg",
    #                     shadow="sm",
    #                     withBorder=True,
    #                     style={
    #                         "backgroundColor": "var(--app-surface-color, #ffffff)",
    #                         "border": f"1px solid var(--app-border-color, {colors['blue']}20)",
    #                         "maxWidth": "500px",
    #                         "marginTop": "2rem",
    #                         "transition": "transform 0.1s ease",
    #                     },
    #                 ),
    #                 style={
    #                     "height": "50vh",
    #                     "display": "flex",
    #                     "alignItems": "center",
    #                     "justifyContent": "center",
    #                 },
    #             ),
    #             id="welcome-message-clickable",
    #             style={"cursor": "pointer"},
    #         )
    #         # Create empty draggable component for callbacks
    #         empty_draggable = html.Div(id="draggable")
    #         return [welcome_message, empty_draggable]
    #     else:
    #         logger.info("🧡 Empty dashboard + Edit mode ON - showing add component message")
    #         # Add component message (orange theme) - now clickable to trigger add button
    #         add_component_message = html.Div(
    #             dmc.Center(
    #                 dmc.Paper(
    #                     dmc.Stack(
    #                         [
    #                             dmc.Center(
    #                                 DashIconify(
    #                                     icon="tabler:square-plus",
    #                                     width=64,
    #                                     height=64,
    #                                     color=colors["orange"],
    #                                 )
    #                             ),
    #                             dmc.Text(
    #                                 "Add your first component",
    #                                 size="xl",
    #                                 fw="bold",
    #                                 ta="center",
    #                                 c=colors["orange"],
    #                                 style={"color": f"var(--app-text-color, {colors['orange']})"},
    #                             ),
    #                             dmc.Text(
    #                                 "Click here to choose from charts, tables, and more",
    #                                 size="md",
    #                                 ta="center",
    #                                 c="gray",
    #                                 style={"color": "var(--app-text-color, #666)"},
    #                             ),
    #                         ],
    #                         gap="md",
    #                         align="center",
    #                     ),
    #                     p="xl",
    #                     radius="lg",
    #                     shadow="sm",
    #                     withBorder=True,
    #                     style={
    #                         "backgroundColor": "var(--app-surface-color, #ffffff)",
    #                         "border": f"1px solid var(--app-border-color, {colors['orange']}20)",
    #                         "maxWidth": "500px",
    #                         "marginTop": "2rem",
    #                         "transition": "transform 0.1s ease",
    #                     },
    #                 ),
    #                 style={
    #                     "height": "50vh",
    #                     "display": "flex",
    #                     "alignItems": "center",
    #                     "justifyContent": "center",
    #                 },
    #             ),
    #             id="add-component-message-clickable",
    #             style={"cursor": "pointer"},
    #         )
    #         # Create empty draggable component for callbacks
    #         empty_draggable = html.Div(id="draggable")
    #         return [add_component_message, empty_draggable]

    # KEEPME - MODULARISE
    # Make welcome message clickable to enable edit mode
    @app.callback(
        Output("unified-edit-mode-button", "checked", allow_duplicate=True),
        Input("welcome-message-clickable", "n_clicks"),
        prevent_initial_call=True,
    )
    def enable_edit_mode_from_welcome_message(n_clicks):
        """Enable edit mode when clicking on the welcome message."""
        if n_clicks:
            logger.info("🔵 Welcome message clicked - enabling edit mode")
            return True
        return dash.no_update

    # KEEPME - MODULARISE
    # Make add component message clickable to trigger add button
    @app.callback(
        Output("add-button", "n_clicks", allow_duplicate=True),
        Input("add-component-message-clickable", "n_clicks"),
        prevent_initial_call=True,
    )
    def trigger_add_button_from_message(n_clicks):
        """Trigger add button when clicking on the add component message."""
        if n_clicks:
            logger.info("🧡 Add component message clicked - triggering add button")
            return 1  # Increment n_clicks to trigger add button callback
        return dash.no_update


# KEEPME - MAIN FUNCTION - TO CLEAN
def design_draggable(
    init_layout: dict,
    init_children: list[dict],
    dashboard_id: str,
    local_data: dict,
    cached_project_data: dict | None = None,
):
    import time

    # logger.info("design_draggable - Initializing draggable layout")
    # logger.info(f"design_draggable - Dashboard ID: {dashboard_id}")
    # logger.info(f"design_draggable - Local data: {local_data}")
    # logger.info(f"design_draggable - Initial layout: {init_layout}")
    # DEBUGGING: Bypass draggable grid entirely when in test mode
    from depictio.dash.layouts.draggable_scenarios.restore_dashboard import (
        USE_SIMPLE_LAYOUT_FOR_TESTING,
    )

    if USE_SIMPLE_LAYOUT_FOR_TESTING:
        logger.info("🧪 TESTING MODE: Bypassing draggable grid, returning simple container")
        # Just return the children wrapped in a simple div
        # The children are already wrapped by render_dashboard in a DMC Stack
        simple_wrapper = html.Div(
            init_children,
            id="draggable",  # Keep the ID for callback compatibility
            style={
                "width": "100%",
                "padding": "0",  # No padding here, Stack handles it
            },
        )

        core = html.Div(
            html.Div(
                simple_wrapper,
                id="draggable-wrapper",
                style={"flex-grow": 1, "width": "100%", "height": "auto"},
            )
        )

        logger.info("🧪 TESTING MODE: Returning simple layout (no grid)")
        return core

    # Generate core layout based on data availability

    # TODO: if required, check if data was registered for the project
    TOKEN = local_data["access_token"]

    # Use cached project data if available, otherwise fallback to HTTP call
    if cached_project_data and cached_project_data.get("cache_key") == f"project_{dashboard_id}":
        logger.info(
            f"✅ DESIGN_DRAGGABLE: Cache HIT - using cached project data for dashboard {dashboard_id}"
        )
        logger.info(
            f"✅ DESIGN_DRAGGABLE: Cache age: {time.time() - cached_project_data.get('timestamp', 0):.2f}s"
        )
        project_json = cached_project_data["project"]
    else:
        cache_info = f"cached_project_data={bool(cached_project_data)}, cache_key={cached_project_data.get('cache_key') if cached_project_data else None}, expected_key=project_{dashboard_id}"
        logger.warning(
            f"❌ DESIGN_DRAGGABLE: Cache MISS ({cache_info}), making blocking HTTP call for dashboard {dashboard_id}"
        )
        start_time = time.time()
        project_json = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_dashboard_id/{dashboard_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()
        http_duration = time.time() - start_time
        logger.warning(f"❌ DESIGN_DRAGGABLE: HTTP call took {http_duration * 1000:.0f}ms")

    # logger.info(f"design_draggable - Project: {project_json}")
    from depictio.models.models.projects import Project

    project = Project.from_mongo(project_json)
    # logger.info(f"design_draggable - Project: {project}")
    workflows = project.workflows
    data_available = False  # Track if any data (DeltaTables or MultiQC) is available

    # Collect all data collections by type
    deltatable_dc_ids = []
    multiqc_dc_ids = []
    for wf in workflows:
        for dc in wf.data_collections:
            dc_type = dc.config.type if dc.config else None
            if dc_type == "multiqc":
                multiqc_dc_ids.append(str(dc.id))
            else:
                # All non-multiqc types use deltatables
                deltatable_dc_ids.append(str(dc.id))

    # Check for DeltaTables
    if deltatable_dc_ids:
        # Single batch API call to check deltatable existence
        logger.info(f"🚀 DESIGN_DRAGGABLE: Batch checking {len(deltatable_dc_ids)} deltatables")
        try:
            batch_response = httpx.post(
                f"{API_BASE_URL}/depictio/api/v1/deltatables/batch/exists",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json=deltatable_dc_ids,
            )
            if batch_response.status_code == 200:
                batch_results = batch_response.json()
                for dc_id, result in batch_results.items():
                    if result.get("exists") and result.get("delta_table_location"):
                        data_available = True
                        logger.info(f"✅ Delta table found: {result['delta_table_location']}")
                    else:
                        logger.warning(f"⚠️  No deltatable found for data collection '{dc_id}'")
                logger.info(f"✅ Batch deltatable check complete: data_available={data_available}")
            else:
                logger.error(f"❌ Batch deltatable check failed: {batch_response.text}")
        except Exception as e:
            logger.error(f"❌ Batch deltatable check exception: {e}")
            # Fallback to individual checks if batch fails
            logger.warning("🔄 Falling back to individual deltatable checks")
            for dc_id in deltatable_dc_ids:
                try:
                    response = httpx.get(
                        f"{API_BASE_URL}/depictio/api/v1/deltatables/get/{dc_id}",
                        headers={"Authorization": f"Bearer {TOKEN}"},
                    )
                    if response.status_code == 200:
                        data_available = True
                        logger.info(f"✅ Delta table found via fallback for {dc_id}")
                except Exception as fallback_e:
                    logger.error(f"❌ Fallback deltatable check failed for {dc_id}: {fallback_e}")

    # Check for MultiQC data
    if multiqc_dc_ids and not data_available:  # Only check if no deltatables found
        logger.info(f"🧬 DESIGN_DRAGGABLE: Checking {len(multiqc_dc_ids)} MultiQC collections")
        for dc_id in multiqc_dc_ids:
            try:
                response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/multiqc/reports/data-collection/{dc_id}",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    params={"limit": 1},  # Just check if any reports exist
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("total_count", 0) > 0:
                        data_available = True
                        logger.info(f"✅ MultiQC reports found for data collection '{dc_id}'")
                        break  # At least one MultiQC collection has data
                    else:
                        logger.warning(f"⚠️  No MultiQC reports for data collection '{dc_id}'")
            except Exception as e:
                logger.error(f"❌ MultiQC check failed for {dc_id}: {e}")

    logger.info(f"📊 DESIGN_DRAGGABLE: Final data availability check: {data_available}")

    if not data_available:
        # When there are no workflows, log information and prepare a message
        # logger.info(f"init_children {init_children}")
        # logger.info(f"init_layout {init_layout}")
        # message = html.Div(["No workflows available."])
        message = html.Div(
            dmc.Center(
                dmc.Paper(
                    dmc.Stack(
                        [
                            dmc.Center(
                                DashIconify(
                                    icon="tabler:database-off",
                                    width=64,
                                    height=64,
                                    color=colors["red"],
                                )
                            ),
                            dmc.Text(
                                "No data available",
                                size="xl",
                                fw="bold",
                                ta="center",
                                c=colors["red"],
                                style={"color": f"var(--app-text-color, {colors['red']})"},
                            ),
                            dmc.Text(
                                "Please first register workflows and data using Depictio CLI",
                                size="md",
                                ta="center",
                                c="gray",
                                style={"color": "var(--app-text-color, #666)"},
                            ),
                        ],
                        gap="md",
                        align="center",
                    ),
                    p="xl",
                    radius="lg",
                    shadow="sm",
                    withBorder=True,
                    style={
                        "border": f"1px solid var(--app-border-color, {colors['red']}20)",
                        "maxWidth": "500px",
                        "marginTop": "2rem",
                    },
                ),
                style={
                    "height": "50vh",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                },
            )
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
    logger.debug("🔍 GRID DEBUG - rowHeight: 20")
    logger.debug("🔍 GRID DEBUG - cols: {'lg': 48, 'md': 48, 'sm': 48, 'xs': 48, 'xxs': 48}")
    logger.debug(
        f"🔍 GRID DEBUG - current_layout items: {len(current_layout) if current_layout else 0}"
    )
    if current_layout:
        for i, layout_item in enumerate(current_layout):
            logger.debug(f"🔍 GRID DEBUG - layout item {i}: {layout_item}")

    # Determine initial edit mode state from dashboard data AND check user permissions
    # This ensures correct className and button visibility on initial load
    initial_edit_mode = True  # Default to edit mode ON
    is_owner = False  # Default to non-owner
    try:
        from depictio.dash.api_calls import api_call_fetch_user_from_token, api_call_get_dashboard

        # Get current user
        current_user = api_call_fetch_user_from_token(TOKEN)

        # Get dashboard data
        dashboard_data_dict = api_call_get_dashboard(dashboard_id, TOKEN)
        if dashboard_data_dict:
            # Check if user is owner
            if current_user:
                owner_ids = [
                    str(owner["id"])
                    for owner in dashboard_data_dict.get("permissions", {}).get("owners", [])
                ]
                is_owner = str(current_user.id) in owner_ids or current_user.is_admin
                logger.info(f"User is owner: {is_owner}")

            # Get edit mode state only for owners (non-owners always have edit mode OFF)
            if "buttons_data" in dashboard_data_dict:
                # Try unified edit mode first, fallback to old key for backward compatibility
                initial_edit_mode = dashboard_data_dict["buttons_data"].get(
                    "unified_edit_mode",
                    dashboard_data_dict["buttons_data"].get("edit_components_button", True),
                )
                logger.info(f"Initial edit mode from dashboard data: {initial_edit_mode}")

                # Force edit mode OFF for non-owners
                if not is_owner:
                    initial_edit_mode = False
                    logger.info("Non-owner user - forcing edit mode OFF")
    except Exception as e:
        logger.warning(
            f"Could not fetch dashboard edit mode state: {e}, defaulting to edit mode ON"
        )

    # Set className based on initial edit mode state
    grid_className = "draggable-grid-container"
    if not initial_edit_mode:
        grid_className += " drag-handles-hidden"
        logger.info("Initial load with edit mode OFF - adding .drag-handles-hidden class")

    draggable = dgl.DashGridLayout(
        id="draggable",
        items=draggable_items,
        itemLayout=current_layout,
        rowHeight=20,  # Ultra-fine row height for maximum vertical precision
        cols={
            "lg": 48,
            "md": 48,
            "sm": 48,
            "xs": 48,
            "xxs": 48,
        },  # 48-column grid for ultimate layout flexibility and precision
        showRemoveButton=False
        if not is_owner
        else False,  # Always False initially, callback controls it
        showResizeHandles=False if not is_owner else True,  # Non-owners: False, Owners: True
        className=grid_className,  # CSS class for styling (with .drag-handles-hidden if edit mode OFF)
        allowOverlap=False,
        # Additional parameters to try to disable responsive scaling
        autoSize=True,  # Let grid auto-size instead of using responsive breakpoints
        margin=[2, 2],  # Minimal margin between grid items [x, y]
        style={
            "display": display_style,
            "flex-grow": 1,
            "width": "100%",
            "height": "auto",
        },
    )

    # Create a wrapper for the draggable that can show empty state messages
    draggable_wrapper = html.Div(
        [draggable],  # Initially just contains the draggable
        id="draggable-wrapper",
        style={"flex-grow": 1, "width": "100%", "height": "auto"},
    )

    # Simple centered loading spinner
    # progress = html.Div(
    #     dmc.Loader(size="lg", type="dots", color="blue"),
    #     id="progress_bar",
    #     style={
    #         "position": "fixed",
    #         "top": "50%",
    #         "left": "50%",
    #         "transform": "translate(-50%, -50%)",
    #         "zIndex": 9999,
    #         "visibility": "hidden",  # Hidden by default
    #     },
    # )

    # Add draggable wrapper to the core children list whether it's visible or not
    core_children.append(draggable_wrapper)
    # core_children.append(progress)

    # The core Div contains all elements, managing visibility as needed
    core = html.Div(core_children)

    return core
