from datetime import datetime, timedelta
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, ctx
import dash
from depictio.api.v1.db import users_collection
from depictio.api.v1.configs.config import logger
from depictio.api.v1.endpoints.user_endpoints.models import Token
from depictio.api.v1.endpoints.user_endpoints.utils import add_token, create_access_token, list_existing_tokens
from dash_extensions.enrich import DashProxy, html, Input, Output, State
from dash_extensions import EventListener
from dash.exceptions import PreventUpdate

# Layout placeholders
event = {"event": "keydown", "props": ["key"]}


def render_tokens_list(tokens):
    if not tokens:
        return html.P("No tokens available.")

    token_items = []
    for token in tokens:
        # for k, v in token.items():
        token_items.append(
            dbc.ListGroupItem(
                [
                    html.Div(
                        [
                            html.Strong(str(token["_id"])),
                            html.P(f"Expiration datetime: {token['expire_datetime']}"),
                            # html.P(f"Last activity: {token['last_activity']}"),
                        ],
                        className="token-details",
                    ),
                    dbc.Button("Delete", id={"type": "delete-token", "index": token['_id']}, color="danger", className="ml-auto"),
                ],
                className="d-flex justify-content-between align-items-center",
            )
        )

    return dbc.ListGroup(token_items)


layout = dbc.Container(
    [
        dbc.Row(dbc.Col(html.H2("Access Tokens", className="text-center"), width=12)),
        dbc.Row(dbc.Col(html.P("Security tokens to access Depictio via API."), width=12)),
        dbc.Row(dbc.Col(dbc.Button("Add Token", id="add-token-button", color="primary", className="mb-4", n_clicks=0), width={"size": 2, "offset": 10})),
        dbc.Row(dbc.Col(html.Div(id="tokens-list", className="token-display mt-3"), width=12)),
        dmc.Modal(
            title="Name Your Token",
            id="token-modal",
            centered=True,
            children=[
                dmc.TextInput(id="token-name-input", label="Token Name", description="Enter a name for your token", required=True),
                dmc.Button("Save", id="save-token-name", className="mt-2"),
            ],
        ),
        dmc.Modal(
            title="Confirm Deletion",
            id="delete-modal",
            centered=True,
            children=[
                dmc.TextInput(id="delete-confirm-input", label="Type 'delete' to confirm", required=True),
                dmc.Button("Confirm Delete", id="confirm-delete-button", className="mt-2", color="danger"),
            ],
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
                    disabled=True,
                ),
                # dmc.CopyButton(
                #     content="Copy",
                #     value="",
                #     className="mt-2",
                #     id="copy-token-button"
                # )
            ],
        ),
    ],
    fluid=True,
)


def register_tokens_management_callbacks(app):
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
        State("session-store", "data"),
        # prevent_initial_call=True,
    )
    def handle_callbacks(add_clicks, save_clicks, confirm_delete_clicks, delete_clicks, token_name, delete_confirm_input, delete_button_id, session_data):
        global token_to_delete
        triggered = ctx.triggered_id

        if not session_data:
            raise PreventUpdate

        tokens = list_existing_tokens(session_data["email"])
        logger.info(f"tokens: {tokens}")
        logger.info(f"triggered: {triggered}")
        logger.info(f"session_data: {session_data}")

        if triggered == "add-token-button" and add_clicks > 0:
            return True, False, render_tokens_list(tokens), False, ""

        elif triggered == "save-token-name" and save_clicks > 0 and token_name:
            token, expire = create_access_token({"name": token_name})
            token_data = {"access_token": token, "expire_datetime": expire.strftime("%Y-%m-%d %H:%M:%S")}
            add_token(session_data["email"], token_data)
            # tokens.append({"name": token_name, "created_time": created_time, "last_activity": created_time})
            
            return False, False, render_tokens_list(tokens), True, token

        elif isinstance(triggered, dict) and triggered.get("type") == "delete-token":
            token_to_delete = triggered.get("index")
            return False, True, render_tokens_list(tokens), False, ""

        elif triggered == "confirm-delete-button" and confirm_delete_clicks > 0 and delete_confirm_input == "delete":
            if token_to_delete in tokens:
                del tokens[token_to_delete]
                token_to_delete = None
            return False, False, render_tokens_list(tokens), False, ""

        return False, False, render_tokens_list(tokens), False, ""
