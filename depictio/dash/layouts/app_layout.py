# import dash_bootstrap_components as dbc  # Not needed for AppShell layout
import dash_mantine_components as dmc
from dash import dcc, html

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, purge_expired_tokens
from depictio.dash.layouts.dashboards_management import layout as dashboards_management_layout

# from depictio.dash.layouts.draggable_scenarios.add_component import register_callbacks_add_component
from depictio.dash.layouts.draggable import design_draggable

# Depictio utils imports
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import load_depictio_data
from depictio.dash.layouts.header import design_header
from depictio.dash.layouts.layouts_toolbox import create_add_with_input_modal
from depictio.dash.layouts.palette import create_color_palette_page
from depictio.dash.layouts.profile import layout as profile_layout
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


def handle_authenticated_user(pathname, local_data, theme="light"):
    logger.info(f"User logged in: {local_data.get('email', 'Unknown')}")
    # logger.info(f"Local data: {local_data}")

    purge_expired_tokens(local_data["access_token"])

    # Map the pathname to the appropriate content and header
    if pathname.startswith("/dashboard/"):
        dashboard_id = pathname.split("/")[-1]
        depictio_dash_data = load_depictio_data(dashboard_id, local_data, theme=theme)
        # logger.info(f"Depictio dash data: {depictio_dash_data}")
        header_content, backend_components = design_header(
            data=depictio_dash_data, local_store=local_data
        )
        dashboard_id = pathname.split("/")[-1]
        return (
            create_dashboard_layout(
                depictio_dash_data=depictio_dash_data,
                dashboard_id=dashboard_id,
                local_data=local_data,
                backend_components=backend_components,
                theme=theme,
            ),
            header_content,
            pathname,
            local_data,
        )

    elif pathname == "/dashboards":
        user = api_call_fetch_user_from_token(local_data["access_token"])
        # user = fetch_user_from_token(local_data["access_token"])
        # logger.info(f"User: {user}")

        # Check if user is anonymous
        is_anonymous = hasattr(user, "is_anonymous") and user.is_anonymous

        create_button = return_create_dashboard_button(user.email, is_anonymous=is_anonymous)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header, pathname, local_data

    elif pathname.startswith("/project/"):
        header = create_default_header("Project Permissions Manager")
        return projectwise_user_management_layout, header, pathname, local_data

        # return projects, header, pathname, local_data

    elif pathname == "/projects":
        header = create_default_header("Projects registered")
        projects = html.Div(id="projects-list")
        return projects, header, pathname, local_data

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
    # Return content for AppShellHeader - Simple text without sidebar button
    return dmc.Group(
        [
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
        justify="flex-start",  # Align to the left
        align="center",
        style={
            "padding": "0 20px",
            "height": "100%",
        },
    )


def create_admin_header(text):
    """
    Creates an admin header with a title and navigation tabs for Users, Projects, and Dashboards.

    Parameters:
    - text (str): The title text to display in the header.

    Returns:
    - dmc.Header: A Dash Mantine Components Header containing the title and navigation tabs.
    """
    from dash_iconify import DashIconify

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
        h=60,  # Height of the header
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
                                            # value="users",
                                            # component=dcc.Link("Users", href="/admin/users", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.TabsTab(  # type: ignore[unresolved-attribute]
                                            "Groups",
                                            leftSection=DashIconify(
                                                icon="mdi:account-group",
                                                width=20,
                                                height=20,
                                            ),
                                            value="groups",
                                            # value="users",
                                            # component=dcc.Link("Users", href="/admin/users", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.TabsTab(  # type: ignore[unresolved-attribute]
                                            "Projects",
                                            leftSection=DashIconify(
                                                icon="mdi:jira",
                                                width=20,
                                                height=20,
                                            ),
                                            value="projects",
                                            # value="projects",
                                            # component=dcc.Link("Projects", href="/admin/projects", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.TabsTab(  # type: ignore[unresolved-attribute]
                                            "Dashboards",
                                            leftSection=DashIconify(
                                                icon="mdi:view-dashboard",
                                                width=20,
                                                height=20,
                                            ),
                                            value="dashboards",
                                            # value="dashboards",
                                            # component=dcc.Link("Dashboards", href="/admin/dashboards", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.TabsPanel(
                                            children=[],
                                            value="users",
                                            id="admin-tabs-users",
                                        ),
                                        # dmc.TabsPanel(
                                        # children=[],
                                        #     value="groups",
                                        #     id="admin-tabs-groups",
                                        # ),
                                        dmc.TabsPanel(
                                            children=[],
                                            value="projects",
                                            id="admin-tabs-projects",
                                        ),
                                        dmc.TabsPanel(
                                            children=[],
                                            value="dashboards",
                                            id="admin-tabs-dashboards",
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
    # Return content for AppShellHeader - Simple text and button without sidebar button
    return dmc.Group(
        [
            dmc.Text(
                text,
                fw="bold",  # DMC 2.0+ equivalent of weight=600
                size="xl",
                style={
                    "fontSize": "28px",
                    "fontFamily": "Virgil",
                },
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
    core = design_draggable(init_layout, init_children, dashboard_id, local_data)

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
        },
    )


# design_header_ui function removed - now using AppShell structure


def create_app_layout():
    from depictio.dash.layouts.sidebar import render_sidebar_content

    return dmc.MantineProvider(
        id="mantine-provider",
        forceColorScheme="light",  # Default to light, will be updated by callback
        children=[
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
            dcc.Store(
                id="sidebar-collapsed",
                storage_type="memory",
                data=False,  # Start with sidebar expanded
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
            dmc.AppShell(
                id="app-shell",  # Add ID for callback targeting
                navbar={
                    "width": 220,
                    "breakpoint": "sm",
                    "collapsed": {"mobile": True, "desktop": False},
                },
                header={"height": 87},
                layout="alt",  # Use alternative layout where header stops at navbar
                style={
                    "height": "100vh",
                    "overflow": "auto",  # ✅ Allow scrolling
                },
                children=[
                    dmc.AppShellNavbar(  # type: ignore[unresolved-attribute]
                        children=render_sidebar_content(""),
                        id="sidebar",
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
                                "minHeight": "calc(100vh - 87px)",  # Ensure minimum height for short content
                                "overflowY": "auto",  # Allow vertical scrolling
                            },
                        ),
                    ),
                ],
            ),
        ],
    )
