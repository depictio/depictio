from datetime import datetime
import json
import os
import shutil
from bson import ObjectId
import dash
from dash import html, dcc, ctx, MATCH, Input, Output, State, ALL
import dash_mantine_components as dmc
import dash_bootstrap_components as dbc
from dash_iconify import DashIconify
import httpx


from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.configs.logging import logger
# from depictio.api.v1.endpoints.dashboards_endpoints.models import DashboardData
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
# from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio_models.models.base import convert_objectid_to_str
from depictio.dash.utils import generate_unique_index

from depictio_models.models.dashboards import DashboardData
from depictio_models.models.users import UserBase


layout = html.Div(
    [
        # dcc.Store(id="modal-store", storage_type="local", data={"email": "", "submitted": False}),
        dcc.Store(id="dashboard-modal-store", storage_type="session", data={"title": ""}),  # Store for new dashboard data
        dcc.Store(id="init-create-dashboard-button", storage_type="memory", data=False),
        dmc.Modal(
            opened=False,
            id="dashboard-modal",
            centered=True,
            children=[
                dmc.Stack(
                    [
                        dmc.Center(dmc.Title("Create New Dashboard", order=2)),
                        dmc.Center(dmc.Space(h=10)),
                        dmc.Center(dmc.TextInput(label="Dashboard Title", style={"width": 300}, placeholder="Enter dashboard title", id="dashboard-title-input")),
                        dmc.Center(dmc.Space(h=10)),
                        dmc.Center(dmc.Badge("Dashboard title must be unique", color="red", size=20), style={"display": "none"}, id="unique-title-warning"),
                        # dmc.Center(dmc.Space(h=20)),
                        dmc.Center(dmc.Button("Create Dashboard", id="create-dashboard-submit", variant="filled", size="lg", color="black")),
                    ],
                    align="center",
                ),
            ],
            closeOnClickOutside=False,
            closeOnEscape=False,
            withCloseButton=True,
            zIndex=10000,
            overlayOpacity=0.3,  # Set lower opacity for the overlay
            overlayColor="black",  # Set overlay color (e.g., black)
        ),
        html.Div(id="landing-page"),  # Initially hidden
    ]
)


def load_dashboards_from_db(token):
    logger.info(f"Loading dashboards from the database with token {token}")
    if not token:
        raise ValueError("Token is required to load dashboards from the database.")

    try:
        response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/list", headers={"Authorization": f"Bearer {token}"})

        if response.status_code == 200:
            dashboards = response.json()
            logger.info(f"dashboards: {dashboards}")

            # # Extract dashboard IDs and determine the maximum dashboard_id
            # dashboard_ids = [int(dashboard["dashboard_id"]) for dashboard in dashboards if "dashboard_id" in dashboard]

            # # If there are no dashboards, start with index 1
            # if dashboard_ids:
            #     next_index = max(dashboard_ids) + 1
            # else:
            #     next_index = 1

            # logger.info(f"next_index: {next_index}")
            return {"dashboards": dashboards}

        else:
            raise ValueError(f"Failed to load dashboards from the database. Error: {response.text}")

    except Exception as e:
        logger.error(f"Error loading dashboards from the database: {e}")
        # return {"next_index": 1, "dashboards": []}
        return {"dashboards": []}


def insert_dashboard(dashboard_id, dashboard_data, token):
    if not token:
        raise ValueError("Token is required to insert a dashboard into the database.")

    if not dashboard_data:
        raise ValueError("Dashboard data is required to insert a dashboard into the database.")

    if not dashboard_id:
        raise ValueError("Dashboard ID is required to insert a dashboard into the database.")

    dashboard_data = convert_objectid_to_str(dashboard_data)

    response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}", headers={"Authorization": f"Bearer {token}"}, json=dashboard_data)

    if response.status_code == 200:
        logger.info(f"Successfully inserted dashboard: {dashboard_data}")

    else:
        raise ValueError(f"Failed to insert dashboard into the database. Error: {response.text}")


def delete_dashboard(dashboard_id, token):
    response = httpx.delete(f"{API_BASE_URL}/depictio/api/v1/dashboards/delete/{dashboard_id}", headers={"Authorization": f"Bearer {token}"})

    if response.status_code == 200:
        logger.info(f"Successfully deleted dashboard with ID: {dashboard_id}")

    else:
        raise ValueError(f"Failed to delete dashboard from the database. Error: {response.text}")


