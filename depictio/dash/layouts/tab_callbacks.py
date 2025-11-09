"""Callbacks for dashboard tab management."""

import httpx
from dash import Input, Output, State
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger


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

        logger.info(
            f"🔄 populate_sidebar_tabs called - pathname: {pathname}, has_cache: {bool(dashboard_cache)}, has_local: {bool(local_data)}"
        )

        # Check if we're on a dashboard page
        if not pathname or "/dashboard/" not in pathname:
            logger.info("⏭️ Not on dashboard page, skipping tab population")
            raise PreventUpdate

        # Extract dashboard ID from pathname
        try:
            dashboard_id = pathname.split("/dashboard/")[1].split("/")[0]
            is_edit_mode = "/edit" in pathname
            logger.info(f"📍 Dashboard ID: {dashboard_id}, Edit mode: {is_edit_mode}")
        except (IndexError, AttributeError) as e:
            logger.warning(f"⚠️ Failed to parse dashboard ID from pathname: {e}")
            raise PreventUpdate

        # Get access token
        if not local_data or "access_token" not in local_data:
            logger.warning(
                f"⚠️ No access token available for tab loading - local_data keys: {local_data.keys() if local_data else 'None'}"
            )
            raise PreventUpdate

        token = local_data["access_token"]

        try:
            # Get current dashboard to determine parent
            current_dash_response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}",
                headers={"Authorization": f"Bearer {token}"},
            )

            if current_dash_response.status_code != 200:
                logger.warning(f"Failed to fetch dashboard {dashboard_id}")
                raise PreventUpdate

            current_dash = current_dash_response.json()

            # Determine parent dashboard ID
            if current_dash.get("is_main_tab", True):
                parent_id = dashboard_id
            else:
                parent_id = str(current_dash["parent_dashboard_id"])

            # Fetch main tab
            main_tab_response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{parent_id}",
                headers={"Authorization": f"Bearer {token}"},
            )

            if main_tab_response.status_code != 200:
                logger.warning(f"Failed to fetch main tab {parent_id}")
                raise PreventUpdate

            main_tab = main_tab_response.json()

            # Fetch all dashboards to find child tabs
            all_dashboards_response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/dashboards/list",
                headers={"Authorization": f"Bearer {token}"},
            )

            if all_dashboards_response.status_code != 200:
                logger.warning("Failed to fetch dashboard list")
                # At minimum, show the main tab
                tabs = [main_tab]
            else:
                all_dashboards = all_dashboards_response.json()

                # Filter child tabs for this parent
                child_tabs = [
                    d
                    for d in all_dashboards
                    if not d.get("is_main_tab", True)
                    and str(d.get("parent_dashboard_id", "")) == parent_id
                ]

                # Combine and sort by tab_order
                tabs = [main_tab] + child_tabs
                tabs.sort(key=lambda t: t.get("tab_order", 0))

            # Build tab items
            tab_items = []
            for tab in tabs:
                # Use "Main" for main tab, otherwise use the tab's title
                tab_label = "Main" if tab.get("is_main_tab", True) else tab.get("title", "Untitled")
                icon_name = tab.get("icon", "mdi:view-dashboard")
                icon_color = tab.get("icon_color", "orange")

                # Only use DashIconify - if icon is a file path, use default icon
                if icon_name and (
                    "/" in icon_name or icon_name.endswith((".png", ".svg", ".jpg", ".jpeg"))
                ):
                    # File path detected - use default icon
                    icon_name = "mdi:view-dashboard"
                    logger.info(f"Tab '{tab_label}': Using default icon (file path detected)")

                tab_items.append(
                    dmc.TabsTab(
                        tab_label,
                        value=str(tab["dashboard_id"]),
                        leftSection=DashIconify(
                            icon=icon_name,
                            color=icon_color,
                            width=24,
                        ),
                        style={
                            "width": "100%",
                            "fontSize": "16px",
                            "padding": "16px 16px",  # Increased height with more vertical padding
                        },
                    )
                )

            # Add "+ Add Tab" button in edit mode
            if is_edit_mode and dashboard_cache:
                # Check if user is owner
                user_id = local_data.get("user_id")
                owner_ids = [
                    str(owner["id"])
                    for owner in dashboard_cache.get("permissions", {}).get("owners", [])
                ]
                is_owner = str(user_id) in owner_ids if user_id else False

                if is_owner:
                    tab_items.append(
                        dmc.TabsTab(
                            "+ Add Tab",
                            value="__add_tab__",
                            leftSection=DashIconify(icon="mdi:plus", color="blue", width=24),
                            style={
                                "width": "100%",
                                "fontSize": "16px",
                                "padding": "16px 16px",  # Increased height to match other tabs
                            },
                        )
                    )

            logger.info(f"Loaded {len(tab_items)} tabs for dashboard {dashboard_id}")
            return tab_items, dashboard_id

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
        This triggers a full page reload for clean DOM rendering.

        Args:
            tab_dashboard_id: The dashboard_id of the clicked tab
            current_pathname: Current URL pathname

        Returns:
            str: New pathname to navigate to
        """
        if not tab_dashboard_id or tab_dashboard_id == "__add_tab__":
            raise PreventUpdate

        # Check if in edit mode
        is_edit_mode = "/edit" in current_pathname

        # Build new pathname
        new_pathname = f"/dashboard/{tab_dashboard_id}"
        if is_edit_mode:
            new_pathname += "/edit"

        logger.info(f"Navigating to tab: {new_pathname}")
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
        Output("url", "pathname", allow_duplicate=True),
        Input("tab-modal-submit", "n_clicks"),
        [
            State("tab-name-input", "value"),
            State("tab-icon-select", "value"),
            State("url", "pathname"),
            State("dashboard-init-data", "data"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def create_tab(n_clicks, tab_name, tab_icon, pathname, dashboard_cache, local_data):
        """
        Create new tab and navigate to it.

        Args:
            n_clicks: Number of times submit button was clicked
            tab_name: Name for the new tab
            tab_icon: Icon for the new tab
            pathname: Current URL pathname
            dashboard_cache: Cached dashboard data
            local_data: Local storage data containing access token

        Returns:
            str: New pathname to navigate to the created tab
        """
        if not n_clicks or not tab_name:
            raise PreventUpdate

        if not local_data or "access_token" not in local_data:
            logger.error("No access token available")
            raise PreventUpdate

        token = local_data["access_token"]

        # Extract current dashboard ID from URL
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

        # Create new dashboard using existing register endpoint
        new_tab_response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/register",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "title": tab_name,
                "icon": tab_icon,
                "icon_color": dashboard_cache.get("icon_color", "orange"),
                "project_id": str(dashboard_cache["project_id"]),
                # Tab-specific fields
                "is_main_tab": False,
                "parent_dashboard_id": parent_id,
                "tab_order": next_order,
                # Copy permissions from parent
                "permissions": dashboard_cache.get("permissions", {}),
            },
        )

        if new_tab_response.status_code != 200:
            logger.error(f"Failed to create new tab: {new_tab_response.text}")
            raise PreventUpdate

        new_tab = new_tab_response.json()
        new_dashboard_id = new_tab["dashboard_id"]

        logger.info(f"Created new tab: {tab_name} (ID: {new_dashboard_id})")

        # Navigate to new tab
        new_pathname = f"/dashboard/{new_dashboard_id}"
        if is_edit_mode:
            new_pathname += "/edit"

        return new_pathname
