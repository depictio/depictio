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
from depictio.dash.component_metadata import (
    get_build_functions,
    get_component_dimensions_dict,
    get_dual_panel_dimensions,
)

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


# ============================================================================
# DUAL-PANEL GRID UTILITIES
# ============================================================================


def extract_component_id(component):
    """
    Extract component ID from a rendered Dash component.

    Handles various component structures including wrapped components.

    Args:
        component: Dash component (may be wrapped)

    Returns:
        str: Component ID or None if not found
    """
    if not component:
        return None

    # Try direct ID
    if hasattr(component, "id") and isinstance(component.id, dict):
        component_id = component.id.get("index")
        if component_id:
            return str(component_id)

    # Try children for wrapped components
    if hasattr(component, "children"):
        children = (
            component.children if isinstance(component.children, list) else [component.children]
        )
        for child in children:
            if child and hasattr(child, "id") and isinstance(child.id, dict):
                component_id = child.id.get("index")
                if component_id:
                    return str(component_id)

    return None


def separate_components_by_panel(stored_metadata):
    """
    Separate components into left panel (interactive) and right panel (all others).

    Args:
        stored_metadata: List of component metadata dicts

    Returns:
        tuple: (interactive_components, right_panel_components)
    """
    interactive_components = []
    right_panel_components = []

    for metadata in stored_metadata:
        component_type = metadata.get("component_type")

        if component_type == "interactive":
            metadata["panel"] = "left"
            interactive_components.append(metadata)
            # Log what's in the metadata for debugging
            logger.debug(
                f"  Interactive component {metadata.get('index')}: "
                f"type={metadata.get('interactive_component_type', 'MISSING')}"
            )
        else:
            metadata["panel"] = "right"
            right_panel_components.append(metadata)
            logger.info(f"  ➡️ RIGHT PANEL: {component_type} component {metadata.get('index')}")

    logger.info(
        f"📊 COMPONENT SEPARATION: {len(interactive_components)} interactive, "
        f"{len(right_panel_components)} right panel"
    )

    return interactive_components, right_panel_components


def calculate_left_panel_positions(components, saved_layout_data=None):
    """
    Calculate grid positions for interactive components in left panel (1-column grid).

    Interactive components always take full width (w=1), heights vary by type.
    Uses saved positions if available, otherwise stacks vertically with automatic positioning.

    Args:
        components: List of interactive component metadata
        saved_layout_data: Optional list of saved layout positions from database

    Returns:
        list: Layout positions [{i, x, y, w, h, static}, ...]
    """
    layout = []
    current_y = 0

    # Create lookup dict for saved positions (keyed by component index)
    # Handle both plain UUIDs and JSON-stringified dict IDs from DashGridLayout
    saved_positions = {}
    if saved_layout_data:
        import json

        for saved_item in saved_layout_data:
            item_id = saved_item.get("i")
            if item_id:
                # Try to parse as JSON (DashGridLayout serializes dict IDs as JSON strings)
                try:
                    parsed_id = json.loads(item_id)
                    # Extract the index from the dict
                    if isinstance(parsed_id, dict) and "index" in parsed_id:
                        component_id = str(parsed_id["index"])
                    else:
                        # Strip box- prefix for consistent lookup
                        component_id = (
                            str(item_id).replace("box-", "")
                            if str(item_id).startswith("box-")
                            else str(item_id)
                        )
                except (json.JSONDecodeError, TypeError):
                    # Not JSON, use as-is (strip box- prefix for consistent lookup)
                    component_id = (
                        str(item_id).replace("box-", "")
                        if str(item_id).startswith("box-")
                        else str(item_id)
                    )

                saved_positions[component_id] = saved_item

    logger.info(f"📐 LEFT: Built saved_positions lookup with {len(saved_positions)} items")
    if saved_positions:
        logger.info(f"📐 LEFT: Sample saved_positions keys: {list(saved_positions.keys())[:3]}")

    for metadata in components:
        index = metadata.get("index")
        interactive_type = metadata.get("interactive_component_type", "Select")
        component_id = str(index)
        logger.debug(
            f"📐 LEFT: Processing component {component_id}, checking if in saved_positions"
        )

        # Check if we have saved position for this component
        if component_id in saved_positions:
            # Use saved position (x, y) and saved height (h)
            # Width (w) is always enforced to 1 for single-column layout
            saved_pos = saved_positions[component_id]
            x = saved_pos.get("x", 0)
            y = saved_pos.get("y", current_y)

            # CRITICAL FIX: Preserve user-resized height for interactive components
            # Width is always 1 (single-column layout), but height can be customized
            dims = get_dual_panel_dimensions("interactive")
            w = dims["w"]  # Always 1 for single-column grid (enforced)
            h = saved_pos.get("h", dims["h"])  # Preserve user-resized height
            logger.info(
                f"📐 LEFT: Using saved position for component {index} ({interactive_type}): "
                f"x={x}, y={y}, h={h} (from saved), w={w} (enforced)"
            )
        else:
            # Auto-position: full width (1 column), stack vertically
            logger.warning(
                f"📐 LEFT: No saved position found for component {index} ({interactive_type}) - auto-positioning"
            )
            logger.warning(f"   Available keys in saved_positions: {list(saved_positions.keys())}")
            x = 0
            y = current_y
            # Use centralized dimensions from component_metadata
            dims = get_dual_panel_dimensions("interactive")
            w = dims["w"]
            h = dims["h"]
            logger.info(
                f"📐 LEFT: Auto-positioning new component {index} ({interactive_type}): "
                f"x={x}, y={y}, w={w}, h={h}"
            )

        layout.append(
            {
                "i": f"box-{component_id}",  # ID with box- prefix to match restore expectations
                "x": int(x),
                "y": int(y),
                "w": w,
                "h": h,
                "static": False,
            }
        )

        # Update current_y for next component (use y + h to stack properly)
        current_y = y + h

    logger.info(f"📐 LEFT PANEL: Generated {len(layout)} positions, max_y={current_y}")
    return layout


