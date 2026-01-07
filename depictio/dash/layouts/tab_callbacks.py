"""Callbacks for dashboard tab management."""

import httpx
from dash import Input, Output, State
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission


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
        if dashboard_cache:
            logger.info(f"   Dashboard cache keys: {list(dashboard_cache.keys())}")

        # EARLY EXIT: Don't populate tabs on component add/edit pages
        # This prevents the callback from running at all when editing/adding components
        if pathname and ("/component/edit/" in pathname or "/component/add/" in pathname):
            logger.info("🔒 Component page detected - skipping tab population entirely")
            raise PreventUpdate

        # Check if we're on a dashboard page (viewer or editor app)
        if not pathname or ("/dashboard/" not in pathname and "/dashboard-edit/" not in pathname):
            logger.info("⏭️ Not on dashboard page, skipping tab population")
            raise PreventUpdate

        # Extract dashboard ID from pathname
        try:
            # Handle both viewer (/dashboard/{id}) and editor (/dashboard-edit/{id}) URLs
            if "/dashboard-edit/" in pathname:
                dashboard_id = pathname.split("/dashboard-edit/")[1].split("/")[0]
                is_edit_mode = True
            else:
                dashboard_id = pathname.split("/dashboard/")[1].split("/")[0]
                is_edit_mode = "/edit" in pathname  # Legacy edit mode check
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

            # Fetch all dashboards to find child tabs (include_child_tabs=true for sidebar)
            all_dashboards_response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/dashboards/list?include_child_tabs=true",
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

                logger.info(
                    f"Found {len(child_tabs)} child tabs for parent {parent_id}: "
                    f"{[t.get('title') for t in child_tabs]}"
                )

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
                tab_dashboard_id = str(tab["dashboard_id"])

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
                        value=tab_dashboard_id,
                        leftSection=dmc.ActionIcon(
                            DashIconify(
                                icon=icon_name,
                                width=20,  # Slightly smaller for tab context
                            ),
                            color=icon_color,
                            radius="xl",  # Circular shape
                            size="md",  # Medium size for tabs
                            variant="filled",  # Solid filled background
                        ),
                        style={
                            "width": "100%",
                            "fontSize": "16px",
                            "padding": "16px 16px",  # Increased height with more vertical padding
                        },
                    )
                )

            # Add "+ Add Tab" button in edit mode
            logger.info(
                f"🔍 Checking if we should add '+ Add Tab': is_edit_mode={is_edit_mode}, has_cache={bool(dashboard_cache)}"
            )

            if is_edit_mode and dashboard_cache:
                # Check if user is owner using user_permissions from init endpoint
                # The API endpoint already validates the user via JWT and returns permission level
                user_permissions = dashboard_cache.get("user_permissions", {})
                is_owner = user_permissions.get("level") == "owner"

                logger.info(
                    f"🔐 Permission check for Add Tab:\n"
                    f"   - is_edit_mode: {is_edit_mode}\n"
                    f"   - has_dashboard_cache: {bool(dashboard_cache)}\n"
                    f"   - dashboard_cache keys: {list(dashboard_cache.keys()) if dashboard_cache else 'None'}\n"
                    f"   - user_permissions: {user_permissions}\n"
                    f"   - level: {user_permissions.get('level')}\n"
                    f"   - is_owner: {is_owner}"
                )

                if is_owner:
                    logger.info("✅ Adding '+ Add Tab' button to sidebar")
                    tab_items.append(
                        dmc.TabsTab(
                            "Add Tab",
                            value="__add_tab__",
                            leftSection=DashIconify(icon="mdi:plus", color="grey", width=24),
                            style={
                                "width": "100%",
                                "fontSize": "16px",
                                "padding": "16px 16px",  # Increased height to match other tabs
                            },
                        )
                    )
                else:
                    logger.warning(
                        f"❌ Not adding '+ Add Tab' button - user level is '{user_permissions.get('level')}', not 'owner'"
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
            logger.info(f"🔒 Skipping tab navigation - on component page: {current_pathname}")
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
