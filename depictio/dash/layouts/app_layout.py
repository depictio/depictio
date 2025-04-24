import dash_bootstrap_components as dbc
import dash_mantine_components as dmc

from depictio.api.v1.configs.custom_logging import logger
import os
from dash import html, Input, Output, State, dcc, ctx, ALL
import dash
from dash_iconify import DashIconify
import httpx


from depictio.dash.api_calls import (
    api_call_fetch_user_from_token,
    purge_expired_tokens,
    check_token_validity,
)


from depictio.dash.layouts.layouts_toolbox import create_add_with_input_modal

from depictio.dash.layouts.profile import layout as profile_layout
from depictio.dash.layouts.users_management import layout as users_management_layout
from depictio.dash.layouts.tokens_management import layout as tokens_management_layout
from depictio.dash.layouts.projectwise_user_management import (
    layout as projectwise_user_management_layout,
)
from depictio.dash.layouts.dashboards_management import (
    layout as dashboards_management_layout,
)
from depictio.dash.layouts.header import design_header

# from depictio.dash.layouts.draggable_scenarios.add_component import register_callbacks_add_component
from depictio.dash.layouts.draggable import (
    design_draggable,
)


# Depictio utils imports
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import (
    load_depictio_data,
)


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
    logger.info("User logged in")
    logger.info(f"Local data: {local_data}")

    response = purge_expired_tokens(local_data["access_token"])

    # Map the pathname to the appropriate content and header
    if pathname.startswith("/dashboard/"):
        dashboard_id = pathname.split("/")[-1]
        depictio_dash_data = load_depictio_data(dashboard_id, local_data)
        logger.info(f"Depictio dash data: {depictio_dash_data}")
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
        logger.info(f"User: {user}")
        create_button = return_create_dashboard_button(user.email)
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

    elif pathname == "/cli_configs":
        header = create_default_header("Depictio-CLI configs Management")
        return create_tokens_management_layout(), header, pathname, local_data

    elif pathname == "/admin":
        # Check if user is admin
        user = api_call_fetch_user_from_token(local_data["access_token"])
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

        # Create a Stack to vertically arrange all elements with proper spacing
        page_content = dmc.Stack(
            spacing="xl",  # Extra large spacing between stack items
            children=[
                # First section: Main cards (GitHub and Documentation)
                dmc.Stack(
                    spacing="md",
                    children=[
                        # Title for Repository & Documentation section
                        dmc.Text(
                            "Resources",
                            size="xl",
                            weight=700,
                            align="center",
                            mb="md",
                        ),
                        # Main cards in a 2-column grid
                        dmc.SimpleGrid(
                            cols=2,  # Number of columns in the grid
                            spacing="xl",  # Space between the cards
                            breakpoints=[
                                {
                                    "maxWidth": 980,
                                    "cols": 1,
                                    "spacing": "md",
                                },  # Responsive design: 1 column on smaller screens
                            ],
                            children=[
                                # Github Repository Card
                                dmc.Card(
                                    withBorder=True,  # Adds a border to the card
                                    shadow="md",  # Medium shadow for depth
                                    radius="md",  # Medium border radius for rounded corners
                                    p="lg",  # Padding inside the card
                                    style={
                                        "textAlign": "center"
                                    },  # Center-align text and elements
                                    children=[
                                        # Icon and Title
                                        dmc.Group(
                                            position="center",
                                            spacing="sm",
                                            children=[
                                                DashIconify(
                                                    icon="mdi:github",
                                                    width=40,
                                                    color="#333",
                                                ),
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
                                                leftIcon=DashIconify(
                                                    icon="mdi:github-circle", width=20
                                                ),
                                            ),
                                        ),
                                    ],
                                ),
                                # Documentation Card
                                dmc.Card(
                                    withBorder=True,
                                    shadow="md",
                                    radius="md",
                                    p="lg",  # Padding inside the card
                                    style={"textAlign": "center"},
                                    children=[
                                        # Icon and Title
                                        dmc.Group(
                                            position="center",
                                            spacing="sm",
                                            children=[
                                                DashIconify(
                                                    icon="mdi:file-document",
                                                    width=40,
                                                    color="#333",
                                                ),
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
                                                leftIcon=DashIconify(
                                                    icon="mdi:file-document-box",
                                                    width=20,
                                                ),
                                            ),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
                # Second section: Funding & Partners
                dmc.Paper(
                    p="xl",  # Extra large padding
                    radius="md",  # Medium border radius
                    withBorder=True,  # Border around the section
                    shadow="xs",  # Light shadow
                    mt="xl",  # Margin top
                    children=[
                        # Title for Funding & Partners section
                        dmc.Text(
                            "Funding",
                            size="xl",
                            weight=700,
                            align="center",
                            mb="xl",  # Margin bottom (increased spacing)
                        ),
                        # Funding & Partners cards in a 3-column grid
                        dmc.SimpleGrid(
                            cols=3,  # Three columns for the three partner cards
                            spacing="xl",  # Space between cards
                            breakpoints=[
                                {"maxWidth": 1200, "cols": 3, "spacing": "md"},
                                {"maxWidth": 980, "cols": 2, "spacing": "md"},
                                {"maxWidth": 755, "cols": 1, "spacing": "md"},
                            ],  # Responsive design
                            children=[
                                # Marie Skłodowska-Curie grant Card
                                dmc.Card(
                                    withBorder=True,
                                    shadow="md",
                                    radius="md",
                                    p="lg",  # Padding inside the card
                                    style={"textAlign": "center"},
                                    children=[
                                        # Logo Image
                                        html.Img(
                                            src=dash.get_asset_url(
                                                "EN_fundedbyEU_VERTICAL_RGB_POS.png"
                                            ),
                                            style={
                                                "height": "100px",
                                                "objectFit": "contain",
                                                "marginBottom": "10px",
                                            },
                                        ),
                                        # Title
                                        dmc.Text(
                                            "Marie Skłodowska-Curie Grant",
                                            size="lg",
                                            weight=700,
                                        ),
                                        # Description
                                        dmc.Text(
                                            "This project has received funding from the European Union's Horizon 2020 research and innovation programme under the Marie Skłodowska-Curie grant agreement No 945405",
                                            size="sm",
                                            color="dimmed",
                                            mt="sm",
                                        ),
                                        # Link Button
                                        dmc.Anchor(
                                            href="https://marie-sklodowska-curie-actions.ec.europa.eu/",
                                            target="_blank",
                                            children=dmc.Button(
                                                "Learn More",
                                                color="dark",
                                                variant="outline",
                                                size="sm",
                                                radius="md",
                                                mt="md",
                                            ),
                                        ),
                                    ],
                                ),
                                # ARISE Programme Card
                                dmc.Card(
                                    withBorder=True,
                                    shadow="md",
                                    radius="md",
                                    p="lg",  # Padding inside the card
                                    style={"textAlign": "center"},
                                    children=[
                                        # Logo Image
                                        html.Img(
                                            src=dash.get_asset_url(
                                                "AriseLogo300dpi.png"
                                            ),
                                            style={
                                                "height": "100px",
                                                "objectFit": "contain",
                                                "marginBottom": "10px",
                                            },
                                        ),
                                        # Title
                                        dmc.Text(
                                            "ARISE Programme",
                                            size="lg",
                                            weight=700,
                                        ),
                                        # Description
                                        dmc.Text(
                                            "ARISE is a postdoctoral research programme for technology developers, hosted at EMBL.",
                                            size="sm",
                                            color="dimmed",
                                            mt="sm",
                                        ),
                                        # Link Button
                                        dmc.Anchor(
                                            href="https://www.embl.org/about/info/arise/",
                                            target="_blank",
                                            children=dmc.Button(
                                                "Learn More",
                                                color="dark",
                                                variant="outline",
                                                size="sm",
                                                radius="md",
                                                mt="md",
                                            ),
                                        ),
                                    ],
                                ),
                                # EMBL Card
                                dmc.Card(
                                    withBorder=True,
                                    shadow="md",
                                    radius="md",
                                    p="lg",  # Padding inside the card
                                    style={"textAlign": "center"},
                                    children=[
                                        # Logo Image
                                        html.Img(
                                            src=dash.get_asset_url(
                                                "EMBL_logo_colour_DIGITAL.png"
                                            ),
                                            style={
                                                "height": "100px",
                                                "objectFit": "contain",
                                                "marginBottom": "10px",
                                            },
                                        ),
                                        # Title
                                        dmc.Text(
                                            "EMBL",
                                            size="lg",
                                            weight=700,
                                        ),
                                        # Description
                                        dmc.Text(
                                            "The European Molecular Biology Laboratory is Europe's flagship laboratory for the life sciences.",
                                            size="sm",
                                            color="dimmed",
                                            mt="sm",
                                        ),
                                        # Link Button
                                        dmc.Anchor(
                                            href="https://www.embl.org/",
                                            target="_blank",
                                            children=dmc.Button(
                                                "Learn More",
                                                color="dark",
                                                variant="outline",
                                                size="sm",
                                                radius="md",
                                                mt="md",
                                            ),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
                # Copyright notice
                dmc.Text(
                    "© 2025 Depictio. All rights reserved.",
                    size="xs",
                    color="dimmed",
                    align="center",
                    mt="xl",
                    mb="xl",  # Add margin bottom to ensure space at page end
                ),
            ],
        )

        # Combine the header and page content in a container with proper padding
        return (
            html.Div(
                [
                    dmc.Container(
                        size="xl",  # Extra large container for content
                        py="xl",  # Padding top and bottom
                        children=[page_content],
                    ),
                ]
            ),
            header,
            pathname,
            local_data,
        )
    else:
        # Fallback to dashboards if path is unrecognized
        return dash.no_update, dash.no_update, "/dashboards", local_data


def create_default_header(text):
    return dmc.Text(
        text,
        weight=600,
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
        leftIcon=DashIconify(icon="mdi:plus-circle", width=16, color="white"),
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
                                            icon=DashIconify(
                                                icon="mdi:account",
                                                width=20,
                                                height=20,
                                            ),
                                            value="users",
                                            # value="users",
                                            # component=dcc.Link("Users", href="/admin/users", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.Tab(
                                            "Groups",
                                            icon=DashIconify(
                                                icon="mdi:account-group",
                                                width=20,
                                                height=20,
                                            ),
                                            value="groups",
                                            # value="users",
                                            # component=dcc.Link("Users", href="/admin/users", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.Tab(
                                            "Projects",
                                            icon=DashIconify(
                                                icon="mdi:jira",
                                                width=20,
                                                height=20,
                                            ),
                                            value="projects",
                                            # value="projects",
                                            # component=dcc.Link("Projects", href="/admin/projects", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.Tab(
                                            "Dashboards",
                                            icon=DashIconify(
                                                icon="mdi:view-dashboard",
                                                width=20,
                                                height=20,
                                            ),
                                            value="dashboards",
                                            # value="dashboards",
                                            # component=dcc.Link("Dashboards", href="/admin/dashboards", style={"textDecoration": "none", "color": "inherit"})
                                        ),
                                        dmc.TabsPanel(
                                            value="users",
                                            id="admin-tabs-users",
                                        ),
                                        # dmc.TabsPanel(
                                        #     value="groups",
                                        #     id="admin-tabs-groups",
                                        # ),
                                        dmc.TabsPanel(
                                            value="projects",
                                            id="admin-tabs-projects",
                                        ),
                                        dmc.TabsPanel(
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


def create_dashboard_layout(depictio_dash_data=dict, dashboard_id=str, local_data=dict):
    # Init layout and children if depictio_dash_data is available, else set to empty
    if depictio_dash_data:
        logger.info(f"Depictio dash data: {depictio_dash_data}")
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

    header = dmc.Header(
        id="header",
        height=87,
        children=[
            dbc.Row(
                [
                    dbc.Col(
                        dmc.Title("", order=2, color="black"),
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

    return dmc.Container(
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
            dcc.Interval(
                id="interval-component", interval=60 * 60 * 1000, n_intervals=0
            ),
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
