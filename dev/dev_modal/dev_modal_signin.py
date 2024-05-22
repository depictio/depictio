from datetime import datetime
import json
import dash_bootstrap_components as dbc
import re
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from dash import MATCH, ALL, ctx


# workflows = [
#     {
#         "title": "nf-core/rnaseq",
#         "creation_time": "2023-01-15 08:30:00",
#         "last_modified": "2023-10-01 14:23:08",
#         "status": "Completed",
#         "data_collections": [
#             {
#                 "type": "Table",
#                 "title": "Gene Expression Levels",
#                 "description": "Differential expression analysis across samples and conditions, presented in a comprehensive table format.",
#                 "creation_time": "2023-01-16 09:00:00",
#                 "last_update_time": "2023-09-30 10:00:00",
#             },
#             {
#                 "type": "Graph",
#                 "title": "Expression Peaks",
#                 "description": "Graphical representation of expression peaks over time.",
#                 "creation_time": "2023-01-16 10:00:00",
#                 "last_update_time": "2023-09-30 11:00:00",
#             },
#         ],
#     },
#     {
#         "title": "galaxy/folding@home",
#         "creation_time": "2023-02-01 07:20:00",
#         "last_modified": "2023-09-20 11:15:42",
#         "status": "In Progress",
#         "data_collections": [
#             {
#                 "type": "JBrowse",
#                 "title": "Protein Interaction Maps",
#                 "description": "Interactive JBrowse map showcasing protein interactions.",
#                 "creation_time": "2023-02-02 08:00:00",
#                 "last_update_time": "2023-09-19 12:00:00",
#             },
#             {
#                 "type": "Graph",
#                 "title": "Folding Rate Analysis",
#                 "description": "Analysis of protein folding rates over time displayed graphically.",
#                 "creation_time": "2023-02-02 09:30:00",
#                 "last_update_time": "2023-09-19 13:00:00",
#             },
#         ],
#     },
#     {
#         "title": "nf-core/ampliseq",
#         "creation_time": "2023-03-05 06:45:00",
#         "last_modified": "2023-10-02 09:02:55",
#         "status": "Completed",
#         "data_collections": [
#             {
#                 "type": "Geomap",
#                 "title": "Sample Collection Locations",
#                 "description": "Geographical map of sample collection sites for environmental data.",
#                 "creation_time": "2023-03-06 10:15:00",
#                 "last_update_time": "2023-10-01 14:00:00",
#             },
#             {
#                 "type": "Table",
#                 "title": "Environmental Metrics",
#                 "description": "Detailed metrics and environmental data collated in tabular form.",
#                 "creation_time": "2023-03-06 11:20:00",
#                 "last_update_time": "2023-10-01 15:30:00",
#             },
#         ],
#     },
# ]


dashboards = []
workflows = []

app = dash.Dash(__name__)
depictio_logo = html.Img(src=dash.get_asset_url("logo.png"), height=40, style={"margin-left": "0px"})

app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        dcc.Location(id="redirect-url", refresh=True),  # Add this component for redirection
        dcc.Store(id="modal-store", storage_type="session", data={"email": "", "submitted": False}),
        dmc.Modal(
            opened=False,
            id="email-modal",
            centered=True,
            children=[
                dmc.Center(depictio_logo),  # Center the logo
                # dmc.Center(dmc.Title("Welcome to Depictio", order=1, style={"fontFamily": "Virgil"}, align="center")),
                dmc.Center(dmc.Text("Please enter your email to login:", style={"paddingTop": 15})),
                dmc.Center(dmc.Space(h=20)),
                dmc.Center(
                    dmc.TextInput(
                        label="Your Email", style={"width": 300}, placeholder="Please enter your email", icon=DashIconify(icon="ic:round-alternate-email"), id="email-input"
                    )
                ),
                dmc.Center(dmc.Space(h=20)),
                dmc.Center(dmc.Button("Login", id="submit-button", variant="filled", disabled=True, size="lg", color="black")),
            ],
            # Prevent closing the modal by clicking outside or pressing ESC
            closeOnClickOutside=False,
            closeOnEscape=False,
            withCloseButton=False,
        ),
        html.Div(id="landing-page", style={"display": "none"}),  # Initially hidden
    ]
)


