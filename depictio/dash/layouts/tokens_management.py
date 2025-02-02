import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State, ctx
import dash
import yaml
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.endpoints.user_endpoints.utils import add_token, delete_token, generate_agent_config, list_existing_tokens
from dash_extensions.enrich import html, Input, Output, State
from dash.exceptions import PreventUpdate

# Layout placeholders
event = {"event": "keydown", "props": ["key"]}


def render_tokens_list(tokens):
    if not tokens:
        return html.P("No depictio-cli configs available.")

    token_items = []
    for token in tokens:
        logger.info(f"Token: {token}")
        # for k, v in token.items():
        token_items.append(
            dbc.ListGroupItem(
                [
                    html.Div(
                        [
                            html.Strong(str(token["name"])),
                            html.P(f"Expiration datetime: {token['expire_datetime']}"),
                            # html.P(f"Last activity: {token['last_activity']}"),
                        ],
                        className="token-details",
                    ),
                    dmc.Button("Delete", id={"type": "delete-token", "index": str(token["id"])}, color="red", className="ml-auto", variant="outline"),
                ],
                className="d-flex justify-content-between align-items-center",
            )
        )

    return dbc.ListGroup(token_items)


layout = dbc.Container(
    [
        dcc.Store(id="delete-token-id-store", storage_type="memory"),
        # html.A(dmc.Button("Back to Home", id="back-to-homepage", variant="outline", color="blue", style={"marginTop": "20px"}), href="/"),
        dbc.Row(dbc.Col(html.H2("depictio-CLI config", className="text-center"), width=12)),
        dbc.Row(dmc.Center(dmc.Text("Security configuration to access Depictio via depictio-cli.", weight=500, size="lg"))),
        dbc.Row(dmc.Center(dmc.Button("Add new config", id="add-token-button", color="primary", className="mb-4", n_clicks=0, variant="outline", size="xl", style={"marginTop": "20px"}))),
        dbc.Row(dbc.Col(html.Div(id="tokens-list", className="token-display mt-3"), width=12)),
        dmc.Modal(
            title="Name Your Config",
            id="token-modal",
            centered=True,
            children=[
                dmc.TextInput(id="token-name-input", label="Token Name", description="Enter a name for your config", required=True),
                dmc.Button("Save", id="save-token-name", className="mt-2", variant="outline"),
            ],
        ),
        dmc.Modal(
            title="Confirm Deletion",
            id="delete-modal",
            centered=True,
            children=[
                dmc.TextInput(id="delete-confirm-input", label="Type 'delete' to confirm", required=True),
                dmc.Button("Confirm Delete", id="confirm-delete-button", className="mt-2", color="red", variant="outline"),
            ],
        ),
        dmc.Modal(
            # title="Token Created",
            id="display-token-modal",
            centered=True,
            children=[html.Div(id="display-agent")],
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
        Output("display-agent", "children"),
        Output("delete-token-id-store", "data"),
        Output("delete-confirm-input", "value"),
        # Output("copy-token-button", "value"),
        Input("add-token-button", "n_clicks"),
        Input("save-token-name", "n_clicks"),
        Input("confirm-delete-button", "n_clicks"),
        Input({"type": "delete-token", "index": dash.dependencies.ALL}, "n_clicks"),
        State("token-name-input", "value"),
        State("delete-confirm-input", "value"),
        State({"type": "delete-token", "index": dash.dependencies.ALL}, "id"),
        State("local-store", "data"),
        State("delete-token-id-store", "data"),
        # prevent_initial_call=True,
    )
    def handle_callbacks(add_clicks, save_clicks, confirm_delete_clicks, delete_clicks, token_name, delete_confirm_input, delete_button_id, local_store, delete_token_id):
        triggered = ctx.triggered_id

        if not local_store:
            raise PreventUpdate

        user = fetch_user_from_token(local_store["access_token"])

        tokens = list_existing_tokens(user.email)
        logger.info(f"tokens: {tokens}")
        logger.info(f"triggered: {triggered}")
        logger.info(f"local_store: {local_store}")
        delete_token_id = delete_token_id or {}

        if triggered == "add-token-button" and add_clicks > 0:
            return True, False, render_tokens_list(tokens), False, "", delete_token_id, ""

        elif triggered == "save-token-name" and save_clicks > 0 and token_name:
            # token, expire = create_access_token({"name": token_name})
            # token_data = {"access_token": token, "expire_datetime": expire.strftime("%Y-%m-%d %H:%M:%S"), "name": token_name}
            token_data = add_token({"sub": user.email, "name": token_name, "token_lifetime": "long-lived"})

            if not token_data:
                div = dmc.Title("Failed to create config. Config with that name already exists.", color="red", order=3)

                return False, False, render_tokens_list(tokens), True, div, delete_token_id, ""

            token_data = token_data.dict()
            logger.info(f"Token data: {token_data}")

            agent_config = generate_agent_config(user.email, token_data, current_token=local_store["access_token"])
            logger.info(f"Config: {agent_config}")

            # tokens.append({"name": token_name, "created_time": created_time, "last_activity": created_time})
            tokens = list_existing_tokens(user.email)

            # Format token data for display using dcc.Markdown, using YAML format
            agent_config = yaml.dump(agent_config, default_flow_style=False)
            logger.info(f"Token data: {token_data}")

            # Add extra formatting to color with YAML ('''...''') and add a copy button
            agent_config = f"""```yaml\n{agent_config}\n```"""

            # Add a copy button to the token display modal

            logger.info(f"Config: {agent_config}")

            div_agent_config = html.Div(
                [
                    dmc.Title("Config created", color="blue", order=3),
                    dcc.Markdown(id="agent-config-md", children=agent_config),
                    dcc.Clipboard(
                        target_id="agent-config-md",
                        style={
                            "position": "absolute",
                            "top": 75,
                            "right": 20,
                            "fontSize": 15,
                        },
                    ),
                    dmc.Text(
                        [
                            "Please copy the config and store it in ",
                            dmc.Code("~/.depictio/depictio-cli.yaml"),
                            " . You will not be able to access this config again once you close this dialog.",
                        ]
                    ),
                ]
            )

            return False, False, render_tokens_list(tokens), True, div_agent_config, delete_token_id, ""

        elif isinstance(triggered, dict) and triggered.get("type") == "delete-token":
            logger.info(f"{triggered}")
            token_to_delete = triggered["index"]
            return False, True, render_tokens_list(tokens), False, "", token_to_delete, ""

        elif triggered == "confirm-delete-button" and confirm_delete_clicks > 0 and delete_confirm_input == "delete":
            logger.info(f"Deleting config {delete_token_id}")
            logger.info(f"tokens: {tokens}")
            if delete_token_id in [str(t["id"]) for t in tokens]:
                # del tokens[token_to_delete]
                # token_to_delete = None
                delete_token(user.email, delete_token_id, local_store["access_token"])
                tokens = [e for e in tokens if str(e["id"]) != delete_token_id]

            return False, False, render_tokens_list(tokens), False, "", {}, ""

        return False, False, render_tokens_list(tokens), False, "", {}, ""
