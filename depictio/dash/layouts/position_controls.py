"""
Position control logic and callbacks for the 2-panel layout system.

Handles component movement within panels/sections:
- Interactive components: Vertical movement only (left panel)
- Card components: Grid movement with 4 columns (right panel, cards section)
- Other components: Vertical movement only (right panel, other section)

Movement operations:
- Up/Down: Swap positions with adjacent component
- Top/Bottom: Move to start/end of section
- Left/Right: Card-only, swap within same row
"""

from dash import ALL, Input, Output, State, callback, ctx
from dash.exceptions import PreventUpdate

from depictio.api.v1.configs.logging_init import logger


def move_component_up(components: list, target_index: int) -> list:
    """
    Move component up one position in a vertical stack.

    Args:
        components: List of components in the section
        target_index: Current index of component to move

    Returns:
        Updated component list with swapped positions
    """
    if target_index <= 0:
        logger.warning(f"Cannot move up: component already at top (index={target_index})")
        return components

    # Swap with component above
    components[target_index], components[target_index - 1] = (
        components[target_index - 1],
        components[target_index],
    )

    # Update panel_position metadata (components are dictionaries)
    if isinstance(components[target_index], dict):
        components[target_index]["panel_position"] = target_index
    if isinstance(components[target_index - 1], dict):
        components[target_index - 1]["panel_position"] = target_index - 1

    logger.info(f"Moved component up: {target_index} -> {target_index - 1}")
    return components


def move_component_down(components: list, target_index: int) -> list:
    """
    Move component down one position in a vertical stack.

    Args:
        components: List of components in the section
        target_index: Current index of component to move

    Returns:
        Updated component list with swapped positions
    """
    if target_index >= len(components) - 1:
        logger.warning(
            f"Cannot move down: component already at bottom (index={target_index}, len={len(components)})"
        )
        return components

    # Swap with component below
    components[target_index], components[target_index + 1] = (
        components[target_index + 1],
        components[target_index],
    )

    # Update panel_position metadata (components are dictionaries)
    if isinstance(components[target_index], dict):
        components[target_index]["panel_position"] = target_index
    if isinstance(components[target_index + 1], dict):
        components[target_index + 1]["panel_position"] = target_index + 1

    logger.info(f"Moved component down: {target_index} -> {target_index + 1}")
    return components


def move_component_to_top(components: list, target_index: int) -> list:
    """
    Move component to the top of a vertical stack.

    Args:
        components: List of components in the section
        target_index: Current index of component to move

    Returns:
        Updated component list with component at position 0
    """
    if target_index == 0:
        logger.warning("Component already at top")
        return components

    # Remove component from current position
    component = components.pop(target_index)

    # Insert at beginning
    components.insert(0, component)

    # Update all panel_position metadata (components are dictionaries)
    for i, comp in enumerate(components):
        if isinstance(comp, dict):
            comp["panel_position"] = i

    logger.info(f"Moved component to top: {target_index} -> 0")
    return components


def move_component_to_bottom(components: list, target_index: int) -> list:
    """
    Move component to the bottom of a vertical stack.

    Args:
        components: List of components in the section
        target_index: Current index of component to move

    Returns:
        Updated component list with component at last position
    """
    if target_index >= len(components) - 1:
        logger.warning("Component already at bottom")
        return components

    # Remove component from current position
    component = components.pop(target_index)

    # Append to end
    components.append(component)

    # Update all panel_position metadata (components are dictionaries)
    for i, comp in enumerate(components):
        if isinstance(comp, dict):
            comp["panel_position"] = i

    logger.info(f"Moved component to bottom: {target_index} -> {len(components) - 1}")
    return components