def render_workflow_item(workflow):
    return dmc.AccordionItem(
        [
            dmc.AccordionControl(dmc.Title(workflow["title"], order=5)),
            dmc.AccordionPanel(
                dmc.Container(
                    [
                        dmc.Text(f"Last Modified: {workflow['last_modified']}"),
                        dmc.Text(f"Status: {workflow['status']}"),
                        dmc.Divider(style={"margin": "20px 0"}),
                        dmc.Title("Data Collections", order=4),
                        dmc.Accordion(
                            children=[
                                dmc.AccordionItem(
                                    [
                                        dmc.AccordionControl(dmc.Title(dc["title"], order=5)),
                                        dmc.AccordionPanel(
                                            dmc.Paper(
                                                dmc.Group(
                                                    [
                                                        html.Div(
                                                            dmc.List(
                                                                [
                                                                    dmc.ListItem(f"Type: {dc['type']}"),
                                                                    dmc.ListItem(f"Description: {dc['description']}"),
                                                                    dmc.ListItem(f"Creation time: {dc['creation_time']}"),
                                                                    dmc.ListItem(f"Last update time: {dc['last_update_time']}"),
                                                                ]
                                                            )
                                                        ),
                                                        dmc.Button("View Data", variant="outline", color="dark", style={"marginRight": 20}),
                                                    ],
                                                    # align="center",
                                                    position="apart",
                                                    grow=False,
                                                    noWrap=False,
                                                    style={"width": "100%"},
                                                ),
                                                shadow="xs",
                                                p="md",
                                                style={"marginBottom": 20},
                                            ),
                                        ),
                                    ],
                                    value=f"{workflow['title']}-{dc['type']}",
                                )
                                for dc in workflow["data_collections"]
                            ],
                        ),
                    ]
                )
            ),
        ],
        value=workflow["title"],  # Ensure each AccordionItem has a unique value
    )


def render_workflows_section(workflows, data):
    return dmc.Accordion(children=[render_workflow_item(workflow) for workflow in workflows])


@app.callback([Output("submit-button", "disabled"), Output("email-input", "error")], [Input("email-input", "value")])
def update_submit_button(email):
    if email:
        valid = re.match(r"^[a-zA-Z0-9_.+-]+@embl\.de$", email)
        return not valid, not valid
    return True, False  # Initially disabled with no error


@app.callback(Output("modal-store", "data"), [Input("submit-button", "n_clicks")], [State("email-input", "value"), State("modal-store", "data")])
def store_email(submit_clicks, email, data):
    print(submit_clicks, email, data)
    if submit_clicks:
        data["email"] = email
        data["submitted"] = True
    return data


@app.callback(Output("email-modal", "opened"), [Input("modal-store", "data")])
def manage_modal(data):
    print(data)
    return not data["submitted"]  # Keep modal open until submitted


@app.callback(Output("landing-page", "style"), [Input("modal-store", "data")])
def show_landing_page(data):
    if data["submitted"]:
        return {"display": "block"}  # Show landing page
    return {"display": "none"}  # Hide landing page



def render_modal_delete(index):
    modal_view = dmc.Modal(
        opened=False,
        id={"type": "delete-confirmation-modal", "index": index},
        centered=True,
        # title="Confirm Deletion",
        children=[
            dmc.Title("Are you sure you want to delete this dashboard?", order=3, color="black", style={"marginBottom": 20}),
            dmc.Button("Delete", id="confirm-delete", color="red", style={"marginRight": 10}),
            dmc.Button("Cancel", id="cancel-delete", color="grey"),
        ],
    )
    return modal_view

# Callback to open the deletion confirmation modal and store the dashboard index
@app.callback(
    Output({"type": "delete-confirmation-modal", "index": MATCH}, "opened"),
    [Input({"type": "delete-dashboard-button", "index": MATCH}, "n_clicks")],
    [State({"type": "delete-dashboard-button", "index": MATCH}, "id")],
    prevent_initial_call=True
)
def open_delete_modal(n_clicks, button_id):
    if n_clicks:
        return True
    return False


