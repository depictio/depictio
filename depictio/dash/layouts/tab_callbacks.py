"""
Callbacks for dashboard tab management.

This module provides callbacks for managing dashboard tabs including:

- Populating sidebar tabs based on the current dashboard
- Navigating between tabs via URL changes
- Opening and handling tab creation/edit modal
- Creating new tabs with custom icons and colors
- Editing existing tabs (title, icon, color)
- Deleting child tabs with confirmation
- Reordering tabs via up/down buttons

Key Callbacks:
    populate_sidebar_tabs: Loads and displays tabs for the dashboard family
    navigate_to_tab: Handles tab click navigation
    open_tab_modal: Opens the tab creation modal
    open_edit_tab_modal: Opens the edit modal with pre-filled values
    save_tab: Creates new tab or updates existing tab
    delete_tab: Deletes a child tab after confirmation
    reorder_tabs: Handles tab reordering via up/down buttons
"""

import httpx
from dash import ALL, Input, Output, State
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission


def _extract_dashboard_id_from_pathname(pathname: str | None) -> tuple[str | None, bool]:
    """
    Extract dashboard ID and edit mode flag from URL pathname.

    Args:
        pathname: URL pathname (e.g., '/dashboard/{id}' or '/dashboard-edit/{id}')

    Returns:
        Tuple of (dashboard_id, is_edit_mode) or (None, False) if invalid
    """
    if not pathname:
        return None, False

    try:
        if "/dashboard-edit/" in pathname:
            dashboard_id = pathname.split("/dashboard-edit/")[1].split("/")[0]
            return dashboard_id, True

        dashboard_id = pathname.split("/dashboard/")[1].split("/")[0]
        is_edit_mode = "/edit" in pathname
        return dashboard_id, is_edit_mode
    except (IndexError, AttributeError):
        return None, False


