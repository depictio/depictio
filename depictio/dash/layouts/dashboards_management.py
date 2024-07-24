from datetime import datetime
import json
import dash_bootstrap_components as dbc
import re
import dash
from dash import html, dcc, ctx, MATCH, Input, Output, State, ALL
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.configs.config import logger


layout = html.Div(
    [
        # dcc.Store(id="modal-store", storage_type="local", data={"email": "", "submitted": False}),
        dcc.Store(id="dashboard-modal-store", storage_type="memory", data={"title": ""}),  # Store for new dashboard data
        dmc.Modal(
            opened=False,
            id="dashboard-modal",
            centered=True,
            children=[
                dmc.Center(dmc.Title("Create New Dashboard", order=2)),
                dmc.Center(dmc.Space(h=20)),
                dmc.Center(dmc.TextInput(label="Dashboard Title", style={"width": 300}, placeholder="Enter dashboard title", id="dashboard-title-input")),
                dmc.Center(dmc.Space(h=20)),
                dmc.Center(dmc.Button("Create Dashboard", id="create-dashboard-submit", variant="filled", size="lg", color="black")),
            ],
            closeOnClickOutside=False,
            closeOnEscape=False,
            withCloseButton=True,
        ),
        html.Div(id="landing-page"),  # Initially hidden
    ]
)


def convert_objectid_to_str(data):
    for item in data:
        if "_id" in item:
            item["_id"] = str(item["_id"])
    return data


def load_dashboards_from_db(owner):
    logger.info("Loading dashboards from MongoDB")
    projection = {"_id": 1, "dashboard_id": 1, "version": 1, "title": 1, "owner": 1}

    # Fetch all dashboards corresponding to owner (email address)
    dashboards = list(dashboards_collection.find({"owner": owner}, projection))

    # turn mongodb ObjectId to string
    dashboards = convert_objectid_to_str(dashboards)

    logger.info(f"dashboards: {dashboards}")
    next_index = dashboards_collection.count_documents({}) + 1
    logger.info(f"next_index: {next_index}")
    return {"next_index": next_index, "dashboards": dashboards}


def insert_dashboard(dashboard):
    logger.info(f"Inserting dashboard: {dashboard}")
    dashboards_collection.insert_one(dashboard)


def delete_dashboard(index):
    logger.info(f"Deleting dashboard with index: {index}")
    dashboards_collection.delete_one({"dashboard_id": str(index)})


def load_dashboards_from_file(filepath):
    logger.info("Loading dashboards from file")
    logger.info(f"{filepath}")
    try:
        with open(filepath, "r") as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        return {"next_index": 1, "dashboards": []}  # Return default if no file exists


def save_dashboards_to_file(data, filepath):
    with open(filepath, "w") as file:
        json.dump(data, file, indent=4)


def render_welcome_section(email):
    style = {
        "border": f"1px solid {dmc.theme.DEFAULT_COLORS['indigo'][4]}",
        "textAlign": "center",
    }
    return dmc.Grid(
        children=[
            dmc.Col(
                html.A(
                    dmc.Tooltip(
                        dmc.Avatar(
                            src="https://e7.pngegg.com/pngimages/799/987/png-clipart-computer-icons-avatar-icon-design-avatar-heroes" "-computer-wallpaper-thumbnail.png",
                            size="lg",
                            radius="xl",
                        ),
                        label=email,
                        position="bottom",
                    ),
                    href="/profile",
                    # target="_blank",
                ),
                span="content",
            ),
            dmc.Col(
                [
                    dmc.Title(f"Welcome, {email}!", order=2, align="center"),
                    dmc.Center(
                        dmc.Button(
                            "+ Create New Dashboard",
                            id={"type": "create-dashboard-button", "index": email},
                            n_clicks=0,
                            variant="gradient",
                            gradient={"from": "black", "to": "grey", "deg": 135},
                            style={"margin": "20px 0", "fontFamily": "Virgil"},
                            size="xl",
                        )
                    ),
                    dcc.Store(id={"type": "dashboard-index-store", "index": email}, storage_type="session", data={"next_index": 1}),  # Store for dashboard index management
                    dmc.Divider(style={"margin": "20px 0"}),
                    dmc.Title("Your Dashboards", order=3),
                    dmc.Divider(style={"margin": "20px 0"}),
                ],
                span=10,
            ),
        ],
        gutter="xl",
    )
    # return dmc.Container(
    #     [

    #     ]
    # )


