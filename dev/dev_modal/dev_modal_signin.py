import dash_bootstrap_components as dbc
import re
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import dash_mantine_components as dmc
from dash_iconify import DashIconify

dashboards = [
    {"title": "Genome Analysis", "last_modified": "2023-10-01 14:23:08", "status": "Completed"},
    {"title": "Protein Folding Study", "last_modified": "2023-09-20 11:15:42", "status": "In Progress"},
    {"title": "Environmental Data Overview", "last_modified": "2023-10-02 09:02:55", "status": "Completed"},
]

# datasets

workflows = [
    {
        "title": "nf-core/rnaseq",
        "creation_time": "2023-01-15 08:30:00",
        "last_modified": "2023-10-01 14:23:08",
        "status": "Completed",
        "data_collections": [
            {
                "type": "Table",
                "title": "Gene Expression Levels",
                "description": "Differential expression analysis across samples and conditions, presented in a comprehensive table format.",
                "creation_time": "2023-01-16 09:00:00",
                "last_update_time": "2023-09-30 10:00:00",
            },
            {
                "type": "Graph",
                "title": "Expression Peaks",
                "description": "Graphical representation of expression peaks over time.",
                "creation_time": "2023-01-16 10:00:00",
                "last_update_time": "2023-09-30 11:00:00",
            },
        ],
    },
    {
        "title": "galaxy/folding@home",
        "creation_time": "2023-02-01 07:20:00",
        "last_modified": "2023-09-20 11:15:42",
        "status": "In Progress",
        "data_collections": [
            {
                "type": "JBrowse",
                "title": "Protein Interaction Maps",
                "description": "Interactive JBrowse map showcasing protein interactions.",
                "creation_time": "2023-02-02 08:00:00",
                "last_update_time": "2023-09-19 12:00:00",
            },
            {
                "type": "Graph",
                "title": "Folding Rate Analysis",
                "description": "Analysis of protein folding rates over time displayed graphically.",
                "creation_time": "2023-02-02 09:30:00",
                "last_update_time": "2023-09-19 13:00:00",
            },
        ],
    },
    {
        "title": "nf-core/ampliseq",
        "creation_time": "2023-03-05 06:45:00",
        "last_modified": "2023-10-02 09:02:55",
        "status": "Completed",
        "data_collections": [
            {
                "type": "Geomap",
                "title": "Sample Collection Locations",
                "description": "Geographical map of sample collection sites for environmental data.",
                "creation_time": "2023-03-06 10:15:00",
                "last_update_time": "2023-10-01 14:00:00",
            },
            {
                "type": "Table",
                "title": "Environmental Metrics",
                "description": "Detailed metrics and environmental data collated in tabular form.",
                "creation_time": "2023-03-06 11:20:00",
                "last_update_time": "2023-10-01 15:30:00",
            },
        ],
    },
]


app = dash.Dash(__name__)

app.layout = html.Div(
    [
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


@app.callback(Output("landing-page", "children"), [Input("modal-store", "data")])
def update_landing_page(data):
    if data["submitted"]:
        return html.Div(
            [
                dmc.Container(
                    [
                        dmc.Title(f"Welcome, {data['email']}!", order=2, align="center"),
                        dmc.Center(
                            dmc.Button(
                                "+ Create New Dashboard",
                                id="create-dashboard-button",
                                variant="gradient",
                                gradient={"from": "black", "to": "grey", "deg": 135},
                                style={"margin": "20px 0", "fontFamily": "Virgil"},
                                size="xl",
                            )
                        ),
                        dmc.Divider(style={"margin": "20px 0"}),
                        dmc.Title("Your Dashboards", order=3),
                        html.Div(
                            [
                                dmc.Paper(
                                    dmc.Group(
                                        [
                                            html.Div(
                                                [
                                                    dmc.Title(d["title"], order=5),
                                                    dmc.Text(f"Last Modified: {d['last_modified']}"),
                                                    dmc.Text(f"Status: {d['status']}"),
                                                ],
                                                style={"flex": "1"},
                                            ),
                                            dmc.Button("View Dashboard", variant="outline", color="dark", style={"marginRight": 20}),
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
                            ],
                            style={"padding": "20px"},
                        ),
                        dmc.Title("Your Workflows & Data Collections", order=3),
                        dmc.Accordion(
                            children=[
                                dmc.AccordionItem(
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
                                                                value=f"{workflow['title']}-{dc['type']}",
                                                            )
                                                            for dc in workflow["data_collections"]
                                                        ],
                                                    ),
                                                ]
                                            )
                                        ),
                                    ],
                                    value=workflow["title"],
                                )
                                for workflow in workflows
                            ],
                        ),
                    ]
                )
            ]
        )


if __name__ == "__main__":
    app.run_server(debug=True)
