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
from depictio.dash.celery_app import (
    generate_dashboard_screenshot_dual,
)


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


def register_auto_screenshot_callback(app):
    """
    Register auto-screenshot callback for dashboard views.

    This callback automatically generates dual-theme screenshots when viewing
    a dashboard if screenshots don't exist yet or need upgrading from legacy
    single-theme to dual-theme.

    Can be registered in both Viewer and Editor apps.
    """

    @app.callback(
        Output("screenshot-debounce-store", "data", allow_duplicate=True),
        Input("url", "pathname"),
        State("screenshot-debounce-store", "data"),
        prevent_initial_call=True,
    )
    def auto_screenshot_on_dashboard_view(pathname, debounce_data):
        """
        Automatically generate dual-theme screenshots when viewing a dashboard if:
        - Screenshots don't exist yet
        - This is useful for dashboards created before the dual-theme feature
        - Or when screenshot generation previously failed

        This callback triggers on URL changes to /dashboard/{id} pages.

        Args:
            pathname: Current URL pathname
            debounce_data: Debounce tracking data

        Returns:
            dict: Updated debounce data
        """
        import os
        import time

        # CRITICAL: Prevent infinite loop - don't trigger screenshots during Playwright visits
        # Playwright browser visits will trigger this callback, which would queue more screenshots
        import flask

        user_agent = flask.request.headers.get("User-Agent", "")
        if "HeadlessChrome" in user_agent or "Playwright" in user_agent:
            logger.debug("Skipping auto-screenshot: Playwright/headless browser detected")
            raise dash.exceptions.PreventUpdate

        # VERBOSE LOGGING for debugging
        logger.info(f"🎬 AUTO-SCREENSHOT CALLBACK TRIGGERED: pathname={pathname}")

        # Only process dashboard view pages
        if not pathname or not pathname.startswith("/dashboard/"):
            logger.debug(f"Skipping auto-screenshot: not a dashboard page (pathname={pathname})")
            raise dash.exceptions.PreventUpdate

        # Skip stepper/edit pages
        if "/component/add/" in pathname or "/edit" in pathname:
            logger.debug(f"Skipping auto-screenshot: stepper or edit page (pathname={pathname})")
            raise dash.exceptions.PreventUpdate

        # Extract dashboard ID from URL
        path_parts = pathname.split("/")
        logger.info(f"  → Path parts: {path_parts}")

        if len(path_parts) < 3:
            logger.debug(f"Skipping auto-screenshot: invalid path structure (parts={path_parts})")
            raise dash.exceptions.PreventUpdate

        dashboard_id = path_parts[2]  # /dashboard/{id}
        logger.info(f"  → Extracted dashboard_id: {dashboard_id}")

        if not dashboard_id:
            logger.debug("Skipping auto-screenshot: empty dashboard_id")
            raise dash.exceptions.PreventUpdate

        # Get current time for debouncing and age checks
        current_time = time.time()

        # Check if dual-theme screenshots exist and if they need updating
        output_folder = "/app/depictio/dash/static/screenshots"
        light_path = os.path.join(output_folder, f"{dashboard_id}_light.png")
        dark_path = os.path.join(output_folder, f"{dashboard_id}_dark.png")
        legacy_path = os.path.join(output_folder, f"{dashboard_id}.png")

        logger.info(f"  → Checking screenshots in: {output_folder}")
        logger.info(f"     Light: {os.path.exists(light_path)}")
        logger.info(f"     Dark: {os.path.exists(dark_path)}")
        logger.info(f"     Legacy: {os.path.exists(legacy_path)}")

        # Smart update detection: check if dashboard changed since screenshot was taken
        needs_update = False
        if os.path.exists(light_path) and os.path.exists(dark_path):
            # Get screenshot file modification time
            light_mtime = os.path.getmtime(light_path)
            dark_mtime = os.path.getmtime(dark_path)
            screenshot_mtime = max(light_mtime, dark_mtime)

            # Note: We could fetch dashboard from API to check last_modified timestamp
            # but we don't have access to the user token in this callback
            # So we use a simpler heuristic: check if screenshot is older than 1 hour
            screenshot_age = current_time - screenshot_mtime

            # If screenshot is recent (< 1 hour old), skip regeneration
            # This prevents constant regeneration while allowing updates for stale screenshots
            if screenshot_age < 3600:  # 1 hour in seconds
                logger.info(
                    f"✅ Recent dual-theme screenshots exist (age: {screenshot_age:.0f}s), skipping auto-generation"
                )
                raise dash.exceptions.PreventUpdate
            else:
                needs_update = True
                logger.info(
                    f"⏰ Screenshots are stale (age: {screenshot_age:.0f}s > 1h), will regenerate"
                )

        # If only legacy screenshot exists, upgrade to dual-theme
        elif os.path.exists(legacy_path):
            needs_update = True
            logger.info(f"🔄 Found legacy screenshot for {dashboard_id}, upgrading to dual-theme")
        else:
            needs_update = True
            logger.info(f"🆕 No screenshots found for {dashboard_id}, will generate")

        # Only proceed if screenshot needs updating
        if not needs_update:
            raise dash.exceptions.PreventUpdate

        # Apply debouncing to avoid spamming screenshot requests
        last_screenshot = debounce_data.get("last_screenshot", 0) if debounce_data else 0
        debounce_seconds = 5

        if current_time - last_screenshot > debounce_seconds:
            logger.info(
                f"📸 QUEUEING dual-theme screenshot task for dashboard {dashboard_id} "
                f"(triggered by page view)"
            )
            try:
                generate_dashboard_screenshot_dual.delay(dashboard_id)
                logger.info(f"✅ Successfully queued screenshot task for dashboard {dashboard_id}")
            except Exception as e:
                logger.error(f"❌ Failed to queue screenshot task: {e}")
                raise dash.exceptions.PreventUpdate
            return {"last_screenshot": current_time}
        else:
            logger.info(
                f"⏱️  Auto-screenshot debounced for {dashboard_id} "
                f"(last: {current_time - last_screenshot:.1f}s ago, threshold: {debounce_seconds}s)"
            )
            raise dash.exceptions.PreventUpdate


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

    Note: This also registers the auto-screenshot callback.
    """

    @app.callback(
        Output("notification-container", "sendNotifications"),
        Output("screenshot-debounce-store", "data"),
        Input("save-button-dashboard", "n_clicks"),
        State("url", "pathname"),
        State("local-store", "data"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": ALL}, "data"),
        State({"type": "left-panel-grid", "index": ALL}, "itemLayout"),
        State({"type": "right-panel-grid", "index": ALL}, "itemLayout"),
        State("screenshot-debounce-store", "data"),
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
        debounce_data,
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
            debounce_data: Debounce tracking data for screenshot generation.

        Returns:
            tuple: (notification data, debounce data) for success/failure feedback to user.

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

        # Initialize debounce data tracking
        import time

        current_time = time.time()
        last_screenshot = debounce_data.get("last_screenshot", 0) if debounce_data else 0
        debounce_seconds = 5

        if success:
            # Smart debouncing: only trigger screenshot if enough time has passed
            if current_time - last_screenshot > debounce_seconds:
                # Trigger dual-theme screenshot generation for main dashboard
                generate_dashboard_screenshot_dual.delay(dashboard_id)
                logger.debug(f"Dual-theme screenshot task queued for main dashboard {dashboard_id}")

                # Also queue screenshot tasks for all child tabs
                from depictio.dash.layouts.dashboards_management import get_child_tabs_info

                try:
                    tabs_info = get_child_tabs_info(dashboard_id, TOKEN)
                    child_tabs = tabs_info.get("tabs", [])

                    if child_tabs:
                        logger.info(f"Queueing screenshot tasks for {len(child_tabs)} child tabs")
                        for tab in child_tabs:
                            # Use dashboard_id (URL identifier) not _id (MongoDB ObjectId)
                            tab_id = tab.get("dashboard_id")
                            if tab_id:
                                generate_dashboard_screenshot_dual.delay(str(tab_id))
                                logger.debug(f"  → Queued screenshot for child tab {tab_id}")
                except Exception as e:
                    logger.warning(f"Failed to queue child tab screenshots: {e}")

                debounce_data = {"last_screenshot": current_time}
            else:
                logger.info(
                    f"Screenshot debounced for dashboard {dashboard_id} "
                    f"(last: {current_time - last_screenshot:.1f}s ago, threshold: {debounce_seconds}s)"
                )
                debounce_data = debounce_data or {"last_screenshot": last_screenshot}
        else:
            logger.error(f"Failed to save dashboard {dashboard_id}")
            debounce_data = debounce_data or {"last_screenshot": last_screenshot}

        # Return notification to user
        from dash_iconify import DashIconify

        if success:
            return (
                [
                    {
                        "id": "save-success",
                        "title": "Dashboard Saved",
                        "message": f"Successfully saved {len(all_metadata)} components and layout positions",
                        "color": "teal",
                        "icon": DashIconify(icon="mdi:check-circle"),
                        "autoClose": 3000,
                    }
                ],
                debounce_data,
            )
        else:
            return (
                [
                    {
                        "id": "save-error",
                        "title": "Save Failed",
                        "message": "Failed to save dashboard. Please try again.",
                        "color": "red",
                        "icon": DashIconify(icon="mdi:alert-circle"),
                        "autoClose": 5000,
                    }
                ],
                debounce_data,
            )

    # Also register auto-screenshot callback (works in both editor and viewer apps)
    register_auto_screenshot_callback(app)