def create_dashboards_view(dashboards):
    dashboards_view = [
        dmc.Paper(
            dmc.Group(
                [
                    html.Div(
                        [
                            dmc.Title(dashboard["title"], order=5),
                            dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                            dmc.Text(f"Status: {dashboard['status']}"),
                            dmc.Text(f"Owner: {dashboard['owner']}"),
                        ],
                        style={"flex": "1"},
                    ),
                    dmc.Button(
                        f"View Dashboard {dashboard['index']}",
                        id={"type": "view-dashboard-button", "index": dashboard["index"]},
                        variant="outline",
                        color="dark",
                        style={"marginRight": 20},
                    ),
                    dmc.Button(
                        "Delete",
                        id={"type": "delete-dashboard-button", "value": dashboard["owner"], "index": dashboard["index"]},
                        variant="outline",
                        color="red",
                        style={"marginRight": 20},
                    ),
                    dmc.Modal(
                        opened=False,
                        id={"type": "delete-confirmation-modal", "index": dashboard["index"]},
                        centered=True,
                        # title="Confirm Deletion",
                        children=[
                            dmc.Title("Are you sure you want to delete this dashboard?", order=3, color="black", style={"marginBottom": 20}),
                            dmc.Button("Delete", id={"type": "confirm-delete", "index": dashboard["index"], "value": dashboard["owner"]}, color="red", style={"marginRight": 10}),
                            dmc.Button("Cancel", id={"type": "cancel-delete", "index": dashboard["index"], "value": dashboard["owner"]}, color="grey"),
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
    return dashboards_view


@app.callback(
    [Output({"type": "dashboard-list", "index": MATCH}, "children"), Output({"type": "dashboard-index-store", "index": MATCH}, "data")],
    [
        Input({"type": "create-dashboard-button", "index": MATCH}, "n_clicks"),
        State({"type": "create-dashboard-button", "index": MATCH}, "id"),
        State({"type": "dashboard-index-store", "index": MATCH}, "data"),
        # Input({"type": "dashboard-index-store", "index": MATCH}, "data"),
    ],
    # prevent_initial_call=True
)
def create_dashboard(n_clicks, id, index_data):
    # if not n_clicks:
    #     return dash.no_update, dash.no_update

    # Assuming index_data also stores a list of dashboards
    dashboards = index_data.get("dashboards", [])

    if n_clicks:
        next_index = index_data.get("next_index", 1)  # Default to 1 if not found

        # Creating a new dashboard entry
        new_dashboard = {
            "title": f"Dashboard {next_index}",
            "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Completed",
            "owner": id["index"],
            "index": next_index,
        }

        dashboards.append(new_dashboard)

        # Updating the store data to include the new list of dashboards and the incremented index
        new_index_data = {"next_index": next_index + 1, "dashboards": dashboards}
    else:
        new_index_data = index_data

    # Creating views for each dashboard
    dashboards_view = [
        dmc.Paper(
            dmc.Group(
                [
                    html.Div(
                        [
                            dmc.Title(dashboard["title"], order=5),
                            dmc.Text(f"Last Modified: {dashboard['last_modified']}"),
                            dmc.Text(f"Status: {dashboard['status']}"),
                            dmc.Text(f"Owner: {dashboard['owner']}"),
                        ],
                        style={"flex": "1"},
                    ),
                    dmc.Button(
                        f"View Dashboard {dashboard['index']}",
                        id={"type": "view-dashboard-button", "value": dashboard["owner"], "index": dashboard["index"]},
                        variant="outline",
                        color="dark",
                        style={"marginRight": 20},
                    ),
                    dmc.Button("Delete", id={"type": "delete-dashboard-button", "index": dashboard["index"]}, variant="outline", color="red", style={"marginRight": 20}),
                    render_modal_delete(dashboard["index"]),
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

    return dashboards_view, new_index_data


def render_welcome_section(email):
    return dmc.Container(
        [
            dmc.Center(depictio_logo),  # Center the logo
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
        ]
    )


def render_dashboard_list_section(email):
    return html.Div(id={"type": "dashboard-list", "index": email}, style={"padding": "20px"})


@app.callback(
    Output("redirect-url", "href"),
    [Input({"type": "view-dashboard-button", "index": ALL}, "n_clicks")],
    [State({"type": "view-dashboard-button", "index": ALL}, "id")],
    prevent_initial_call=True,
)
def redirect_to_dashboard(n_clicks, ids):
    if not any(n_clicks):
        raise dash.exceptions.PreventUpdate

    # Find the index of the clicked button
    clicked_index = next((i for i, v in enumerate(n_clicks) if v), None)
    if clicked_index is not None:
        dashboard_id = ids[clicked_index]["index"]
        return f"http://localhost:5080"
    raise dash.exceptions.PreventUpdate


@app.callback(
    Output("landing-page", "children"),
    [
        Input("url", "pathname"),
        Input("modal-store", "data"),
        Input({"type": "view-dashboard-button", "index": ALL}, "n_clicks"),
    ],
)
def update_landing_page(
    pathname,
    data,
    view_dashboard_clicks,
):
    print("\n")
    print("update_landing_page")
    print(f"CTX triggered: {ctx.triggered}")
    print(f"CTX triggered prop IDs: {ctx.triggered_prop_ids}")
    print(f"CTX triggered ID {ctx.triggered_id}")
    print(f"CTX inputs: {ctx.inputs}")
    print("\n")

    # Check which input triggered the callback
    if not ctx.triggered:
        return dash.no_update
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Respond to URL changes
    if trigger_id == "url":
        if pathname:
            if pathname.startswith("/dashboard/"):
                dashboard_id = pathname.split("/")[-1]
                # Fetch dashboard data based on dashboard_id and return the appropriate layout
                return html.Div([f"Displaying Dashboard {dashboard_id}", dbc.Button("Go back", href="/", color="black", external_link=True)])
            # Add more conditions for other routes
            # return html.Div("This is the home page")
            return dash.no_update

    # Respond to modal-store data changes
    elif trigger_id == "modal-store":
        if data and data.get("submitted"):
            return html.Div(
                [
                    render_welcome_section(data["email"]),
                    dmc.Title("Your Dashboards", order=3),
                    render_dashboard_list_section(data["email"]),
                    dmc.Title("Your Workflows & Data Collections", order=3),
                    render_workflows_section(workflows),
                ]
            )
        # return html.Div("Please login to view this page.")
        return dash.no_update

    return dash.no_update


if __name__ == "__main__":
    app.run_server(debug=True)