def move_card_left(cards: list, target_index: int) -> list:
    """
    Move card left within the same row (4-column grid).

    Args:
        cards: List of card components
        target_index: Current index of card to move

    Returns:
        Updated card list with swapped positions
    """
    # Calculate row and column
    row = target_index // 4
    col = target_index % 4

    if col == 0:
        logger.warning("Cannot move left: card already at leftmost position (col=0)")
        return cards

    # Swap with card to the left (same row, col-1)
    left_index = target_index - 1
    cards[target_index], cards[left_index] = cards[left_index], cards[target_index]

    # Update row/col/panel_position metadata (cards are dictionaries)
    if isinstance(cards[target_index], dict):
        cards[target_index]["panel_position"] = target_index
        cards[target_index]["row"] = target_index // 4
        cards[target_index]["col"] = target_index % 4

    if isinstance(cards[left_index], dict):
        cards[left_index]["panel_position"] = left_index
        cards[left_index]["row"] = left_index // 4
        cards[left_index]["col"] = left_index % 4

    logger.info(f"Moved card left: {target_index} (row={row}, col={col}) -> {left_index}")
    return cards


def move_card_right(cards: list, target_index: int) -> list:
    """
    Move card right within the same row (4-column grid).

    Args:
        cards: List of card components
        target_index: Current index of card to move

    Returns:
        Updated card list with swapped positions
    """
    # Calculate row and column
    row = target_index // 4
    col = target_index % 4

    # Check if card is at rightmost position (col=3) or no card exists to the right
    if col >= 3 or target_index >= len(cards) - 1:
        logger.warning(
            f"Cannot move right: card at rightmost position or no card exists (col={col}, index={target_index})"
        )
        return cards

    # Additional check: ensure the next card is in the same row
    next_card_row = (target_index + 1) // 4
    if next_card_row != row:
        logger.warning("Cannot move right: next position is in different row")
        return cards

    # Swap with card to the right (same row, col+1)
    right_index = target_index + 1
    cards[target_index], cards[right_index] = cards[right_index], cards[target_index]

    # Update row/col/panel_position metadata (cards are dictionaries)
    if isinstance(cards[target_index], dict):
        cards[target_index]["panel_position"] = target_index
        cards[target_index]["row"] = target_index // 4
        cards[target_index]["col"] = target_index % 4

    if isinstance(cards[right_index], dict):
        cards[right_index]["panel_position"] = right_index
        cards[right_index]["row"] = right_index // 4
        cards[right_index]["col"] = right_index % 4

    logger.info(f"Moved card right: {target_index} (row={row}, col={col}) -> {right_index}")
    return cards


def move_card_up_in_grid(cards: list, target_index: int) -> list:
    """
    Move card up one row in the 4-column grid.

    Args:
        cards: List of card components
        target_index: Current index of card to move

    Returns:
        Updated card list with swapped positions
    """
    # Calculate row and column
    row = target_index // 4
    col = target_index % 4

    if row == 0:
        logger.warning("Cannot move up: card already in first row (row=0)")
        return cards

    # Calculate target position (same column, previous row)
    up_index = target_index - 4

    if up_index < 0:
        logger.warning("Cannot move up: target position out of bounds")
        return cards

    # Swap with card above
    cards[target_index], cards[up_index] = cards[up_index], cards[target_index]

    # Update row/col/panel_position metadata (cards are dictionaries)
    if isinstance(cards[target_index], dict):
        cards[target_index]["panel_position"] = target_index
        cards[target_index]["row"] = target_index // 4
        cards[target_index]["col"] = target_index % 4

    if isinstance(cards[up_index], dict):
        cards[up_index]["panel_position"] = up_index
        cards[up_index]["row"] = up_index // 4
        cards[up_index]["col"] = up_index % 4

    logger.info(f"Moved card up in grid: {target_index} (row={row}, col={col}) -> {up_index}")
    return cards


def move_card_down_in_grid(cards: list, target_index: int) -> list:
    """
    Move card down one row in the 4-column grid.

    Args:
        cards: List of card components
        target_index: Current index of card to move

    Returns:
        Updated card list with swapped positions
    """
    # Calculate row and column
    row = target_index // 4
    col = target_index % 4

    # Calculate target position (same column, next row)
    down_index = target_index + 4

    if down_index >= len(cards):
        logger.warning(f"Cannot move down: target position out of bounds (index={down_index})")
        return cards

    # Swap with card below
    cards[target_index], cards[down_index] = cards[down_index], cards[target_index]

    # Update row/col/panel_position metadata (cards are dictionaries)
    if isinstance(cards[target_index], dict):
        cards[target_index]["panel_position"] = target_index
        cards[target_index]["row"] = target_index // 4
        cards[target_index]["col"] = target_index % 4

    if isinstance(cards[down_index], dict):
        cards[down_index]["panel_position"] = down_index
        cards[down_index]["row"] = down_index // 4
        cards[down_index]["col"] = down_index % 4

    logger.info(f"Moved card down in grid: {target_index} (row={row}, col={col}) -> {down_index}")
    return cards