def calculate_right_panel_positions(components, saved_layout_data=None):
    """
    Calculate grid positions for cards and other components in right panel (8-column grid).

    Uses saved positions if available, otherwise arranges cards in 4-column grid (2 columns each).

    Args:
        components: List of right panel component metadata
        saved_layout_data: Optional list of saved layout positions from database

    Returns:
        list: Layout positions [{i, x, y, w, h, static}, ...]
    """
    layout = []

    # Separate cards from other components
    cards = [c for c in components if c.get("component_type") == "card"]
    other = [c for c in components if c.get("component_type") != "card"]

    # Create lookup dict for saved positions (keyed by component index)
    # Handle both plain UUIDs and JSON-stringified dict IDs from DashGridLayout
    saved_positions = {}
    if saved_layout_data:
        import json

        for saved_item in saved_layout_data:
            item_id = saved_item.get("i")
            if item_id:
                # Try to parse as JSON (DashGridLayout serializes dict IDs as JSON strings)
                try:
                    parsed_id = json.loads(item_id)
                    # Extract the index from the dict
                    if isinstance(parsed_id, dict) and "index" in parsed_id:
                        component_id = str(parsed_id["index"])
                    else:
                        # Strip box- prefix for consistent lookup
                        component_id = (
                            str(item_id).replace("box-", "")
                            if str(item_id).startswith("box-")
                            else str(item_id)
                        )
                except (json.JSONDecodeError, TypeError):
                    # Not JSON, use as-is (strip box- prefix for consistent lookup)
                    component_id = (
                        str(item_id).replace("box-", "")
                        if str(item_id).startswith("box-")
                        else str(item_id)
                    )

                saved_positions[component_id] = saved_item

    logger.info(f"📐 RIGHT: Built saved_positions lookup with {len(saved_positions)} items")
    if saved_positions:
        logger.info(f"📐 RIGHT: Sample saved_positions keys: {list(saved_positions.keys())[:3]}")

    # Cards: 4-column grid (2 columns per card in 8-column system)
    # With rowHeight=100: h=5 gives 500px height, w=2 gives 25% width (4 per row)
    card_y = 0
    for idx, card in enumerate(cards):
        index = card.get("index")
        component_id = str(index)
        logger.debug(f"📐 RIGHT: Processing card {component_id}, checking if in saved_positions")

        # Check if we have saved position for this component
        if component_id in saved_positions:
            # Use saved x/y position, but ALWAYS use standard card dimensions (w=2, h=5)
            # This ensures cards maintain consistent size regardless of saved data
            saved_pos = saved_positions[component_id]
            x = saved_pos.get("x", 0)
            y = saved_pos.get("y", 0)
            # Use centralized dimensions from component_metadata
            dims = get_dual_panel_dimensions("card")
            w = dims["w"]  # Standard card width (25% of 8-column grid)
            h = dims["h"]  # Standard card height from centralized config
            logger.info(
                f"📐 RIGHT: Using saved position for card {index}: x={x}, y={y}, "
                f"w={w} (standard), h={h} (standard)"
            )
        else:
            # Auto-position: 4 cards per row
            logger.warning(f"📐 RIGHT: No saved position found for card {index} - auto-positioning")
            logger.warning(f"   Available keys in saved_positions: {list(saved_positions.keys())}")
            # Use centralized dimensions from component_metadata
            dims = get_dual_panel_dimensions("card")
            w = dims["w"]
            h = dims["h"]
            col = idx % 4
            row = idx // 4
            x = col * w  # Position based on card width
            y = row * h  # Position based on card height
            logger.info(
                f"📐 RIGHT: Auto-positioning new card {index}: "
                f"x={x}, y={y}, w={w}, h={h} (col={col}, row={row})"
            )

        layout.append(
            {
                "i": f"box-{component_id}",  # ID with box- prefix to match restore expectations
                "x": int(x),
                "y": int(y),
                "w": w,
                "h": h,
                "static": True,  # Cards: Fixed size, no drag/resize
            }
        )

        card_y = max(card_y, y + h)

    # Other components: Process figures, tables, etc.
    # Figures positioned below cards using centralized dimensions
    for idx, component in enumerate(other):
        component_type = component.get("component_type", "figure")
        index = component.get("index")
        component_id = str(index)

        logger.debug(f"📐 RIGHT: Processing {component_type} {component_id}")

        # Check if we have saved position for this component
        if component_id in saved_positions:
            # Use saved position AND size (figures and tables are resizable)
            saved_pos = saved_positions[component_id]
            x = saved_pos.get("x", 0)
            y = saved_pos.get("y", card_y)  # Default below cards if no saved y

            # CRITICAL FIX: Use saved dimensions if available (user may have resized)
            # Fall back to standard dimensions only if not saved
            dims = get_dual_panel_dimensions(component_type)
            w = saved_pos.get("w", dims["w"])  # Preserve user-resized width
            h = saved_pos.get("h", dims["h"])  # Preserve user-resized height

            logger.info(
                f"📐 RIGHT: Using saved position for {component_type} {index}: x={x}, y={y}, "
                f"w={w}, h={h} {'(saved)' if 'w' in saved_pos else '(default)'}"
            )
        else:
            # Auto-position: figures take 50% width (w=4 in 8-column grid)
            logger.warning(
                f"📐 RIGHT: No saved position for {component_type} {index} - auto-positioning"
            )
            # Use centralized dimensions from component_metadata
            dims = get_dual_panel_dimensions(component_type)
            w = dims["w"]
            h = dims["h"]
            # Position: 2 figures per row for w=4, stacked below cards
            col = idx % 2  # 2 figures per row (8/4 = 2)
            row = idx // 2
            x = col * w  # Position based on component width
            y = card_y + (row * h)  # Stack below cards
            logger.info(
                f"📐 RIGHT: Auto-positioning {component_type} {index}: "
                f"x={x}, y={y}, w={w}, h={h} (col={col}, row={row})"
            )

        layout.append(
            {
                "i": f"box-{component_id}",
                "x": int(x),
                "y": int(y),
                "w": w,
                "h": h,
                "static": False,
                "resizeHandles": ["se", "s", "e", "sw", "w"],  # Figures: Full resize handles
            }
        )

    logger.info(
        f"📐 RIGHT PANEL: Generated {len(layout)} positions "
        f"({len(cards)} cards, {len(other)} other components)"
    )
    return layout


