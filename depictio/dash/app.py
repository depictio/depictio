import os
from dash import html, Input, Output, State, dcc, ctx, ALL
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx

# Depictio imports
from depictio.api.v1.configs.config import settings

# Depictio components imports - design step
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.endpoints.user_endpoints.utils import check_token_validity, purge_expired_tokens
from depictio.dash.modules.card_component.frontend import register_callbacks_card_component
from depictio.dash.modules.interactive_component.frontend import register_callbacks_interactive_component
from depictio.dash.modules.figure_component.frontend import register_callbacks_figure_component
from depictio.dash.modules.jbrowse_component.frontend import register_callbacks_jbrowse_component
from depictio.dash.modules.table_component.frontend import register_callbacks_table_component

# TODO: markdown component


# Depictio layout imports
from depictio.dash.layouts.stepper import register_callbacks_stepper
from depictio.dash.layouts.stepper_parts.part_one import register_callbacks_stepper_part_one
from depictio.dash.layouts.stepper_parts.part_two import register_callbacks_stepper_part_two
from depictio.dash.layouts.stepper_parts.part_three import register_callbacks_stepper_part_three
from depictio.dash.layouts.header import design_header, register_callbacks_header

# from depictio.dash.layouts.draggable_scenarios.add_component import register_callbacks_add_component
from depictio.dash.layouts.draggable import (
    design_draggable,
    register_callbacks_draggable,
)


# Depictio utils imports
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import load_depictio_data

from depictio.api.v1.configs.logging import logger

import os 
os.environ["DEPICTIO_CONTEXT"] = "server"
from depictio_models.utils import get_depictio_context
DEPICTIO_CONTEXT = get_depictio_context()


# Start the app
app = dash.Dash(
    __name__,
    requests_pathname_prefix="/",
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        {
            "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
            "rel": "stylesheet",
        },
    ],
    suppress_callback_exceptions=True,
    title="Depictio",
)

server = app.server  # This is the Flask server instance

# Configure Flask's logger to use your logging settings
server.logger.handlers = logger.handlers
server.logger.setLevel(logger.level)

# Register callbacks for layout
register_callbacks_stepper(app)
register_callbacks_stepper_part_one(app)
register_callbacks_stepper_part_two(app)
register_callbacks_stepper_part_three(app)
register_callbacks_header(app)
register_callbacks_draggable(app)


# Register callbacks for components
register_callbacks_card_component(app)
register_callbacks_interactive_component(app)
register_callbacks_figure_component(app)
register_callbacks_jbrowse_component(app)
register_callbacks_table_component(app)

# Register callbacks for draggable layout
# register_callbacks_add_component(app)

from depictio.dash.layouts.dashboards_management import register_callbacks_dashboards_management
from depictio.dash.layouts.dashboards_management import layout as dashboards_management_layout

register_callbacks_dashboards_management(app)


from depictio.dash.layouts.profile import register_profile_callbacks
from depictio.dash.layouts.profile import layout as profile_layout

register_profile_callbacks(app)

from depictio.dash.layouts.users_management import register_callbacks_users_management
from depictio.dash.layouts.users_management import layout as users_management_layout

register_callbacks_users_management(app)

from depictio.dash.layouts.tokens_management import register_tokens_management_callbacks
from depictio.dash.layouts.tokens_management import layout as tokens_management_layout

register_tokens_management_callbacks(app)


from depictio.dash.layouts.sidebar import register_sidebar_callbacks

register_sidebar_callbacks(app)

from depictio.dash.layouts.save import register_callbacks_save

register_callbacks_save(app)

from depictio.dash.layouts.projects import register_workflows_callbacks

register_workflows_callbacks(app)

from depictio.dash.layouts.admin_management import register_admin_callbacks

register_admin_callbacks(app)


from depictio.dash.layouts.projects import register_projects_callbacks

register_projects_callbacks(app)


