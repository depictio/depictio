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

# dashboards = [
#     {"title": "Genome Analysis", "last_modified": "2023-10-01 14:23:08", "status": "Completed"},
#     {"title": "Protein Folding Study", "last_modified": "2023-09-20 11:15:42", "status": "In Progress"},
#     {"title": "Environmental Data Overview", "last_modified": "2023-10-02 09:02:55", "status": "Completed"},
# ]

# # datasets

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

app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        html.Div(id="hidden-div", style={"display": "none"}),
        html.Div(id="page-content"),
        dcc.Store(id="modal-store", storage_type="session", data={"email": "", "submitted": False}),
        dmc.Modal(
            opened=False,
            id="email-modal",
            centered=True,
            children=[
                dmc.Center(dmc.Title("Welcome to Depictio", order=1, style={"fontFamily": "Virgil"}, align="center")),
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


@app.callback(
    Output("url", "pathname"),
    [Input({"type": "view-dashboard-button", "index": ALL, "value": ALL}, "n_clicks")],
    [State({"type": "view-dashboard-button", "index": ALL, "value": ALL}, "id")],
)
def navigate_to_dashboard(n_clicks, ids):
    print("Navigating to dashboard")
    print(n_clicks)
    print(ids)
    print(ctx.triggered)
    for i in ctx.triggered:
        if i["value"] is not None:
            print(i)
            print(ctx.triggered_id)
            return f"/dashboard/{ctx.triggered_id['index']}"


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


@app.callback(
    Output({"type": "dashboard-list", "index": MATCH}, "children"),
    [Input({"type": "create-dashboard-button", "index": MATCH}, "n_clicks"), Input({"type": "create-dashboard-button", "index": MATCH}, "id")],
)
def create_dashboard(n_clicks, id):
    print(n_clicks, id)
    if n_clicks:
        dashboards.append(
            {
                "title": f"Dashboard {n_clicks}",
                "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "Completed",
                "owner": id["index"],
                "index": n_clicks,
            }
        )
    if dashboards:
        return [
            dmc.Paper(
                dmc.Group(
                    [
                        html.Div(
                            [
                                dmc.Title(d["title"], order=5),
                                dmc.Text(f"Last Modified: {d['last_modified']}"),
                                dmc.Text(f"Status: {d['status']}"),
                                dmc.Text(f"Owner: {d['owner']}"),
                            ],
                            style={"flex": "1"},
                        ),
                        dmc.Button(
                            f"View Dashboard {d['index']}",
                            id={"type": "view-dashboard-button", "value": d["owner"], "index": d["index"]},
                            variant="outline",
                            color="dark",
                            style={"marginRight": 20},
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
            for d in dashboards
        ]


def render_welcome_section(email):
    return dmc.Container(
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
            dmc.Divider(style={"margin": "20px 0"}),
        ]
    )


def render_dashboard_list_section(email):
    return html.Div(id={"type": "dashboard-list", "index": email}, style={"padding": "20px"})


def render_data_collection_item(data_collection):
    return dmc.AccordionItem(
        [
            dmc.AccordionControl(dmc.Title(data_collection["title"], order=5)),
            dmc.AccordionPanel(
                dmc.Paper(
                    dmc.Group(
                        [
                            html.Div(
                                dmc.List(
                                    [
                                        dmc.ListItem(f"Type: {data_collection['type']}"),
                                        dmc.ListItem(f"Description: {data_collection['description']}"),
                                        dmc.ListItem(f"Creation time: {data_collection['creation_time']}"),
                                        dmc.ListItem(f"Last update time: {data_collection['last_update_time']}"),
                                    ]
                                )
                            ),
                            dmc.Button("View Data", variant="outline", color="dark", style={"marginRight": 20}),
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
                ),
            ),
        ],
        value=f"{data_collection['title']}-{data_collection['type']}",
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
                        dmc.Accordion(children=[render_data_collection_item(dc) for dc in workflow["data_collections"]]),
                    ]
                )
            ),
        ],
        value=workflow["title"],
    )


def render_workflows_section(workflows):
    return dmc.Accordion(children=[render_workflow_item(workflow) for workflow in workflows])

from dash import no_update


@app.callback(Output("landing-page", "children"), [Input("url", "pathname"), Input("modal-store", "data")])
def update_landing_page(pathname, data):
    ctx = dash.callback_context

    # Check which input triggered the callback
    if not ctx.triggered:
        return no_update
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
            return no_update

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
        return no_update

    return no_update


if __name__ == "__main__":
    app.run_server(debug=True)
