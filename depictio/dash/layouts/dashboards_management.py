from datetime import datetime
import json
from bson import ObjectId
import dash
from dash import html, dcc, ctx, MATCH, Input, Output, State, ALL
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import httpx


from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.dashboards_endpoints.models import DashboardData
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.api.v1.models.base import convert_objectid_to_str


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

    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/dashboards/list", headers={"Authorization": f"Bearer {token}"})

    if response.status_code == 200:
        dashboards = response.json()
        logger.info(f"dashboards: {dashboards}")

        # Extract dashboard IDs and determine the maximum dashboard_id
        dashboard_ids = [int(dashboard["dashboard_id"]) for dashboard in dashboards if "dashboard_id" in dashboard]

        # If there are no dashboards, start with index 1
        if dashboard_ids:
            next_index = max(dashboard_ids) + 1
        else:
            next_index = 1

        logger.info(f"next_index: {next_index}")
        return {"next_index": next_index, "dashboards": dashboards}

    else:
        raise ValueError(f"Failed to load dashboards from the database. Error: {response.text}")


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
                                dmc.Title(dashboard["title"], order=5),
                                # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                dmc.Text(f"Version: {dashboard['version']}"),
                                dmc.Text(f"Owner: {dashboard['permissions']['owners'][0]['email']}"),
                            ],
                            style={"flex": "1"},
                        ),
                        dcc.Link(
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

    def create_homepage_view(dashboards, email):
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

        def create_buttons(dashboard):
            group = dmc.Group(
                [
                    html.Div(
                        [
                            dmc.Title(dashboard["title"], order=5),
                            # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                            dmc.Text(f"Version: {dashboard['version']}"),
                            dmc.Text(f"Owner: {dashboard['permissions']['owners'][0]['email']}"),
                        ],
                        style={"flex": "1"},
                    ),
                    dcc.Link(
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
                ]
                # align="center",
                # position="apart",
                # grow=False,
                # noWrap=False,
                # style={"width": "100%"},
            )
            return group

        def return_thumbnail(email, dashboard):
            import os

            import sys

            # log current working directory
            logger.info(f"Current working directory: {os.getcwd()}")

            thumbnail_path = f"assets/screenshots/{email}_{dashboard['dashboard_id']}.png"
            thumbnail_path_check = f"depictio/dash/{thumbnail_path}"

            logger.info(f"Thumbnail path: {thumbnail_path_check}")
            logger.info(f"Thumbnail exists: {os.path.exists(thumbnail_path_check)}")

            # Check if the thumbnail exists in the assets folder, if not, create a placeholder
            if not os.path.exists(thumbnail_path_check):
                logger.warning(f"Thumbnail not found at path: {thumbnail_path}")
                # thumbnail_path = "assets/screenshots/admin@embl.de_2.png"
                thumbnail_path = "assets/default_thumbnail.png"

                thumbnail = html.Div(
                    [
                        dcc.Link(
                            dmc.CardSection([dmc.Center(dmc.Image(src=thumbnail_path, height=150, width=150, style={"padding": "20px 0px"}))]),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                        ),
                        dmc.Text("No thumbnail available yet", size=18, align="center", color="gray", style={"fontFamily": "Virgil"}),
                    ]
                )
            else:
                thumbnail = dcc.Link(dmc.CardSection(dmc.Image(src=thumbnail_path, height=250, width=450)), href=f"/dashboard/{dashboard['dashboard_id']}")

            return thumbnail

        def loop_over_dashboards(email, dashboards):
            view = list()
            for dashboard in dashboards:
                modal = modal_delete_dashboard(dashboard)
                buttons = create_buttons(dashboard)
                thumbnail = return_thumbnail(email, dashboard)
                view.append(
                    dmc.Card(
                        withBorder=True,
                        shadow="sm",
                        radius="md",
                        style={"width": 500},
                        children=[
                            thumbnail,
                            buttons,
                            modal,
                        ],
                    )
                )
            return view

        dashboards_view = dmc.SimpleGrid(loop_over_dashboards(email, dashboards), cols=3, spacing="xl", verticalSpacing="xl")
        # logger.info(f"dashboards_view: {dashboards_view}")

        return html.Div([dmc.Grid([title], justify="space-between", align="center"), html.Hr(), dashboards_view])

    @app.callback(
        [Output({"type": "dashboard-list", "index": ALL}, "children"), Output({"type": "dashboard-index-store", "index": ALL}, "data")],
        [
            Input({"type": "confirm-delete", "index": ALL}, "n_clicks"),
        ],
        [
            State({"type": "create-dashboard-button", "index": ALL}, "id"),
            State({"type": "dashboard-index-store", "index": ALL}, "data"),
            State({"type": "confirm-delete", "index": ALL}, "index"),
            State("local-store", "data"),
            Input("dashboard-modal-store", "data"),
        ],
    )
    def update_dashboards(delete_n_clicks_list, create_ids_list, store_data_list, delete_ids_list, user_data, modal_data):
        logger.info("\nupdate_dashboards triggered")
        log_context_info()

        current_user = fetch_user_from_token(user_data["access_token"])
        current_userbase = UserBase(**current_user.dict(exclude={"tokens", "is_active", "is_verified", "last_login", "registration_date", "password"}))

        index_data = load_dashboards_from_db(user_data["access_token"])
        dashboards = [DashboardData(**dashboard) for dashboard in index_data.get("dashboards", [])]
        next_index = index_data.get("next_index", 1)

        if not ctx.triggered_id:
            return handle_no_trigger(dashboards, next_index, store_data_list, current_userbase)

        if "type" not in ctx.triggered_id:
            if ctx.triggered_id == "dashboard-modal-store":
                return handle_dashboard_creation(dashboards, next_index, modal_data, user_data, current_userbase, store_data_list)

        if ctx.triggered_id.get("type") == "confirm-delete":
            return handle_dashboard_deletion(dashboards, delete_ids_list, user_data, store_data_list)

        return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def log_context_info():
        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"CTX triggered prop IDs: {ctx.triggered_prop_ids}")
        logger.info(f"CTX triggered ID: {ctx.triggered_id}")
        logger.info(f"CTX inputs: {ctx.inputs}")

    def handle_no_trigger(dashboards, next_index, store_data_list, current_userbase):
        logger.info("No trigger")
        return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_creation(dashboards, next_index, modal_data, user_data, current_userbase, store_data_list):
        if modal_data.get("title"):
            logger.info("Creating new dashboard")
            new_dashboard = DashboardData(
                title=modal_data["title"],
                last_saved_ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                permissions={"owners": [current_userbase], "viewers": []},
                dashboard_id=str(next_index),
            )
            dashboards.append(new_dashboard)
            insert_dashboard(next_index, new_dashboard.mongo(), user_data["access_token"])
            next_index += 1

        return generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase)

    def handle_dashboard_deletion(dashboards, delete_ids_list, user_data, store_data_list):
        ctx_triggered_dict = ctx.triggered[0]
        index_confirm_delete = eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
        delete_dashboard(index_confirm_delete, user_data["access_token"])

        dashboards = [dashboard for dashboard in dashboards if dashboard["dashboard_id"] != index_confirm_delete]
        return generate_dashboard_view_response(dashboards, len(dashboards) + 1, store_data_list)

    def generate_dashboard_view_response(dashboards, next_index, store_data_list, current_userbase):
        dashboards = [convert_objectid_to_str(dashboard.mongo()) for dashboard in dashboards]
        dashboards_view = create_homepage_view(dashboards, current_userbase.email)
        new_index_data = {"next_index": next_index, "dashboards": dashboards}

        logger.info(f"Generated dashboard view: {dashboards_view}")
        return [dashboards_view] * len(store_data_list), [new_index_data] * len(store_data_list)

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
                    dcc.Store(id={"type": "dashboard-index-store", "index": user.email}, storage_type="session", data={"next_index": 1}),  # Store for dashboard index management
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