def _fetch_dashboard(dashboard_id: str, token: str) -> dict | None:
    """
    Fetch dashboard data from the API.

    Args:
        dashboard_id: The dashboard ID to fetch
        token: Authentication token

    Returns:
        Dashboard data dict or None if fetch failed
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 200:
            return response.json()
        logger.warning(f"Failed to fetch dashboard {dashboard_id}: {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Error fetching dashboard {dashboard_id}: {e}")
        return None


def _get_parent_dashboard_id(dashboard: dict, current_id: str) -> str:
    """
    Get the parent dashboard ID from dashboard data.

    For main tabs, the current dashboard is the parent.
    For child tabs, use the parent_dashboard_id field.

    Args:
        dashboard: Dashboard data dictionary
        current_id: Current dashboard ID (used if this is a main tab)

    Returns:
        Parent dashboard ID as string
    """
    if dashboard.get("is_main_tab", True):
        return current_id
    return str(dashboard["parent_dashboard_id"])


def _fetch_all_tabs(parent_id: str, token: str) -> list[dict]:
    """
    Fetch all tabs (main + children) for a parent dashboard using the dedicated API endpoint.

    Args:
        parent_id: The parent dashboard ID
        token: Authentication token

    Returns:
        List of all tabs (main tab first, then children sorted by tab_order)
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/tabs/{parent_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            logger.warning(
                f"Failed to fetch tabs for dashboard {parent_id}: {response.status_code}"
            )
            return []

        data = response.json()
        if not data.get("success"):
            logger.warning(f"Tabs API returned failure for dashboard {parent_id}")
            return []

        # Combine main tab with child tabs
        main_tab = data.get("main_tab")
        child_tabs = data.get("child_tabs", [])

        if not main_tab:
            logger.warning(f"No main tab returned for dashboard {parent_id}")
            return []

        # Return all tabs (main tab already has tab_order=0)
        return [main_tab] + child_tabs

    except Exception as e:
        logger.error(f"Error fetching tabs for {parent_id}: {e}")
        return []


def _create_add_tab_button():
    """Create the '+ Add Tab' button for the sidebar."""
    import dash_mantine_components as dmc

    return dmc.TabsTab(
        "Add Tab",
        value="__add_tab__",
        leftSection=DashIconify(icon="mdi:plus", color="grey", width=24),
        style={
            "width": "100%",
            "fontSize": "16px",
            "padding": "16px 16px",
        },
    )


def _build_tab_item(
    tab: dict,
    is_edit_mode: bool = False,
    is_owner: bool = False,
    all_tabs: list | None = None,
    workflow_data: dict | None = None,
    parent_dashboard: dict | None = None,
):
    """
    Build a DMC TabsTab component from tab data.

    Args:
        tab: Tab dictionary containing dashboard data
        is_edit_mode: Whether we're in dashboard edit mode
        is_owner: Whether current user is an owner
        all_tabs: List of all tabs (for reorder button state)
        workflow_data: Optional workflow data for automatic color selection
        parent_dashboard: Parent dashboard data (for main tab to inherit icon/color)

    Returns:
        DMC TabsTab component
    """
    import dash_mantine_components as dmc
    from dash import html

    is_main_tab = tab.get("is_main_tab", True)

    # For main tabs, show main_tab_name if set, otherwise "Main"
    if is_main_tab:
        tab_label = tab.get("main_tab_name") or "Main"
    else:
        tab_label = tab.get("title", "Untitled")

    # Determine icon and color from tab data
    icon_name = tab.get("tab_icon") or tab.get("icon", "mdi:view-dashboard")
    icon_color = tab.get("tab_icon_color") or tab.get("icon_color", "gray")

    tab_dashboard_id = str(tab["dashboard_id"])

    # Build the tab content with optional edit controls
    # Support image paths as icons (PNG/SVG) alongside DashIconify icons
    if icon_name and (icon_name.startswith("/assets/") or icon_name.endswith((".png", ".svg"))):
        icon_element = html.Img(
            src=icon_name,
            style={"width": "22px", "height": "22px", "objectFit": "contain"},
        )
        left_section = dmc.ActionIcon(
            icon_element,
            id={"type": "tab-icon", "index": tab_dashboard_id},
            color=icon_color,
            radius="xl",
            size="md",
            variant="transparent",  # Transparent for image icons
        )
    else:
        left_section = dmc.ActionIcon(
            DashIconify(icon=icon_name, width=20),
            id={"type": "tab-icon", "index": tab_dashboard_id},
            color=icon_color,
            radius="xl",
            size="md",
            variant="filled",
        )

    # In edit mode for owners, add a menu with edit/reorder options
    right_section = None
    if is_edit_mode and is_owner:
        # Determine boundary states for child tabs based on position in sorted list
        child_tabs = [t for t in (all_tabs or []) if not t.get("is_main_tab", True)]
        child_tabs_sorted = sorted(child_tabs, key=lambda t: t.get("tab_order", 0))

        # Find current tab's position among child tabs
        current_tab_position = -1
        for idx, ct in enumerate(child_tabs_sorted):
            if str(ct.get("dashboard_id", "")) == tab_dashboard_id:
                current_tab_position = idx
                break

        # Boundary checks based on actual position
        is_first_child = current_tab_position == 0
        is_last_child = (
            current_tab_position == len(child_tabs_sorted) - 1 if child_tabs_sorted else True
        )

        # Debug logging
        logger.debug(
            f"Tab {tab_label} ({tab_dashboard_id}): is_main={is_main_tab}, "
            f"position={current_tab_position}/{len(child_tabs_sorted)}, "
            f"first={is_first_child}, last={is_last_child}"
        )

        # Build menu items
        menu_items = [
            # Edit option (always available)
            dmc.MenuItem(
                "Edit",
                id={"type": "tab-edit-button", "index": tab_dashboard_id},
                leftSection=DashIconify(icon="mdi:pencil", width=14),
                n_clicks=0,
            ),
        ]

        # Add reorder options for child tabs only
        if not is_main_tab:
            menu_items.extend(
                [
                    dmc.MenuDivider(),
                    dmc.MenuItem(
                        "Move Up",
                        id={"type": "tab-move-up", "index": tab_dashboard_id},
                        leftSection=DashIconify(icon="mdi:arrow-up", width=14),
                        disabled=is_first_child,
                        n_clicks=0,
                    ),
                    dmc.MenuItem(
                        "Move Down",
                        id={"type": "tab-move-down", "index": tab_dashboard_id},
                        leftSection=DashIconify(icon="mdi:arrow-down", width=14),
                        disabled=is_last_child,
                        n_clicks=0,
                    ),
                ]
            )

        # Single menu trigger button
        right_section = dmc.Menu(
            [
                dmc.MenuTarget(
                    dmc.ActionIcon(
                        DashIconify(icon="mdi:dots-vertical", width=16),
                        color="gray",
                        radius="xl",
                        size="xs",
                        variant="subtle",
                    ),
                ),
                dmc.MenuDropdown(menu_items),
            ],
            position="bottom-end",
            withArrow=True,
            shadow="md",
        )

    return dmc.TabsTab(
        dmc.Group(
            [
                html.Span(tab_label, style={"flex": "1"}),
                right_section,
            ]
            if right_section
            else tab_label,
            justify="space-between" if right_section else "flex-start",
            wrap="nowrap",
            style={"width": "100%"},
        ),
        value=tab_dashboard_id,
        leftSection=left_section,
        style={
            "width": "100%",
            "fontSize": "16px",
            "padding": "16px 16px",
        },
    )


def register_tab_callbacks(app):
    """Register all tab-related callbacks with the app instance."""

    @app.callback(
        [
            Output("sidebar-tabs-list", "children"),
            Output("sidebar-tabs", "value"),
            Output("sidebar-collapsed", "data"),
            Output("sidebar-tabs", "color"),
        ],
        [
            Input("url", "pathname"),
            Input("dashboard-init-data", "data"),
        ],
        State("local-store", "data"),
        prevent_initial_call=False,
    )
    def populate_sidebar_tabs(pathname, dashboard_cache, local_data):
        """
        Populate sidebar tabs based on current dashboard.

        Fetches all tabs for the dashboard family and displays them,
        including "+ Add Tab" button in edit mode for owners.

        Also sets sidebar collapsed state based on tab count:
        - 1 tab (main only): collapsed (True)
        - 2+ tabs: expanded (False)

        Updates the tabs selection color to match the dashboard's icon_color.

        Args:
            pathname: Current URL pathname
            dashboard_cache: Cached dashboard data
            local_data: Local storage data containing access token

        Returns:
            tuple: (tab_items list, selected tab value, sidebar_collapsed, tabs_color)
        """

        # Early exits for non-applicable pages
        if pathname and ("/component/edit/" in pathname or "/component/add/" in pathname):
            raise PreventUpdate

        if not pathname or ("/dashboard/" not in pathname and "/dashboard-edit/" not in pathname):
            raise PreventUpdate

        # Extract dashboard ID and edit mode from pathname
        dashboard_id, is_edit_mode = _extract_dashboard_id_from_pathname(pathname)
        if not dashboard_id:
            raise PreventUpdate

        # Validate access token
        if not local_data or "access_token" not in local_data:
            logger.warning("No access token available for tab loading")
            raise PreventUpdate

        token = local_data["access_token"]

        try:
            # Fetch current dashboard to determine parent
            current_dash = _fetch_dashboard(dashboard_id, token)
            if not current_dash:
                raise PreventUpdate

            # Determine parent dashboard ID
            parent_id = _get_parent_dashboard_id(current_dash, dashboard_id)

            # Fetch all tabs (main + children) using dedicated endpoint
            tabs = _fetch_all_tabs(parent_id, token)
            if not tabs:
                logger.warning(f"No tabs found for parent {parent_id}")
                raise PreventUpdate

            # Sort by tab_order (should already be sorted, but ensure consistency)
            tabs.sort(key=lambda t: t.get("tab_order", 0))

            # Determine if user is owner for edit controls
            is_owner = False
            if is_edit_mode and dashboard_cache:
                user_permissions = dashboard_cache.get("user_permissions", {})
                is_owner = user_permissions.get("level") == "owner"

            # Get parent dashboard (main tab) for workflow data and icon inheritance
            parent_dashboard = tabs[0] if tabs else None

            # Try to get workflow data for automatic tab color
            # Check parent dashboard first, then fall back to dashboard_cache
            workflow_data = None
            workflow_system = None

            if parent_dashboard:
                workflow_system = parent_dashboard.get("workflow_system")

            if not workflow_system or workflow_system == "none":
                # Fall back to dashboard_cache
                if dashboard_cache:
                    workflow_system = dashboard_cache.get("workflow_system")

            if workflow_system and workflow_system != "none":
                # Construct workflow-like data for color lookup
                workflow_catalog = None
                if parent_dashboard:
                    workflow_catalog = parent_dashboard.get("workflow_catalog")
                if not workflow_catalog and dashboard_cache:
                    workflow_catalog = dashboard_cache.get("workflow_catalog")

                workflow_data = {
                    "engine": {"name": workflow_system},
                    "catalog": workflow_catalog,
                }

            # Build tab items using helper function with edit controls in edit mode
            tab_items = [
                _build_tab_item(
                    tab,
                    is_edit_mode=is_edit_mode,
                    is_owner=is_owner,
                    all_tabs=tabs,
                    workflow_data=workflow_data,
                    parent_dashboard=parent_dashboard,
                )
                for tab in tabs
            ]

            # Add "+ Add Tab" button in edit mode for owners
            if is_edit_mode and is_owner:
                tab_items.append(_create_add_tab_button())

            # Set sidebar collapsed based on tab count:
            # - 1 tab (main only): collapsed (True) - no need to show sidebar
            # - 2+ tabs: expanded (False) - show tabs for navigation
            sidebar_collapsed = len(tabs) <= 1

            # Set tabs color from the active tab's icon color
            active_tab = next((t for t in tabs if str(t.get("dashboard_id")) == dashboard_id), None)
            if active_tab:
                tabs_color = active_tab.get("tab_icon_color") or active_tab.get(
                    "icon_color", "orange"
                )
            else:
                tabs_color = "orange"

            # Mantine Tabs color prop needs named colors, not hex
            _hex_to_mantine = {
                "#1d855c": "green",
                "#6495ed": "blue",
                "#9966cc": "violet",
                "#45b8ac": "teal",
                "#8bc34a": "lime",
                "#f68b33": "orange",
                "#e6779f": "pink",
                "#f9cb40": "yellow",
                "#e53935": "red",
            }
            if tabs_color:
                tabs_color = _hex_to_mantine.get(tabs_color.lower(), tabs_color)

            return tab_items, dashboard_id, sidebar_collapsed, tabs_color

        except PreventUpdate:
            raise
        except Exception as e:
            logger.error(f"Error populating sidebar tabs: {e}")
            raise PreventUpdate

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input("sidebar-tabs", "value"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def navigate_to_tab(tab_dashboard_id, current_pathname):
        """
        Navigate to selected tab via URL change.

        When a tab is clicked, navigate to that dashboard's URL.
        Preserves viewer/editor app context.

        Args:
            tab_dashboard_id: The dashboard_id of the clicked tab
            current_pathname: Current URL pathname

        Returns:
            str: New pathname to navigate to
        """
        if not tab_dashboard_id or tab_dashboard_id == "__add_tab__":
            raise PreventUpdate

        # CRITICAL FIX: Don't navigate if we're on a component edit/add page
        # This prevents breaking the component editing workflow
        if current_pathname and (
            "/component/edit/" in current_pathname or "/component/add/" in current_pathname
        ):
            raise PreventUpdate

        # Check if in editor app or legacy edit mode
        if "/dashboard-edit/" in current_pathname:
            # Editor app: use /dashboard-edit/ prefix
            new_pathname = f"/dashboard-edit/{tab_dashboard_id}"
        else:
            # Viewer app or legacy mode
            is_edit_mode = "/edit" in current_pathname
            new_pathname = f"/dashboard/{tab_dashboard_id}"
            if is_edit_mode:
                # Legacy edit mode: append /edit suffix
                new_pathname += "/edit"

        return new_pathname

    @app.callback(
        Output("tab-modal", "opened"),
        Input("sidebar-tabs", "value"),
        prevent_initial_call=True,
    )
    def open_tab_modal(tab_value):
        """
        Open modal when '+ Add Tab' is clicked.

        Args:
            tab_value: The value of the clicked tab

        Returns:
            bool: True to open modal, raises PreventUpdate otherwise
        """
        if tab_value == "__add_tab__":
            logger.info("Opening tab creation modal")
            return True
        raise PreventUpdate

    @app.callback(
        [
            Output("tab-modal", "opened", allow_duplicate=True),
            Output("tab-modal-edit-mode", "data"),
            Output("tab-name-input", "value"),
            Output("tab-icon-select", "value"),
            Output("tab-icon-color-picker", "value"),
            Output("main-tab-name-input", "value"),
        ],
        Input({"type": "tab-edit-button", "index": ALL}, "n_clicks"),
        [
            State("url", "pathname"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_edit_tab_modal(n_clicks_list, pathname, local_data):
        """
        Open edit modal with pre-filled values when edit button is clicked.

        Args:
            n_clicks_list: List of n_clicks for all edit buttons
            pathname: Current URL pathname
            local_data: Local storage with access token

        Returns:
            tuple: (modal_opened, edit_mode_data, tab_name, icon, color, main_tab_name)
        """
        from dash import ctx

        if not ctx.triggered_id or not any(n_clicks_list):
            raise PreventUpdate

        # Get the dashboard_id from the triggered button
        triggered_id = ctx.triggered_id
        dashboard_id = triggered_id.get("index")

        if not dashboard_id:
            raise PreventUpdate

        if not local_data or "access_token" not in local_data:
            logger.warning("No access token for edit modal")
            raise PreventUpdate

        token = local_data["access_token"]

        # Fetch the tab data
        tab_data = _fetch_dashboard(dashboard_id, token)
        if not tab_data:
            logger.error(f"Failed to fetch tab data for {dashboard_id}")
            raise PreventUpdate

        is_main_tab = tab_data.get("is_main_tab", True)

        # Build edit mode data
        edit_mode_data = {
            "is_edit": True,
            "is_child_tab": not is_main_tab,
            "dashboard_id": dashboard_id,
            "parent_dashboard_id": str(tab_data.get("parent_dashboard_id", ""))
            if not is_main_tab
            else None,
        }

        # Pre-fill form values
        if is_main_tab:
            tab_name = tab_data.get("title", "")
            main_tab_name = tab_data.get("main_tab_name", "")
        else:
            tab_name = tab_data.get("title", "")
            main_tab_name = ""

        tab_icon = tab_data.get("tab_icon") or tab_data.get("icon", "mdi:view-dashboard")
        tab_icon_color = tab_data.get("tab_icon_color") or tab_data.get("icon_color", "orange")

        logger.info(f"Opening edit modal for tab {dashboard_id}: {tab_name}")

        return True, edit_mode_data, tab_name, tab_icon, tab_icon_color, main_tab_name

    @app.callback(
        Output("tab-delete-confirm-modal", "opened"),
        Input("tab-modal-delete", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_delete_confirm_modal(n_clicks):
        """Open delete confirmation modal when delete button is clicked."""
        if n_clicks:
            return True
        raise PreventUpdate

    @app.callback(
        Output("tab-delete-confirm-modal", "opened", allow_duplicate=True),
        Input("tab-delete-cancel", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_delete_confirm_modal(n_clicks):
        """Close delete confirmation modal on cancel."""
        if n_clicks:
            return False
        raise PreventUpdate

    @app.callback(
        [
            Output("url", "pathname", allow_duplicate=True),
            Output("tab-modal", "opened", allow_duplicate=True),
            Output("tab-delete-confirm-modal", "opened", allow_duplicate=True),
        ],
        Input("tab-delete-confirm", "n_clicks"),
        [
            State("tab-modal-edit-mode", "data"),
            State("url", "pathname"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def delete_tab(n_clicks, edit_mode_data, pathname, local_data):
        """
        Delete a child tab after confirmation.

        Args:
            n_clicks: Delete confirm button clicks
            edit_mode_data: Edit mode state with dashboard_id
            pathname: Current URL pathname
            local_data: Local storage with access token

        Returns:
            tuple: (new_pathname, tab_modal_closed, confirm_modal_closed)
        """
        if not n_clicks:
            raise PreventUpdate

        if not edit_mode_data or not edit_mode_data.get("is_edit"):
            raise PreventUpdate

        if not local_data or "access_token" not in local_data:
            logger.error("No access token for delete")
            raise PreventUpdate

        token = local_data["access_token"]
        dashboard_id = edit_mode_data.get("dashboard_id")
        parent_dashboard_id = edit_mode_data.get("parent_dashboard_id")

        if not dashboard_id:
            raise PreventUpdate

        logger.info(f"🗑️ Deleting tab {dashboard_id}")

        response = httpx.delete(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/tab/{dashboard_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code != 200:
            logger.error(f"Failed to delete tab: {response.text}")
            raise PreventUpdate

        logger.info(f"✅ Tab {dashboard_id} deleted successfully")

        # Navigate to parent dashboard
        if parent_dashboard_id:
            if "/dashboard-edit/" in pathname:
                new_pathname = f"/dashboard-edit/{parent_dashboard_id}"
            else:
                is_edit_mode = "/edit" in pathname
                new_pathname = f"/dashboard/{parent_dashboard_id}"
                if is_edit_mode:
                    new_pathname += "/edit"
        else:
            # Fallback to current pathname (shouldn't happen for child tabs)
            new_pathname = pathname

        return new_pathname, False, False

    @app.callback(
        Output("sidebar-tabs-list", "children", allow_duplicate=True),
        [
            Input({"type": "tab-move-up", "index": ALL}, "n_clicks"),
            Input({"type": "tab-move-down", "index": ALL}, "n_clicks"),
        ],
        [
            State("url", "pathname"),
            State("dashboard-init-data", "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def reorder_tabs(up_clicks, down_clicks, pathname, dashboard_cache, local_data):
        """
        Reorder tabs when up/down buttons are clicked.

        Args:
            up_clicks: List of n_clicks for up buttons
            down_clicks: List of n_clicks for down buttons
            pathname: Current URL pathname
            dashboard_cache: Dashboard init data
            local_data: Local storage with access token

        Returns:
            Updated tab list (triggers sidebar refresh)
        """
        from dash import ctx

        if not ctx.triggered_id:
            raise PreventUpdate

        # Check if any button was actually clicked
        if not any(up_clicks or []) and not any(down_clicks or []):
            raise PreventUpdate

        triggered_id = ctx.triggered_id
        direction = triggered_id.get("type")
        dashboard_id = triggered_id.get("index")

        if not dashboard_id or direction not in ("tab-move-up", "tab-move-down"):
            raise PreventUpdate

        if not local_data or "access_token" not in local_data:
            raise PreventUpdate

        token = local_data["access_token"]

        # Extract dashboard ID from pathname
        current_dashboard_id, is_edit_mode = _extract_dashboard_id_from_pathname(pathname)
        if not current_dashboard_id:
            raise PreventUpdate

        # Fetch current dashboard to determine parent
        current_dash = _fetch_dashboard(current_dashboard_id, token)
        if not current_dash:
            raise PreventUpdate

        # Determine parent dashboard ID
        parent_id = _get_parent_dashboard_id(current_dash, current_dashboard_id)

        # Fetch all tabs and filter to only child tabs (for reordering)
        all_tabs = _fetch_all_tabs(parent_id, token)
        child_tabs = [t for t in all_tabs if not t.get("is_main_tab", True)]
        if not child_tabs:
            raise PreventUpdate

        # Sort by tab_order
        child_tabs.sort(key=lambda t: t.get("tab_order", 0))

        # Find the tab being moved
        tab_index = None
        for i, tab in enumerate(child_tabs):
            if str(tab["dashboard_id"]) == dashboard_id:
                tab_index = i
                break

        if tab_index is None:
            raise PreventUpdate

        # Calculate new positions
        if direction == "tab-move-up" and tab_index > 0:
            # Swap with previous tab
            child_tabs[tab_index], child_tabs[tab_index - 1] = (
                child_tabs[tab_index - 1],
                child_tabs[tab_index],
            )
        elif direction == "tab-move-down" and tab_index < len(child_tabs) - 1:
            # Swap with next tab
            child_tabs[tab_index], child_tabs[tab_index + 1] = (
                child_tabs[tab_index + 1],
                child_tabs[tab_index],
            )
        else:
            raise PreventUpdate

        # Build new tab_orders (starting from 1 for child tabs)
        tab_orders = [
            {"dashboard_id": str(tab["dashboard_id"]), "tab_order": i + 1}
            for i, tab in enumerate(child_tabs)
        ]

        # Call API to reorder
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/tabs/reorder",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"parent_dashboard_id": parent_id, "tab_orders": tab_orders},
        )

        if response.status_code != 200:
            logger.error(f"Failed to reorder tabs: {response.text}")
            raise PreventUpdate

        logger.info("Tabs reordered successfully")

        # Fetch updated tabs and rebuild the tab list
        updated_tabs = _fetch_all_tabs(parent_id, token)
        if not updated_tabs:
            raise PreventUpdate

        # Sort by tab_order
        updated_tabs.sort(key=lambda t: t.get("tab_order", 0))

        # Determine if user is owner for edit controls
        is_owner = False
        if is_edit_mode and dashboard_cache:
            user_permissions = dashboard_cache.get("user_permissions", {})
            is_owner = user_permissions.get("level") == "owner"

        # Get parent dashboard (main tab) for workflow data and icon inheritance
        parent_dashboard = updated_tabs[0] if updated_tabs else None

        # Try to get workflow data for automatic tab color
        workflow_data = None
        workflow_system = None

        if parent_dashboard:
            workflow_system = parent_dashboard.get("workflow_system")

        if not workflow_system or workflow_system == "none":
            if dashboard_cache:
                workflow_system = dashboard_cache.get("workflow_system")

        if workflow_system and workflow_system != "none":
            workflow_catalog = None
            if parent_dashboard:
                workflow_catalog = parent_dashboard.get("workflow_catalog")
            if not workflow_catalog and dashboard_cache:
                workflow_catalog = dashboard_cache.get("workflow_catalog")

            workflow_data = {
                "engine": {"name": workflow_system},
                "catalog": workflow_catalog,
            }

        # Build updated tab items
        tab_items = [
            _build_tab_item(
                tab,
                is_edit_mode=is_edit_mode,
                is_owner=is_owner,
                all_tabs=updated_tabs,
                workflow_data=workflow_data,
                parent_dashboard=parent_dashboard,
            )
            for tab in updated_tabs
        ]

        # Add "+ Add Tab" button in edit mode for owners
        if is_edit_mode and is_owner:
            tab_items.append(_create_add_tab_button())

        return tab_items

    @app.callback(
        Output("tab-modal", "opened", allow_duplicate=True),
        Input("tab-modal-cancel", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_tab_modal(n_clicks):
        """
        Close modal on cancel button click.

        Args:
            n_clicks: Number of times cancel button was clicked

        Returns:
            bool: False to close modal
        """
        if n_clicks:
            logger.info("Closing tab modal")
            return False
        raise PreventUpdate

    @app.callback(
        [
            Output("url", "pathname", allow_duplicate=True),
            Output("tab-modal", "opened", allow_duplicate=True),
        ],
        Input("tab-modal-submit", "n_clicks"),
        [
            State("tab-name-input", "value"),
            State("tab-icon-select", "value"),
            State("tab-icon-color-picker", "value"),
            State("main-tab-name-input", "value"),
            State("tab-modal-edit-mode", "data"),
            State("url", "pathname"),
            State("dashboard-init-data", "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def save_tab(
        n_clicks,
        tab_name,
        tab_icon,
        tab_icon_color,
        main_tab_name,
        edit_mode_data,
        pathname,
        dashboard_cache,
        local_data,
    ):
        """
        Create new tab or update existing tab.

        Handles both creation of new child tabs and editing of existing tabs
        (main or child) based on the edit_mode_data state.

        Args:
            n_clicks: Number of times submit button was clicked
            tab_name: Name for the tab
            tab_icon: Icon for the tab (e.g., "mdi:view-dashboard")
            tab_icon_color: Color for the icon
            main_tab_name: Custom display name for main tabs (only used for main tabs)
            edit_mode_data: Dict with is_edit, is_child_tab, dashboard_id, parent_dashboard_id
            pathname: Current URL pathname
            dashboard_cache: Cached dashboard data
            local_data: Local storage data containing access token

        Returns:
            tuple: (new_pathname, modal_closed) - New pathname and modal state
        """
        if not n_clicks or not tab_name:
            raise PreventUpdate

        # Check if we're in edit mode
        is_edit_mode = edit_mode_data and edit_mode_data.get("is_edit", False)

        if is_edit_mode:
            # Update existing tab
            return _update_existing_tab(
                tab_name,
                tab_icon,
                tab_icon_color,
                main_tab_name,
                edit_mode_data,
                pathname,
                local_data,
            )
        else:
            # Create new tab (existing logic)
            return _create_new_tab(
                tab_name,
                tab_icon,
                tab_icon_color,
                pathname,
                dashboard_cache,
                local_data,
            )


def _update_existing_tab(
    tab_name, tab_icon, tab_icon_color, main_tab_name, edit_mode_data, pathname, local_data
):
    """Update an existing tab via the API."""
    if not local_data or "access_token" not in local_data:
        logger.error("No access token available")
        raise PreventUpdate

    token = local_data["access_token"]
    dashboard_id = edit_mode_data.get("dashboard_id")
    is_child_tab = edit_mode_data.get("is_child_tab", True)

    if not dashboard_id:
        logger.error("No dashboard_id in edit mode data")
        raise PreventUpdate

    # Build update payload
    update_data = {
        "title": tab_name,
        "tab_icon": tab_icon,
        "tab_icon_color": tab_icon_color,
    }

    # Add main_tab_name only for main tabs
    if not is_child_tab and main_tab_name:
        update_data["main_tab_name"] = main_tab_name

    logger.info(f"🔄 Updating tab {dashboard_id} with: {update_data}")

    response = httpx.patch(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/tab/{dashboard_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=update_data,
    )

    if response.status_code != 200:
        logger.error(f"Failed to update tab: {response.text}")
        raise PreventUpdate

    logger.info(f"✅ Tab {dashboard_id} updated successfully")

    # Return same pathname and close modal
    # Returning the same pathname won't trigger navigation but will close modal
    return pathname, False


def _create_new_tab(tab_name, tab_icon, tab_icon_color, pathname, dashboard_cache, local_data):
    """Create a new child tab (original create_tab logic)."""
    logger.info(
        f"Creating new tab: tab_name={tab_name}, tab_icon={tab_icon}, tab_icon_color={tab_icon_color}"
    )

    if not local_data or "access_token" not in local_data:
        logger.error("No access token available")
        raise PreventUpdate

    token = local_data["access_token"]

    # Extract current dashboard ID and edit mode from URL using helper
    current_dashboard_id, is_edit_mode = _extract_dashboard_id_from_pathname(pathname)
    if not current_dashboard_id:
        logger.error("Failed to extract dashboard ID from pathname")
        raise PreventUpdate

    # Determine parent dashboard ID using helper
    parent_id = _get_parent_dashboard_id(dashboard_cache, current_dashboard_id)

    # Get next tab order (count existing child tabs)
    all_dashboards_response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/list",
        headers={"Authorization": f"Bearer {token}"},
    )

    if all_dashboards_response.status_code != 200:
        logger.error("Failed to fetch dashboard list")
        raise PreventUpdate

    all_dashboards = all_dashboards_response.json()

    # Count child tabs for this parent
    child_tabs = [
        d
        for d in all_dashboards
        if not d.get("is_main_tab", True) and str(d.get("parent_dashboard_id", "")) == parent_id
    ]
    next_order = len(child_tabs) + 1  # Main tab is 0

    # Fetch parent dashboard's full permissions to copy to new tab
    parent_response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{parent_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    if parent_response.status_code == 200:
        parent_dashboard = parent_response.json()
        parent_permissions_dict = parent_dashboard.get("permissions", {})
        parent_project_id = str(
            parent_dashboard.get("project_id", dashboard_cache.get("project_id"))
        )
    else:
        logger.warning("Failed to fetch parent dashboard, using cached data")
        parent_permissions_dict = {}
        parent_project_id = str(dashboard_cache.get("project_id"))

    # Convert parent permissions dict to Permission model
    parent_permissions = Permission(**parent_permissions_dict)

    # Generate new dashboard ID for the tab
    new_dashboard_id = PyObjectId()

    logger.info(
        f"🎨 Creating DashboardData instance:\n"
        f"   - icon (from modal): {tab_icon}\n"
        f"   - icon_color (from modal): {tab_icon_color}\n"
        f"   - parent_dashboard_id: {parent_id}"
    )

    # Create DashboardData instance for the new tab, copying structure from parent
    new_tab_dashboard = DashboardData(
        dashboard_id=new_dashboard_id,
        version=1,
        title=tab_name,
        subtitle="",
        icon=tab_icon,
        icon_color=tab_icon_color,  # Use color from modal, not parent
        icon_variant="filled",
        workflow_system="none",
        notes_content="",
        permissions=parent_permissions,
        is_public=False,
        last_saved_ts="",
        project_id=PyObjectId(parent_project_id),  # Convert string to PyObjectId
        # Tab-specific fields
        is_main_tab=False,
        parent_dashboard_id=PyObjectId(parent_id),  # Convert string to PyObjectId
        tab_order=next_order,
        tab_icon=tab_icon,
        tab_icon_color=tab_icon_color,
    )

    # Convert to JSON-serializable dict
    new_tab_payload = convert_objectid_to_str(new_tab_dashboard.model_dump())

    new_tab_response = httpx.post(
        f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{str(new_dashboard_id)}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=new_tab_payload,
    )

    if new_tab_response.status_code != 200:
        logger.error(f"Failed to create new tab: {new_tab_response.text}")
        raise PreventUpdate

    # The /save/ endpoint returns the saved DashboardData
    # new_dashboard_id was generated above, so we already have it
    saved_tab = new_tab_response.json()
    logger.info(
        f"✅ Created new tab: {tab_name} (ID: {str(new_dashboard_id)})\n"
        f"   - Saved icon value: {saved_tab.get('icon', 'NOT FOUND')}\n"
        f"   - Saved icon_color: {saved_tab.get('icon_color', 'NOT FOUND')}"
    )

    # Navigate to new tab (preserves viewer/editor app context)
    if "/dashboard-edit/" in pathname:
        # Editor app: use /dashboard-edit/ prefix
        new_pathname = f"/dashboard-edit/{str(new_dashboard_id)}"
    else:
        # Viewer app
        new_pathname = f"/dashboard/{str(new_dashboard_id)}"
        if is_edit_mode:
            # Legacy edit mode: append /edit suffix
            new_pathname += "/edit"

    # Close modal and navigate to new tab
    return new_pathname, False
