# import dash_bootstrap_components as dbc  # Not needed for AppShell layout
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, purge_expired_tokens

# Analytics tracking
from depictio.dash.components.analytics_tracker import (
    create_analytics_tracker,
)
from depictio.dash.layouts.dashboards_management import layout as dashboards_management_layout

# from depictio.dash.layouts.draggable_scenarios.add_component import register_callbacks_add_component
from depictio.dash.layouts.draggable import design_draggable

# Depictio utils imports
from depictio.dash.layouts.layouts_toolbox import create_add_with_input_modal
from depictio.dash.layouts.notes_footer import create_notes_footer
from depictio.dash.layouts.palette import create_color_palette_page
from depictio.dash.layouts.profile import layout as profile_layout
from depictio.dash.layouts.project_data_collections import (
    layout as project_data_collections_layout,
)
from depictio.dash.layouts.projects import layout as projects_layout
from depictio.dash.layouts.projectwise_user_management import (
    layout as projectwise_user_management_layout,
)
from depictio.dash.layouts.tokens_management import layout as tokens_management_layout
from depictio.dash.layouts.users_management import layout as users_management_layout


def return_create_dashboard_button(email, is_anonymous=False):
    # For anonymous users, show "Login to Create Dashboards" button that redirects to profile
    # For authenticated users, show normal "+ New Dashboard" button
    button_text = "+ New Dashboard" if not is_anonymous else "Login to Create Dashboards"
    button_color = (
        "orange" if not is_anonymous else "blue"
    )  # Use blue to match temporary user button

    create_button = dmc.Button(
        button_text,
        id={"type": "create-dashboard-button", "index": email},
        n_clicks=0,
        color=button_color,
        style={
            "fontFamily": "Virgil",
            "marginRight": "10px",
        },
        size="lg",  # Changed from xl to lg for better proportions
        radius="md",
        disabled=False,  # Always enabled - behavior changes based on user type
    )
    return create_button


def return_create_project_button(email, is_anonymous=False):
    # For anonymous users, show "Login to Create Projects" button that redirects to profile
    # For authenticated users, show normal "+ Create Project" button
    button_text = "+ Create Project" if not is_anonymous else "Login to Create Projects"
    button_color = (
        "teal" if not is_anonymous else "blue"  # Use teal color matching colors.py
    )  # Use blue to match temporary user button

    create_button = dmc.Button(
        button_text,
        id="create-project-button",
        n_clicks=0,
        color=button_color,
        # leftSection=DashIconify(icon="mdi:plus", width=16),
        style={
            "fontFamily": "Virgil",
            "marginRight": "10px",
        },
        size="lg",  # Changed from xl to lg for better proportions
        radius="md",
        disabled=False,  # Always enabled - behavior changes based on user type
    )
    return create_button


def handle_unauthenticated_user(pathname):
    header = create_default_header("Welcome to Depictio")
    logger.info("User not logged in")

    # Redirect any path to the login/auth page
    return (
        create_users_management_layout(),
        header,
        "/auth",
        {"logged_in": False, "access_token": None},
    )