def register_callbacks_draggable(app):
    # KEEPME - MODULARISE - TO EVALUATE
    logger.info("⚠️ store_wf_dc_selection callback (duplicate/edit buttons) DISABLED for debugging")

    # TEMPORARILY DISABLED FOR DEBUGGING - this callback handles duplicate-box-button
    # @app.callback(
    #     Output("local-store-components-metadata", "data"),
    #     [
    #         State({"type": "workflow-selection-label", "index": ALL}, "value"),
    #         State({"type": "datacollection-selection-label", "index": ALL}, "value"),
    #         Input("url", "pathname"),
    #         Input({"type": "btn-done", "index": ALL}, "n_clicks"),
    #         Input({"type": "btn-done-edit", "index": ALL}, "n_clicks"),
    #         Input({"type": "edit-box-button", "index": ALL}, "n_clicks"),
    #         Input({"type": "duplicate-box-button", "index": ALL}, "n_clicks"),
    #     ],
    #     [
    #         State("local-store", "data"),  # Contains 'access_token'
    #         State("local-store-components-metadata", "data"),  # Existing components' data
    #         State({"type": "workflow-selection-label", "index": ALL}, "id"),
    #         State({"type": "datacollection-selection-label", "index": ALL}, "id"),
    #         State("current-edit-parent-index", "data"),  # Retrieve parent_index
    #     ],
    #     prevent_initial_call=True,
    # )
    def store_wf_dc_selection__disabled(
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

        # PERFORMANCE OPTIMIZATION: Skip if no buttons were actually clicked
        # During progressive component loading, buttons mount with n_clicks=0/None
        # This triggers the callback but no user action occurred - skip processing
        # This eliminates 26 serial API calls (2241ms → 0ms) on page load
        all_button_clicks = [
            *btn_done_clicks,
            *btn_done_edit_clicks,
            *edit_box_button_clicks,
            *duplicate_box_button_clicks,
        ]
        has_actual_click = any(clicks is not None and clicks > 0 for clicks in all_button_clicks)

        if not has_actual_click:
            logger.info(
                "[PERF] Metadata callback SKIPPED: No button clicks detected "
                "(triggered by component mounting during progressive load)"
            )
            return components_store or dash.no_update

        logger.info(f"[PERF] Metadata callback PROCESSING (triggered by: {ctx.triggered_id})")

        # PERFORMANCE OPTIMIZATION: Save original state for comparison at end
        # This enables hash-based change detection to prevent unnecessary downstream updates
        import json

        original_components_store_json = json.dumps(
            components_store if components_store else {}, sort_keys=True
        )

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

        # PERFORMANCE OPTIMIZATION: Compare metadata before returning
        # Only update if metadata has actually changed to prevent downstream callback cascade
        # This reduces unnecessary re-renders and saves when metadata is identical
        try:
            # Compare serialized versions to detect actual changes
            # Sort keys for consistent comparison regardless of dict insertion order
            current_components_store_json = json.dumps(components_store, sort_keys=True)

            if original_components_store_json == current_components_store_json:
                logger.info(
                    "[PERF] Metadata unchanged after processing - using dash.no_update to prevent cascade"
                )
                return dash.no_update

            logger.info("[PERF] Metadata changed - returning updated components_store")
        except Exception as e:
            logger.warning(f"[PERF] Failed to compare metadata: {e}, returning components_store")

        # logger.debug(f"Components store data after update: {components_store}")
        return components_store

    # KEEPME
    # Add callback to control grid edit mode like in the prototype (dual-panel mode)
    @app.callback(
        [
            Output({"type": "left-panel-grid", "index": ALL}, "className", allow_duplicate=True),
            Output({"type": "right-panel-grid", "index": ALL}, "className", allow_duplicate=True),
        ],
        Input("url", "pathname"),
        State({"type": "left-panel-grid", "index": ALL}, "className"),
        State({"type": "right-panel-grid", "index": ALL}, "className"),
        prevent_initial_call="initial_duplicate",
    )
    def update_grid_edit_mode(pathname, left_grids, right_grids):
        """Update dual-panel grid edit mode based on URL path (edit mode detection)"""
        # Detect edit mode from URL:
        # - Editor app: /dashboard-edit/{id}
        # - Legacy edit mode: /dashboard/{id}/edit
        # Handle trailing slashes and ensure we're on a dashboard page
        if not pathname or ("/dashboard/" not in pathname and "/dashboard-edit/" not in pathname):
            raise dash.exceptions.PreventUpdate

        # Remove trailing slash for consistent detection
        pathname_normalized = pathname.rstrip("/")

        # Edit mode if:
        # 1. URL starts with /dashboard-edit/ (Editor App)
        # 2. URL ends with /edit (Legacy edit mode)
        edit_mode_enabled = pathname_normalized.startswith(
            "/dashboard-edit/"
        ) or pathname_normalized.endswith("/edit")
        logger.info(f"Dual-panel grid edit mode from URL ({pathname}): {edit_mode_enabled}")

        if edit_mode_enabled:
            # Edit mode: Remove .drag-handles-hidden class → CSS shows action icons on hover
            class_name = "draggable-grid-container"
        else:
            # View mode: Add .drag-handles-hidden class → CSS hides all action icons
            class_name = "draggable-grid-container drag-handles-hidden"

        # Return lists matching the actual number of grids in each panel
        # If a panel has 0 grids, return empty list; otherwise return list with class_name for each grid
        left_output = [class_name] * len(left_grids) if left_grids else []
        right_output = [class_name] * len(right_grids) if right_grids else []

        return [left_output, right_output]

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
    stored_metadata: list[dict] | None = None,
    edit_mode: bool = False,
    left_panel_layout_data: list | None = None,
    right_panel_layout_data: list | None = None,
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
        logger.info("🎨 DUAL-PANEL MODE: Creating two-panel layout with grids")
        logger.info(f"🔍 Received {len(init_children)} children to process")

        # Use cached metadata as source of truth for component types
        if not stored_metadata:
            logger.warning("⚠️ No stored_metadata provided - cannot separate components into panels")
            stored_metadata = []

        logger.info(f"📊 Using {len(stored_metadata)} metadata entries from cache")

        # Separate components into left/right panels using cached metadata
        interactive_metadata, right_panel_metadata = separate_components_by_panel(stored_metadata)

        # Create mapping of box_id to metadata for quick lookup
        metadata_by_index = {str(meta.get("index")): meta for meta in stored_metadata}

        # Separate actual component children into panels based on metadata
        # Also track the component IDs for grid item creation
        interactive_children = []
        interactive_ids = []
        right_panel_children = []
        right_panel_ids = []

        for child in init_children:
            if not child:
                continue

            # Extract box ID (which corresponds to component index)
            box_id = None
            if hasattr(child, "id") and isinstance(child.id, str):
                # Box ID is like "box-{uuid}"
                if child.id.startswith("box-"):
                    box_id = child.id.replace("box-", "")

            if not box_id:
                logger.warning(f"⚠️ Could not extract box_id from child: {child}")
                continue

            # Look up component metadata
            metadata = metadata_by_index.get(box_id)
            if not metadata:
                logger.warning(f"⚠️ No metadata found for component {box_id}")
                continue

            component_type = metadata.get("component_type")

            # Add to appropriate panel with ID tracking
            if component_type == "interactive":
                interactive_children.append(child)
                interactive_ids.append(box_id)
                logger.debug(f"✅ Added interactive component {box_id} to LEFT panel")
            else:
                right_panel_children.append(child)
                right_panel_ids.append(box_id)
                logger.debug(f"✅ Added {component_type} component {box_id} to RIGHT panel")

        logger.info(
            f"📊 DUAL-PANEL: Separated {len(interactive_children)} interactive, "
            f"{len(right_panel_children)} right panel components"
        )

        # Extract layout data for position calculation
        # Convert dict layout to list format if needed
        if isinstance(init_layout, dict):
            layout_list = [{"i": k, **v} for k, v in init_layout.items() if isinstance(v, dict)]
        elif isinstance(init_layout, list):
            layout_list = init_layout
        else:
            layout_list = []

        # Enrich metadata with layout data (x, y positions)
        # interactive_metadata and right_panel_metadata already populated by separate_components_by_panel()
        logger.info(
            f"📐 Enriching {len(interactive_metadata)} interactive components with layout data"
        )
        for meta in interactive_metadata:
            layout_data = next(
                (item for item in layout_list if item.get("i") == f"box-{meta['index']}"), {}
            )
            meta["x"] = layout_data.get("x")
            meta["y"] = layout_data.get("y")
            logger.debug(
                f"  - Interactive {meta['index']}: type={meta.get('interactive_component_type', 'UNKNOWN')}, "
                f"x={meta.get('x')}, y={meta.get('y')}"
            )

        logger.info(
            f"📐 Enriching {len(right_panel_metadata)} right panel components with layout data"
        )
        for meta in right_panel_metadata:
            layout_data = next(
                (item for item in layout_list if item.get("i") == f"box-{meta['index']}"), {}
            )
            meta["x"] = layout_data.get("x")
            meta["y"] = layout_data.get("y")

        # Use provided dual-panel layout data (from dashboard data)
        left_panel_saved_layout = (
            left_panel_layout_data if left_panel_layout_data is not None else []
        )
        right_panel_saved_layout = (
            right_panel_layout_data if right_panel_layout_data is not None else []
        )

        logger.info(
            f"📐 Saved layout data - LEFT: {len(left_panel_saved_layout)} items, "
            f"RIGHT: {len(right_panel_saved_layout)} items"
        )

        # Calculate positions for both panels (with saved layout data)
        # logger.info(
        #     f"📐 Calculating positions for {len(interactive_metadata)} interactive components"
        # )
        # logger.info(
        #     f"📐 Interactive metadata sample: {interactive_metadata[:2] if interactive_metadata else []}"
        # )
        left_layout = calculate_left_panel_positions(interactive_metadata, left_panel_saved_layout)
        logger.info(f"📐 Left layout calculated: {len(left_layout)} items")
        logger.info(f"📐 Left layout sample: {left_layout[:2] if left_layout else []}")

        logger.info(
            f"📐 Calculating positions for {len(right_panel_metadata)} right panel components"
        )
        right_layout = calculate_right_panel_positions(
            right_panel_metadata, right_panel_saved_layout
        )
        logger.info(f"📐 Right layout calculated: {len(right_layout)} items")
        logger.info(f"📐 Right layout sample: {right_layout[:2] if right_layout else []}")

        # Create grid items using tracked IDs
        left_grid_items = [
            html.Div(
                child,
                id=f"box-{component_id}",  # Must match layout 'i' field exactly
                style={
                    "width": "100%",
                    "height": "100%",
                },
            )
            for child, component_id in zip(interactive_children, interactive_ids)
        ]
        logger.info(f"🎨 Created {len(left_grid_items)} left grid items")
        logger.info(f"🎨 Left grid item IDs (from interactive_ids): {interactive_ids}")
        logger.info(
            f"🎨 Left layout IDs (from left_layout): {[item.get('i') for item in left_layout]}"
        )

        right_grid_items = [
            html.Div(
                child,
                id=f"box-{component_id}",  # Must match layout 'i' field exactly
                style={
                    "width": "100%",
                    "height": "100%",
                },
            )
            for child, component_id in zip(right_panel_children, right_panel_ids)
        ]
        logger.info(f"🎨 Created {len(right_grid_items)} right grid items")
        logger.info(f"🎨 Right grid item IDs (from right_panel_ids): {right_panel_ids}")
        logger.info(
            f"🎨 Right layout IDs (from right_layout): {[item.get('i') for item in right_layout]}"
        )

        # Get edit mode state
        is_owner = local_data.get("user_id") == local_data.get("dashboard_owner_id", None)
        grid_className = ""
        if not is_owner:
            grid_className = "drag-handles-hidden"

        # Create left panel grid (1 column, rowHeight=100) - 1 component per row
        left_grid = dgl.DashGridLayout(
            id={"type": "left-panel-grid", "index": dashboard_id},
            items=left_grid_items,
            itemLayout=left_layout,
            rowHeight=50,
            cols={"lg": 1, "md": 1, "sm": 1, "xs": 1, "xxs": 1},
            showRemoveButton=False,
            showResizeHandles=False,  # Never allow resizing
            className=grid_className,
            allowOverlap=False,
            compactType="vertical",
            margin=[10, 10],
            style={
                "width": "100%",
                "minWidth": "280px",  # Ensure grid has minimum width
                "height": "auto",
            },
        )

        # Create right panel grid (8 columns, rowHeight=100)
        right_grid = dgl.DashGridLayout(
            id={"type": "right-panel-grid", "index": dashboard_id},
            items=right_grid_items,
            itemLayout=right_layout,
            rowHeight=100,
            cols={"lg": 8, "md": 8, "sm": 8, "xs": 8, "xxs": 8},
            showRemoveButton=False,
            showResizeHandles=True,  # Enable per-item resize handles (controlled by resizeHandles property)
            className=grid_className,
            allowOverlap=False,
            compactType="vertical",
            margin=[10, 10],
            style={"width": "100%", "height": "auto"},
        )

        # Create dual-panel layout
        dual_panel_layout = dmc.Grid(
            columns=12,
            gutter="sm",
            style={"height": "100%", "overflow": "hidden"},  # Prevent Grid-level scrolling
            children=[
                # Left panel: Interactive components (wider - 3 out of 12 = 25%)
                dmc.GridCol(
                    span=3,
                    children=[left_grid] if left_grid_items else [dmc.Center("No filters")],
                    style={
                        # "backgroundColor": "var(--app-surface-color, #f8f9fa)",
                        "borderRight": "1px solid var(--app-border-color, #ddd)",
                        "padding": "12px",
                        "height": "calc(100vh - 65px)",  # Full viewport height minus header
                        "overflowY": "auto",  # Individual panel scrollbar
                        "minWidth": "300px",  # Ensure minimum width
                    },
                ),
                # Right panel: Cards and other components (9 out of 12 = 75%)
                dmc.GridCol(
                    span=9,
                    children=[right_grid] if right_grid_items else [dmc.Center("No components")],
                    style={
                        # "backgroundColor": "var(--app-bg-color, #ffffff)",
                        "padding": "12px",
                        "height": "calc(100vh - 65px)",  # Full viewport height minus header
                        "overflowY": "auto",  # Individual panel scrollbar
                    },
                ),
            ],
            id="draggable",  # Keep ID for callback compatibility
        )

        core = html.Div(
            html.Div(
                dual_panel_layout,
                id="draggable-wrapper",
                style={
                    "width": "100%",
                    "height": "100%",  # Full height of parent container
                    "overflow": "hidden",  # Prevent scrolling at wrapper level
                },
            ),
            style={
                "width": "100%",
                "height": "100%",  # Full height to enable panel scrolling
                "overflow": "hidden",  # Prevent scrolling at container level
            },
        )

        logger.info("🎨 DUAL-PANEL: Returning two-panel layout with grids")
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

    # Extract project data from enriched API response
    # API returns: {"project": {...}, "delta_locations": {...}}
    project_data = project_json.get("project", project_json)
    project = Project.from_mongo(project_data)
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
        # EDIT MODE CONTROL: Only show remove button and resize handles in edit mode
        # In view mode: always False (read-only dashboard)
        # In edit mode: respect permissions (is_owner = True)
        showRemoveButton=False if not edit_mode else (is_owner and edit_mode),
        showResizeHandles=False if not edit_mode else (is_owner and edit_mode),
        className=grid_className,  # CSS class for styling (with .drag-handles-hidden if edit mode OFF)
        allowOverlap=False,
        # Additional parameters to try to disable responsive scaling
        autoSize=True,  # Let grid auto-size instead of using responsive breakpoints
        margin=[2, 2],  # Minimal margin between grid items [x, y]
        style={
            "display": display_style,
            "flexGrow": 1,
            "width": "100%",
            "height": "auto",
        },
    )

    # Create a wrapper for the draggable that can show empty state messages
    draggable_wrapper = html.Div(
        [draggable],  # Initially just contains the draggable
        id="draggable-wrapper",
        style={"flexGrow": 1, "width": "100%", "height": "auto"},
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
