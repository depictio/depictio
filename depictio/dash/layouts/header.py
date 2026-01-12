"""
Dashboard Header Component

This module provides the main dashboard header with navigation, controls, and interactive elements.
Includes modular components for buttons, badges, modals, and responsive layout management.
"""

import datetime

import dash
import dash_mantine_components as dmc
import httpx
from dash import Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token
from depictio.dash.colors import colors

# Constants
BUTTON_STYLE = {"margin": "0 0px", "fontFamily": "Virgil", "marginTop": "5px"}


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def _check_filter_activity(interactive_values):
    """Check if any interactive components have active filters by comparing current values with default states."""
    # logger.debug(f"🔍 _check_filter_activity called with: {interactive_values}")

    if not interactive_values:
        logger.info("📭 No interactive_values provided")
        return False

    # Handle different possible structures in interactive_values
    interactive_values_data = []

    if "interactive_components_values" in interactive_values:
        interactive_values_data = interactive_values["interactive_components_values"]
        logger.info(f"📦 Found interactive_components_values: {len(interactive_values_data)} items")
    elif isinstance(interactive_values, dict):
        # Look for any values that might be interactive components
        for key, value in interactive_values.items():
            if isinstance(value, dict) and "value" in value:
                interactive_values_data.append(value)
        logger.info(f"📦 Extracted from dict structure: {len(interactive_values_data)} items")

    if not interactive_values_data:
        logger.info("📭 No interactive component data found")
        return False

    logger.info(f"🔍 Checking {len(interactive_values_data)} components for filter activity")

    for i, component_data in enumerate(interactive_values_data):
        if isinstance(component_data, dict):
            component_value = component_data.get("value")
            component_metadata = component_data.get("metadata", {})
            default_state = component_metadata.get("default_state", {})

            logger.info(f"🎛️ Component {i}: value={component_value}")
            logger.info(f"  🎯 Default state: {default_state}")

            # Skip None values
            if component_value is None:
                logger.info("  ⏭️ Skipping None value")
                continue

            # Skip if no default_state available
            if not default_state:
                logger.info("  ⚠️ No default_state available, skipping")
                continue

            # Compare current value with default state
            if _is_different_from_default(component_value, default_state):
                logger.info("  ✅ Component differs from default state - filter active!")
                return True
            else:
                logger.info("  ⏭️ Component matches default state")

    logger.info("📭 No active filters detected")
    return False


def _is_empty_selection(value):
    """
    Check if a value represents an empty selection.
    Handles both empty arrays [] and null/None values.
    """
    return value is None or (isinstance(value, list) and len(value) == 0)


def _is_different_from_default(current_value, default_state):
    """
    Simple comparison of current value with default state.

    Args:
        current_value: The current value of the component
        default_state (dict): The default state configuration for the component

    Returns:
        bool: True if the component differs from its default state
    """
    try:
        # For range sliders, compare with default_range
        if "default_range" in default_state:
            default_range = default_state["default_range"]
            return current_value != default_range

        # For all other components, compare with default_value
        elif "default_value" in default_state:
            default_value = default_state["default_value"]

            # Special handling for MultiSelect components:
            # Both empty array [] and null should be considered equivalent (no selection)
            if _is_empty_selection(current_value) and _is_empty_selection(default_value):
                return False  # Both are empty, so no difference

            return current_value != default_value

        # If no recognizable default state structure, assume not filtered
        else:
            logger.debug(f"Unknown default_state structure: {default_state}")
            return False

    except Exception as e:
        logger.warning(f"Error comparing with default state: {e}")
        return False


def _get_user_permissions(current_user, data):
    """Extract user permissions for the dashboard."""
    owner = str(current_user.id) in [str(e["id"]) for e in data["permissions"]["owners"]]

    viewer_ids = [str(e["id"]) for e in data["permissions"]["viewers"] if e != "*"]
    is_viewer = str(current_user.id) in viewer_ids
    has_wildcard = "*" in data["permissions"]["viewers"]
    is_public = data.get("is_public", False)
    viewer = is_viewer or has_wildcard or is_public

    return owner, viewer


# =============================================================================
# COMPONENT BUILDERS
# =============================================================================


def _create_action_icon(icon, button_id, disabled=False, n_clicks=None, tooltip=None, **kwargs):
    """Create a standardized action icon button with optional tooltip."""
    # Add n_clicks to constructor parameters if provided
    action_icon_params = {
        "id": button_id,
        "size": "md",
        "radius": "xl",
        "variant": "subtle",
        "color": "gray",
        "style": BUTTON_STYLE,
        "disabled": disabled,
    }

    # Include n_clicks if provided
    if n_clicks is not None:
        action_icon_params["n_clicks"] = n_clicks

    # Merge additional kwargs
    action_icon_params.update(kwargs)

    button = dmc.ActionIcon(
        DashIconify(icon=icon, width=28, color="gray"),
        **action_icon_params,
    )

    if tooltip:
        return dmc.Tooltip(
            label=tooltip,
            position="bottom",
            withArrow=True,
            openDelay=800,
            children=button,
        )

    return button