def handle_authenticated_user(pathname, local_data, theme="light", cached_project_data=None):
    logger.info(f"User logged in: {local_data.get('email', 'Unknown')}")
    # logger.info(f"Local data: {local_data}")

    # OPTIMIZATION: Check dashboard route FIRST to return faster
    if pathname.startswith("/dashboard/"):
        # Handle add component routes
        if "/add_component" in pathname:
            from depictio.dash.layouts.component_creator import create_component_creator_layout

            # Extract dashboard_id and optional component_id from URL
            path_parts = pathname.strip("/").split("/")
            dashboard_id = None
            component_id = None

            for i, part in enumerate(path_parts):
                if part == "dashboard" and i + 1 < len(path_parts):
                    dashboard_id = path_parts[i + 1]
                elif part == "add_component" and i + 1 < len(path_parts):
                    component_id = path_parts[i + 1]

            if not dashboard_id:
                # Fallback to dashboard content if no dashboard_id found
                header_content = create_default_header("Dashboard")
                dashboard_layout = dmc.Container(
                    id="dashboard-content",
                    style={
                        "--container-size": "none",  # Disable container size constraint
                        "maxWidth": "none",
                        "width": "100%",
                    },
                )
                return dashboard_layout, header_content, pathname, local_data

            header_content = create_default_header("Add Component")
            creator_layout = create_component_creator_layout(dashboard_id, component_id)
            return creator_layout, header_content, pathname, local_data

        # Return immediately for regular dashboard routes with tabs header
        # Extract dashboard_id and optional tab from pathname
        import re

        # Support URLs like: /dashboard/{id} or /dashboard/{id}/{tab} (with optional anchors)
        # Remove anchor part for routing logic
        clean_pathname = pathname.split("#")[0] if "#" in pathname else pathname
        dashboard_match = re.match(
            r"/dashboard/([a-f0-9]{24})(?:/([a-zA-Z0-9_-]+))?", clean_pathname
        )

        if dashboard_match:
            dashboard_id = dashboard_match.group(1)
            tab_name_from_url = dashboard_match.group(2)

            # For dashboard routes, we'll validate the tab dynamically in the dashboard content loading
            # Here we just accept the tab name from URL and let dashboard content handle validation
            active_tab = tab_name_from_url if tab_name_from_url else None
            header_content = create_dashboard_tabs_header(dashboard_id, active_tab=active_tab)
        else:
            # For dashboard routes without specific ID, still show tabs header
            header_content = create_dashboard_tabs_header("default", active_tab="overview")

        dashboard_layout = dmc.Container(
            id="dashboard-content",
            style={
                "--container-size": "none",  # Disable container size constraint
                "maxWidth": "none",
                "width": "100%",
            },
        )
        return dashboard_layout, header_content, pathname, local_data

    # For all other routes, purge tokens as normal
    purge_expired_tokens(local_data["access_token"])

    # Map the pathname to the appropriate content and header
    # Test: Check exact paths first before pattern matching
    if pathname == "/dashboards":
        user = api_call_fetch_user_from_token(local_data["access_token"])
        # user = fetch_user_from_token(local_data["access_token"])
        # logger.info(f"User: {user}")

        # Check if user is anonymous
        is_anonymous = hasattr(user, "is_anonymous") and user.is_anonymous

        create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header, pathname, local_data

    elif pathname.startswith("/project/") and pathname.endswith("/permissions"):
        header = create_default_header("Project Permissions Manager")
        return projectwise_user_management_layout, header, pathname, local_data

    elif pathname.startswith("/project/") and pathname.endswith("/data"):
        header = create_default_header("Project Data Collections Manager")
        return project_data_collections_layout, header, pathname, local_data

        # return projects, header, pathname, local_data

    elif pathname == "/projects":
        user = api_call_fetch_user_from_token(local_data["access_token"])

        # Check if user is anonymous
        is_anonymous = hasattr(user, "is_anonymous") and user.is_anonymous

        create_button = return_create_project_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Projects", create_button)
        content = create_projects_layout()
        return content, header, pathname, local_data

    elif pathname == "/profile":
        header = create_default_header("Profile")
        return create_profile_layout(), header, pathname, local_data

    elif pathname == "/palette":
        header = create_default_header("Depictio Color Palette")
        return create_color_palette_page(), header, pathname, local_data

    elif pathname == "/cli_configs":
        header = create_default_header("Depictio-CLI configs Management")
        return create_tokens_management_layout(), header, pathname, local_data

    elif pathname == "/admin":
        # Check if user is admin
        user = api_call_fetch_user_from_token(local_data["access_token"])
        if not user.is_admin:
            # Fallback to dashboards if user is not admin
            content = create_dashboards_management_layout()

            # Check if user is anonymous
            is_anonymous = hasattr(user, "is_anonymous") and user.is_anonymous

            create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
            header = create_header_with_button("Dashboards", create_button)

            return content, header, "/dashboards", local_data

        header = create_admin_header("Admin")
        admin = html.Div(id="admin-management-content")
        return admin, header, pathname, local_data

    elif pathname == "/about":
        header = create_default_header("About")
        from depictio.dash.layouts.about import layout as about_layout

        return about_layout, header, pathname, local_data
    else:
        # Fallback to dashboards if path is unrecognized
        user = api_call_fetch_user_from_token(local_data["access_token"])
        # Check if user is anonymous
        is_anonymous = hasattr(user, "is_anonymous") and user.is_anonymous

        create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header, "/dashboards", local_data


