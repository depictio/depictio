import re
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import dash_mantine_components as dmc
from dash_iconify import DashIconify

dashboards = [
    {"title": "Genome Analysis", "last_modified": "2023-10-01 14:23:08", "status": "Completed"},
    {"title": "Protein Folding Study", "last_modified": "2023-09-20 11:15:42", "status": "In Progress"},
    {"title": "Environmental Data Overview", "last_modified": "2023-10-02 09:02:55", "status": "Completed"}
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
                dmc.Title("Welcome to Depictio", order=4),
                dmc.Text("Please enter your email to continue:"),
                dmc.Space(h=20),
                dmc.TextInput(label="Your Email", style={"width": 200}, placeholder="Your Email", icon=DashIconify(icon="ic:round-alternate-email"), id="email-input"),
                dmc.Space(h=20),
                dmc.Button("Submit", id="submit-button", variant="filled", disabled=True, size="lg", color="black"),
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
                        dmc.Button("Create New Dashboard", id="create-dashboard-button", variant="filled", color="blue", style={"margin": "20px 0"}),
                        dmc.Divider(),
                        dmc.Title("Your Dashboards", order=4),
                        html.Div(
                            [
                                dmc.Paper(
                                    [
                                        dmc.Title(d["title"], order=5),
                                        dmc.Text(f"Last Modified: {d['last_modified']}"),
                                        dmc.Text(f"Status: {d['status']}"),
                                        dmc.Space(h=10),
                                        dmc.Button("View Dashboard", variant="outline"),
                                    ],
                                    shadow="xs",
                                    p="md",
                                    style={"marginBottom": 20},
                                )
                                for d in dashboards
                            ],
                            style={"padding": "20px"},
                        ),
                    ]
                )
            ]
        )


if __name__ == "__main__":
    app.run_server(debug=True)