def return_create_dashboard_button(email):
    create_button = dmc.Button(
        "+ New Dashboard",
        id={"type": "create-dashboard-button", "index": email},
        n_clicks=0,
        color="orange",
        # variant="gradient",
        # gradient={"from": "black", "to": "grey", "deg": 135},
        style={"fontFamily": "Virgil", "marginRight": "10px"},
        size="xl",
        radius="md",
    )
    return create_button


@app.callback(
    Output("page-content", "children"),
    Output("header", "children"),
    Output("url", "pathname"),
    Output("local-store", "data", allow_duplicate=True),
    [Input("url", "pathname"), Input("local-store", "data")],
    prevent_initial_call=True,
)
def display_page(pathname, local_data):
    trigger = ctx.triggered_id
    logger.debug(f"Trigger: {trigger}")
    logger.debug(f"Local Data: {local_data}")
    logger.debug(f"URL Pathname: {pathname}")

    if not local_data or not local_data.get("logged_in") or not check_token_validity(local_data["access_token"]):
        logger.debug("DISPLAY PAGE - User not logged in")
        logger.debug("DISPLAY PAGE - Redirect to /auth")
        return handle_unauthenticated_user(pathname)

    # Default to /dashboards if pathname is None or "/"
    if pathname is None or pathname == "/" or pathname == "/auth":
        logger.debug("DISPLAY PAGE - Pathname is None or /")
        logger.debug("DISPLAY PAGE - Redirect to /dashboards")
        pathname = "/dashboards"

    logger.debug(f"DISPLAY PAGE - Pathname: {pathname}")
    logger.debug(f"DISPLAY PAGE - Local Data: {local_data}")
    logger.debug(f"DISPLAY PAGE - Access Token: {local_data['access_token']}")
    logger.debug(f"DISPLAY PAGE - Logged In: {local_data['logged_in']}")
    logger.debug(f"DISPLAY PAGE - Check Token Validity: {check_token_validity(local_data['access_token'])}")
    logger.debug(f"DISPLAY PAGE - HANDLE AUTHENTICATED USER")

    # Handle authenticated user logic
    return handle_authenticated_user(pathname, local_data)


def handle_unauthenticated_user(pathname):
    header = create_default_header("Welcome to Depictio")
    logger.info("User not logged in")

    # Redirect any path to the login/auth page
    return create_users_management_layout(), header, "/auth", {"logged_in": False, "access_token": None}