def create_default_header(text):
    # Return content for AppShellHeader - Simple text with burger menu
    return dmc.Group(
        [
            dmc.Burger(
                id="burger-menu",
                opened=False,
                style={"marginRight": "15px"},
            ),
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon="material-symbols:biotech", height=28),
                        size="lg",
                        radius="md",
                        variant="gradient",
                        gradient={"from": "green", "to": "teal"},
                        style={"marginRight": "8px"},
                    ),
                    dmc.Text(
                        text,
                        fw="bold",  # DMC 2.0+ equivalent of weight=600
                        size="xl",
                        style={
                            "fontSize": "24px",
                            "fontFamily": "Virgil",
                        },
                    ),
                ],
                gap="xs",
                align="center",
            ),
        ],
        justify="flex-start",  # Align to the left
        align="center",
        style={
            "padding": "0 20px",
            "height": "100%",
        },
    )


def create_dashboard_tabs_header(dashboard_id, active_tab="dashboard"):
    """Create simple dashboard header with title and management controls"""

    # No longer need tab title since it's shown in dmc.Tabs
    # Tabs will be populated dynamically by callbacks

    # Header with tabs and management controls in horizontal layout
    header_content = dmc.Group(
        id="dashboard-header-content",
        children=[
            # Visible tabs component with pills style
            dmc.Tabs(
                id="dashboard-tabs",
                value=active_tab,
                variant="pills",
                children=[
                    # Tab list will be populated by dashboard structure callback
                    dmc.TabsList([])  # Empty initially, filled by callback
                ],
            ),
            # Management controls for tabs only
            dmc.Group(
                children=[
                    dmc.Button(
                        "Add Tab",
                        leftSection=DashIconify(icon="material-symbols:add", height=16),
                        id="add-tab-btn",
                        variant="light",
                        size="xs",
                        color="blue",
                    ),
                ],
                gap="xs",
            ),
        ],
        justify="space-between",
        align="center",
        style={"flex": "1", "padding": "0 10px"},
    )

    return dmc.Group(
        [
            dmc.Burger(
                id="burger-menu",
                opened=False,
                # style={"marginRight": "15px"},
            ),
            dmc.Group(
                [
                    dmc.ThemeIcon(
                        DashIconify(icon="material-symbols:biotech", height=24),
                        size="md",
                        radius="md",
                        variant="gradient",
                        gradient={"from": "green", "to": "teal"},
                        # style={"marginRight": "8px"},
                    ),
                ],
                gap="xs",
                align="center",
            ),
            header_content,
            dmc.Group(
                [
                    dmc.ActionIcon(
                        DashIconify(icon="material-symbols:play-arrow", height=20),
                        id="run-analysis-btn",
                        variant="light",
                        size="lg",
                        color="green",
                    ),
                    dmc.ActionIcon(
                        DashIconify(icon="material-symbols:save", height=20),
                        id="save-analysis-btn",
                        variant="light",
                        size="lg",
                    ),
                    dmc.ActionIcon(
                        DashIconify(icon="material-symbols:edit", height=20),
                        id="edit-mode-toggle-btn",
                        variant="light",
                        size="lg",
                        color="orange",
                    ),
                    dmc.ActionIcon(
                        DashIconify(icon="material-symbols:more-vert", height=20),
                        id="more-options-btn",
                        variant="light",
                        size="lg",
                    ),
                    dmc.ActionIcon(
                        DashIconify(icon="material-symbols:side-navigation", height=20),
                        id="aside-toggle-btn",
                        variant="light",
                        size="lg",
                        color="blue",
                    ),
                ],
                gap="sm",
                # style={"marginRight": "20px"},
            ),
        ],
        justify="space-between",
        style={"width": "100%", "alignItems": "center", "height": "100%", "padding": "0 20px"},
    )