def _create_reset_filters_button():
    """Create the reset all filters button with consistent styling."""
    button = dmc.ActionIcon(
        DashIconify(icon="bx:reset", width=28, color="gray"),
        id="reset-all-filters-button",
        size="md",  # Medium button size
        radius="xl",
        variant="subtle",  # Use subtle variant like other buttons when no filters
        color="gray",
        style=BUTTON_STYLE,
        disabled=False,
        n_clicks=0,
    )

    return dmc.Tooltip(
        label="Reset all applied filters\nto their default values",
        position="bottom",
        withArrow=True,
        openDelay=800,
        children=button,
    )


def _create_apply_filters_button():
    """Create the apply filters button with checkmark icon."""
    button = dmc.ActionIcon(
        DashIconify(icon="material-symbols:check", width=28, color="gray"),
        id="apply-filters-button",
        size="md",  # Medium button size
        radius="xl",
        variant="subtle",  # Default subtle variant
        color="gray",
        # style=BUTTON_STYLE,
        style={"display": "none"},  # Hide by default, shown only if live interactivity is OFF
        disabled=True,  # Disabled by default (no pending changes)
        n_clicks=0,
    )

    return dmc.Tooltip(
        label="Apply pending filter changes\nto update the dashboard",
        position="bottom",
        withArrow=True,
        openDelay=800,
        children=button,
    )


def _create_info_badges(data, project_name):
    """Create the informational badges for project, owner, and last saved."""
    return dmc.Stack(
        [
            dmc.Badge(
                f"Project: {project_name}",
                color=colors["teal"],
                leftSection=DashIconify(icon="mdi:jira", width=16, color="white"),
            ),
            dmc.Badge(
                f"Owner: {data['permissions']['owners'][0]['email']}",
                color=colors["blue"],
                leftSection=DashIconify(icon="mdi:account", width=16, color="white"),
            ),
            dmc.Badge(
                _format_last_saved(data["last_saved_ts"]),
                color=colors["purple"],
                leftSection=DashIconify(
                    icon="mdi:clock-time-four-outline", width=16, color="white"
                ),
            ),
        ],
        justify="center",
        align="flex-start",
        gap=5,
    )


def _format_last_saved(timestamp):
    """Format the last saved timestamp."""
    if timestamp == "":
        return "Last saved: Never"
    else:
        formatted_ts = datetime.datetime.strptime(timestamp.split(".")[0], "%Y-%m-%d %H:%M:%S")
        return f"Last saved: {formatted_ts}"


def _create_backend_components():
    """Create backend components (stores, modals, etc.)."""
    modal_save_button = dmc.Modal(
        children=[
            dmc.Stack(
                [
                    dmc.Text(
                        "Your amazing dashboard was successfully saved!",
                        size="lg",
                        c="green",
                        ta="center",
                    )
                ],
                gap="md",
                style={"padding": "20px", "backgroundColor": "var(--app-success-bg, #F0FFF0)"},
            )
        ],
        id="success-modal-dashboard",
        opened=False,
        centered=True,
        closeOnClickOutside=True,
        closeOnEscape=True,
        title=dmc.Group(
            [
                DashIconify(icon="material-symbols:check-circle", width=24, color="green"),
                dmc.Text("Success!", size="xl", fw="bold", c="green"),
            ],
            gap="xs",
            justify="center",
        ),
    )

    # DMC Box instead of html.Div for backend stores
    # Import interactive stores from dedicated module
    from depictio.dash.modules.interactive_component.callbacks.core_interactivity import (
        get_interactive_stores,
    )

    backend_stores = dmc.Stack(
        [
            *get_interactive_stores(),  # Interactive filtering stores
            # NOTE: dashboard-tabs-store moved to global app layout (app_layout.py)
            # to ensure it's always available before dashboard-specific callbacks run
        ],
        gap=0,  # No gap needed for stores
    )

    # DMC Box instead of html.Div for backend components container
    return dmc.Box(
        [
            backend_stores,
            modal_save_button,
            html.Div(
                id="stepper-output", style={"display": "none"}
            ),  # Keep html.Div for hidden output
            html.Div(
                id="edit-mode-navigation-dummy", style={"display": "none"}
            ),  # Dummy output for edit mode navigation callback
        ]
    )


# =============================================================================
# CALLBACKS
# =============================================================================


