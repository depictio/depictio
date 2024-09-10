import dash
from dash import html, Input, Output, State, ctx
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import uuid
from datetime import datetime, timedelta
import jwt

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Secret key for JWT encoding
PRIVATE_KEY = "your_private_key_here"
ALGORITHM = "HS256"

app.layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H2("Access Tokens", className="text-center"),
                width=12
            )
        ),
        dbc.Row(
            dbc.Col(
                html.P("Security tokens to access Seqera Cloud via API."),
                width=12
            )
        ),
        dbc.Row(
            dbc.Col(
                dbc.Button(
                    "Add Token",
                    id="add-token-button",
                    color="primary",
                    className="mb-4",
                    n_clicks=0
                ),
                width={"size": 2, "offset": 10}
            )
        ),
        dbc.Row(
            dbc.Col(
                html.Div(
                    id="tokens-list",
                    className="token-display mt-3"
                ),
                width=12
            )
        ),
        dmc.Modal(
            title="Name Your Token",
            id="token-modal",
            centered=True,
            children=[
                dmc.TextInput(
                    id="token-name-input",
                    label="Token Name",
                    description="Enter a name for your token",
                    required=True
                ),
                dmc.Button("Save", id="save-token-name", className="mt-2")
            ]
        ),
        dmc.Modal(
            title="Confirm Deletion",
            id="delete-modal",
            centered=True,
            children=[
                dmc.TextInput(
                    id="delete-confirm-input",
                    label="Type 'delete' to confirm",
                    required=True
                ),
                dmc.Button("Confirm Delete", id="confirm-delete-button", className="mt-2", color="danger")
            ]
        ),
        dmc.Modal(
            title="Token Created",
            id="display-token-modal",
            centered=True,
            children=[
                dmc.TextInput(
                    id="display-token-input",
                    label="Token",
                    value="",
                    # readOnly=True,
                    className="mt-2",
                    disabled=True
                ),
                # dmc.CopyButton(
                #     content="Copy",
                #     value="",
                #     className="mt-2",
                #     id="copy-token-button"
                # )
            ]
        )
    ],
    fluid=True
)

# Store tokens in a dictionary
tokens = {}
token_to_delete = None

@app.callback(
    Output("token-modal", "opened"),
    Output("delete-modal", "opened"),
    Output("tokens-list", "children"),
    Output("display-token-modal", "opened"),
    Output("display-token-input", "value"),
    # Output("copy-token-button", "value"),
    Input("add-token-button", "n_clicks"),
    Input("save-token-name", "n_clicks"),
    Input("confirm-delete-button", "n_clicks"),
    Input({"type": "delete-token", "index": dash.dependencies.ALL}, "n_clicks"),
    State("token-name-input", "value"),
    State("delete-confirm-input", "value"),
    State({"type": "delete-token", "index": dash.dependencies.ALL}, "id"),
    prevent_initial_call=True
)
def handle_callbacks(add_clicks, save_clicks, confirm_delete_clicks, delete_clicks, token_name, delete_confirm_input, delete_button_id):
    global token_to_delete
    triggered = ctx.triggered_id

    if triggered == "add-token-button" and add_clicks > 0:
        return True, False, render_tokens_list(), False, ""
    
    if triggered == "save-token-name" and save_clicks > 0 and token_name:
        token, created_time = create_access_token({"name": token_name})
        tokens[token] = {
            "name": token_name,
            "created_time": created_time,
            "last_activity": created_time
        }
        return False, False, render_tokens_list(), True, token

    
    if isinstance(triggered, dict) and triggered.get("type") == "delete-token":
        token_to_delete = triggered.get("index")
        return False, True, render_tokens_list(), False, ""
    
    if triggered == "confirm-delete-button" and confirm_delete_clicks > 0 and delete_confirm_input == "delete":
        if token_to_delete in tokens:
            del tokens[token_to_delete]
            token_to_delete = None
        return False, False, render_tokens_list(), False, ""

    return False, False, render_tokens_list(), False, ""

def create_access_token(data, expires_delta=timedelta(minutes=15)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    created_time = datetime.now().strftime("%b %d, %Y, %I:%M:%S %p")
    return encoded_jwt, created_time

def render_tokens_list():
    if not tokens:
        return html.P("No tokens available.")
    
    token_items = []
    for token, details in tokens.items():
        token_items.append(
            dbc.ListGroupItem(
                [
                    html.Div(
                        [
                            html.Strong(details["name"]),
                            html.P(f"Created: {details['created_time']}"),
                            html.P(f"Last activity: {details['last_activity']}"),
                        ],
                        className="token-details"
                    ),
                    dbc.Button(
                        "Delete",
                        id={"type": "delete-token", "index": token},
                        color="danger",
                        className="ml-auto"
                    )
                ],
                className="d-flex justify-content-between align-items-center"
            )
        )
    
    return dbc.ListGroup(token_items)

if __name__ == '__main__':
    app.run_server(debug=True)