def handle_authenticated_user(pathname, local_data):
    logger.info("User logged in")
    logger.info(f"Local data: {local_data}")

    response = purge_expired_tokens(local_data["access_token"])

    # Map the pathname to the appropriate content and header
    if pathname.startswith("/dashboard/"):
        dashboard_id = pathname.split("/")[-1]
        depictio_dash_data = load_depictio_data(dashboard_id, local_data)
        header = design_header(data=depictio_dash_data, local_store=local_data)
        return create_dashboard_layout(depictio_dash_data=depictio_dash_data, local_data=local_data), header, pathname, local_data

    elif pathname == "/dashboards":
        user = fetch_user_from_token(local_data["access_token"])
        create_button = return_create_dashboard_button(user.email)
        header = create_header_with_button("Dashboards", create_button)
        content = create_dashboards_management_layout()
        return content, header, pathname, local_data

    elif pathname == "/projects":
        header = create_default_header("Projects registered")
        projects = html.Div(id="projects-list")
        return projects, header, pathname, local_data

    elif pathname == "/profile":
        header = create_default_header("Profile")
        return create_profile_layout(), header, pathname, local_data

    elif pathname == "/tokens":
        header = create_default_header("Tokens Management")
        return create_tokens_management_layout(), header, pathname, local_data

    elif pathname == "/admin":
        # Check if user is admin
        user = fetch_user_from_token(local_data["access_token"])
        if not user.is_admin:
            # Fallback to dashboards if user is not admin
            content = create_dashboards_management_layout()
            create_button = return_create_dashboard_button(user.email)
            header = create_header_with_button("Dashboards", create_button)

            return content, header, "/dashboards", local_data

        header = create_admin_header("Admin")
        admin = html.Div(id="admin-management-content")
        return admin, header, pathname, local_data

    elif pathname == "/about":
        header = create_default_header("About")
        # Enhanced About Page
        about_page = dmc.SimpleGrid(
            cols=2,  # Number of columns in the grid
            spacing="xl",  # Space between the cards
            breakpoints=[
                {"maxWidth": 980, "cols": 1, "spacing": "md"},  # Responsive design: 1 column on smaller screens
            ],
            children=[
                # Github Repository Card
                dmc.Card(
                    withBorder=True,  # Adds a border to the card
                    shadow="md",  # Medium shadow for depth
                    # padding="lg",  # Large padding inside the card
                    
                    radius="md",  # Medium border radius for rounded corners
                    style={"textAlign": "center"},  # Center-align text and elements
                    children=[
                        # Icon and Title
                        dmc.Group(
                            position="center",
                            spacing="sm",
                            children=[
                                DashIconify(icon="mdi:github", width=40, color="#333"),
                                dmc.Text(
                                    "GitHub Repository",
                                    size="xl",
                                    weight=700,  # Bold text
                                ),
                            ],
                        ),
                        # Description
                        dmc.Text(
                            "Explore the source code of Depictio on GitHub.",
                            size="md",
                            color="dimmed",
                            mt="sm",  # Margin top for spacing
                        ),
                        # GitHub Button with Link
                        dmc.Anchor(
                            href="https://github.com/depictio/depictio",  # Replace with your GitHub repo URL
                            target="_blank",  # Opens the link in a new tab
                            children=dmc.Button(
                                "GitHub",
                                color="dark",
                                variant="filled",
                                size="md",
                                radius="md",
                                mt="md",  # Margin top for spacing
                                leftIcon=DashIconify(icon="mdi:github-circle", width=20),
                            ),
                        ),
                    ],
                ),
                # Documentation Card
                dmc.Card(
                    withBorder=True,
                    shadow="md",
                    # padding="lg",
                    radius="md",
                    style={"textAlign": "center"},
                    children=[
                        # Icon and Title
                        dmc.Group(
                            position="center",
                            spacing="sm",
                            children=[
                                DashIconify(icon="mdi:file-document", width=40, color="#333"),
                                dmc.Text(
                                    "Documentation",
                                    size="xl",
                                    weight=700,
                                ),
                            ],
                        ),
                        # Description
                        dmc.Text(
                            "Learn how to use Depictio with our comprehensive documentation.",
                            size="md",
                            color="dimmed",
                            mt="sm",
                        ),
                        # Documentation Button with Link
                        dmc.Anchor(
                            href="https://depictio.github.io/depictio-docs/",  # Replace with your documentation URL
                            target="_blank",
                            children=dmc.Button(
                                "Documentation",
                                color="dark",
                                variant="filled",
                                size="md",
                                radius="md",
                                mt="md",
                                leftIcon=DashIconify(icon="mdi:file-document-box", width=20),
                            ),
                        ),
                    ],
                ),
            ],
        )
        return about_page, header, pathname, local_data

    else:
        # Fallback to dashboards if path is unrecognized
        return dash.no_update, dash.no_update, "/dashboards", local_data


def create_default_header(text):
    return dmc.Text(text, weight=600, size="xl", style={"fontSize": "28px", "fontFamily": "Virgil", "padding": "20px 10px"})