def register_callbacks_header(app):
    logger.info("🔧 REGISTERING HEADER CALLBACKS (including interactive filter Store callback)")

    # REMOVED: toggle_buttons clientside callback (replaced by URL-based edit mode)
    # Previously controlled button disabled states based on unified-edit-mode-button toggle
    # Now buttons are conditionally rendered in header based on edit_mode parameter
    # - View mode (/dashboard/{id}): Only reset filters + edit dashboard button visible
    # - Edit mode (/dashboard/{id}/edit): All edit controls visible
    # showRemoveButton/showResizeHandles now controlled in design_draggable(edit_mode=...)

    # REMOVED: toggle_share_modal_dashboard callback (share functionality not implemented)
    # Previously controlled share modal visibility for dashboard sharing feature
    # Feature incomplete - modal UI doesn't exist, button hidden
    # Removed to reduce callback graph size and improve startup performance

    # PHASE 3 SPRINT 1: Converted to clientside for instant response (-1212ms)
    # Pure boolean toggle, no server logic needed
    # NOTES FOOTER DISABLED: Removed notes-footer-content references
    app.clientside_callback(
        """
        function(n_clicks, is_open) {
            console.log('🔧 CLIENTSIDE OFFCANVAS TOGGLE:', n_clicks, 'is_open:', is_open);

            if (!n_clicks) {
                return is_open;
            }

            const new_drawer_state = !is_open;
            console.log('→ Toggling drawer to:', new_drawer_state);
            return new_drawer_state;
        }
        """,
        Output("offcanvas-parameters", "opened"),
        Input("open-offcanvas-parameters-button", "n_clicks"),
        State("offcanvas-parameters", "opened"),
        prevent_initial_call=True,
    )

    # REMOVED: Edit badge sync callbacks (replaced by URL-based edit mode)
    # Previously synced edit status badges with unified-edit-mode-button toggle
    # Now edit mode is determined by URL and displayed via "Edit Dashboard" / "Exit Edit Mode" buttons
    # Removed callbacks:
    # - edit_badge_drawer_sync: Updated edit-status-badge-drawer based on toggle
    # - edit_button_header_sync: Updated edit-status-badge-clickable-2 based on toggle
    # - edit_badge_clickable: Made edit badge clickable to toggle edit mode

    # Update live interactivity badge based on toggle state
    # @app.callback(
    #     [
    #         Output("live-interactivity-badge", "children"),
    #         Output("live-interactivity-badge", "color"),
    #         Output("live-interactivity-badge", "leftSection"),
    #     ],
    #     [
    #         Input("live-interactivity-toggle", "checked"),
    #         Input("live-interactivity-store", "data"),
    #     ],
    #     prevent_initial_call=False,
    # )
    # def update_live_interactivity_badge(toggle_checked, store_data):
    #     """Update the live interactivity badge based on toggle state."""
    #     # Use store data as source of truth, fall back to toggle
    #     is_live_on = store_data if store_data is not None else toggle_checked
    #     if is_live_on:
    #         return (
    #             "Live ON",
    #             "green",
    #             DashIconify(icon="mdi:lightning-bolt", width=8, color="white"),
    #         )
    #     else:
    #         return (
    #             "Live OFF",
    #             "gray",
    #             DashIconify(icon="mdi:lightning-bolt-outline", width=8, color="white"),
    #         )

    # Make live interactivity badge clickable to toggle live mode
    # @app.callback(
    #     [
    #         Output("live-interactivity-toggle", "checked", allow_duplicate=True),
    #         Output("live-interactivity-store", "data", allow_duplicate=True),
    #     ],
    #     Input("live-interactivity-badge-clickable", "n_clicks"),
    #     State("live-interactivity-toggle", "checked"),
    #     prevent_initial_call=True,
    # )
    # def toggle_live_interactivity_from_badge(n_clicks, current_state):
    #     """Toggle live interactivity when clicking on live interactivity badge."""
    #     if n_clicks:
    #         new_state = not current_state
    #         return new_state, new_state
    #     return dash.no_update, dash.no_update

    # # Sync toggle and store on toggle change
    # @app.callback(
    #     Output("live-interactivity-store", "data", allow_duplicate=True),
    #     Input("live-interactivity-toggle", "checked"),
    #     prevent_initial_call=True,
    # )
    # def sync_live_interactivity_store(toggle_checked):
    #     """Sync the live interactivity store when toggle changes."""
    #     return toggle_checked

    # @app.callback(
    #     [
    #         Output("reset-all-filters-button", "color"),
    #         Output("reset-all-filters-button", "variant"),
    #         Output("reset-all-filters-button", "leftSection"),
    #     ],
    #     Input("interactive-values-store", "data"),
    #     prevent_initial_call=False,
    # )
    # def update_reset_button_style(interactive_values):
    #     """Update reset button style and icon color based on filter activity."""
    #     # Use INFO level logging so it's visible by default
    #     # logger.debug(f"🔍 Reset button style check - interactive_values: {interactive_values}")

    #     has_active_filters = _check_filter_activity(interactive_values)

    #     logger.info(f"🎯 Filter activity detected: {has_active_filters}")

    #     if has_active_filters:
    #         # Orange filled variant with white icon when filters are active
    #         logger.info("🟠 Setting reset button to orange with white icon (filters active)")
    #         icon = DashIconify(icon="bx:reset", width=16, color="white")
    #         return colors["orange"], "filled", icon
    #     else:
    #         # Gray subtle variant with gray icon when no filters
    #         logger.info("⚪ Setting reset button to gray with gray icon (no filters)")
    #         icon = DashIconify(icon="bx:reset", width=16, color="gray")
    #         return "gray", "light", icon

    # @app.callback(
    #     Output("stored_metadata", "data"),
    #     Input("url", "pathname"),  # Assuming you have a URL component triggering on page load
    #     prevent_initial_call=True
    # )
    # def load_stored_metadata(pathname):
    #     """
    #     Load stored_metadata from MongoDB and store it in the 'stored_metadata' dcc.Store.
    #     """
    #     try:
    #         dashboard_id = pathname.split("/")[-1]
    #         logger.info(f"Loading stored_metadata for dashboard_id: {dashboard_id}")

    #         from depictio.api.v1.db import dashboards_collection
    #         dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_id})
    #         if not dashboard:
    #             logger.error(f"Dashboard with ID {dashboard_id} not found.")
    #             return dash.no_update

    #         stored_metadata = dashboard.get("stored_metadata", [])
    #         if not stored_metadata:
    #             logger.warning(f"No stored_metadata found for dashboard_id: {dashboard_id}.")
    #             return []

    #         logger.info(f"Loaded stored_metadata: {stored_metadata}")
    #         return stored_metadata

    #     except Exception as e:
    #         logger.exception("Failed to load stored_metadata from MongoDB.")
    #         return dash.no_update

    # =============================================================================
    # BURGER BUTTON CALLBACKS (DMC Burger for navbar toggle) - CLIENTSIDE
    # =============================================================================

    # Sync burger opened state with sidebar-collapsed store (inverted) - CLIENTSIDE for instant response
    app.clientside_callback(
        """
        function(is_collapsed) {
            console.log('🍔 CLIENTSIDE BURGER SYNC: collapsed=' + is_collapsed);
            // Burger opened = NOT collapsed
            return (is_collapsed !== null && is_collapsed !== undefined) ? !is_collapsed : true;
        }
        """,
        Output("burger-button", "opened", allow_duplicate=True),
        Input("sidebar-collapsed", "data"),
        prevent_initial_call=True,
    )

    # Update sidebar-collapsed store when burger is clicked - CLIENTSIDE for instant response
    app.clientside_callback(
        """
        function(burger_opened, pathname) {
            console.log('🍔 CLIENTSIDE BURGER CLICK: opened=' + burger_opened + ', pathname=' + pathname);
            // Only update on dashboard pages (viewer or editor app)
            if (!pathname || !(pathname.startsWith('/dashboard/') || pathname.startsWith('/dashboard-edit/'))) {
                console.log('🚫 Ignoring burger click on non-dashboard page');
                return window.dash_clientside.no_update;
            }

            // sidebar-collapsed = NOT burger_opened
            const is_collapsed = !burger_opened;
            console.log('✅ Setting collapsed=' + is_collapsed);
            return is_collapsed;
        }
        """,
        Output("sidebar-collapsed", "data", allow_duplicate=True),
        Input("burger-button", "opened"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )

    # =============================================================================
    # EDIT MODE NAVIGATION CALLBACKS (CLIENTSIDE WITH HARD RELOAD)
    # =============================================================================

    # Unified clientside callback for edit mode toggle with hard page reload
    # Uses window.location.href to force full browser reload when switching modes
    # NOTE: Using prevent_initial_call="initial_duplicate" to avoid firing on page load
    app.clientside_callback(
        """
        function(enter_clicks, exit_clicks, current_pathname) {
            console.log('═══════════════════════════════════════════════');
            console.log('🔧 EDIT MODE TOGGLE CALLBACK FIRED');
            console.log('   enter_clicks:', enter_clicks);
            console.log('   exit_clicks:', exit_clicks);
            console.log('   current_pathname:', current_pathname);

            // Determine which button was clicked
            const triggered = window.dash_clientside.callback_context.triggered;
            console.log('   triggered:', triggered);

            if (!triggered || triggered.length === 0) {
                console.log('   ❌ No trigger, preventing update');
                throw window.dash_clientside.PreventUpdate;
            }

            const trigger_id = triggered[0].prop_id.split('.')[0];
            const trigger_value = triggered[0].value;
            console.log('   trigger_id:', trigger_id);
            console.log('   trigger_value:', trigger_value);

            // CRITICAL: Only proceed if the click count is > 0
            // This prevents firing when buttons are initialized with null/0 on page load
            if (!trigger_value || trigger_value === 0) {
                console.log('   ❌ Invalid click count, preventing update');
                throw window.dash_clientside.PreventUpdate;
            }

            if (trigger_id === 'enter-edit-mode-button') {
                console.log('   ✅ ENTER EDIT MODE button clicked');
                // Enter edit mode: /dashboard/{id} -> /dashboard-edit/{id}
                if (current_pathname && current_pathname.startsWith('/dashboard/')) {
                    // Extract dashboard ID and navigate to editor app
                    const dashboardId = current_pathname.split('/')[2];
                    const target_url = '/dashboard-edit/' + dashboardId;
                    console.log('   🎨 Navigating to editor app (hard reload): ' + target_url);
                    console.log('   🚀 Calling window.location.href = ' + target_url);
                    window.location.href = target_url;
                    return;
                } else {
                    console.log('   ❌ Invalid pathname for edit mode:', current_pathname);
                }
            } else if (trigger_id === 'exit-edit-mode-button') {
                console.log('   ✅ EXIT EDIT MODE button clicked');
                // Exit edit mode: /dashboard-edit/{id} -> /dashboard/{id}
                if (current_pathname && current_pathname.startsWith('/dashboard-edit/')) {
                    // Extract dashboard ID and navigate to viewer app
                    const dashboardId = current_pathname.split('/')[2];
                    const target_url = '/dashboard/' + dashboardId;
                    console.log('   👁️ Navigating to viewer app (hard reload): ' + target_url);
                    console.log('   🚀 Calling window.location.href = ' + target_url);
                    window.location.href = target_url;
                    return;
                } else {
                    console.log('   ⚠️ Not in editor app, no action needed');
                }
            } else {
                console.log('   ❌ Unknown trigger:', trigger_id);
            }

            console.log('   Preventing update at end of callback');
            console.log('═══════════════════════════════════════════════');
            throw window.dash_clientside.PreventUpdate;
        }
        """,
        Output("edit-mode-navigation-dummy", "data"),
        Input("enter-edit-mode-button", "n_clicks"),
        Input("exit-edit-mode-button", "n_clicks"),
        State("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )

    # UNSAVED CHANGES TRACKER: Listen to layout change trigger from JavaScript
    # JavaScript drag event listener triggers the hidden button
    app.clientside_callback(
        """
        function(layoutChangeTrigger) {
            console.log('⚠️ LAYOUT TRACKER: Layout change detected via trigger');
            return false;  // Mark as unsaved
        }
        """,
        Output("layout-saved-state", "data"),
        Input("layout-change-trigger", "n_clicks"),
        prevent_initial_call=True,
    )

    # SAVE BUTTON TRACKER: Mark as saved when save button clicked
    app.clientside_callback(
        """
        function(saveClicks) {
            console.log('✅ LAYOUT TRACKER: Save clicked, marking as saved');
            return true;  // Mark as saved
        }
        """,
        Output("layout-saved-state", "data", allow_duplicate=True),
        Input("save-button-dashboard", "n_clicks"),
        prevent_initial_call=True,
    )

    # SAVE BUTTON VISUAL INDICATOR: Update button color based on saved state
    # Adds pulsing animation class when unsaved
    app.clientside_callback(
        """
        function(isSaved) {
            console.log('🎨 SAVE BUTTON UPDATE: isSaved=', isSaved);

            if (isSaved === false) {
                // Unsaved changes - orange color with pulsing animation
                console.log('⚠️ Showing UNSAVED indicator (orange + pulse)');
                return ['orange', 'save-button-unsaved'];  // Array for multiple outputs
            } else {
                // Saved - normal teal color
                console.log('✅ Showing SAVED state (teal)');
                return ['teal', ''];  // Array for multiple outputs
            }
        }
        """,
        Output("save-button-dashboard", "color"),
        Output("save-button-dashboard", "className"),
        Input("layout-saved-state", "data"),
    )


# =============================================================================
# MAIN LAYOUT FUNCTION
# =============================================================================


def design_header(data, local_store, edit_mode: bool = False):
    """
    Design the main dashboard header with modular components.

    Args:
        data: Dashboard data
        local_store: Local storage with access token
        edit_mode: If True, show full edit controls. If False, show simplified view-mode header.
    """
    # Ensure data structure exists
    if data:
        if "stored_add_button" not in data:
            data["stored_add_button"] = {"count": 0}
        if "stored_edit_dashboard_mode_button" not in data:
            data["stored_edit_dashboard_mode_button"] = [int(0)]
        if "buttons_data" not in data:
            data["buttons_data"] = {"unified_edit_mode": True}  # Default edit mode ON for owners

    # Get user and permissions
    current_user = api_call_fetch_user_from_token(local_store["access_token"])
    owner, viewer = _get_user_permissions(current_user, data)

    # Determine button states based on ownership
    # Edit mode controls (add/edit/save/share) are only available to owners
    # They are conditionally rendered based on edit_mode parameter (URL-based)
    if not owner:
        # Non-owners: disable all edit controls (but they won't be rendered in view mode anyway)
        disabled = True
    else:
        # Owners: enable controls (will be rendered based on edit_mode)
        disabled = False

    # Get project name
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
        params={"project_id": data["project_id"]},
        headers={"Authorization": f"Bearer {local_store['access_token']}"},
        timeout=settings.performance.api_request_timeout,
    )
    if response.status_code != 200:
        raise Exception("Failed to fetch project data.")
    project_name = response.json()["name"]

    # Initialize click counts
    init_nclicks_add_button = (
        data["stored_add_button"] if data else {"count": 0, "initialized": False, "_id": ""}
    )
    init_nclicks_edit_dashboard_mode_button = (
        data["stored_edit_dashboard_mode_button"] if data else [int(0)]
    )

    # SIMPLIFIED HEADER: Consistent button styling
    # All buttons use dmc.Button for consistent UX
    # Removed: add_new_component_button, save_button, apply_filters_button

    # Reset filters button - simplified text
    # IMPORTANT: ID must be "reset-all-filters-button" to match callbacks
    reset_filters_button = dmc.Button(
        "Reset",
        id="reset-all-filters-button",
        leftSection=DashIconify(icon="bx:reset", width=16, color="white"),
        size="sm",
        color="orange",
        variant="filled",
        n_clicks=0,  # Required for callback
    )

    # Settings button - always visible to access dashboard info and settings
    open_offcanvas_parameters_button = dmc.Button(
        "Settings",
        id="open-offcanvas-parameters-button",
        leftSection=DashIconify(icon="ic:baseline-settings", width=16, color="white"),
        size="sm",
        color="gray",
        variant="filled",
    )

    # REMOVED: edit_mode_button_header (replaced by dedicated Edit Dashboard / Exit Edit Mode buttons)
    # The old edit-status-badge-clickable-2 button was used to toggle edit mode via unified-edit-mode-button
    # Now we use URL-based edit mode with explicit navigation buttons

    # Create "Edit" button for view mode (navigates to /edit URL)
    # Uses blue color matching edit ActionIcon in components
    edit_dashboard_button = dmc.Button(
        "Edit",
        id="enter-edit-mode-button",
        leftSection=DashIconify(icon="mdi:pencil", width=16, color="white"),
        size="sm",
        color="blue",
        variant="filled",
        disabled=disabled,  # Disable for non-owners
        style={"display": "none" if edit_mode else "block"},  # Only show in view mode
        n_clicks=0,  # Required for clientside callback
    )

    # Create "Exit" button for edit mode (navigates back to view URL)
    exit_edit_button = dmc.Button(
        "Exit Edit",
        id="exit-edit-mode-button",
        leftSection=DashIconify(icon="mdi:eye", width=16, color="white"),
        size="sm",
        color="gray",
        variant="filled",
        style={"display": "block" if edit_mode else "none"},  # Only show in edit mode
        n_clicks=0,  # Required for clientside callback
    )

    # Create "Add Component" button for edit mode
    add_component_button = dmc.Button(
        "Add",
        id="add-button",  # Must match callback in add_component_simple.py
        leftSection=DashIconify(icon="mdi:plus-circle", width=16, color="white"),
        size="sm",
        color="green",
        variant="filled",
        disabled=disabled,  # Disable for non-owners
        style={"display": "block" if edit_mode else "none"},  # Only show in edit mode
        # n_clicks not set - Dash preserves count across re-renders
    )

    # Create "Save Dashboard" button for edit mode
    save_dashboard_button = dmc.Button(
        "Save",
        id="save-button-dashboard",  # Must match callback in save.py
        leftSection=DashIconify(icon="mdi:content-save", width=16, color="white"),
        size="sm",
        color="teal",
        variant="filled",
        disabled=disabled,  # Disable for non-owners
        style={"display": "block" if edit_mode else "none"},  # Only show in edit mode
        n_clicks=0,  # Required for callback to trigger properly
    )

    # Create remove all components button for offcanvas
    remove_all_components_button = dmc.Button(
        "Remove all components",
        id="remove-all-components-button",
        leftSection=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
        size="md",
        radius="xl",
        variant="gradient",
        gradient={"from": "red", "to": "pink", "deg": 105},
        disabled=disabled,
        fullWidth=True,
    )

    # NEW: Dashboard Info Section for drawer
    dashboard_info_group = dmc.Stack(
        [
            dmc.Title("Dashboard Info", order=4),
            dmc.Stack(
                [
                    dmc.Badge(
                        f"Project: {project_name}",
                        size="lg",
                        color=colors["teal"],
                        leftSection=DashIconify(icon="mdi:jira", width=16, color="white"),
                        style={"width": "100%", "justifyContent": "flex-start"},
                    ),
                    dmc.Badge(
                        f"Owner: {data['permissions']['owners'][0]['email']}",
                        size="lg",
                        color=colors["blue"],
                        leftSection=DashIconify(icon="mdi:account", width=16, color="white"),
                        style={"width": "100%", "justifyContent": "flex-start"},
                    ),
                    dmc.Badge(
                        _format_last_saved(data["last_saved_ts"]),
                        size="lg",
                        color=colors["purple"],
                        leftSection=DashIconify(
                            icon="mdi:clock-time-four-outline", width=16, color="white"
                        ),
                        style={"width": "100%", "justifyContent": "flex-start"},
                    ),
                ],
                gap="sm",
            ),
            dmc.Divider(),
            # Status badges section
            # dmc.Group(
            #     [
            #         dmc.Text("Edit Mode:", fw="bold", size="sm"),
            #         dmc.Badge(
            #             "Edit OFF",
            #             id="edit-status-badge-drawer",
            #             size="sm",
            #             color="gray",
            #             leftSection=DashIconify(icon="mdi:pencil-off", width=8, color="white"),
            #         ),
            #     ],
            #     justify="space-between",
            #     style={"width": "100%"},
            # ),
            dmc.Group(
                [
                    dmc.Text("Live Interactivity:", fw="bold", size="sm"),
                    dmc.Badge(
                        "Live OFF",
                        id="live-interactivity-badge-drawer",
                        size="sm",
                        color="gray",
                        leftSection=DashIconify(
                            icon="mdi:lightning-bolt-outline", width=8, color="white"
                        ),
                    ),
                ],
                justify="space-between",
                style={"width": "100%", "display": "none"},  # Hidden for now
            ),
        ],
        gap="md",
    )

    # DMC Stack instead of html.Div for better theme support
    toggle_switches_group = dmc.Stack(
        [
            dmc.Title("Switches", order=4),
            dmc.Group(
                dmc.Select(
                    id="dashboard-version",
                    data=[f"{data['version']}"],
                    value=f"{data['version']}",
                    label="Dashboard version",
                    style={"width": 150, "padding": "0 10px", "display": "none"},
                    leftSection=DashIconify(
                        icon="mdi:format-list-bulleted-square",
                        width=16,
                        color="blue.5",
                    ),
                    # rightSection=DashIconify(icon="radix-icons:chevron-down"),
                )
            ),
            # REMOVED: unified-edit-mode-button toggle (replaced by URL-based edit mode)
            # Edit mode is now controlled by URL: /dashboard/{id} vs /dashboard/{id}/edit
            # Use "Edit Dashboard" / "Exit Edit Mode" buttons in header instead
            dmc.Group(
                [
                    dmc.Switch(
                        id="toggle-interactivity-button",
                        checked=True,
                        color="gray",
                    ),
                    dmc.Text("Toggle interactivity", style={"fontFamily": "default"}),
                ],
                align="center",
                gap="sm",
                style={"padding": "5px", "margin": "5px 0"},
            ),
            dmc.Group(
                [
                    dmc.Switch(
                        id="live-interactivity-toggle",
                        checked=False,  # Default off
                        color="blue",
                    ),
                    dmc.Text("Live interactivity", style={"fontFamily": "default"}),
                ],
                align="center",
                gap="sm",
                style={"padding": "5px", "margin": "5px 0"},
            ),
        ],
        gap="xs",
    )

    # DMC Stack for action buttons (only shown in edit mode)
    # In view mode, these buttons should not be accessible
    buttons_group = dmc.Stack(
        [
            dmc.Title("Actions", order=4),
            dmc.Group(
                [remove_all_components_button],
                align="center",
                gap="sm",
                style={"padding": "5px", "margin": "5px 0"},
            ),
            # REMOVED: Share button (feature not implemented)
            # Previously had share-button ActionIcon with modal - removed to reduce callback graph size
        ],
        gap="md",
        style={"display": "block" if edit_mode else "none"},  # Hide in view mode
    )

    # Drawer content - conditionally include buttons_group only in edit mode
    drawer_children = [dashboard_info_group, toggle_switches_group]
    if edit_mode:
        drawer_children.append(buttons_group)

    offcanvas_parameters = dmc.Drawer(
        id="offcanvas-parameters",
        title="Dashboard Settings",
        position="right",
        opened=False,
        closeOnClickOutside=True,
        closeOnEscape=True,
        children=dmc.Stack(drawer_children, gap="lg"),
        size="400px",
    )

    # notes_button and open_offcanvas_parameters_button are now created above with tooltips

    # These dummy outputs are created in _create_backend_components
    # dummy_output = html.Div(id="dummy-output", style={"display": "none"})
    # dummy_output2 = html.Div(id="dummy-output2", style={"display": "none"})
    # stepper_output = html.Div(id="stepper-output", style={"display": "none"})

    # Store the number of clicks for the add button and edit dashboard mode button
    stores_add_edit = [
        dcc.Store(
            id="stored-add-button",
            # storage_type="memory",
            storage_type="local",
            data=init_nclicks_add_button,
        ),
        dcc.Store(
            id="initialized-add-button",
            storage_type="memory",
            data=False,
        ),
        dcc.Store(
            id="stored-edit-dashboard-mode-button",
            # storage_type="memory",
            storage_type="session",
            data=init_nclicks_edit_dashboard_mode_button,
        ),
    ]

    # DMC Burger for navbar toggle (replaces custom sidebar button)
    burger_button = dmc.Burger(
        id="burger-button",
        opened=False,  # Consistent initial state, managed by sidebar-collapsed store
        size="md",
        color="gray",
        style={"marginRight": "10px"},
    )

    # DMC 2.0+ - Use Group instead of Grid for better flex control
    header_content = dmc.Group(
        [
            # Left section - burger button + dashboard icon + title + subtitle
            dmc.Group(
                [
                    burger_button,  # DMC Burger instead of custom button
                    # Dashboard icon from DashboardData model with filled variant
                    # Check if icon is an image path or Iconify icon
                    (
                        html.Img(
                            src=data.get("icon", "mdi:view-dashboard"),
                            style={
                                "width": "32px",
                                "height": "32px",
                                "objectFit": "contain",
                                "borderRadius": "50%",
                                "padding": "4px",
                            },
                        )
                        if data.get("icon", "").startswith("/assets/")
                        else dmc.ActionIcon(
                            DashIconify(
                                icon=data.get("icon", "mdi:view-dashboard"),
                                width=24,
                                height=24,
                            ),
                            color=data.get("icon_color", "orange"),
                            radius="xl",
                            size="lg",
                            variant="filled",
                        )
                    ),
                    # Title only (subtitle removed for simplified header)
                    dmc.Title(
                        f"{data['title']}",
                        order=3,
                        id="dashboard-title",
                        fw="bold",
                        fz=20,
                        m=0,
                        style={"lineHeight": "1.2"},
                    ),
                ],
                gap="sm",
                align="center",
                style={"minWidth": "fit-content", "flexShrink": 0},  # Prevent shrinking
            ),
            # Center section - spacer for layout balance
            dmc.Box(
                style={
                    "flex": "1",
                    "minWidth": 0,
                },
            ),
            # Right section - "Powered by" + action buttons (compact spacing)
            # CONDITIONAL RENDERING: In view mode, only show essential buttons
            # In edit mode, show all buttons including add, save, edit controls
            dmc.Group(
                [
                    # Powered by Depictio section (always shown) - clickable link to docs
                    html.A(
                        dmc.Group(
                            [
                                dmc.Text(
                                    "Powered by",
                                    size="xs",
                                    c="gray",
                                    fw="bold",
                                    style={"opacity": "0.7"},
                                ),
                                dmc.Image(
                                    id="header-powered-by-logo",
                                    src=dash.get_asset_url("images/logos/logo_black.svg"),
                                    h=20,
                                    w="auto",
                                ),
                            ],
                            gap=5,
                            align="center",
                            style={
                                "marginRight": "15px",
                                "borderRight": "1px solid var(--app-border-color, #ddd)",
                                "paddingRight": "15px",
                            },
                        ),
                        href="https://depictio.github.io/depictio-docs/",
                        target="_blank",
                        rel="noopener noreferrer",
                        style={
                            "textDecoration": "none",
                            "cursor": "pointer",
                            "transition": "opacity 0.2s",
                        },
                        className="hover-link",
                    ),
                ]
                + [
                    # EDIT MODE TOGGLE BUTTONS: Both always in layout, visibility controlled by display style
                    exit_edit_button,  # Only visible when edit_mode=True (controlled by style display)
                    edit_dashboard_button,  # Only visible when edit_mode=False (controlled by style display)
                ]
                + [
                    # EDIT MODE ACTIONS: Only visible in edit mode
                    add_component_button,  # Add new component (only visible in edit mode)
                    save_dashboard_button,  # Save dashboard (only visible in edit mode)
                ]
                + [
                    # COMMON CONTROLS: Always shown (settings at the end)
                    reset_filters_button,  # Reset all filters
                    open_offcanvas_parameters_button,  # Settings/dashboard info drawer (rightmost)
                ],
                gap=8,  # Comfortable gap between buttons for better UX
                style={"minWidth": "fit-content", "flexShrink": 0},
            ),
        ],
        justify="space-between",
        align="center",
        style={
            "height": "100%",
            "padding": "0 20px",
            "width": "100%",
            "flexWrap": "nowrap",  # Prevent wrapping
            "minWidth": 0,  # Allow flex items to shrink
        },
    )

    # Store components for button states
    stores_add_edit = [
        dcc.Store(
            id="stored-add-button",
            storage_type="local",
            data=init_nclicks_add_button,
        ),
        dcc.Store(
            id="initialized-add-button",
            storage_type="memory",
            data=False,
        ),
        dcc.Store(
            id="stored-edit-dashboard-mode-button",
            storage_type="session",
            data=init_nclicks_edit_dashboard_mode_button,
        ),
        # PERFORMANCE: Cache dashboard permissions to avoid redundant API calls in toggle_buttons
        # This cache is populated during layout creation and eliminates a 2147ms dashboard fetch
        dcc.Store(
            id="dashboard-permissions-cache",
            storage_type="session",
            data={
                "dashboard_id": str(data.get("dashboard_id"))
                if data and data.get("dashboard_id")
                else None,
                "owner": owner,
                "viewer": viewer,
            },
        ),
    ]

    # Backend components
    backend_components = _create_backend_components()

    # Extended backend components that need to be in the layout (DMC Stack)
    backend_components_extended = dmc.Stack(
        [
            backend_components,
            offcanvas_parameters,
            dmc.Stack(children=stores_add_edit, gap=0),  # DMC Stack for stores list
        ],
        gap=0,  # No gap needed for backend components
    )

    # Return header content (tabs are now in sidebar, not header)
    return header_content, backend_components_extended