def create_admin_header(text):
    """
    Creates an admin header with a title and navigation tabs for Users, Projects, and Dashboards.

    Parameters:
    - text (str): The title text to display in the header.

    Returns:
    - dmc.Header: A Dash Mantine Components Header containing the title and navigation tabs.
    """

    add_group_button = dmc.Button(
        "Add Group",
        color="blue",
        variant="filled",
        size="sm",
        id="group-add-button",
        style={"display": "none"},
        leftSection=DashIconify(icon="mdi:plus-circle", width=16, color="white"),
    )

    text_group_input = dmc.TextInput(
        placeholder="Enter group name",
        size="sm",
        id="group-add-modal-text-input",
    )

    add_group_modal, _ = create_add_with_input_modal(
        id_prefix="group",
        input_field=text_group_input,
        title="Add Group",
        message="Please complete the input field to add a new group.",
        confirm_button_text="Add",
        cancel_button_text="Cancel",
        icon="mdi:plus-circle",
        opened=False,
    )

    header = dmc.AppShellHeader(  # type: ignore[unresolved-attribute]
        # Height is controlled by AppShell config
        # padding="xs",  # Padding inside the header
        children=[
            dmc.Container(
                fluid=True,  # Make the container fluid (full-width)
                children=[
                    dmc.Group(
                        justify="space-between",  # Space between the title and tabs
                        align="center",
                        style={"height": "100%"},
                        children=[
                            # Navigation Tabs
                            dmc.Tabs(
                                value="users",  # Default active tab
                                id="admin-tabs",  # ID for the tabs component
                                # onTabChange=lambda value: dash.callback_context.triggered,  # Placeholder for callback
                                children=dmc.TabsList(
                                    [
                                        dmc.TabsTab(  # type: ignore[unresolved-attribute]
                                            "Users",
                                            leftSection=DashIconify(
                                                icon="mdi:account",
                                                width=20,
                                                height=20,
                                            ),
                                            value="users",
                                        ),
                                        dmc.TabsTab(  # type: ignore[unresolved-attribute]
                                            "Projects",
                                            leftSection=DashIconify(
                                                icon="mdi:jira",
                                                width=20,
                                                height=20,
                                            ),
                                            value="projects",
                                        ),
                                        dmc.TabsPanel(
                                            children=[],
                                            value="users",
                                            id="admin-tabs-users",
                                        ),
                                        dmc.TabsPanel(
                                            children=[],
                                            value="projects",
                                            id="admin-tabs-projects",
                                        ),
                                    ]
                                ),
                                # orientation="horizontal",
                                radius="md",
                                # variant="outline",
                                # grow=True,
                                # styles={
                                #     "tab": {"fontSize": "14px", "padding": "8px 12px"},
                                #     "tabActive": {"backgroundColor": "var(--mantine-color-blue-light)", "color": "var(--mantine-color-blue-dark)"},
                                # }
                            ),
                            add_group_button,
                            add_group_modal,
                        ],
                    )
                ],
            )
        ],
        # fixed=True,  # Fix the header to the top
    )
    return header


def create_header_with_button(text, button):
    # Return content for AppShellHeader - Simple text and button with burger menu
    return dmc.Group(
        [
            dmc.Group(
                [
                    dmc.Burger(
                        id="burger-menu",
                        opened=False,
                        style={"marginRight": "15px"},
                    ),
                    dmc.Text(
                        text,
                        fw="bold",  # DMC 2.0+ equivalent of weight=600
                        size="xl",
                        style={
                            "fontSize": "28px",
                            "fontFamily": "Virgil",
                        },
                    ),
                ],
                align="center",
            ),
            button,
        ],
        justify="space-between",  # DMC 2.0+ equivalent of position="apart"
        align="center",
        style={
            "padding": "0 20px",
            "height": "100%",
        },
    )