def edit_dashboard_name(new_name, dashboard_id, dashboards, token):
    logger.info(f"Editing dashboard name for dashboard ID: {dashboard_id}")
    logger.info(f"dashboards: {dashboards}")
    logger.info(f"token: {token}")

    updated_dashboards = list()

    # Iterate over the dashboards to find the dashboard with the matching ID and update the name
    for dashboard in dashboards:
        if dashboard.dashboard_id == dashboard_id:
            logger.info(f"Found dashboard to edit: {dashboard}")
            dashboard.title = new_name
        updated_dashboards.append(dashboard)

    response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/dashboards/edit_name/{dashboard_id}", headers={"Authorization": f"Bearer {token}"}, json={"new_name": new_name})

    if response.status_code == 200:
        logger.info(f"Successfully edited dashboard name: {dashboard}")

    else:
        raise ValueError(f"Failed to edit dashboard name in the database. Error: {response.text}")

    logger.info(f"updated_dashboards: {updated_dashboards}")

    return updated_dashboards


def render_welcome_section(email):
    style = {
        "border": f"1px solid {dmc.theme.DEFAULT_COLORS['indigo'][4]}",
        "textAlign": "center",
    }
    return dmc.Grid(
        children=[
            dmc.Col(
                dcc.Link(
                    dmc.Tooltip(
                        dmc.Avatar(
                            src=f"https://ui-avatars.com/api/?format=svg&name={email}&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16",
                            size="lg",
                            radius="xl",
                        ),
                        label=email,
                        position="bottom",
                    ),
                    href="/profile",
                    # tar ="_blank",
                ),
                span="content",
            ),
            dmc.Col(
                [
                    dmc.Title(f"Welcome, {email}!", order=2, align="center"),
                    dmc.Center(
                        dmc.Button(
                            "+ New Dashboard",
                            id={"type": "create-dashboard-button", "index": email},
                            n_clicks=0,
                            variant="gradient",
                            gradient={"from": "black", "to": "grey", "deg": 135},
                            style={"margin": "20px 0", "fontFamily": "Virgil"},
                            size="xl",
                        ),
                    ),
                    dmc.Divider(style={"margin": "20px 0"}),
                    dmc.Title("Your Dashboards", order=3),
                    dmc.Divider(style={"margin": "20px 0"}),
                ],
                span=10,
            ),
        ],
        gutter="xl",
    )


def render_dashboard_list_section(email):
    return html.Div(id={"type": "dashboard-list", "index": email}, style={"padding": "20px"})