def render_dashboard_list_section(email):
    return html.Div(id={"type": "dashboard-list", "index": email}, style={"padding": "20px"})


def register_callbacks_dashboards_management(app):
    # @app.callback(Output("landing-page", "style"), [Input("modal-store", "data")])
    # def show_landing_page(data):
    #     if data["submitted"]:
    #         return {"display": "block"}  # Show landing page
    #     return {"display": "none"}  # Hide landing page

    def create_dashboards_view(dashboards):
        dashboards_view = [
            dmc.Paper(
                dmc.Group(
                    [
                        html.Div(
                            [
                                dmc.Title(dashboard["title"], order=5),
                                # dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                                dmc.Text(f"Version: {dashboard['version']}"),
                                dmc.Text(f"Owner: {dashboard['owner']}"),
                            ],
                            style={"flex": "1"},
                        ),
                        dcc.Link(
                            dmc.Button(
                                f"View",
                                id={"type": "view-dashboard-button", "index": dashboard["dashboard_id"]},
                                variant="outline",
                                color="dark",
                                # style={"marginRight": 5},
                            ),
                            href=f"/dashboard/{dashboard['dashboard_id']}",
                        ),
                        dmc.Button(
                            "Delete",
                            id={"type": "delete-dashboard-button", "index": dashboard["dashboard_id"]},
                            variant="outline",
                            color="red",
                            # style={"marginRight": 5},
                        ),
                        dmc.Modal(
                            opened=False,
                            id={"type": "delete-confirmation-modal", "index": dashboard["dashboard_id"]},
                            centered=True,
                            # title="Confirm Deletion",
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
                        # dcc.Store(id={"type": "dashboard-delete-index", "index": dashboard["index"]}, storage_type="session", data={})
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

    @app.callback(
        [Output({"type": "dashboard-list", "index": ALL}, "children"), Output({"type": "dashboard-index-store", "index": ALL}, "data")],
        [
            # Input("create-dashboard-submit", "n_clicks"),
            Input({"type": "confirm-delete", "index": ALL}, "n_clicks"),
        ],
        [
            State({"type": "create-dashboard-button", "index": ALL}, "id"),
            State({"type": "dashboard-index-store", "index": ALL}, "data"),
            State({"type": "confirm-delete", "index": ALL}, "index"),
            # State("modal-store", "data"),
            State("session-store", "data"),
            Input("dashboard-modal-store", "data"),
        ],
    )
    def update_dashboards(
        # create_n_clicks_list,
        # submit_n_clicks,
        delete_n_clicks_list,
        create_ids_list,
        store_data_list,
        delete_ids_list,
        user_data,
        modal_data,
    ):
        logger.info("\n")
        logger.info("update_dashboards")
        logger.info(f"CTX triggered: {ctx.triggered}")
        logger.info(f"CTX triggered prop IDs: {ctx.triggered_prop_ids}")
        logger.info(f"CTX triggered ID {ctx.triggered_id}")
        logger.info(f"CTX inputs: {ctx.inputs}")
        logger.info(f"create_ids_list: {create_ids_list}")
        logger.info(f"store_data_list: {store_data_list}")
        logger.info(f"delete_ids_list: {delete_ids_list}")
        logger.info(f"modal_data: {modal_data}")
        logger.info(f"user_data: {user_data}")

        # filepath = "dashboards.json"
        # index_data = load_dashboards_from_file(filepath)
        user_email = user_data["email"]
        index_data = load_dashboards_from_db(user_email)

        dashboards = index_data.get("dashboards", [])
        next_index = index_data.get("next_index", 1)

        logger.info(f"dashboards: {dashboards}")
        logger.info(f"CTX triggered ID {ctx.triggered_id}")

        if not ctx.triggered_id:
            dashboards_view = create_dashboards_view(dashboards)
            logger.info("No trigger")
            logger.info(f"dashboards_view: {dashboards_view}")
            logger.info(f"next_index: {next_index}")
            logger.info(f"{[dashboards_view] * len(store_data_list)}")
            logger.info(f'{[{"next_index": next_index, "dashboards": dashboards}] * len(store_data_list)}')
            return [dashboards_view] * len(store_data_list), [{"next_index": next_index, "dashboards": dashboards}] * len(store_data_list)

        if "type" not in ctx.triggered_id:
            if ctx.triggered_id == "dashboard-modal-store":
                logger.info("Creating new dashboard")
                logger.info(f"modal_data: {modal_data}")
                new_dashboard = {
                    "title": modal_data["title"],
                    "last_saved_ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "version": "V1",
                    "owner": create_ids_list[0]["index"],
                    "dashboard_id": str(next_index),
                }
                dashboards.append(new_dashboard)
                logger.info(f"dashboards: {dashboards}")
                insert_dashboard(new_dashboard)
                next_index += 1
        else:
            if ctx.triggered_id["type"] == "confirm-delete":
                ctx_triggered_dict = ctx.triggered[0]
                import ast

                index_confirm_delete = ast.literal_eval(ctx_triggered_dict["prop_id"].split(".")[0])["index"]
                delete_dashboard(index_confirm_delete)
                dashboards = [dashboard for dashboard in dashboards if dashboard["dashboard_id"] != index_confirm_delete]

        logger.info(f"TEST")
        logger.info(f"dashboards: {dashboards}")

        dashboards = convert_objectid_to_str(dashboards)

        new_index_data = {"next_index": next_index, "dashboards": dashboards}
        # save_dashboards_to_file(new_index_data, filepath)
        dashboards_view = create_dashboards_view(dashboards)

        return [dashboards_view] * len(store_data_list), [new_index_data] * len(store_data_list)

    # New callback to handle the creation of a new dashboard
    @app.callback(
        Output("dashboard-modal-store", "data"),
        [Input("create-dashboard-submit", "n_clicks")],
        [State("dashboard-title-input", "value")],
        prevent_initial_call=True,
    )
    def handle_create_dashboard(n_clicks, title):
        logger.info("handle_create_dashboard")
        logger.info(f"n_clicks: {n_clicks}")
        logger.info(f"title: {title}")
        data = {"title": ""}
        if n_clicks:
            data["title"] = title
        return data

    # New callback to open the create dashboard modal
    @app.callback(
        Output("dashboard-modal", "opened"),
        [Input({"type": "create-dashboard-button", "index": ALL}, "n_clicks"), Input("create-dashboard-submit", "n_clicks")],
        [State("dashboard-modal", "opened")],
        prevent_initial_call=True,
    )
    def open_dashboard_modal(n_clicks_create, n_clicks_submit, opened):
        if any(n_clicks_create):
            return not opened
        elif n_clicks_submit:
            return opened
        return opened

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
            Input("session-store", "data"),
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
        logger.info(f"pathname: {pathname}")
        logger.info(f"data: {data}")
        logger.info("\n")

        def render_landing_page(data):
            return html.Div(
                [
                    render_welcome_section(data["email"]),
                    render_dashboard_list_section(data["email"]),
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
                if pathname.startswith("/dashboard/"):
                    dashboard_id = pathname.split("/")[-1]
                    # Fetch dashboard data based on dashboard_id and return the appropriate layout
                    # return html.Div([f"Displaying Dashboard {dashboard_id}", dbc.Button("Go back", href="/", color="black", external_link=True)])
                    return None
                # Add more conditions for other routes
                # return html.Div("This is the home page")
                return render_landing_page(data)

        # Respond to modal-store data changes
        elif trigger_id == "session-store":
            if data:
                return render_landing_page(data)
            # return html.Div("Please login to view this page.")
            return dash.no_update

        return dash.no_update


# if __name__ == "__main__":
#     app.run_server(debug=True)
