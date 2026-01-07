"""
Simple remove component callback with layout patching.

Removes components using Dash Patch() for efficient updates,
avoiding full dashboard re-render for better performance.
"""

from dash import Patch, ctx
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger


def find_component_in_children(children_list, component_id):
    """
    Find index of component with matching ID in children list.

    Components are wrapped with an ID pattern: box-{component_id}

    Args:
        children_list: List of wrapped components (can be dicts or objects)
        component_id: Component ID to find

    Returns:
        int: Index of component, or -1 if not found
    """
    if not children_list:
        return -1

    logger.debug(
        f"  🔍 FIND_COMPONENT: Searching for ID={component_id} in {len(children_list)} children"
    )

    for i, child in enumerate(children_list):
        # Get the child's ID (box-{component_id} format)
        child_id = None
        if isinstance(child, dict):
            child_id = child.get("props", {}).get("id")
        elif hasattr(child, "id"):
            child_id = child.id

        if child_id:
            logger.debug(f"  🔍 FIND_COMPONENT: Child {i} has ID={child_id}")

            # Extract component_id from box-{component_id} format
            if isinstance(child_id, str) and child_id.startswith("box-"):
                extracted_id = child_id[4:]  # Remove "box-" prefix
                logger.debug(f"  🔍 FIND_COMPONENT: Child {i} extracted ID={extracted_id}")

                if extracted_id == str(component_id):
                    logger.debug(f"  🔍 FIND_COMPONENT: MATCH found at index {i}")
                    return i

    logger.debug(f"  🔍 FIND_COMPONENT: No match found for ID={component_id}")
    return -1


def register_remove_component_simple_callback(app):
    """
    Register the patch-based remove component callback.

    ⚠️ TEMPORARILY DISABLED FOR DEBUGGING
    """
    logger.info("⚠️ Remove button callback DISABLED for debugging")
    pass

    # TEMPORARILY DISABLED FOR DEBUGGING
    # @app.callback(
    #     Output("draggable", "children", allow_duplicate=True),
    #     Input({"type": "remove-box-button", "index": ALL}, "n_clicks"),
    #     State("draggable", "children"),  # Get current layout
    #     State({"type": "stored-metadata-component", "index": ALL}, "data"),
    #     State("url", "pathname"),
    #     State("local-store", "data"),
    #     prevent_initial_call=True,
    # )


