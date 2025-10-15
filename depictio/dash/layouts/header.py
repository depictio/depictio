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
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_call_get_dashboard
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


def _create_action_icon(icon, button_id, disabled=False, n_clicks=0, tooltip=None, **kwargs):
    """Create a standardized action icon button with optional tooltip."""
    button = dmc.ActionIcon(
        DashIconify(icon=icon, width=28, color="gray"),
        id=button_id,
        size="md",  # Medium button size
        radius="xl",
        variant="subtle",
        color="gray",
        style=BUTTON_STYLE,
        disabled=disabled,
        n_clicks=n_clicks,
        **kwargs,
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
    backend_stores = dmc.Stack(
        [
            dcc.Store(id="stored-draggable-children", storage_type="session", data={}),
            dcc.Store(id="stored-edit-component", data=None, storage_type="memory"),
            dcc.Store(id="stored-draggable-layouts", storage_type="session", data={}),
            dcc.Store(id="interactive-values-store", storage_type="session", data={}),
            dcc.Store(id="pending-changes-store", storage_type="memory", data={}),
            dcc.Store(id="live-interactivity-store", storage_type="session", data=True),
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
            # dcc.Store(id="button-style-tracker", data={}),
            # dcc.Store(id="progress-monitor", data={}),
        ]
    )


# =============================================================================
# CALLBACKS
# =============================================================================


def register_callbacks_header(app):
    @app.callback(
        Output("add-button", "disabled"),
        Output("save-button-dashboard", "disabled"),
        Output("remove-all-components-button", "disabled"),
        Output("toggle-interactivity-button", "disabled"),
        Output("dashboard-version", "disabled"),
        Output("share-button", "disabled"),
        Output("toggle-notes-button", "disabled"),
        Output("draggable", "showRemoveButton"),
        Output("draggable", "showResizeHandles"),
        Input("unified-edit-mode-button", "checked"),
        State("local-store", "data"),
        State("url", "pathname"),
        State("user-cache-store", "data"),
    )
    def toggle_buttons(switch_state, local_store, pathname, user_cache):
        """Handle button states based on edit mode and user permissions."""
        len_output = 9

        # Use consolidated user cache
        from depictio.models.models.users import UserContext

        current_user = UserContext.from_cache(user_cache)
        if not current_user:
            current_user = api_call_fetch_user_from_token(local_store["access_token"])

        if not local_store["access_token"]:
            return [True] * len_output

        dashboard_id = pathname.split("/")[-1]
        data = api_call_get_dashboard(dashboard_id, local_store["access_token"])
        if not data:
            return [True] * len_output

        # Get user permissions
        owner, viewer = _get_user_permissions(current_user, data)

        logger.debug(f"owner: {owner}, viewer: {viewer}, switch_state: {switch_state}")

        # If not owner, disable all editing controls
        if not owner:
            return [True] * (len_output - 2) + [False] * 2

        return [not switch_state] * (len_output - 2) + [switch_state] * 2

    @app.callback(
        Output("share-modal-dashboard", "is_open"),
        [
            Input("share-button", "n_clicks"),
            Input("share-modal-close", "n_clicks"),
        ],
        [State("share-modal-dashboard", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_share_modal_dashboard(n_share, n_close, is_open):
        ctx = dash.callback_context

        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        # logger.info(trigger_id, n_save, n_close)

        if trigger_id == "share-button":
            if n_share is None or n_share == 0:
                raise dash.exceptions.PreventUpdate
            else:
                return True

        elif trigger_id == "share-modal-close":
            if n_close is None or n_close == 0:
                raise dash.exceptions.PreventUpdate
            else:
                return False

        return is_open

    @app.callback(
        Output("offcanvas-parameters", "opened"),
        Output("notes-footer-content", "className", allow_duplicate=True),
        Output("page-content", "className", allow_duplicate=True),
        Input("open-offcanvas-parameters-button", "n_clicks"),
        State("offcanvas-parameters", "opened"),
        State("notes-footer-content", "className"),
        State("page-content", "className"),
        prevent_initial_call=True,
    )
    def toggle_offcanvas_parameters(n_clicks, is_open, current_footer_class, current_page_class):
        logger.info(f"toggle_offcanvas_parameters: {n_clicks}, {is_open}")
        if n_clicks:
            new_drawer_state = not is_open

            # If we're opening the drawer, close the notes footer
            current_footer_class = current_footer_class or ""
            current_page_class = current_page_class or ""

            if new_drawer_state and (
                "footer-visible" in current_footer_class
                or "footer-fullscreen" in current_footer_class
            ):
                # Opening drawer and footer is visible - close footer
                new_footer_class = ""
                new_page_class = current_page_class.replace("notes-fullscreen", "").strip()
                logger.info(
                    f"Closing notes footer when opening offcanvas drawer. Footer: '{new_footer_class}', Page: '{new_page_class}'"
                )
                return new_drawer_state, new_footer_class, new_page_class
            else:
                # Either closing drawer or footer already hidden - no footer change needed
                return new_drawer_state, current_footer_class, current_page_class

        return is_open, current_footer_class, current_page_class

    # Sync drawer edit status badge with edit mode toggle
    @app.callback(
        [
            Output("edit-status-badge-drawer", "children"),
            Output("edit-status-badge-drawer", "color"),
            Output("edit-status-badge-drawer", "leftSection"),
        ],
        Input("unified-edit-mode-button", "checked"),
        prevent_initial_call=False,
    )
    def update_edit_status_badge_drawer(edit_mode_checked):
        """Update the drawer edit status badge based on edit mode state."""
        if edit_mode_checked:
            return ("Edit ON", "blue", DashIconify(icon="mdi:pencil", width=8, color="white"))
        else:
            return ("Edit OFF", "gray", DashIconify(icon="mdi:pencil-off", width=8, color="white"))

    # Sync header edit button with edit mode toggle
    @app.callback(
        [
            Output("edit-status-badge-clickable-2", "children"),
            Output("edit-status-badge-clickable-2", "color"),
            Output("edit-status-badge-clickable-2", "variant"),
        ],
        Input("unified-edit-mode-button", "checked"),
        prevent_initial_call=False,
    )
    def update_edit_button_header(edit_mode_checked):
        """Update the header edit button based on edit mode state."""
        if edit_mode_checked:
            # Edit ON: blue filled button with white icon
            return (
                DashIconify(icon="mdi:pencil", width=28, color="white"),
                "blue",
                "filled",
            )
        else:
            # Edit OFF: gray subtle button with gray icon
            return (
                DashIconify(icon="mdi:pencil-off", width=28, color="gray"),
                "gray",
                "subtle",
            )

    # Make edit status badge clickable to toggle edit mode
    @app.callback(
        Output("unified-edit-mode-button", "checked", allow_duplicate=True),
        Input("edit-status-badge-clickable-2", "n_clicks"),
        State("unified-edit-mode-button", "checked"),
        prevent_initial_call=True,
    )
    def toggle_edit_mode_from_badge(n_clicks, current_state):
        """Toggle edit mode when clicking on edit status badge."""
        if n_clicks:
            return not current_state
        return dash.no_update

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

    @app.callback(
        [
            Output("reset-all-filters-button", "color"),
            Output("reset-all-filters-button", "variant"),
            Output("reset-all-filters-button", "children"),
        ],
        Input("interactive-values-store", "data"),
        prevent_initial_call=False,
    )
    def update_reset_button_style(interactive_values):
        """Update reset button style and icon color based on filter activity."""
        # Use INFO level logging so it's visible by default
        # logger.debug(f"🔍 Reset button style check - interactive_values: {interactive_values}")

        has_active_filters = _check_filter_activity(interactive_values)

        logger.info(f"🎯 Filter activity detected: {has_active_filters}")

        if has_active_filters:
            # Orange filled variant with white icon when filters are active
            logger.info("🟠 Setting reset button to orange with white icon (filters active)")
            icon = DashIconify(icon="bx:reset", width=28, color="white")
            return colors["orange"], "filled", icon
        else:
            # Gray subtle variant with gray icon when no filters
            logger.info("⚪ Setting reset button to gray with gray icon (no filters)")
            icon = DashIconify(icon="bx:reset", width=28, color="gray")
            return "gray", "subtle", icon

    # @app.callback(
    #     [
    #         Output("apply-filters-button", "color"),
    #         Output("apply-filters-button", "variant"),
    #         Output("apply-filters-button", "children"),
    #         Output("apply-filters-button", "disabled"),
    #     ],
    #     [
    #         Input("pending-changes-store", "data"),
    #         Input("live-interactivity-toggle", "checked"),
    #     ],
    #     prevent_initial_call=False,
    # )
    # def update_apply_button_style(pending_changes, live_interactivity_on):
    #     """Update apply button style and state based on pending changes and live interactivity mode."""
    #     logger.info(f"🔍 Apply button style check - pending_changes: {pending_changes}")
    #     logger.info(f"🔍 Live interactivity mode: {live_interactivity_on}")
    #     # If live interactivity is ON, hide/disable the apply button
    #     if live_interactivity_on:
    #         icon = DashIconify(icon="material-symbols:check", width=35, color="gray")
    #         return "gray", "subtle", icon, True

    #     # If live interactivity is OFF, check for pending changes
    #     # Compare current values with default states to detect real changes
    #     def has_meaningful_pending_changes(changes):
    #         if not changes or not isinstance(changes, dict):
    #             return False

    #         for key, value in changes.items():
    #             if key == "interactive_components_values" and value:
    #                 # Check if there are actual component values that differ from defaults
    #                 if isinstance(value, list) and len(value) > 0:
    #                     for component in value:
    #                         if isinstance(component, dict):
    #                             current_value = component.get("value")
    #                             metadata = component.get("metadata", {})
    #                             default_state = metadata.get("default_state", {})

    #                             # Use the same logic as _is_different_from_default
    #                             if _is_different_from_default(current_value, default_state):
    #                                 logger.info(
    #                                     f"🔍 Found pending change: current={current_value}, default_state={default_state}"
    #                                 )
    #                                 return True
    #             elif value:  # Other non-empty values
    #                 return True
    #         return False

    #     has_pending_changes = has_meaningful_pending_changes(pending_changes)

    #     logger.info(f"📝 Pending changes detected: {has_pending_changes}")

    #     if has_pending_changes:
    #         # Green filled variant with white icon when pending changes exist (matching Live ON badge)
    #         logger.info("🟢 Setting apply button to green with white icon (pending changes)")
    #         icon = DashIconify(icon="material-symbols:check", width=35, color="white")
    #         return "green", "filled", icon, False
    #     else:
    #         # Gray subtle variant with gray icon when no pending changes
    #         logger.info("⚪ Setting apply button to gray with gray icon (no pending changes)")
    #         icon = DashIconify(icon="material-symbols:check", width=35, color="gray")
    #         return "gray", "subtle", icon, True

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

    # Apply pending filter changes when Apply button is clicked and clear pending changes atomically
    # @app.callback(
    #     [
    #         Output("interactive-values-store", "data", allow_duplicate=True),
    #         Output("pending-changes-store", "data", allow_duplicate=True),
    #     ],
    #     Input("apply-filters-button", "n_clicks"),
    #     [
    #         State("pending-changes-store", "data"),
    #         State("interactive-values-store", "data"),
    #     ],
    #     prevent_initial_call=True,
    # )
    # def apply_and_clear_pending_changes(n_clicks, pending_changes, current_interactive_values):
    #     """Apply pending filter changes and clear pending changes atomically in a single callback."""
    #     if not n_clicks or not pending_changes:
    #         return dash.no_update, dash.no_update

    #     logger.info("🔄 Applying pending filter changes and clearing pending store")
    #     logger.info(f"🔄 Pending changes keys: {list(pending_changes.keys())}")

    #     # Start with current interactive values
    #     updated_values = current_interactive_values.copy() if current_interactive_values else {}

    #     # Merge at component level to preserve all components
    #     if "interactive_components_values" in pending_changes:
    #         if "interactive_components_values" not in updated_values:
    #             updated_values["interactive_components_values"] = []

    #         # Create dict for quick lookup of current components by index
    #         existing_components = {
    #             comp.get("index"): comp for comp in updated_values["interactive_components_values"]
    #         }

    #         # Apply pending changes to components
    #         pending_components = pending_changes["interactive_components_values"]
    #         logger.info(f"🔄 Applying {len(pending_components)} pending component changes")

    #         for pending_component in pending_components:
    #             component_index = pending_component.get("index")
    #             if component_index:
    #                 # Debug: Log before and after values
    #                 old_value = existing_components.get(component_index, {}).get(
    #                     "value", "NOT_FOUND"
    #                 )
    #                 new_value = pending_component.get("value")
    #                 logger.info(
    #                     f"🔄 Updating component {component_index}: {old_value} -> {new_value}"
    #                 )

    #                 existing_components[component_index] = pending_component
    #                 logger.info(
    #                     f"🔄 Applied pending change: {component_index} = {pending_component.get('value')}"
    #                 )

    #         # Convert back to list
    #         updated_values["interactive_components_values"] = list(existing_components.values())

    #     logger.info(
    #         f"✅ Applied pending filter changes - {len(updated_values.get('interactive_components_values', []))} components updated"
    #     )
    #     logger.info("🧹 Clearing pending changes after successful apply")

    #     # Return both updated interactive values and empty pending changes
    #     return updated_values, {}

    # =============================================================================
    # BURGER BUTTON CALLBACKS (DMC Burger for navbar toggle)
    # =============================================================================

    # Sync burger opened state with sidebar-collapsed store (inverted)
    # Burger opened=True means navbar visible, sidebar-collapsed=False
    @app.callback(
        Output("burger-button", "opened", allow_duplicate=True),
        Input("sidebar-collapsed", "data"),
        prevent_initial_call=True,
    )
    def sync_burger_from_store(is_collapsed):
        """Sync burger button state from sidebar-collapsed store (inverted)."""
        # Burger opened = NOT collapsed
        return not is_collapsed if is_collapsed is not None else True

    # Update sidebar-collapsed store when burger is clicked
    @app.callback(
        Output("sidebar-collapsed", "data", allow_duplicate=True),
        Input("burger-button", "opened"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def update_collapsed_from_burger(burger_opened, pathname):
        """Update sidebar-collapsed store when burger is clicked (only on dashboard pages)."""
        # Only update on dashboard pages
        if not pathname or not pathname.startswith("/dashboard/"):
            logger.info(f"Ignoring burger click on non-dashboard page: {pathname}")
            raise dash.exceptions.PreventUpdate

        # sidebar-collapsed = NOT burger_opened
        is_collapsed = not burger_opened
        logger.info(f"Burger clicked: opened={burger_opened}, setting collapsed={is_collapsed}")
        return is_collapsed


# =============================================================================
# MAIN LAYOUT FUNCTION
# =============================================================================


def design_header(data, local_store):
    """Design the main dashboard header with modular components."""
    # Ensure data structure exists
    if data:
        if "stored_add_button" not in data:
            data["stored_add_button"] = {"count": 0}
        if "stored_edit_dashboard_mode_button" not in data:
            data["stored_edit_dashboard_mode_button"] = [int(0)]
        if "buttons_data" not in data:
            data["buttons_data"] = {"unified_edit_mode": False}  # Default edit mode OFF

    # Get user and permissions
    current_user = api_call_fetch_user_from_token(local_store["access_token"])
    owner, viewer = _get_user_permissions(current_user, data)

    # Determine button states - ALWAYS check permission first
    if not owner:
        # Non-owners: ALWAYS force edit mode OFF and disable controls
        disabled = True
        unified_edit_mode_checked = False
    else:
        # Owners only: enable controls and use stored edit mode
        disabled = False
        # Set default edit mode to OFF (False) and only use stored value if explicitly set
        buttons_data = data.get("buttons_data", {})
        unified_edit_mode_checked = False  # Always default to OFF

        # Only check stored value for owners
        if "unified_edit_mode" in buttons_data:
            unified_edit_mode_checked = buttons_data["unified_edit_mode"]
        elif "edit_dashboard_mode_button" in buttons_data:
            unified_edit_mode_checked = buttons_data["edit_dashboard_mode_button"]
        elif "edit_components_button" in buttons_data:
            unified_edit_mode_checked = buttons_data["edit_components_button"]

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

    # Create action buttons with tooltips
    add_new_component_button = _create_action_icon(
        "material-symbols:add",
        "add-button",
        disabled=disabled,
        n_clicks=init_nclicks_add_button["count"],
        tooltip="Add a new component\nto your dashboard",
    )

    save_button = _create_action_icon(
        "ic:baseline-save",
        "save-button-dashboard",
        disabled=disabled,
        tooltip="Save current dashboard\nconfiguration and layout",
    )

    notes_button = _create_action_icon(
        "material-symbols:edit-note",
        "toggle-notes-button",
        tooltip="Toggle notes footer",
    )

    open_offcanvas_parameters_button = _create_action_icon(
        "ic:baseline-settings",
        "open-offcanvas-parameters-button",
        tooltip="Open dashboard settings\nand configuration panel",
    )

    reset_filters_button = _create_reset_filters_button()
    apply_filters_button = _create_apply_filters_button()

    # Create clickable edit mode button using the same pattern as other action buttons
    edit_mode_button_header = _create_action_icon(
        "mdi:pencil-off",
        "edit-status-badge-clickable-2",
        disabled=disabled,  # Disable for non-owners
        n_clicks=0,
        tooltip="Toggle edit mode\nfor dashboard editing",
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
            dmc.Group(
                [
                    dmc.Switch(
                        id="unified-edit-mode-button",
                        checked=unified_edit_mode_checked,
                        disabled=disabled,
                        color="gray",
                    ),
                    dmc.Text("Edit Mode", style={"fontFamily": "default"}),
                ],
                align="center",
                gap="sm",
                style={"padding": "5px", "margin": "5px 0"},
            ),
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

    # DMC Stack instead of html.Div for better theme support
    buttons_group = dmc.Stack(
        [
            dmc.Title("Buttons", order=4),
            dmc.Group(
                [remove_all_components_button],
                align="center",
                gap="sm",
                style={"padding": "5px", "margin": "5px 0"},
            ),
            dmc.Group(
                [
                    # dmc.Button(
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:share-variant", width=24, color="white"),
                        id="share-button",
                        color="gray",
                        variant="filled",
                        disabled=disabled,
                        n_clicks=0,
                    ),
                    dmc.Text("Share", style={"fontFamily": "default"}),
                ],
                align="center",
                gap="sm",
                style={"padding": "5px", "margin": "5px 0", "display": "none"},
            ),
        ],
        gap="md",
    )

    offcanvas_parameters = dmc.Drawer(
        id="offcanvas-parameters",
        title="Dashboard Settings",
        position="right",
        opened=False,
        closeOnClickOutside=True,
        closeOnEscape=True,
        children=dmc.Stack(
            [dashboard_info_group, toggle_switches_group, buttons_group], gap="lg"
        ),  # Added dashboard_info_group first
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
        # dcc.Store(
        #     id="initialized-edit-button",
        #     storage_type="memory",
        #     data=False,
        # ),
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
                    # Title and optional subtitle
                    dmc.Stack(
                        [
                            dmc.Title(
                                f"{data['title']}",
                                order=3,
                                id="dashboard-title",
                                fw="bold",
                                fz=20,
                                m=0,
                                style={"lineHeight": "1.2"},
                            ),
                            # Subtitle (only shown if provided)
                            dmc.Text(
                                data.get("subtitle", ""),
                                size="xs",
                                c="gray",
                                style={
                                    "lineHeight": "1.2",
                                    "display": "block" if data.get("subtitle") else "none",
                                    "opacity": "0.7",
                                },
                            ),
                        ],
                        gap=2,
                        justify="center",
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
            dmc.Group(
                [
                    # Powered by Depictio section
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
                    # Edit mode button (clickable)
                    edit_mode_button_header,
                    # Action buttons
                    apply_filters_button,
                    add_new_component_button,
                    reset_filters_button,
                    save_button,
                    notes_button,
                    open_offcanvas_parameters_button,
                ],
                gap=3,  # Tighter gap (3px) for compact buttons
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
