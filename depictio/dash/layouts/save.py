"""
Dashboard Save Module

This module provides functionality for saving dashboard state and metadata.
It includes callbacks for persisting dashboard layouts, component metadata,
and user preferences to the database via API calls.

The module is organized into:
- Layout validation and cleanup functions
- Minimal save callback registration for lightweight saves
"""

import dash
from dash import ALL, Input, Output, State

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_get_dashboard,
    api_call_save_dashboard,
)
from depictio.dash.celery_app import generate_dashboard_screenshot


def validate_and_clean_orphaned_layouts(stored_layout_data, stored_metadata):
    """
    Validate and clean orphaned layout entries that don't have corresponding metadata entries.

    Args:
        stored_layout_data (list): List of layout entries with 'i' field containing 'box-{index}'
        stored_metadata (list): List of metadata entries with 'index' field

    Returns:
        list: Cleaned layout data with orphaned entries removed
    """
    if not stored_layout_data or not stored_metadata:
        return stored_layout_data or []

    # Extract valid component IDs from metadata
    valid_component_ids = {
        str(meta.get("index")) for meta in stored_metadata if meta.get("index") is not None
    }

    cleaned_layout_data = []
    orphaned_layouts = []

    for layout_entry in stored_layout_data:
        layout_id = layout_entry.get("i", "")

        # Extract component ID from layout ID (format: 'box-{index}')
        if layout_id.startswith("box-"):
            component_id = layout_id[4:]  # Remove 'box-' prefix

            if component_id in valid_component_ids:
                cleaned_layout_data.append(layout_entry)
            else:
                orphaned_layouts.append(layout_entry)
                logger.debug(f"Removing orphaned layout: {layout_id} (no matching metadata)")
        else:
            # Keep entries that don't follow the 'box-{index}' pattern for safety
            cleaned_layout_data.append(layout_entry)
            logger.warning(
                f"⚠️ LAYOUT VALIDATION - Layout entry with unexpected ID format: {layout_id}"
            )

    if orphaned_layouts:
        logger.debug(f"Removed {len(orphaned_layouts)} orphaned layout entries")
        logger.debug(f"Kept {len(cleaned_layout_data)} valid layout entries")
    else:
        logger.debug(f"No orphaned layouts found, all {len(cleaned_layout_data)} entries are valid")

    return cleaned_layout_data


