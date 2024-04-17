import re
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import dash_mantine_components as dmc
from dash_iconify import DashIconify

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
                dmc.Button("Submit", id="submit-button", variant="filled", disabled=True,size="lg", color="black"),
            ],
            # Prevent closing the modal by clicking outside or pressing ESC
            closeOnClickOutside=False,
            closeOnEscape=False,
            withCloseButton=False,
        ),
    ]
)


@app.callback(
    [Output("submit-button", "disabled"), Output("email-input", "error")],
    [Input("email-input", "value")]
)
def update_submit_button(email):
    if email:
        valid = re.match(r"^[a-zA-Z0-9_.+-]+@embl\.de$", email)
        return not valid, not valid
    return True, False  # Initially disabled with no error

@app.callback(
    Output("modal-store", "data"),
    [Input("submit-button", "n_clicks")],
    [State("email-input", "value"), State("modal-store", "data")]
)
def store_email(submit_clicks, email, data):
    print(submit_clicks, email, data)
    if submit_clicks:
        data["email"] = email
        data["submitted"] = True
    return data

@app.callback(
    Output("email-modal", "opened"),
    [Input("modal-store", "data")]
)
def manage_modal(data):
    print(data)
    return not data["submitted"]  # Keep modal open until submitted


if __name__ == "__main__":
    app.run_server(debug=True)