def register_callbacks_dashboards_management(app):
    def create_dashboards_view(dashboards):
        logger.info(f"dashboards: {dashboards}")

        # dashboards = [convert_objectid_to_str(dashboard.mongo()) for dashboard in dashboards]

        dashboards_view = [
            dmc.Paper(
                dmc.Group(
                    [
                        html.Div(
                            [
                                dmc.Center(dmc.Title(dashboard["title"], order=5)),
                                # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                dmc.Text(f"Version: {dashboard['version']}"),
                                dmc.Text(f"Owner: {dashboard['permissions']['owners'][0]['email']}"),
                            ],
                            style={"flex": "1"},
                        ),
                        html.A(
                            dmc.Button(
                                f"View",
                                id={"type": "view-dashboard-button", "index": dashboard["dashboard_id"]},
                                variant="outline",
                                color="dark",
                            ),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                        ),
                        dmc.Button(
                            "Delete",
                            id={"type": "delete-dashboard-button", "index": dashboard["dashboard_id"]},
                            variant="outline",
                            color="red",
                        ),
                        dmc.Modal(
                            opened=False,
                            id={"type": "delete-confirmation-modal", "index": dashboard["dashboard_id"]},
                            centered=True,
                            children=[
                                dmc.Title("Are you sure you want to delete this dashboard?", order=3, color="black", style={"marginBottom": 20}),
                                dmc.Button(
                                    "Delete",
                                    id={
                                        "type": "confirm-delete",
                                        "index": dashboard["dashboard_id"],
                                    },
                                    color="red",
                                    style={"marginRight": 10},
                                ),
                                dmc.Button(
                                    "Cancel",
                                    id={
                                        "type": "cancel-delete",
                                        "index": dashboard["dashboard_id"],
                                    },
                                    color="grey",
                                ),
                            ],
                        ),
                    ],
                    align="center",
                    position="apart",
                    grow=False,
                    noWrap=False,
                    style={"width": "100%"},
                ),
                shadow="xs",
                p="md",
                style={"marginBottom": 20},
            )
            for dashboard in dashboards
        ]
        logger.info(f"dashboards_view: {dashboards_view}")
        return dashboards_view

    def create_homepage_view(dashboards, user_id):
        logger.info(f"dashboards: {dashboards}")

        # dashboards = [convert_objectid_to_str(dashboard.mongo()) for dashboard in dashboards]

        title = dmc.Title("Recently viewed:", order=3)

        def modal_delete_dashboard(dashboard):
            modal = dmc.Modal(
                opened=False,
                id={"type": "delete-confirmation-modal", "index": dashboard["dashboard_id"]},
                centered=True,
                children=[
                    dmc.Title("Are you sure you want to delete this dashboard?", order=3, color="black", style={"marginBottom": 20}),
                    dmc.Button(
                        "Delete",
                        id={
                            "type": "confirm-delete",
                            "index": dashboard["dashboard_id"],
                        },
                        color="red",
                        style={"marginRight": 10},
                    ),
                    dmc.Button(
                        "Cancel",
                        id={
                            "type": "cancel-delete",
                            "index": dashboard["dashboard_id"],
                        },
                        color="grey",
                    ),
                ],
            )
            return modal

        def modal_edit_name_dashboard(dashboard):
            modal = dmc.Modal(
                id={"type": "edit-password-modal", "index": dashboard["dashboard_id"]},
                opened=False,
                centered=True,
                withCloseButton=True,
                closeOnEscape=True,
                closeOnClickOutside=True,
                size="lg",
                title="Edit Dashboard name",
                style={"fontSize": 16},
                children=[
                    dmc.TextInput(placeholder="New name", label="New name", id={"type": "new-name-dashboard", "index": dashboard["dashboard_id"]}),
                    dmc.Text(id={"type": "message-edit-name-dashboard", "index": dashboard["dashboard_id"]}, color="red", style={"display": "none"}),
                    dmc.Center(dmc.Button("Save", color="blue", id={"type": "save-edit-name-dashboard", "index": dashboard["dashboard_id"]}, style={"margin": "10px 0"})),
                ],
            )
            return modal

        def create_dashboad_view_header(dashboard, user_id):
            public = True if "*" in [e for e in dashboard["permissions"]["viewers"]] else False

            if str(user_id) in [str(owner["_id"]) for owner in dashboard["permissions"]["owners"]]:
                color_badge_ownership = "blue"
            else:
                color_badge_ownership = "gray"
            badge_icon = "material-symbols:public" if public else "material-symbols:lock"

            badge_owner = dmc.Badge(
                f"Owner: {dashboard['permissions']['owners'][0]['email']}", color=color_badge_ownership, leftSection=DashIconify(icon="mdi:account", width=16, color="grey")
            )
            badge_status = dmc.Badge("Public" if public else "Private", color="green" if public else "violet", leftSection=DashIconify(icon=badge_icon, width=16, color="grey"))

            group = html.Div(
                [
                    dmc.Group(
                        [
                            html.Div(
                                [
                                    dmc.Title(dashboard["title"], order=5),
                                    # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                    # dmc.Text(f"Version: {dashboard['version']}"),
                                    # dmc.Text(f"Owner: {dashboard['permissions']['owners'][0]['email']}"),
                                ],
                                style={"flex": "1"},
                            )
                        ]
                    ),
                    dmc.Space(h=10),
                    dmc.Group(
                        [badge_owner, badge_status],
                    ),
                    dmc.Space(h=10),
                ]
            )
            return group

        def create_buttons(dashboard, user_id):
            disabled = True if str(user_id) not in [str(owner["_id"]) for owner in dashboard["permissions"]["owners"]] else False
            public = True if "*" in [e for e in dashboard["permissions"]["viewers"]] else False
            privacy_button_title = "Make private" if public else "Make public"
            color_privacy_button = "violet" if public else "green"

            group = html.Div(
                [
                    dmc.Group(
                        [
                            html.A(
                                dmc.Button(
                                    f"View",
                                    id={"type": "view-dashboard-button", "index": dashboard["dashboard_id"]},
                                    variant="outline",
                                    color="dark",
                                    size="xs",
                                    # style={"fontFamily": "Virgil"},
                                    # leftIcon=DashIconify(icon="mdi:eye", width=12, color="black"),
                                    style={"padding": "2px 6px", "fontSize": "12px"},
                                ),
                                href=f"/dashboard/{dashboard['dashboard_id']}",
                            ),
                            dmc.Button(
                                "Edit name",
                                id={"type": "edit-dashboard-button", "index": dashboard["dashboard_id"]},
                                variant="outline",
                                color="blue",
                                # style={"fontFamily": "Virgil"},
                                disabled=disabled,
                                size="xs",
                                style={"padding": "2px 6px", "fontSize": "12px"},
                            ),
                            dmc.Button(
                                "Duplicate",
                                id={"type": "duplicate-dashboard-button", "index": dashboard["dashboard_id"]},
                                variant="outline",
                                color="gray",
                                # style={"fontFamily": "Virgil"},
                                size="xs",
                                style={"padding": "2px 6px", "fontSize": "12px"},
                            ),
                            dmc.Button(
                                "Delete",
                                id={"type": "delete-dashboard-button", "index": dashboard["dashboard_id"]},
                                variant="outline",
                                color="red",
                                # style={"fontFamily": "Virgil"},
                                disabled=disabled,
                                size="xs",
                                style={"padding": "2px 6px", "fontSize": "12px"},
                            ),
                            dmc.Button(
                                privacy_button_title,
                                id={"type": "make-public-dashboard-button", "index": dashboard["dashboard_id"]},
                                variant="outline",
                                color=color_privacy_button,
                                # style={"fontFamily": "Virgil"},
                                disabled=disabled,
                                size="xs",
                                style={"padding": "2px 6px", "fontSize": "12px"},
                            ),
                        ]
                        # align="center",
                        # position="apart",
                        # grow=False,
                        # noWrap=False,
                        # style={"width": "100%"},
                    ),
                ]
            )
            return group

        def return_thumbnail(user_id, dashboard):
            import os

            import sys

            # log current working directory
            logger.info(f"Current working directory: {os.getcwd()}")

            logger.info(f"sys.path: {sys.path}")
            logger.info(f"dashboard: {dashboard}")

            # Define the output folder where screenshots are saved
            output_folder = "/app/depictio/dash/static/screenshots"  # Directly set to the desired path
            # output_folder = os.path.join(os.path.dirname(__file__), 'static', 'screenshots')

            # Define the filename and paths
            filename = f"{dashboard['_id']}.png"
            # Filesystem path to check existence
            thumbnail_fs_path = os.path.join(output_folder, filename)
            # URL path for the Image src
            thumbnail_url = f"/static/screenshots/{filename}"

            # thumbnail_path = f"assets/screenshots/{user_id}_{dashboard['_id']}.png"
            # thumbnail_path_check = f"depictio/dash/{thumbnail_path}"

            logger.info(f"Thumbnail filesystem path: {thumbnail_fs_path}")
            logger.info(f"Thumbnail URL path: {thumbnail_url}")
            logger.info(f"Thumbnail exists: {os.path.exists(thumbnail_fs_path)}")

            # Check if the thumbnail exists in the static/screenshots folder
            if not os.path.exists(thumbnail_fs_path):
                logger.warning(f"Thumbnail not found at path: {thumbnail_fs_path}")
                # Use the default thumbnail from static/
                default_thumbnail_url = "/assets/default_thumbnail.png"

                thumbnail = html.Div(
                    [
                        html.A(
                            dmc.CardSection([dmc.Center(dmc.Image(src=default_thumbnail_url, height=220, width=220, style={"padding": "0px 0px"}))]),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                        ),
                        dmc.Text("No thumbnail available yet", size=18, align="center", color="gray", style={"fontFamily": "Virgil"}),
                    ]
                )
            else:
                thumbnail = html.A(dmc.CardSection(dmc.Image(src=thumbnail_url, height=250, width=400)), href=f"/dashboard/{dashboard['dashboard_id']}")

            return thumbnail

        def loop_over_dashboards(user_id, dashboards):
            view = list()
            for dashboard in dashboards:
                delete_modal = modal_delete_dashboard(dashboard)
                edit_name_modal = modal_edit_name_dashboard(dashboard)
                buttons = create_buttons(dashboard, user_id)
                dashboard_header = create_dashboad_view_header(dashboard, user_id)

                buttons = dmc.Accordion(
                    [
                        dmc.AccordionItem(
                            value="actions",
                            children=[
                                dmc.AccordionControl(
                                    dmc.Group(
                                        [
                                            # Reduce padding and margins for a smaller look
                                            DashIconify(icon="mdi:interaction-double-tap", width=20, color="gray"),
                                            dmc.Text(
                                                "Dashboard Actions",
                                                style={
                                                    "fontSize": "12px",  # Smaller font size
                                                    "padding": "2px 4px",  # Reduce padding
                                                },
                                            ),
                                        ],
                                        style={
                                            "gap": "4px",  # Smaller gap between components
                                        },
                                    ),
                                    style={
                                        "padding": "4px",  # Smaller control padding
                                        "fontSize": "12px",  # Smaller font for control
                                    },
                                ),
                                dmc.AccordionPanel(
                                    buttons,
                                    style={
                                        "padding": "4px",  # Smaller padding for the panel
                                        "fontSize": "12px",  # Smaller font for the panel
                                    },
                                ),
                            ],
                        ),
                    ],
                    style={
                        "width": "100%",  # Adjust width as needed
                        "padding": "4px",  # Smaller padding for the accordion
                        "fontSize": "12px",  # Reduce overall font size
                    },
                    # variant="separated",
                    chevronPosition="left",
                )

                thumbnail = return_thumbnail(user_id, dashboard)
                view.append(
                    dmc.Card(
                        withBorder=True,
                        shadow="sm",
                        radius="md",
                        # style={"width": 480},
                        # Remove fixed width to allow flexibility
                        style={
                            "width": "100%",
                            "height": "100%",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                        children=[thumbnail, dashboard_header, buttons, delete_modal, edit_name_modal],
                    )
                )
            return view

        private_dashboards_section_header = dmc.Title([DashIconify(icon="mdi:lock", width=18, color="#7d56f2"), " Private Dashboards"], order=3)
        private_dashboards = [d for d in dashboards if "*" not in d["permissions"]["viewers"]]
        private_dashboards_ids = [d["dashboard_id"] for d in private_dashboards]
        private_dashboards_view = dmc.SimpleGrid(
            loop_over_dashboards(user_id, private_dashboards),
            cols=3,  # Default number of columns
            spacing="xl",
            verticalSpacing="xl",
            breakpoints=[
                {"maxWidth": 1600, "cols": 3},  # Large screens
                {"maxWidth": 1200, "cols": 2},  # Medium screens
                {"maxWidth": 768, "cols": 1},  # Small screens
            ],
            style={"width": "100%"},
        )
        public_dashboards_section_header = dmc.Title([DashIconify(icon="material-symbols:public", width=18, color="#54ca74"), " Public Dashboards"], order=3)

        public_dashboards = [d for d in dashboards if "*" in d["permissions"]["viewers"] and d["dashboard_id"] not in private_dashboards_ids]
        public_dashboards_view = dmc.SimpleGrid(
            loop_over_dashboards(user_id, public_dashboards),
            cols=3,  # Default number of columns
            spacing="xl",
            verticalSpacing="xl",
            breakpoints=[
                {"maxWidth": 1600, "cols": 3},  # Large screens
                {"maxWidth": 1200, "cols": 2},  # Medium screens
                {"maxWidth": 768, "cols": 1},  # Small screens
            ],
            style={"width": "100%"},
        )

        # Optional: Add padding to the parent div for better spacing on smaller screens
        return html.Div(
            [
                # dmc.Grid([title], justify="space-between", align="center", style={"width": "100%", "padding": "20px 0"}), html.Hr(),
                # private_dashboards_view
                private_dashboards_section_header,
                dmc.Space(h=10),
                private_dashboards_view,
                dmc.Space(h=20),
                html.Hr(),
                public_dashboards_section_header,
                dmc.Space(h=10),
                public_dashboards_view,
            ],
            style={"width": "100%", "padding": "0 20px"},
        )

    @app.callback(
        Output({"type": "dashboard-list", "index": ALL}, "children"),
        # [Output({"type": "dashboard-list", "index": ALL}, "children"), Output({"type": "dashboard-index-store", "index": ALL}, "data")],
        [
            Input({"type": "confirm-delete", "index": ALL}, "n_clicks"),
            Input({"type": "save-edit-name-dashboard", "index": ALL}, "n_clicks"),
            Input({"type": "duplicate-dashboard-button", "index": ALL}, "n_clicks"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "n_clicks"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "children"),
            Input({"type": "make-public-dashboard-button", "index": ALL}, "id"),
        ],
        [
            State({"type": "create-dashboard-button", "index": ALL}, "id"),
            # State({"type": "dashboard-index-store", "index": ALL}, "data"),
            State({"type": "confirm-delete", "index": ALL}, "index"),
            State({"type": "new-name-dashboard", "index": ALL}, "value"),
            State({"type": "new-name-dashboard", "index": ALL}, "id"),
            State("local-store", "data"),
            Input("dashboard-modal-store", "data"),
        ],
    )
    def update_dashboards(
        delete_n_clicks_list,
        edit_n_clicks_list,
        duplicate_n_clicks_list,
        make_public_n_clicks_list,
        make_public_children_list,
        make_public_id_list,
        # create_ids_list,
        store_data_list,
        delete_ids_list,
        new_name_list_values,
        new_name_list_ids,
        user_data,
        modal_data,
    ):
        logger.info("\nupdate_dashboards triggered")
        log_context_info()

        current_user = fetch_user_from_token(user_data["access_token"])
        current_userbase = UserBase(**current_user.dict(exclude={"tokens", "is_active", "is_verified", "last_login", "registration_date", "password"}))

        index_data = load_dashboards_from_db(user_data["access_token"])
        dashboards = [DashboardData.from_mongo(dashboard) for dashboard in index_data.get("dashboards", [])]
        logger.info(f"dashboards: {dashboards}")
        # next_index = index_data.get("next_index", 1)

        if not ctx.triggered_id:
            return handle_no_trigger(dashboards, store_data_list, current_userbase)
            # return handle_no_trigger(dashboards, next_index, store_data_list, current_userbase)

        if "type" not in ctx.triggered_id:
            if ctx.triggered_id == "dashboard-modal-store":
                return handle_dashboard_creation(dashboards, modal_data, user_data, current_userbase, store_data_list)
                # return handle_dashboard_creation(dashboards, next_index, modal_data, user_data, current_userbase, store_data_list)

        if ctx.triggered_id.get("type") == "confirm-delete":
            return handle_dashboard_deletion(dashboards, delete_ids_list, user_data, store_data_list, current_userbase)

        if ctx.triggered_id.get("type") == "duplicate-dashboard-button":
            return handle_dashboard_duplication(dashboards, user_data, store_data_list, current_userbase)

        if ctx.triggered_id.get("type") == "make-public-dashboard-button":
            logger.info("Make public dashboard button clicked")
            logger.info(f"make_public_children_list: {make_public_children_list}")
            logger.info(f"make_public_n_clicks_list: {make_public_n_clicks_list}")
            logger.info(f"make_public_id_list: {make_public_id_list}")
            public_current_status = [child for child, id in zip(make_public_children_list, make_public_id_list) if id["index"] == ctx.triggered_id["index"]][0]
            logger.info(f"public_current_status: {public_current_status}")
            public_current_status = False if public_current_status == "Make public" else True
            logger.info(f"public_current_status: {public_current_status}")

            return handle_dashboard_make_public(dashboards, user_data, store_data_list, current_userbase, public_current_status)

        if ctx.triggered_id.get("type") == "save-edit-name-dashboard":
            logger.info("Edit dashboard button clicked")
            # Extract the new name from the input field
            index = ctx.triggered_id["index"]

            # Iterate over the new_name_list to find the new name corresponding to the index
            new_name = [value for value, id in zip(new_name_list_values, new_name_list_ids) if id["index"] == index][0]

            return handle_dashboard_edit(new_name, dashboards, user_data, store_data_list, current_userbase)

        return generate_dashboard_view_response(dashboards, store_data_list, current_userbase)
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def log_context_info():
        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"CTX triggered prop IDs: {ctx.triggered_prop_ids}")
        logger.info(f"CTX triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX inputs: {ctx.inputs}")

    def handle_no_trigger(dashboards, store_data_list, current_userbase):
        logger.info("No trigger")
        return generate_dashboard_view_response(dashboards, store_data_list, current_userbase)
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_creation(dashboards, modal_data, user_data, current_userbase, store_data_list):
        if modal_data.get("title"):
            logger.info("Creating new dashboard")

            dashboard_id = str(ObjectId())
            # dashboard_id = generate_unique_index()

            new_dashboard = DashboardData(
                id=str(dashboard_id),
                title=modal_data["title"],
                last_saved_ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                permissions={"owners": [current_userbase], "viewers": []},
                dashboard_id=str(dashboard_id),
            )
            dashboards.append(new_dashboard)
            insert_dashboard(dashboard_id, new_dashboard.mongo(), user_data["access_token"])
            # next_index += 1

        return generate_dashboard_view_response(dashboards, store_data_list, current_userbase)
        # return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_deletion(dashboards, delete_ids_list, user_data, store_data_list, current_userbase):
        ctx_triggered_dict = ctx.triggered[0]
        index_confirm_delete = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        delete_dashboard(index_confirm_delete, user_data["access_token"])

        dashboards = [dashboard for dashboard in dashboards if dashboard.dashboard_id != index_confirm_delete]
        return generate_dashboard_view_response(dashboards, store_data_list, current_userbase)
        # return generate_dashboard_view_response(dashboards, len(dashboards) + 1, store_data_list, current_userbase)

    def handle_dashboard_make_public(dashboards, user_data, store_data_list, current_userbase, public_current_status):
        logger.info("Make public dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        logger.info(f"ctx_triggered_dict: {ctx_triggered_dict}")
        index_make_public = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        logger.info(f"index_make_public: {index_make_public}")
        logger.info(f"User data: {user_data}")
        logger.info(f"current_userbase: {current_userbase}")
        logger.info(f"public_current_status: {public_current_status}")
        logger.info(f"NOT public_current_status: {not public_current_status}")

        updated_dashboards = list()
        for dashboard in dashboards:
            if dashboard.dashboard_id == index_make_public:
                logger.info(f"Found dashboard to update status: {dashboard}")
                response = httpx.post(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/toggle_public_status/{index_make_public}",
                    headers={"Authorization": f"Bearer {user_data['access_token']}"},
                    json={"public": not public_current_status},
                )
                dashboard.permissions = response.json()["permissions"]
                updated_dashboards.append(dashboard)

                if response.status_code == 200:
                    logger.info(f"Successfully made dashboard '{not public_current_status}': {dashboard}")

                else:
                    raise ValueError(f"Failed to make dashboard public. Error: {response.text}")
            else:
                updated_dashboards.append(dashboard)

        return generate_dashboard_view_response(updated_dashboards, store_data_list, current_userbase)

    def handle_dashboard_duplication(dashboards, user_data, store_data_list, current_userbase):
        logger.info("Duplicate dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        index_duplicate = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        logger.info(f"index_duplicate: {index_duplicate}")
        logger.info(f"User data: {user_data}")
        logger.info(f"current_userbase: {current_userbase}")

        updated_dashboards = list()
        for dashboard in dashboards:
            updated_dashboards.append(dashboard)
            if dashboard.dashboard_id == index_duplicate:
                logger.info(f"Found dashboard to duplicate: {dashboard}")

                # Load full dashboard data from the database
                dashboard_data_response = httpx.get(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{index_duplicate}", headers={"Authorization": f"Bearer {user_data['access_token']}"}
                )
                if dashboard_data_response.status_code != 200:
                    raise ValueError(f"Failed to load dashboard data from the database. Error: {dashboard_data_response.text}")
                else:
                    dashboard_data_response = dashboard_data_response.json()

                # deep copy the dashboard object
                new_dashboard = DashboardData.from_mongo(dashboard_data_response)
                new_dashboard.id = ObjectId()
                new_dashboard.title = f"{dashboard.title} (copy)"
                new_dashboard.dashboard_id = str(new_dashboard.id)
                new_dashboard.permissions.owners = [current_userbase]
                new_dashboard.permissions.viewers = []
                # new_dashboard.dashboard_id = generate_unique_index()
                # new_dashboard.dashboard_id = str(len(dashboards) + 1)
                updated_dashboards.append(new_dashboard)
                insert_dashboard(new_dashboard.dashboard_id, new_dashboard.mongo(), user_data["access_token"])

                # Copy thumbnail
                thumbnail_filename = f"{str(dashboard.id)}.png"
                # thumbnail_filename = f"{str(current_userbase.id)}_{str(dashboard.id)}.png"
                thumbnail_fs_path = f"/app/depictio/dash/static/screenshots/{thumbnail_filename}"

                if not os.path.exists(thumbnail_fs_path):
                    logger.warning(f"Thumbnail not found at path: {thumbnail_fs_path}")
                else:
                    # Copy the thumbnail to the new dashboard ID
                    new_thumbnail_fs_path = f"/app/depictio/dash/static/screenshots/{str(new_dashboard.id)}.png"
                    shutil.copy(thumbnail_fs_path, new_thumbnail_fs_path)

        return generate_dashboard_view_response(updated_dashboards, store_data_list, current_userbase)
        # return generate_dashboard_view_response(updated_dashboards, len(updated_dashboards) + 1, store_data_list, current_userbase)

    def handle_dashboard_edit(new_name, dashboards, user_data, store_data_list, current_userbase):
        logger.info("Edit dashboard button clicked")
        ctx_triggered_dict = ctx.triggered[0]
        index_edit = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        logger.info(f"index_edit: {index_edit}")
        updated_dashboards = edit_dashboard_name(new_name, index_edit, dashboards, user_data["access_token"])

        return generate_dashboard_view_response(updated_dashboards, store_data_list, current_userbase)
        # return generate_dashboard_view_response(updated_dashboards, len(updated_dashboards) + 1, store_data_list, current_userbase)

    def generate_dashboard_view_response(dashboards, store_data_list, current_userbase):
        dashboards = [convert_objectid_to_str(dashboard.mongo()) for dashboard in dashboards]
        logger.info(f"dashboards: {dashboards}")
        dashboards_view = create_homepage_view(dashboards, current_userbase.id)
        # new_index_data = {"next_index": next_index, "dashboards": dashboards}
        new_index_data = {"dashboards": dashboards}

        logger.info(f"Generated dashboard view: {dashboards_view}")
        return [dashboards_view] * len(store_data_list)
        # return [dashboards_view] * len(store_data_list), [new_index_data] * len(store_data_list)

    @app.callback(
        Output({"type": "edit-password-modal", "index": MATCH}, "opened"),
        [Input({"type": "edit-dashboard-button", "index": MATCH}, "n_clicks")],
        [State({"type": "edit-password-modal", "index": MATCH}, "opened")],
        prevent_initial_call=True,
    )
    def open_edit_password_modal(n_clicks, opened):
        return not opened

    @app.callback(
        [Output("dashboard-modal-store", "data"), Output("dashboard-modal", "opened"), Output("init-create-dashboard-button", "data"), Output("unique-title-warning", "style")],
        [Input({"type": "create-dashboard-button", "index": ALL}, "n_clicks"), Input("create-dashboard-submit", "n_clicks")],
        [State("dashboard-title-input", "value"), State("dashboard-modal", "opened"), State("local-store", "data"), State("init-create-dashboard-button", "data")],
        prevent_initial_call=True,
    )
    def handle_create_dashboard_and_toggle_modal(n_clicks_create, n_clicks_submit, title, opened, user_data, init_create_dashboard_button):
        logger.info("handle_create_dashboard_and_toggle_modal")
        logger.info(f"n_clicks_create: {n_clicks_create}")
        logger.info(f"n_clicks_submit: {n_clicks_submit}")
        logger.info(f"title: {title}")
        logger.info(f"opened: {opened}")
        logger.info(f"user_data: {user_data}")
        logger.info(f"init_create_dashboard_button: {init_create_dashboard_button}")
        data = {"title": ""}

        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"CTX triggered prop IDs: {ctx.triggered_prop_ids}")
        logger.info(f"CTX triggered ID {ctx.triggered_id}")

        if not init_create_dashboard_button:
            logger.info("Init create dashboard button")
            return data, opened, True, dash.no_update

        if "type" in ctx.triggered_id:
            triggered_id = ctx.triggered_id["type"]
        else:
            triggered_id = ctx.triggered_id

        if triggered_id == "create-dashboard-button":
            logger.info("Create button clicked")
            # Toggle the modal when the create button is clicked
            return dash.no_update, True, dash.no_update, dash.no_update

        if triggered_id == "create-dashboard-submit":
            logger.info("Submit button clicked")
            dashboards = load_dashboards_from_db(user_data["access_token"])["dashboards"]
            logger.info(f"dashboards: {dashboards}")
            logger.info(f"Len dashboards: {len(dashboards)}")
            if len(dashboards) > 0:
                existing_titles = [dashboard["title"] for dashboard in dashboards]

                logger.info(f"existing_titles: {existing_titles}")
                logger.info(f"title: {title}")
                if title in existing_titles:
                    logger.warning(f"Dashboard with title '{title}' already exists.")
                    return dash.no_update, True, dash.no_update, {"display": "block"}

            # Set the title and keep the modal open (or toggle it based on your preference)
            data["title"] = title
            return data, False, False, {"display": "none"}

        logger.info("No relevant clicks")
        # Return default values if no relevant clicks happened
        return data, opened, False, dash.no_update

    # # New callback to handle the creation of a new dashboard
    # @app.callback(
    #     Output("dashboard-modal-store", "data"),
    #     [Input("create-dashboard-submit", "n_clicks")],
    #     [State("dashboard-title-input", "value")],
    #     prevent_initial_call=True,
    # )
    # def handle_create_dashboard(n_clicks, title):
    #     logger.info("handle_create_dashboard")
    #     logger.info(f"n_clicks: {n_clicks}")
    #     logger.info(f"title: {title}")
    #     data = {"title": ""}
    #     if n_clicks:
    #         data["title"] = title
    #     return data

    # # New callback to open the create dashboard modal
    # @app.callback(
    #     Output("dashboard-modal", "opened"),
    #     [Input({"type": "create-dashboard-button", "index": ALL}, "n_clicks"), Input("create-dashboard-submit", "n_clicks")],
    #     [State("dashboard-modal", "opened")],
    #     prevent_initial_call=True,
    # )
    # def open_dashboard_modal(n_clicks_create, n_clicks_submit, opened):
    #     if any(n_clicks_create):
    #         return not opened
    #     elif n_clicks_submit:
    #         return opened
    #     return opened

    @app.callback(
        Output({"type": "delete-confirmation-modal", "index": MATCH}, "opened"),
        [
            Input({"type": "delete-dashboard-button", "index": MATCH}, "n_clicks"),
            Input({"type": "confirm-delete", "index": MATCH}, "n_clicks"),
            Input({"type": "cancel-delete", "index": MATCH}, "n_clicks"),
        ],
        [State({"type": "delete-confirmation-modal", "index": MATCH}, "opened")],
        prevent_initial_call=True,
    )
    def open_delete_modal(n1, n2, n3, opened):
        return not opened

    @app.callback(
        Output("landing-page", "children"),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
        ],
    )
    def update_landing_page(
        pathname,
        data,
    ):
        logger.info("\n")
        logger.info("update_landing_page")
        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"CTX triggered prop IDs: {ctx.triggered_prop_ids}")
        logger.info(f"CTX triggered ID {ctx.triggered_id}")
        logger.info(f"CTX inputs: {ctx.inputs}")
        logger.info(f"URL pathname: {pathname}")
        logger.info(f"data: {data}")
        logger.info("\n")

        user = fetch_user_from_token(data["access_token"])

        def render_landing_page(data):
            return html.Div(
                [
                    # dcc.Store(id={"type": "dashboard-index-store", "index": user.email}, storage_type="session", data={"next_index": 1}),  # Store for dashboard index management
                    # render_welcome_section(user.email),
                    render_dashboard_list_section(user.email),
                ]
            )

        # Check which input triggered the callback
        if not ctx.triggered:
            # return dash.no_update
            raise dash.exceptions.PreventUpdate
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"trigger_id: {trigger_id}")

        # Respond to URL changes
        if trigger_id == "url":
            if pathname:
                logger.info(f"trigger_id: {trigger_id}")
                logger.info(f"URL pathname: {pathname}")
                if pathname.startswith("/dashboard/"):
                    dashboard_id = pathname.split("/")[-1]
                    # Fetch dashboard data based on dashboard_id and return the appropriate layout
                    # return html.Div([f"Displaying Dashboard {dashboard_id}", dbc.Button("Go back", href="/", color="black", external_link=True)])
                    return dash.no_update
                elif pathname == "/dashboards":
                    return render_landing_page(data)

        # Respond to modal-store data changes
        elif trigger_id == "local-store":
            if data:
                return render_landing_page(data)
            # return html.Div("Please login to view this page.")
            return dash.no_update

        return dash.no_update