def register_callbacks_save_lite(app):
    """
    Minimal save callback - captures component metadata only.

    Simplified architecture:
    - Listens to component metadata stores
    - Fetches current dashboard from DB
    - Updates metadata field only
    - Validates with Pydantic DashboardData model
    - Saves to DB without enrichment

    Skipped features (for simplicity):
    - Layout positions (no draggable state)
    - Notes content (no notes-editor-store)
    - Interactive component values
    - Complex metadata deduplication
    - Edit mode state tracking
    """

    @app.callback(
        Output("notification-container", "sendNotifications"),
        Input("save-button-dashboard", "n_clicks"),
        State("url", "pathname"),
        State("local-store", "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "left-panel-grid", "index": ALL}, "itemLayout"),
        State({"type": "right-panel-grid", "index": ALL}, "itemLayout"),
        prevent_initial_call=True,
    )
    def save_dashboard_minimal(
        n_clicks,
        pathname,
        local_store,
        stored_metadata,
        interactive_metadata,
        left_panel_layouts,
        right_panel_layouts,
    ):
        """
        Minimal dashboard save callback.

        Captures component metadata and layout positions, validates with Pydantic,
        and persists to database via API. This is a lightweight save that focuses
        on essential dashboard state.

        Args:
            n_clicks: Number of times save button has been clicked.
            pathname: Current URL pathname containing dashboard ID.
            local_store: Local storage data containing access token.
            stored_metadata: List of component metadata from stored-metadata-component stores.
            interactive_metadata: List of interactive component metadata.
            left_panel_layouts: Layout data from left panel grid.
            right_panel_layouts: Layout data from right panel grid.

        Returns:
            list: Notification data for success/failure feedback to user.

        Raises:
            dash.exceptions.PreventUpdate: When save should be skipped (no auth, stepper page).
        """
        from depictio.models.models.dashboards import DashboardData

        # 1. Validate trigger
        if not n_clicks or not local_store:
            raise dash.exceptions.PreventUpdate

        # Skip if on stepper page
        if pathname and "/component/add/" in pathname:
            logger.debug("Skipping save on stepper page")
            raise dash.exceptions.PreventUpdate

        # 2. Extract dashboard_id and token
        # Handle both /dashboard/{id} and /dashboard/{id}/edit paths
        path_parts = pathname.split("/")
        if path_parts[-1] == "edit":
            dashboard_id = path_parts[-2]  # Get ID before /edit
        else:
            dashboard_id = path_parts[-1]  # Get last part
        TOKEN = local_store["access_token"]

        logger.info(
            f"Saving dashboard {dashboard_id}: {len(stored_metadata)} components, "
            f"{len(interactive_metadata)} interactive"
        )

        # 3. Fetch current dashboard from DB (baseline)
        dashboard_dict = api_call_get_dashboard(dashboard_id, TOKEN)
        if not dashboard_dict:
            logger.error(f"Failed to fetch dashboard {dashboard_id}")
            raise dash.exceptions.PreventUpdate

        # 4. Update with captured state (metadata + dual-panel layouts)
        # Merge both metadata lists (general components + interactive components)
        all_metadata = stored_metadata + interactive_metadata
        dashboard_dict["stored_metadata"] = all_metadata

        # RECALCULATE positions in Python to ensure correct IDs and dimensions
        # This avoids relying on DashGridLayout's internal state which may be stale/incorrect
        from depictio.dash.layouts.draggable import (
            calculate_left_panel_positions,
            calculate_right_panel_positions,
            separate_components_by_panel,
        )

        # Separate components by panel
        interactive_components, right_panel_components = separate_components_by_panel(all_metadata)

        # Extract layout data from pattern-matched grids with proper validation
        # Pattern-matched ALL returns list of lists: [[layout_data], ...]
        left_panel_saved_data = (
            left_panel_layouts[0]
            if left_panel_layouts and len(left_panel_layouts) > 0 and left_panel_layouts[0]
            else None
        )
        right_panel_saved_data = (
            right_panel_layouts[0]
            if right_panel_layouts and len(right_panel_layouts) > 0 and right_panel_layouts[0]
            else None
        )

        # Recalculate fresh layout positions using current metadata
        # Pass existing saved data so we preserve user's drag positions (x/y)
        left_panel_layout = calculate_left_panel_positions(
            interactive_components,
            saved_layout_data=left_panel_saved_data,
        )
        right_panel_layout = calculate_right_panel_positions(
            right_panel_components,
            saved_layout_data=right_panel_saved_data,
        )

        dashboard_dict["left_panel_layout_data"] = left_panel_layout
        dashboard_dict["right_panel_layout_data"] = right_panel_layout

        # 5. Validate with Pydantic model
        try:
            DashboardData.from_mongo(dashboard_dict)
        except Exception as e:
            logger.error(f"Pydantic validation failed: {e}")
            raise dash.exceptions.PreventUpdate

        # 6. Save to database via API
        success = api_call_save_dashboard(
            dashboard_id,
            dashboard_dict,
            TOKEN,
            enrich=False,  # Fast save, no enrichment needed
        )

        if success:
            # Trigger screenshot generation in background (fire-and-forget)
            # User gets immediate feedback, screenshot happens asynchronously
            generate_dashboard_screenshot.delay(dashboard_id)
            logger.debug(f"Screenshot task queued for dashboard {dashboard_id}")
        else:
            logger.error(f"Failed to save dashboard {dashboard_id}")

        # Return notification to user
        from dash_iconify import DashIconify

        if success:
            return [
                {
                    "id": "save-success",
                    "title": "Dashboard Saved",
                    "message": f"Successfully saved {len(all_metadata)} components and layout positions",
                    "color": "teal",
                    "icon": DashIconify(icon="mdi:check-circle"),
                    "autoClose": 3000,
                }
            ]
        else:
            return [
                {
                    "id": "save-error",
                    "title": "Save Failed",
                    "message": "Failed to save dashboard. Please try again.",
                    "color": "red",
                    "icon": DashIconify(icon="mdi:alert-circle"),
                    "autoClose": 5000,
                }
            ]