def create_dashboards_management_layout():
    return dashboards_management_layout


def create_dashboard_error_layout():
    """Return a static error layout for dashboard routes - prevents Loading... display"""
    return dmc.Center(
        dmc.Stack(
            [
                DashIconify(icon="material-symbols:error", width=48, height=48, color="red"),
                dmc.Title("Dashboard Error", order=3),
                dmc.Text("Unable to load dashboard content", c="gray"),
            ],
            align="center",
        ),
        style={"height": "50vh"},
    )


def create_projects_layout():
    return projects_layout


def create_users_management_layout():
    return users_management_layout


def create_profile_layout():
    return profile_layout


def create_tokens_management_layout():
    return tokens_management_layout


def create_dashboard_layout(
    depictio_dash_data=None,
    dashboard_id: str = "",
    local_data=None,
    backend_components=None,
    theme="light",
    cached_project_data=None,
):
    # Init layout and children if depictio_dash_data is available, else set to empty
    if depictio_dash_data and isinstance(depictio_dash_data, dict):
        # logger.info(f"Depictio dash data: {depictio_dash_data}")
        if "stored_layout_data" in depictio_dash_data:
            init_layout = depictio_dash_data["stored_layout_data"]
        else:
            init_layout = {}
        if "stored_children_data" in depictio_dash_data:
            init_children = depictio_dash_data["stored_children_data"]
        else:
            init_children = list()
    else:
        init_layout = {}
        init_children = list()

    # logger.info(f"Loaded depictio init_layout: {init_layout}")
    # header, backend_components = design_header(depictio_dash_data)

    # Generate draggable layout
    # Ensure local_data is a dict
    local_data = local_data or {}
    core = design_draggable(
        init_layout,
        init_children,
        dashboard_id,
        local_data,
        cached_project_data=cached_project_data,
    )

    # Add progressive loading components if we have metadata
    progressive_loading_components = []
    if (
        depictio_dash_data
        and isinstance(depictio_dash_data, dict)
        and "stored_metadata" in depictio_dash_data
    ):
        from depictio.dash.layouts.draggable_scenarios.progressive_loading import (
            create_loading_progress_display,
        )

        stored_metadata = depictio_dash_data["stored_metadata"]
        if stored_metadata:
            logger.info(f"Adding simple progressive loading for {len(stored_metadata)} components")

            # Create simple loading progress display
            progressive_loading_components.append(create_loading_progress_display(dashboard_id))

    return dmc.Container(
        [
            # Include backend components (Store components)
            backend_components if backend_components else html.Div(),
            # Progressive loading components
            html.Div(progressive_loading_components),
            html.Div(
                [
                    # Draggable layout
                    core,
                ],
            ),
            # Notes footer - positioned as overlay
            create_notes_footer(dashboard_data=depictio_dash_data),
            # html.Div(id="test-input"),
            html.Div(id="test-output", style={"display": "none"}),
            # html.Div(id="test-output-visible"),
        ],
        fluid=True,
        style={
            "display": "flex",
            "maxWidth": "100%",
            "flexGrow": "1",
            "maxHeight": "100%",
            "flexDirection": "column",
            "width": "100%",
            "height": "100%",
            "position": "relative",  # Allow positioned children
        },
    )


# design_header_ui function removed - now using AppShell structure