def remove_component_from_dashboard__disabled(
    remove_clicks_all, current_children, stored_metadata_all, pathname, local_data
):
    """
    Remove component by patching the children tree.

    This avoids full re-render by directly manipulating the layout structure.

    Args:
        remove_clicks_all: List of n_clicks for all remove buttons
        current_children: Current draggable children (layout structure)
        stored_metadata_all: All component metadata
        pathname: Current URL pathname
        local_data: Local storage data with TOKEN

    Returns:
        Modified children with component removed
    """

    if not ctx.triggered:
        raise PreventUpdate

    # Get component ID to remove
    triggered_id = ctx.triggered_id
    component_id_to_remove = str(triggered_id["index"])

    # CRITICAL FIX: Guard against spurious triggers from layout re-renders
    # When duplicate/add callbacks re-render the dashboard, they recreate remove buttons
    # This can cause Dash to trigger this callback even though no button was clicked

    # Get the actual n_clicks value that triggered this callback
    triggered_prop_id = ctx.triggered[0]["prop_id"]
    triggered_value = ctx.triggered[0]["value"]

    logger.info("🗑️ REMOVE COMPONENT - Callback triggered")
    logger.info(f"  Component ID: {component_id_to_remove}")
    logger.info(f"  Triggered property: {triggered_prop_id}")
    logger.info(f"  Triggered value (n_clicks): {triggered_value}")

    # Guard 1: Ensure n_clicks is actually a positive number (genuine click)
    if triggered_value is None or triggered_value == 0:
        logger.warning(
            f"  ⚠️ GUARD TRIGGERED - n_clicks is {triggered_value}, not a real button click"
        )
        logger.warning("  ⚠️ Likely triggered by layout re-render, preventing deletion")
        raise PreventUpdate

    # Guard 2: Verify this is actually a remove-box-button trigger
    if not triggered_id or triggered_id.get("type") != "remove-box-button":
        logger.warning(f"  ⚠️ GUARD TRIGGERED - Wrong button type: {triggered_id.get('type')}")
        logger.warning("  ⚠️ Expected 'remove-box-button', preventing deletion")
        raise PreventUpdate

    # Guard 3: Check if multiple triggers occurred (sign of re-render)
    if len(ctx.triggered) > 1:
        logger.warning(f"  ⚠️ GUARD TRIGGERED - Multiple triggers detected ({len(ctx.triggered)})")
        logger.warning("  ⚠️ This suggests a layout re-render, preventing deletion")
        # Log all triggers for debugging
        for trigger in ctx.triggered:
            logger.warning(f"    - {trigger}")
        raise PreventUpdate

    logger.info("  ✅ All guards passed - proceeding with component removal")

    # Get component metadata to determine panel
    target_metadata = None
    for meta in stored_metadata_all:
        if str(meta.get("index")) == component_id_to_remove:
            target_metadata = meta
            break

    if not target_metadata:
        logger.warning(f"Component {component_id_to_remove} not found in metadata")
        raise PreventUpdate

    component_type = target_metadata.get("component_type")
    logger.info(f"  Component type: {component_type}")

    # Navigate and patch the layout structure
    # DEBUG: Log the actual structure we received
    logger.info(f"  DEBUG: current_children type: {type(current_children)}")
    logger.info(f"  DEBUG: current_children is list: {isinstance(current_children, list)}")
    logger.info(
        f"  DEBUG: current_children length: {len(current_children) if isinstance(current_children, list) else 'N/A'}"
    )

    if isinstance(current_children, list) and len(current_children) > 0:
        logger.info(f"  DEBUG: current_children[0] type: {type(current_children[0])}")
        if hasattr(current_children[0], "__class__"):
            logger.info(
                f"  DEBUG: current_children[0] class: {current_children[0].__class__.__name__}"
            )

        # Check if it's a dict (serialized component)
        if isinstance(current_children[0], dict):
            logger.info(f"  DEBUG: current_children[0] keys: {list(current_children[0].keys())}")
            if "props" in current_children[0]:
                logger.info(
                    f"  DEBUG: current_children[0]['props'] keys: {list(current_children[0]['props'].keys())}"
                )
                if "children" in current_children[0]["props"]:
                    children_val = current_children[0]["props"]["children"]
                    logger.info(
                        f"  DEBUG: current_children[0]['props']['children'] type: {type(children_val)}"
                    )
                    logger.info(
                        f"  DEBUG: current_children[0]['props']['children'] length: {len(children_val) if isinstance(children_val, list) else 'not a list'}"
                    )
        elif hasattr(current_children[0], "children"):
            logger.info(
                f"  DEBUG: current_children[0].children length: {len(current_children[0].children) if isinstance(current_children[0].children, list) else 'not a list'}"
            )

    # current_children structure can be:
    # Option 1 (expected): [left_panel, right_panel_group] - 2 elements
    # Option 2 (actual?): [dmc.Group([left_panel, right_panel_group])] - 1 element wrapping both panels
    if not current_children or not isinstance(current_children, list):
        logger.warning(f"Invalid layout structure: expected list, got {type(current_children)}")
        raise PreventUpdate

    # Handle both structure options (dict vs object)
    def get_children(component):
        """Get children from component (dict or object).

        Always returns a list, even if there's only one child.
        """
        children = None
        if isinstance(component, dict):
            children = component.get("props", {}).get("children", [])
        elif hasattr(component, "children"):
            children = component.children
        else:
            return []

        # Ensure we always return a list
        if children is None:
            return []
        elif isinstance(children, list):
            return children
        else:
            # Single child - wrap in list
            return [children]

    # Detect structure type to determine Patch() paths
    # Actual structure: [html.Div([debug_header, dmc.Grid([GridCol(left), GridCol(right)])])]
    has_group_wrapper = False
    grid_index = None  # Track position of Grid in wrapper's children

    if len(current_children) == 1:
        # Structure is wrapped in a container Div
        logger.info("  Layout structure: Single container wrapper")
        has_group_wrapper = True
        wrapper = current_children[0]
        wrapper_children = get_children(wrapper)
        logger.info(
            f"  DEBUG: Wrapper children length: {len(wrapper_children) if isinstance(wrapper_children, list) else 'not a list'}"
        )

        # Find the Grid component (might be at index 0 or 1 depending on debug_header presence)
        grid_component = None
        for i, child in enumerate(wrapper_children):
            # Check if it's a Grid by looking for namespace/type
            if isinstance(child, dict):
                namespace = child.get("namespace")
                child_type = child.get("type")
                if namespace == "dash_mantine_components" and child_type == "Grid":
                    grid_component = child
                    grid_index = i
                    logger.info(f"  DEBUG: Found Grid at wrapper index {i}")
                    break
            elif hasattr(child, "__class__"):
                if "Grid" in child.__class__.__name__:
                    grid_component = child
                    grid_index = i
                    logger.info(f"  DEBUG: Found Grid at wrapper index {i}")
                    break

        if not grid_component:
            logger.warning("  No Grid found in wrapper - falling back to direct children")
            # Fallback: assume first two children are panels
            left_panel = wrapper_children[0] if len(wrapper_children) > 0 else None
            right_panel_group = wrapper_children[1] if len(wrapper_children) > 1 else None
        else:
            # Extract left and right panels from Grid's children (GridCol components)
            grid_children = get_children(grid_component)
            logger.info(f"  DEBUG: Grid has {len(grid_children)} GridCol children")

            if len(grid_children) < 2:
                logger.warning(f"  Grid doesn't have 2 GridCol children (got {len(grid_children)})")
                raise PreventUpdate

            # GridCol[0] contains left_panel_content, GridCol[1] contains right_panel_content
            left_grid_col = grid_children[0]
            right_grid_col = grid_children[1]

            # Extract content from GridCol children
            left_panel = get_children(left_grid_col)[0] if get_children(left_grid_col) else None
            right_panel_group = (
                get_children(right_grid_col)[0] if get_children(right_grid_col) else None
            )

    elif len(current_children) == 2:
        # Structure is [left_panel, right_panel_group]
        logger.info("  Layout structure: Direct two panels")
        has_group_wrapper = False
        left_panel = current_children[0]
        right_panel_group = current_children[1]
    else:
        logger.warning(
            f"Invalid layout structure: expected 1 or 2 elements, got {len(current_children)}"
        )
        raise PreventUpdate

    if not left_panel or not right_panel_group:
        logger.warning("  Could not extract left/right panels from structure")
        raise PreventUpdate

    # Create Patch object for efficient partial updates
    patch = Patch()

    # Determine which panel to patch and construct proper Patch() path
    if component_type == "interactive":
        # Remove from left panel Stack
        logger.info("  Patching left panel (interactive)")
        left_children = get_children(left_panel)
        if left_children:
            idx = find_component_in_children(left_children, component_id_to_remove)
            if idx >= 0:
                # Delete using Patch with structure-aware nested path
                if has_group_wrapper:
                    # Structure: [Div([..., Grid([GridCol(left_panel), GridCol(right_panel)])])]
                    # Path: wrapper -> Grid -> GridCol[0] -> Stack (single dict!) -> children[idx]
                    del patch[0]["props"]["children"][grid_index]["props"]["children"][0]["props"][
                        "children"
                    ]["props"]["children"][idx]
                else:
                    # Structure: [left_panel, right_panel_group]
                    # Path: patch[0]['props']['children'][idx]
                    del patch[0]["props"]["children"][idx]
                logger.info(f"    Removed interactive component at index {idx} using Patch()")
            else:
                logger.warning("    Component not found in left panel")
                raise PreventUpdate
        else:
            logger.warning("    Left panel has no children")
            raise PreventUpdate

    elif component_type == "card":
        # Try to remove from cards grid (first child of right panel Group)
        logger.info("  Patching right panel cards grid")
        right_children = get_children(right_panel_group)
        logger.info(
            f"  DEBUG: Right panel children count: {len(right_children) if right_children else 0}"
        )

        removed = False
        if right_children and len(right_children) > 0:
            cards_grid = right_children[0]
            logger.info(f"  DEBUG: Cards grid type: {type(cards_grid)}")
            cards_grid_children = get_children(cards_grid)
            logger.info(
                f"  DEBUG: Cards grid children count: {len(cards_grid_children) if cards_grid_children else 0}"
            )

            # Debug: log first few children to see structure
            if cards_grid_children:
                logger.info(f"  DEBUG: Inspecting all {len(cards_grid_children)} cards in grid...")
                for i, child in enumerate(cards_grid_children):  # All cards
                    logger.info(f"  DEBUG: Card {i} type: {type(child)}")
                    if isinstance(child, dict):
                        logger.info(f"  DEBUG: Card {i} keys: {list(child.keys())}")
                        child_id = child.get("props", {}).get("id")
                        logger.info(f"  DEBUG: Card {i} ID: {child_id}")
                        child_children = child.get("props", {}).get("children", [])
                        logger.info(
                            f"  DEBUG: Card {i} children type: {type(child_children)}, len: {len(child_children) if isinstance(child_children, list) else 'N/A'}"
                        )

                        # Handle both list and dict children
                        children_to_inspect = child_children
                        if not isinstance(child_children, list):
                            children_to_inspect = [child_children]

                        if isinstance(children_to_inspect, list) and len(children_to_inspect) > 0:
                            first_child = children_to_inspect[0]
                            logger.info(f"  DEBUG: Card {i} first child type: {type(first_child)}")
                            if isinstance(first_child, dict):
                                logger.info(
                                    f"  DEBUG: Card {i} first child keys: {list(first_child.keys())}"
                                )
                                first_child_type = first_child.get("type")
                                first_child_namespace = first_child.get("namespace")
                                logger.info(
                                    f"  DEBUG: Card {i} first child component: {first_child_namespace}.{first_child_type}"
                                )
                                store_id = first_child.get("props", {}).get("id")
                                logger.info(f"  DEBUG: Card {i} first child ID: {store_id}")

            if cards_grid_children:
                idx = find_component_in_children(cards_grid_children, component_id_to_remove)
                if idx >= 0:
                    # Delete from cards grid using Patch with structure-aware nested path
                    if has_group_wrapper:
                        # Log detailed structure for debugging Patch() path
                        logger.info(f"  🔍 PATCH PATH TRACE for card at index {idx}:")
                        logger.info(f"    [0] = wrapper (type: {type(current_children[0])})")
                        logger.info(f"    ['props']['children'][{grid_index}] = Grid")
                        logger.info("    ['props']['children'][1] = GridCol[1] (right panel)")
                        logger.info("    ['props']['children'][0] = right_panel_group content")
                        logger.info("    ['props']['children'][0] = cards_grid")
                        logger.info(f"    ['props']['children'][{idx}] = target card")

                        # Verify path step by step
                        try:
                            step1 = current_children[0]
                            logger.info(f"    ✓ Step 1: wrapper = {type(step1)}")

                            step2 = step1["props"]["children"][grid_index]
                            logger.info(f"    ✓ Step 2: Grid = {step2.get('type')}")

                            step3 = step2["props"]["children"][1]
                            logger.info(f"    ✓ Step 3: GridCol[1] = {step3.get('type')}")

                            step4 = step3["props"]["children"]
                            logger.info(
                                f"    ✓ Step 4: GridCol[1] children type = {type(step4)}, is_list = {isinstance(step4, list)}"
                            )

                            if isinstance(step4, list):
                                step5 = step4[0]
                            else:
                                step5 = step4
                            logger.info(
                                f"    ✓ Step 5: right_panel_group = {type(step5)}, type = {step5.get('type') if isinstance(step5, dict) else 'N/A'}"
                            )

                            step6 = (
                                step5["props"]["children"]
                                if isinstance(step5, dict)
                                else step5.children
                            )
                            logger.info(
                                f"    ✓ Step 6: right_panel children type = {type(step6)}, is_list = {isinstance(step6, list)}"
                            )

                            if isinstance(step6, list):
                                step7 = step6[0]
                            else:
                                step7 = step6
                            logger.info(
                                f"    ✓ Step 7: cards_grid = {type(step7)}, type = {step7.get('type') if isinstance(step7, dict) else 'N/A'}"
                            )

                            step8 = (
                                step7["props"]["children"]
                                if isinstance(step7, dict)
                                else step7.children
                            )
                            logger.info(
                                f"    ✓ Step 8: cards_grid children type = {type(step8)}, is_list = {isinstance(step8, list)}, len = {len(step8) if isinstance(step8, list) else 'N/A'}"
                            )

                            logger.info(f"    ✓ All steps verified - target is at index {idx}")
                        except Exception as e:
                            logger.error(f"    ✗ Path verification failed: {e}")

                        # Structure: [Div([..., Grid([GridCol(left), GridCol(right_panel)])])]
                        # Path: wrapper -> Grid -> GridCol[1] -> Stack (single dict!) -> cards_grid -> children[idx]
                        # Note: GridCol children is a SINGLE DICT (Stack), not a list, so no [0] indexing needed
                        del patch[0]["props"]["children"][grid_index]["props"]["children"][1][
                            "props"
                        ]["children"]["props"]["children"][0]["props"]["children"][idx]
                    else:
                        # Structure: [left_panel, right_panel_group]
                        # Path: patch[1]['props']['children'][0]['props']['children'][idx]
                        del patch[1]["props"]["children"][0]["props"]["children"][idx]
                    logger.info(f"    Removed card at index {idx} from grid using Patch()")
                    removed = True

        # Fallback: If not found in grid, try other components section
        if not removed and right_children and len(right_children) > 1:
            logger.info("  Card not in grid, trying other components section...")
            idx = find_component_in_children(right_children, component_id_to_remove)
            if idx >= 0:
                # Delete from other components using Patch with structure-aware path
                if has_group_wrapper:
                    # Structure: [Div([..., Grid([GridCol(left), GridCol(right_panel)])])]
                    # Path: wrapper -> Grid -> GridCol[1] -> Stack (single dict!) -> children[idx]
                    del patch[0]["props"]["children"][grid_index]["props"]["children"][1]["props"][
                        "children"
                    ]["props"]["children"][idx]
                else:
                    # Structure: [left_panel, right_panel_group]
                    # Path: patch[1]['props']['children'][idx]
                    del patch[1]["props"]["children"][idx]
                logger.info(f"    Removed card at index {idx} from other components using Patch()")
                removed = True

        if not removed:
            logger.warning(
                f"    Card not found anywhere in right panel (looking for ID: {component_id_to_remove})"
            )
            raise PreventUpdate

    else:
        # Remove from other components (rest of right panel Group children, after cards_grid)
        logger.info("  Patching right panel other components")
        right_children = get_children(right_panel_group)
        if right_children:
            idx = find_component_in_children(right_children, component_id_to_remove)
            if idx >= 0:
                # Delete using Patch with structure-aware path
                if has_group_wrapper:
                    # Structure: [Div([..., Grid([GridCol(left), GridCol(right_panel)])])]
                    # Path: wrapper -> Grid -> GridCol[1] -> Stack (single dict!) -> children[idx]
                    del patch[0]["props"]["children"][grid_index]["props"]["children"][1]["props"][
                        "children"
                    ]["props"]["children"][idx]
                else:
                    # Structure: [left_panel, right_panel_group]
                    # Path: patch[1]['props']['children'][idx]
                    del patch[1]["props"]["children"][idx]
                logger.info(f"    Removed other component at index {idx} using Patch()")
            else:
                logger.warning("    Component not found in right panel")
                raise PreventUpdate
        else:
            logger.warning("    Right panel has no children")
            raise PreventUpdate

    # Save updated metadata to backend
    dashboard_id = pathname.split("/")[-1] if pathname else None
    TOKEN = local_data.get("access_token") if local_data else None

    if dashboard_id and TOKEN:
        # Filter out removed component from metadata
        updated_metadata = [
            meta for meta in stored_metadata_all if str(meta.get("index")) != component_id_to_remove
        ]

        logger.info(f"  💾 Saving to backend: {len(updated_metadata)} components remaining")

        try:
            from datetime import datetime

            from depictio.dash.api_calls import (
                api_call_get_dashboard,
                api_call_save_dashboard,
            )

            # Fetch current dashboard data
            dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
            if not dashboard_data:
                logger.warning("⚠️ Could not fetch dashboard data for save")
                raise PreventUpdate

            # Update only the stored_metadata field
            dashboard_data["stored_metadata"] = updated_metadata
            dashboard_data["last_saved_ts"] = str(datetime.now())

            # Save the complete dashboard data
            save_success = api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)
            if save_success:
                logger.info("✅ Component removed and saved (patch mode)")
            else:
                logger.warning("⚠️ Failed to save dashboard")
        except Exception as e:
            logger.warning(f"⚠️ Failed to save dashboard: {e}")
    else:
        logger.warning("  ⚠️ Cannot save: missing dashboard_id or TOKEN")

    logger.info("  🎉 Component removed successfully using Patch()!")

    # Return Patch object - Dash will apply the changes efficiently
    return patch