# Main callback to handle all position button clicks
# OPTIMIZATION: Updates position-metadata-store to trigger clientside visual updates
# instead of full dashboard re-render, preserving component state
# CRITICAL: Also updates ALL stored-metadata-component stores to keep them in sync
@callback(
    [
        Output("position-metadata-store", "data", allow_duplicate=True),
        Output({"type": "stored-metadata-component", "index": ALL}, "data", allow_duplicate=True),
    ],
    Input({"type": "position-top-btn", "index": ALL}, "n_clicks"),
    Input({"type": "position-up-btn", "index": ALL}, "n_clicks"),
    Input({"type": "position-down-btn", "index": ALL}, "n_clicks"),
    Input({"type": "position-bottom-btn", "index": ALL}, "n_clicks"),
    Input({"type": "position-left-btn", "index": ALL}, "n_clicks"),
    Input({"type": "position-right-btn", "index": ALL}, "n_clicks"),
    State({"type": "stored-metadata-component", "index": ALL}, "data"),
    State("url", "pathname"),
    State("local-store", "data"),
    State("unified-edit-mode-button", "checked"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def handle_position_change(
    top_clicks_all,
    up_clicks_all,
    down_clicks_all,
    bottom_clicks_all,
    left_clicks_all,
    right_clicks_all,
    stored_metadata_list_all,
    pathname,
    local_data,
    edit_mode,
    theme_store,
):
    """
    Handle position button clicks and update component positions.

    OPTIMIZATION: Updates metadata stores and triggers clientside CSS changes
    instead of full dashboard re-render, preserving component state.

    Args:
        top_clicks_all: List of n_clicks for all top buttons (ALL pattern)
        up_clicks_all: List of n_clicks for all up buttons (ALL pattern)
        down_clicks_all: List of n_clicks for all down buttons (ALL pattern)
        bottom_clicks_all: List of n_clicks for all bottom buttons (ALL pattern)
        left_clicks_all: List of n_clicks for all left buttons (ALL pattern)
        right_clicks_all: List of n_clicks for all right buttons (ALL pattern)
        stored_metadata_list_all: List of all component metadata (ALL State)
        pathname: Current URL pathname
        local_data: Local storage data with TOKEN
        edit_mode: Current edit mode state
        theme_store: Current theme data

    Returns:
        Tuple of:
        - Updated metadata for position-metadata-store (triggers clientside CSS updates)
        - Updated metadata for ALL stored-metadata-component stores (keeps state in sync)
    """
    if not ctx.triggered:
        raise PreventUpdate

    # Identify which button was clicked
    triggered_id = ctx.triggered_id
    if not triggered_id:
        raise PreventUpdate

    button_type = triggered_id["type"]
    component_index = str(triggered_id["index"])  # Convert to string for comparison

    logger.info(f"🔄 Position change triggered: {button_type} for component {component_index}")

    # The stored_metadata_list_all is from ALL State - it's a list of all metadata dicts
    if not stored_metadata_list_all:
        logger.warning("Empty stored_metadata_list_all")
        raise PreventUpdate

    # Convert to regular list in case it's wrapped
    stored_metadata = list(stored_metadata_list_all)

    # PRE-PROCESS: Compute panel metadata from component_type for ALL components
    # This is critical because stored-metadata-component stores don't contain panel fields
    # They are computed during rendering in restore_dashboard.py
    logger.info("🔧 PRE-PROCESSING: Computing panel metadata from component_type")
    for comp in stored_metadata:
        comp_type = comp.get("component_type")

        if comp_type == "interactive":
            comp["panel"] = "left"
            comp["component_section"] = None
        elif comp_type == "card":
            comp["panel"] = "right"
            comp["component_section"] = "cards"
        else:
            comp["panel"] = "right"
            comp["component_section"] = "other"

    # Find the target component in metadata
    target_component = None
    for comp in stored_metadata:
        if str(comp.get("index")) == component_index:
            target_component = comp
            break

    if target_component is None:
        logger.warning(f"Component {component_index} not found in stored_metadata")
        raise PreventUpdate

    # Get component metadata for positioning logic
    component_type = target_component.get("component_type")
    panel = target_component.get("panel")
    component_section = target_component.get("component_section")

    logger.info(
        f"  Component details: panel={panel}, section={component_section}, type={component_type}"
    )

    # Separate components by panel and section
    left_panel_components = []  # Interactive
    right_panel_cards = []  # Cards
    right_panel_other = []  # Figures, tables, etc.

    for comp in stored_metadata:
        comp_panel = comp.get("panel")
        comp_section = comp.get("component_section")

        if comp_panel == "left":
            left_panel_components.append(comp)
        elif comp_panel == "right":
            if comp_section == "cards":
                right_panel_cards.append(comp)
            else:
                right_panel_other.append(comp)

    # Determine which list to manipulate based on component's panel/section
    if panel == "left":
        components_list = left_panel_components
        logger.info(f"  Working with left panel (interactive), {len(components_list)} components")
    elif panel == "right" and component_section == "cards":
        components_list = right_panel_cards
        logger.info(f"  Working with right panel cards, {len(components_list)} components")
    else:  # right panel, other section
        components_list = right_panel_other
        logger.info(f"  Working with right panel other, {len(components_list)} components")

    # Find position in the filtered list
    filtered_position = None
    for i, comp in enumerate(components_list):
        if str(comp.get("index")) == component_index:
            filtered_position = i
            break

    if filtered_position is None:
        logger.warning("Component not found in filtered list")
        raise PreventUpdate

    logger.info(f"  Position in filtered list: {filtered_position}/{len(components_list)}")

    # Apply movement function based on button type
    if button_type == "position-up-btn":
        if component_type == "card":
            components_list = move_card_up_in_grid(components_list, filtered_position)
        else:
            components_list = move_component_up(components_list, filtered_position)

    elif button_type == "position-down-btn":
        if component_type == "card":
            components_list = move_card_down_in_grid(components_list, filtered_position)
        else:
            components_list = move_component_down(components_list, filtered_position)

    elif button_type == "position-top-btn":
        components_list = move_component_to_top(components_list, filtered_position)

    elif button_type == "position-bottom-btn":
        components_list = move_component_to_bottom(components_list, filtered_position)

    elif button_type == "position-left-btn":
        if component_type == "card":
            components_list = move_card_left(components_list, filtered_position)
        else:
            logger.warning("Left movement only available for cards")
            raise PreventUpdate

    elif button_type == "position-right-btn":
        if component_type == "card":
            components_list = move_card_right(components_list, filtered_position)
        else:
            logger.warning("Right movement only available for cards")
            raise PreventUpdate

    # Reconstruct stored_metadata with updated positions
    # Put updated list back in the correct place
    if panel == "left":
        left_panel_components = components_list
    elif panel == "right" and component_section == "cards":
        right_panel_cards = components_list
    else:
        right_panel_other = components_list

    # Rebuild full metadata list in correct order
    new_metadata = left_panel_components + right_panel_cards + right_panel_other

    # Update metadata fields for all components
    for i, comp in enumerate(new_metadata):
        comp_panel = comp.get("panel")
        comp_section = comp.get("component_section")

        # Update panel_position based on filtered position
        if comp_panel == "left":
            comp["panel_position"] = left_panel_components.index(comp)
        elif comp_panel == "right" and comp_section == "cards":
            pos = right_panel_cards.index(comp)
            comp["panel_position"] = pos
            comp["row"] = pos // 4
            comp["col"] = pos % 4
        else:
            comp["panel_position"] = right_panel_other.index(comp)

    # Save updated metadata to backend
    TOKEN = local_data.get("access_token") if local_data else None
    if not TOKEN:
        logger.warning("No access token available")
        raise PreventUpdate

    # Extract dashboard_id from pathname (e.g., /dashboard/abc123)
    dashboard_id = pathname.split("/")[-1] if pathname else None
    if not dashboard_id:
        logger.warning("Could not extract dashboard_id from pathname")
        raise PreventUpdate

    # Extract theme from theme_store
    theme = "light"  # Default
    if theme_store:
        if isinstance(theme_store, dict):
            theme = theme_store.get("colorScheme", "light")
        elif isinstance(theme_store, str):
            theme = theme_store

    logger.info(
        f"🔄 Updating position metadata (optimization: no re-render, state preserved, theme={theme})"
    )

    # OPTIMIZATION: Don't render_dashboard - just update metadata and save
    # Clientside callback will handle visual updates via CSS order changes
    # This preserves component state (filters, zoom, etc.)

    # Save to backend asynchronously (non-blocking, best-effort)
    try:
        from datetime import datetime

        from depictio.dash.api_calls import api_call_get_dashboard, api_call_save_dashboard

        # Fetch current dashboard data
        dashboard_data = api_call_get_dashboard(dashboard_id, TOKEN)
        if not dashboard_data:
            logger.warning("⚠️ Could not fetch dashboard data for save")
        else:
            # Update only the stored_metadata field
            dashboard_data["stored_metadata"] = new_metadata
            dashboard_data["last_saved_ts"] = str(datetime.now())

            # Save the complete dashboard data
            save_success = api_call_save_dashboard(dashboard_id, dashboard_data, TOKEN)
            if save_success:
                logger.info(f"✅ Position change saved successfully for dashboard {dashboard_id}")
            else:
                logger.warning("⚠️ Failed to save dashboard (layout will revert on refresh)")
    except Exception as e:
        logger.warning(f"⚠️ Failed to save dashboard: {e} (layout will revert on refresh)")

    # OPTIMIZATION: Return updated metadata to BOTH outputs
    # 1. position-metadata-store: triggers clientside callback (CSS order changes)
    # 2. stored-metadata-component stores: keeps metadata in sync for subsequent moves
    # Components stay mounted → state preserved (filters, zoom, selections, etc.)
    logger.info(f"✅ Returning updated metadata to both outputs ({len(new_metadata)} components)")
    return new_metadata, new_metadata


def register_position_clientside_callback(app):
    """
    Register clientside callback for lightweight position updates.

    This callback applies CSS order/grid changes to components without
    triggering React re-renders, preserving component state.
    """
    app.clientside_callback(
        """
        function(newMetadata) {
            // Position update via CSS without re-rendering
            if (!newMetadata || !Array.isArray(newMetadata)) {
                return window.dash_clientside.no_update;
            }

            console.log('🔄 CLIENTSIDE POSITION UPDATE: Processing', newMetadata.length, 'components');

            // Apply position changes via CSS order property
            newMetadata.forEach(comp => {
                const boxId = `box-${comp.index}`;
                const elem = document.getElementById(boxId);

                if (!elem) {
                    console.warn('⚠️  Component not found:', boxId);
                    return;
                }

                const panel = comp.panel;
                const componentSection = comp.component_section;
                const panelPosition = comp.panel_position;

                // Apply flexbox order for vertical stacking (left panel, right panel other)
                if (panel === 'left' || (panel === 'right' && componentSection === 'other')) {
                    elem.style.order = panelPosition;
                    console.log(`  ✓ Set order=${panelPosition} for ${boxId} (${panel}/${componentSection || 'main'})`);
                }

                // Apply grid positioning for cards (4-column grid)
                if (panel === 'right' && componentSection === 'cards') {
                    const row = comp.row;
                    const col = comp.col;
                    if (row !== undefined && col !== undefined) {
                        // CSS Grid uses 1-based indexing
                        elem.style.gridRow = (row + 1).toString();
                        elem.style.gridColumn = (col + 1).toString();
                        console.log(`  ✓ Set grid position (${row},${col}) for card ${boxId}`);
                    }
                }
            });

            console.log('✅ CLIENTSIDE POSITION UPDATE: Complete');
            return null;  // No DOM update needed
        }
        """,
        Output("position-update-dummy", "children"),
        Input("position-metadata-store", "data"),
        prevent_initial_call=True,
    )

    logger.info("✅ Clientside position update callback registered")