def create_app_layout():
    from depictio.dash.layouts.sidebar import render_sidebar_content

    return dmc.MantineProvider(
        id="mantine-provider",
        forceColorScheme="light",  # Default to light, will be updated by callback
        children=[
            # Add CSS for smooth transitions and responsive positioning
            html.Div(id="global-css-injection"),
            dcc.Location(id="url", refresh=False),
            dcc.Store(
                id="local-store",
                storage_type="local",
                data={"logged_in": False, "access_token": None},
            ),
            dcc.Store(
                id="theme-store",
                storage_type="local",
                data="light",  # Start with light theme as fallback, will be updated by theme detection
            ),
            # Hidden div to trigger theme detection on app load
            html.Div(id="theme-detection-trigger", style={"display": "none"}),
            dcc.Store(
                id="theme-relay-store",
                storage_type="memory",
                data={"theme": "light", "timestamp": 0},  # Bridge for theme updates
            ),
            # Analytics tracking components
            create_analytics_tracker(),
            dcc.Store(
                id="sidebar-collapsed",
                storage_type="local",  # Changed to local storage to persist user preference
                data=False,  # Default to expanded if no preference saved
            ),
            dcc.Store(
                id="edit-mode-store",
                storage_type="session",  # Session storage for edit mode
                data=False,  # Default to view mode
            ),
            # Consolidated user cache to reduce API calls
            dcc.Store(
                id="user-cache-store",
                storage_type="session",  # Changed to session to persist across navigation
                data=None,  # Will be populated by consolidated callback
            ),
            # Server status cache
            dcc.Store(
                id="server-status-cache",
                storage_type="session",  # Changed to session to persist across navigation
                data=None,  # Will be populated by consolidated callback
            ),
            # Project data cache (dashboard-specific)
            dcc.Store(
                id="project-cache-store",
                storage_type="session",
                data=None,  # Will be populated by consolidated callback
            ),
            dcc.Store(
                id="local-store-components-metadata",
                data={},
                storage_type="local",
            ),
            dcc.Store(id="current-edit-parent-index", storage_type="memory"),
            dcc.Interval(id="interval-component", interval=60 * 60 * 1000, n_intervals=0),
            html.Div(
                id="dummy-plotly-output", style={"display": "none"}
            ),  # Hidden output for Plotly theme callback
            html.Div(
                id="dummy-resize-output", style={"display": "none"}
            ),  # Hidden output for resize callback
            html.Div(
                id="dummy-tab-output", style={"display": "none"}
            ),  # Hidden output for tab creation
            html.Div(
                id="dummy-navlink-output", style={"display": "none"}
            ),  # Hidden output for navlink creation
            html.Div(
                id="dummy-section-output", style={"display": "none"}
            ),  # Hidden output for section management
            dmc.Drawer(
                title="",
                id="drawer-simple",
                padding="md",
                zIndex=10000,
                size="xl",
                overlayProps={"overlayOpacity": 0.1},
                children=[],
            ),
            dmc.NotificationContainer(id="notification-container"),
            html.Div(id="admin-password-warning-trigger", style={"display": "none"}),
            # Navigation editing modals removed - using tab_management modals instead
            dmc.Modal(
                title="Add New NavLink",
                id="add-navlink-modal",
                opened=False,
                children=[
                    dmc.Stack(
                        [
                            dmc.TextInput(
                                label="NavLink Name",
                                placeholder="Enter navlink name",
                                id="navlink-name-input",
                            ),
                            dmc.Select(
                                label="Icon",
                                placeholder="Select an icon",
                                id="navlink-icon-select",
                                data=[
                                    {"value": "material-symbols:biotech", "label": "🧬 Biotech"},
                                    {
                                        "value": "material-symbols:analytics",
                                        "label": "📊 Analytics",
                                    },
                                    {"value": "material-symbols:folder", "label": "📁 Folder"},
                                    {"value": "material-symbols:settings", "label": "⚙️ Settings"},
                                    {"value": "material-symbols:storage", "label": "🗃️ Storage"},
                                    {"value": "material-symbols:link", "label": "🔗 Link"},
                                ],
                            ),
                            dmc.TextInput(
                                label="URL (optional)",
                                placeholder="Enter URL or leave empty",
                                id="navlink-url-input",
                            ),
                            dmc.Switch(
                                label="Nest under current navlink",
                                id="navlink-nested-switch",
                            ),
                            dmc.Group(
                                [
                                    dmc.Button(
                                        "Cancel", id="navlink-modal-cancel", variant="light"
                                    ),
                                    dmc.Button(
                                        "Add NavLink", id="navlink-modal-confirm", color="blue"
                                    ),
                                ],
                                justify="flex-end",
                            ),
                        ],
                        gap="md",
                    ),
                ],
                size="md",
            ),
            dmc.AppShell(
                id="app-shell",  # Add ID for callback targeting
                # navbar, aside and header will be set by callbacks
                layout="default",  # Use default layout
                header={"height": 30},  # Set header height
                # style={
                #     "height": "100vh",
                #     "overflow": "auto",
                #     "transition": "all 0.15s ease-out",  # Faster, simpler transition
                # },
                children=[
                    dmc.AppShellNavbar(  # type: ignore[unresolved-attribute]
                        children=render_sidebar_content(""),
                        id="main-navbar",
                        style={
                            "borderRight": "1px solid var(--app-border-color, #dee2e6)",
                            "transition": "transform 0.1s ease-out",  # Simplified and faster transition
                        },
                    ),
                    dmc.AppShellAside(  # type: ignore[unresolved-attribute]
                        children=[],  # Will be populated by callback for dashboard features
                        id="dashboard-aside",
                        style={
                            "borderLeft": "1px solid var(--app-border-color, #dee2e6)",
                            "transition": "transform 0.1s ease-out",  # Simplified and faster transition
                        },
                    ),
                    dmc.AppShellHeader(  # type: ignore[unresolved-attribute]
                        children=[],  # Will be populated by callback
                        id="header-content",
                    ),
                    dmc.AppShellMain(  # type: ignore[unresolved-attribute]
                        html.Div(
                            id="page-content",
                            style={
                                "padding": "1rem",
                                "minHeight": "calc(100vh - 30px)",  # Updated for 30px header height
                                "overflowY": "auto",
                                "transition": "margin 0.1s ease-out",  # Simplified and faster transition
                            },
                        ),
                        style={
                            "transition": "margin 0.1s ease-out",  # Simplified and faster transition
                        },
                    ),
                ],
            ),
        ],
    )