def create_admin_header(text):
    """
    Creates an admin header with a title and navigation tabs for Users, Projects, and Dashboards.

    Parameters:
    - text (str): The title text to display in the header.

    Returns:
    - dmc.Header: A Dash Mantine Components Header containing the title and navigation tabs.
    """
    header = dmc.Header(
        height=60,  # Height of the header
        # padding="xs",  # Padding inside the header
        children=[
            dmc.Container(
                fluid=True,  # Make the container fluid (full-width)
                children=[
                    dmc.Group(
                        position="apart",  # Space between the title and tabs
                        align="center",
                        style={"height": "100%"},
                        children=[
                            # Title Section
                            # dmc.Title(
                            #     text,
                            #     order=3,  # Corresponds to h3
                            #     size="h3",
                            #     weight=700,
                            #     color="dark",
                            # ),
                            # Navigation Tabs
                            dmc.Tabs(
                                value="users",  # Default active tab
                                id="admin-tabs",  # ID for the tabs component
                                # onTabChange=lambda value: dash.callback_context.triggered,  # Placeholder for callback
                                children=dmc.TabsList(
                                    [
                                        dmc.Tab(
                                            "Users",
                                            icon=DashIconify(icon="mdi:account-group", width=20, height=20),
                                            value="users",
                                            # value="users",
                                            # component=dcc.Link("Users", href="/admin/users", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.Tab(
                                            "Projects",
                                            icon=DashIconify(icon="mdi:jira", width=20, height=20),
                                            value="projects",
                                            # value="projects",
                                            # component=dcc.Link("Projects", href="/admin/projects", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.Tab(
                                            "Dashboards",
                                            icon=DashIconify(icon="mdi:view-dashboard", width=20, height=20),
                                            value="dashboards",
                                            # value="dashboards",
                                            # component=dcc.Link("Dashboards", href="/admin/dashboards", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.TabsPanel(value="users", id="admin-tabs-users"),
                                        dmc.TabsPanel(value="projects", id="admin-tabs-projects"),
                                        dmc.TabsPanel(value="dashboards", id="admin-tabs-dashboards"),
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
                        ],
                    )
                ],
            )
        ],
        # fixed=True,  # Fix the header to the top
    )
    return header


def create_header_with_button(text, button):
    return dmc.Group(
        [
            create_default_header(text),
            button,
        ],
        position="apart",
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


def create_dashboard_layout(depictio_dash_data=None, local_data=None):
    # Init layout and children if depictio_dash_data is available, else set to empty
    if depictio_dash_data:
        if "stored_layout_data" in depictio_dash_data:
            init_layout = depictio_dash_data["stored_layout_data"]
        else:
            init_layout = {}
        if "stored_children_data" in depictio_dash_data:
            init_children = depictio_dash_data["stored_children_data"]
        else:
            init_children = list()

    logger.info(f"Loaded depictio init_layout: {init_layout}")
    # header, backend_components = design_header(depictio_dash_data)

    # Generate draggable layout
    core = design_draggable(depictio_dash_data, init_layout, init_children, local_data)

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
        style={"display": "flex", "maxWidth": "100%", "flexGrow": "1", "maxHeight": "100%", "flexDirection": "column", "width": "100%", "height": "100%"},
    )


def design_header_ui(data):
    """
    Design the header of the dashboard
    """

    header = dmc.Header(
        id="header",
        height=87,
        children=[
            dbc.Row(
                [
                    dbc.Col(dmc.Title("", order=2, color="black"), width=11, align="center", style={"textAlign": "left"}),
                ],
                style={"height": "100%"},
            ),
        ],
    )

    return header


header = design_header_ui(data=None)


def create_app_layout():
    from depictio.dash.layouts.sidebar import render_sidebar

    navbar = render_sidebar("")

    return dmc.Container(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="local-store", storage_type="local", data={"logged_in": False, "access_token": None}),
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
                size=200,
                overlayOpacity=0.1,
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
                style={"display": "flex", "maxWidth": "100%", "flexGrow": "1", "maxHeight": "100%", "flexDirection": "column", "overflow": "hidden"},
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


app.layout = create_app_layout


if __name__ == "__main__":
    app.run_server(debug=True, host=settings.dash.host, port=settings.dash.port)
