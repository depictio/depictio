import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

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
        style={"fontFamily": "Virgil", "marginRight": "10px"},
        size="xl",
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


def handle_authenticated_user(pathname, local_data):
    logger.info(f"User logged in: {local_data.get('email', 'Unknown')}")
    # logger.info(f"Local data: {local_data}")

    purge_expired_tokens(local_data["access_token"])

    # Map the pathname to the appropriate content and header
    if pathname.startswith("/dashboard/"):
        dashboard_id = pathname.split("/")[-1]
        depictio_dash_data = load_depictio_data(dashboard_id, local_data)
        # logger.info(f"Depictio dash data: {depictio_dash_data}")
        header = design_header(data=depictio_dash_data, local_store=local_data)
        dashboard_id = pathname.split("/")[-1]
        return (
            create_dashboard_layout(
                depictio_dash_data=depictio_dash_data,
                dashboard_id=dashboard_id,
                local_data=local_data,
            ),
            header,
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
        return dash.no_update, dash.no_update, "/dashboards", local_data


def create_default_header(text):
    return dmc.Text(
        text,
        fw="bold",
        size="xl",
        style={"fontSize": "28px", "fontFamily": "Virgil", "padding": "20px 10px"},
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

    add_group_modal, add_group_modal_id = create_add_with_input_modal(
        id_prefix="group",
        input_field=text_group_input,
        title="Add Group",
        message="Please complete the input field to add a new group.",
        confirm_button_text="Add",
        cancel_button_text="Cancel",
        icon="mdi:plus-circle",
        opened=False,
    )

    # DMC 2.0+ AppShell system for proper navigation layout
    header = dmc.AppShellHeader(
        h=60,
        children=[
            dmc.Group(
                justify="space-between",
                align="center",
                h="100%",
                px="md",
                children=[
                    dmc.Title(
                        text,
                        order=3,
                        size="h3",
                        fw="bold",
                        c="dark",
                    ),
                    # DMC 2.0+ navigation using ActionIcon and Group for header actions
                    dmc.Group(
                        gap="sm",
                        children=[
                            add_group_button,
                            add_group_modal,
                        ],
                    ),
                ],
            )
        ],
    )
    return header


def create_header_with_button(text, button):
    return dmc.Group(
        [
            create_default_header(text),
            button,
        ],
        justify="space-between",
        align="center",
        style={"backgroundColor": "#fff"},
    )


def create_dashboards_management_layout():
    return dashboards_management_layout


def create_users_management_layout():
    return users_management_layout


def create_profile_layout():
    return profile_layout


def create_tokens_management_layout():
    return tokens_management_layout


def create_dashboard_layout(depictio_dash_data=None, dashboard_id: str = "", local_data=None):
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

    return dmc.Container(
        [
            html.Div(
                [
                    # Backend components & header
                    # backend_components,
                    # header,
                    # Draggable layout
                    core,
                ],
            ),
            html.Div(id="test-input"),
            html.Div(id="test-output", style={"display": "none"}),
            html.Div(id="test-output-visible"),
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


def design_header_ui(data):
    """
    Design the header of the dashboard
    """

    # TODO: DMC 2.0+ - Header component no longer exists, need to replace with alternative
    header = dmc.Container(
        id="header",
        style={"height": "87px", "backgroundColor": "#f8f9fa", "padding": "10px"},
        children=[
            dbc.Row(
                [
                    dbc.Col(
                        dmc.Title("", order=2, c="gray"),
                        width=11,
                        align="center",
                        style={"textAlign": "left"},
                    ),
                ],
                style={"height": "100%"},
            ),
        ],
    )

    return header


def create_app_layout():
    from depictio.dash.layouts.sidebar import render_sidebar

    navbar = render_sidebar("")
    header = design_header_ui(data=None)

    return dmc.MantineProvider(
        dmc.Container(
            [
                dcc.Location(id="url", refresh=False),
                dcc.Store(
                    id="local-store",
                    storage_type="local",
                    # storage_type="memory",
                    data={"logged_in": False, "access_token": None},
                ),
                dcc.Store(
                    id="local-store-components-metadata",
                    data={},
                    storage_type="local",
                ),
                dcc.Store(id="current-edit-parent-index", storage_type="memory"),
                dcc.Interval(id="interval-component", interval=60 * 60 * 1000, n_intervals=0),
                navbar,
                dmc.Drawer(
                    title="",
                    id="drawer-simple",
                    padding="md",
                    zIndex=10000,
                    size="xl",
                    # overlayOpacity=0.1,
                    overlayProps={"overlayOpacity": 0.1},
                    children=[],
                ),
                dmc.Container(
                    [
                        header,
                        dmc.Container(
                            [
                                html.Div(
                                    id="page-content",
                                    # full width and height
                                    style={"width": "100%", "height": "100%"},
                                )
                            ],
                            id="page-container",
                            p=0,
                            fluid=True,
                            style={
                                "width": "100%",
                                "height": "100%",
                                "overflowY": "auto",  # Allow vertical scrolling
                                "flexGrow": "1",
                            },
                        ),
                    ],
                    fluid=True,
                    size="100%",
                    p=0,
                    m=0,
                    style={
                        "display": "flex",
                        "maxWidth": "100%",
                        "flexGrow": "1",
                        "maxHeight": "100%",
                        "flexDirection": "column",
                        "overflow": "hidden",
                    },
                    id="content-container",
                ),
            ],
            # size="100%",
            fluid=True,
            p=0,
            m=0,
            style={
                "display": "flex",
                "maxWidth": "100%",
                "maxHeight": "100%",
                "flexGrow": "1",
                "position": "absolute",
                "top": 0,
                "left": 0,
                "width": "100%",
                "height": "100%",
                "overflow": "hidden",  # Hide overflow content
            },
            id="overall-container",
        )
    )