def normalize_tab_name_for_url(tab_name):
    """Convert tab name to URL-friendly format: lowercase, no accents, spaces to underscores"""
    import re
    import unicodedata

    if not tab_name:
        return ""

    # Remove accents and normalize unicode
    normalized = unicodedata.normalize("NFD", tab_name)
    no_accents = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    # Convert to lowercase and replace spaces with underscores
    url_safe = no_accents.lower().replace(" ", "_")

    # Remove any remaining non-alphanumeric characters except underscores and hyphens
    url_safe = re.sub(r"[^a-z0-9_-]", "", url_safe)

    # Remove multiple consecutive underscores
    url_safe = re.sub(r"_+", "_", url_safe)

    # Remove leading/trailing underscores
    url_safe = url_safe.strip("_")

    return url_safe or "tab"  # Fallback if name becomes empty


def register_tab_routing_callback(app):
    """Register callback for tab routing with URL parameters"""
    import re

    from dash import Input, Output, State

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        [Input("dashboard-tabs", "value")],
        [State("url", "pathname")],
        prevent_initial_call=True,
        suppress_callback_exceptions=True,  # Suppress exceptions for missing components
    )
    def update_url_on_tab_change(tab_value, current_pathname):
        """Update URL when tab changes - tab values are already normalized names"""
        from dash import no_update

        # Handle None or missing values
        if not tab_value or not current_pathname:
            return no_update

        # Extract dashboard_id from current pathname
        dashboard_match = re.match(r"/dashboard/([a-f0-9]{24})", current_pathname)
        if not dashboard_match:
            return no_update

        dashboard_id = dashboard_match.group(1)

        # Tab value is already a normalized name (since we now use normalized names as tab IDs)
        # So we can use it directly in the URL
        new_pathname = f"/dashboard/{dashboard_id}/{tab_value}"

        return new_pathname
