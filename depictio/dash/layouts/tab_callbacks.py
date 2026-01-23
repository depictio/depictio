"""
Callbacks for dashboard tab management.

This module provides callbacks for managing dashboard tabs including:

- Populating sidebar tabs based on the current dashboard
- Navigating between tabs via URL changes
- Opening and handling tab creation modal
- Creating new tabs with custom icons and colors

Key Callbacks:
    populate_sidebar_tabs: Loads and displays tabs for the dashboard family
    navigate_to_tab: Handles tab click navigation
    open_tab_modal: Opens the tab creation modal
    create_tab: Creates a new child tab under the parent dashboard
"""

import httpx
from dash import Input, Output, State
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission


def _extract_dashboard_id_from_pathname(pathname: str) -> tuple[str | None, bool]:
    """
    Extract dashboard ID and edit mode flag from URL pathname.

    Args:
        pathname: URL pathname (e.g., '/dashboard/{id}' or '/dashboard-edit/{id}')

    Returns:
        Tuple of (dashboard_id, is_edit_mode) or (None, False) if invalid
    """
    try:
        if "/dashboard-edit/" in pathname:
            dashboard_id = pathname.split("/dashboard-edit/")[1].split("/")[0]
            return dashboard_id, True
        else:
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


def _fetch_child_tabs(parent_id: str, token: str) -> list[dict]:
    """
    Fetch child tabs for a parent dashboard.

    Args:
        parent_id: The parent dashboard ID
        token: Authentication token

    Returns:
        List of child tab dictionaries sorted by tab_order
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/list?include_child_tabs=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            logger.warning("Failed to fetch dashboard list for child tabs")
            return []

        all_dashboards = response.json()
        child_tabs = [
            d
            for d in all_dashboards
            if not d.get("is_main_tab", True) and str(d.get("parent_dashboard_id", "")) == parent_id
        ]
        return child_tabs
    except Exception as e:
        logger.error(f"Error fetching child tabs: {e}")
        return []


def _build_tab_item(tab: dict):
    """
    Build a DMC TabsTab component from tab data.

    Args:
        tab: Tab dictionary containing dashboard data

    Returns:
        DMC TabsTab component
    """
    import dash_mantine_components as dmc

    tab_label = "Main" if tab.get("is_main_tab", True) else tab.get("title", "Untitled")
    icon_name = tab.get("icon", "mdi:view-dashboard")
    icon_color = tab.get("icon_color", "orange")
    tab_dashboard_id = str(tab["dashboard_id"])

    # Use default icon if icon is a file path
    if icon_name and ("/" in icon_name or icon_name.endswith((".png", ".svg", ".jpg", ".jpeg"))):
        icon_name = "mdi:view-dashboard"

    return dmc.TabsTab(
        tab_label,
        value=tab_dashboard_id,
        leftSection=dmc.ActionIcon(
            DashIconify(icon=icon_name, width=20),
            color=icon_color,
            radius="xl",
            size="md",
            variant="filled",
        ),
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

        Args:
            pathname: Current URL pathname
            dashboard_cache: Cached dashboard data
            local_data: Local storage data containing access token

        Returns:
            tuple: (tab_items list, selected tab value)
        """
        import dash_mantine_components as dmc

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
            parent_id = (
                dashboard_id
                if current_dash.get("is_main_tab", True)
                else str(current_dash["parent_dashboard_id"])
            )

            # Fetch main tab
            main_tab = _fetch_dashboard(parent_id, token)
            if not main_tab:
                raise PreventUpdate

            # Fetch child tabs and combine with main tab
            child_tabs = _fetch_child_tabs(parent_id, token)

            tabs = [main_tab] + child_tabs
            tabs.sort(key=lambda t: t.get("tab_order", 0))

            # Build tab items using helper function
            tab_items = [_build_tab_item(tab) for tab in tabs]

            # Add "+ Add Tab" button in edit mode for owners
            if is_edit_mode and dashboard_cache:
                user_permissions = dashboard_cache.get("user_permissions", {})
                is_owner = user_permissions.get("level") == "owner"

                if is_owner:
                    tab_items.append(
                        dmc.TabsTab(
                            "Add Tab",
                            value="__add_tab__",
                            leftSection=DashIconify(icon="mdi:plus", color="grey", width=24),
                            style={
                                "width": "100%",
                                "fontSize": "16px",
                                "padding": "16px 16px",
                            },
                        )
                    )

            return tab_items, dashboard_id

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
            State("url", "pathname"),
            State("dashboard-init-data", "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def create_tab(
        n_clicks, tab_name, tab_icon, tab_icon_color, pathname, dashboard_cache, local_data
    ):
        """
        Create new tab and navigate to it.

        Args:
            n_clicks: Number of times submit button was clicked
            tab_name: Name for the new tab
            tab_icon: Icon for the new tab (e.g., "mdi:view-dashboard")
            tab_icon_color: Color for the icon (hex format, e.g., "#ff6b35")
            pathname: Current URL pathname
            dashboard_cache: Cached dashboard data
            local_data: Local storage data containing access token

        Returns:
            tuple: (new_pathname, modal_closed) - New pathname and modal state
        """
        if not n_clicks or not tab_name:
            raise PreventUpdate

        logger.info(
            f"🎨 Creating new tab:\n"
            f"   - tab_name: {tab_name}\n"
            f"   - tab_icon: {tab_icon}\n"
            f"   - tab_icon_color: {tab_icon_color}"
        )

        if not local_data or "access_token" not in local_data:
            logger.error("No access token available")
            raise PreventUpdate

        token = local_data["access_token"]

        # Extract current dashboard ID from URL
        if "/dashboard-edit/" in pathname:
            current_dashboard_id = pathname.split("/dashboard-edit/")[1].split("/")[0]
            is_edit_mode = True
        else:
            current_dashboard_id = pathname.split("/dashboard/")[1].split("/")[0]
            is_edit_mode = "/edit" in pathname

        # Determine parent dashboard ID
        if dashboard_cache.get("is_main_tab", True):
            parent_id = current_dashboard_id
        else:
            parent_id = str(dashboard_cache["parent_dashboard_id"])

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
