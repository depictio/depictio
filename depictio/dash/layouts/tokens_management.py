import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import yaml
from dash import ALL, ctx, dcc
from dash.exceptions import PreventUpdate
from dash_extensions.enrich import Input, Output, State, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import (
    api_call_create_token,
    api_call_delete_token,
    api_call_fetch_user_from_token,
    api_call_generate_agent_config,
    api_call_list_tokens,
)
from depictio.dash.colors import colors
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import TokenData

# Define consistent theme elements
CARD_SHADOW = "md"
CARD_RADIUS = "lg"
CARD_PADDING = "xl"
BUTTON_RADIUS = "md"
ICON_SIZE = 20

# Layout placeholders
event = {"event": "keydown", "props": ["key"]}

clipboard_icon_uri = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'..."


def render_tokens_list(tokens):
    """Render the list of CLI configuration tokens with improved styling"""
    if not tokens:
        # Return the empty state message using the provided template
        return dmc.Center(
            dmc.Paper(
                children=[
                    dmc.Stack(
                        children=[
                            dmc.Center(
                                DashIconify(
                                    icon="bi:terminal-x",  # Changed icon to show terminal is off/unavailable
                                    width=64,
                                    height=64,
                                    style={
                                        "color": colors["blue"] + "80"
                                    },  # Using brand color with opacity
                                )
                            ),
                            dmc.Text(
                                "No CLI Configurations Available",
                                align="center",
                                weight=700,
                                size="xl",
                                style={"color": colors["blue"]},
                            ),
                            dmc.Text(
                                "Add a new configuration to access Depictio via the command line interface.",
                                align="center",
                                color="dimmed",
                                size="sm",
                            ),
                        ],
                        align="center",
                        spacing="sm",
                    )
                ],
                shadow="sm",
                radius="md",
                p="xl",
                withBorder=True,
                style={
                    "width": "100%",
                    "maxWidth": "700px",
                    "borderColor": colors["teal"] + "40",
                },
            ),
            style={"height": "300px"},
        )

    # If we have tokens, render a nicer looking list
    token_items = []
    for token in tokens:
        # logger.info(f"Token: {token}")

        # Format expiration date nicer
        expiration = token["expire_datetime"]

        token_items.append(
            dmc.Paper(
                children=[
                    dmc.Group(
                        [
                            # Token icon and name
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:key-variant",
                                        width=28,
                                        style={"color": colors["blue"] + "80"},
                                    ),
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                str(token["name"]),
                                                weight=700,
                                                size="lg",
                                                style={"color": colors["blue"]},
                                            ),
                                            dmc.Text(
                                                f"Expires: {expiration}",
                                                size="xs",
                                                color="dimmed",
                                            ),
                                        ],
                                        spacing=0,
                                    ),
                                ],
                                spacing="sm",
                            ),
                            # Delete button
                            dmc.Button(
                                "Delete",
                                id={"type": "delete-token", "index": str(token["_id"])},
                                variant="subtle",
                                radius="md",
                                leftIcon=DashIconify(
                                    icon="mdi:delete",
                                    width=16,
                                ),
                                styles={
                                    "root": {
                                        "color": colors["red"],
                                        "&:hover": {
                                            "backgroundColor": colors["red"] + "10",
                                        },
                                    },
                                },
                            ),
                        ],
                        position="apart",
                        style={"width": "100%"},
                    ),
                ],
                p="md",
                withBorder=True,
                radius="md",
                shadow="xs",
                style={
                    "marginBottom": "10px",
                    "borderColor": colors["teal"] + "40",
                },
            )
        )

    return dmc.Stack(
        children=token_items,
        style={
            "width": "100%",
            "maxWidth": "800px",
            "marginLeft": "auto",
            "marginRight": "auto",
        },
    )


layout = dbc.Container(
    [
        dcc.Store(id="delete-token-id-store", storage_type="memory"),
        # Header section with improved styling
        dmc.Center(
            dmc.Paper(
                children=[
                    dmc.Stack(
                        [
                            # Title with icon
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:console-line",
                                        width=32,
                                        height=32,
                                        style={"color": colors["green"]},
                                    ),
                                    dmc.Title(
                                        "Depictio-CLI Configurations",
                                        order=2,
                                        style={"color": colors["green"]},
                                    ),
                                ],
                                spacing="xs",
                                position="center",
                            ),
                            # Description
                            dmc.Text(
                                "Security configurations to access Depictio via the command line interface.",
                                align="center",
                                color="dimmed",
                                size="sm",
                            ),
                            # Add new config button with improved styling
                            dmc.Button(
                                "Add New Configuration",
                                id="add-token-button",
                                leftIcon=DashIconify(
                                    icon="mdi:plus-circle",
                                    width=20,
                                    style={"color": "white"},
                                ),
                                radius="md",
                                size="md",
                                styles={
                                    "root": {
                                        "backgroundColor": colors["green"],
                                        "marginTop": "20px",
                                        "marginBottom": "10px",
                                        "&:hover": {
                                            "backgroundColor": colors["green"] + "cc",
                                        },
                                    }
                                },
                                disabled=settings.auth.unauthenticated_mode,
                            ),
                        ],
                        align="center",
                        spacing="xs",
                    ),
                ],
                shadow="xs",
                p="xl",
                withBorder=True,
                radius="md",
                style={
                    "marginBottom": "20px",
                    "borderColor": colors["teal"] + "40",
                    "width": "100%",
                    "maxWidth": "700px",
                },
            )
        ),
        # List of tokens with improved styling
        html.Div(id="tokens-list", className="token-display mt-3"),
        # Name token modal with improved styling
        dmc.Modal(
            # title="Name Your Configuration",
            id="token-modal",
            centered=True,
            withCloseButton=False,
            children=[
                dmc.Group(
                    position="left",
                    spacing="sm",
                    children=[
                        DashIconify(
                            icon="mdi:console-line",
                            width=28,
                            height=28,
                            color=colors["green"],
                        ),
                        dmc.Title(
                            "Name Your Configuration",
                            order=4,
                            style={"margin": 0},
                            color=colors["green"],
                        ),
                    ],
                    style={
                        "marginBottom": "20px",
                        "marginTop": "10px",
                    },
                ),
                dmc.TextInput(
                    id="token-name-input",
                    label="Configuration Name",
                    # placeholder="test cli",
                    placeholder="Enter a name for your CLI configuration",
                    # placeholder="e.g., My Workstation",
                    required=True,
                    # icon=DashIconify(icon="mdi:tag", width=20),
                    # persistence="memory",
                ),
                # Alert message if token name is empty or already exists
                dmc.Alert(
                    id="token-name-alert",
                    title="CLI Configuration creation failed",
                    color="red",
                    icon=DashIconify(icon="mdi:alert-circle", width=24),
                    style={
                        "display": "none",  # Initially hidden
                    },
                ),
                dmc.Group(
                    [
                        dmc.Button(
                            "Cancel",
                            variant="subtle",
                            color="gray",
                            radius="md",
                            id="cancel-token-modal",
                        ),
                        dmc.Button(
                            "Save",
                            id="save-token-name",
                            radius="md",
                            styles={
                                "root": {
                                    "backgroundColor": colors["green"],
                                    "&:hover": {
                                        "backgroundColor": colors["green"] + "cc",
                                    },
                                }
                            },
                        ),
                    ],
                    position="right",
                    mt="xl",
                ),
            ],
        ),
        # Delete confirmation modal with improved styling
        dmc.Modal(
            title="Confirm Deletion",
            id="delete-modal",
            centered=True,
            styles={
                "title": {
                    "color": colors["red"],
                    "fontWeight": 600,
                }
            },
            children=[
                dmc.Stack(
                    [
                        dmc.Text(
                            "Are you sure you want to delete this configuration? This action cannot be undone.",
                            size="sm",
                            color="dimmed",
                        ),
                        dmc.TextInput(
                            id="delete-confirm-input",
                            label="Type 'delete' to confirm",
                            required=True,
                            icon=DashIconify(icon="mdi:delete-alert", width=20),
                        ),
                        dmc.Group(
                            [
                                dmc.Button(
                                    "Cancel",
                                    variant="subtle",
                                    color="gray",
                                    radius="md",
                                    id="cancel-delete-modal",
                                ),
                                dmc.Button(
                                    "Confirm Delete",
                                    id="confirm-delete-button",
                                    radius="md",
                                    styles={
                                        "root": {
                                            "backgroundColor": colors["red"],
                                            "&:hover": {
                                                "backgroundColor": colors["red"] + "cc",
                                            },
                                        }
                                    },
                                ),
                            ],
                            position="right",
                            mt="xl",
                        ),
                    ],
                    spacing="md",
                ),
            ],
        ),
        # Display token modal with improved styling
        dmc.Modal(
            id="display-token-modal",
            centered=True,
            size="lg",
            styles={
                "title": {
                    "color": colors["blue"],
                    "fontWeight": 600,
                }
            },
            children=[html.Div(id="display-agent")],
        ),
    ],
    fluid=True,
    className="py-4",
)


def register_tokens_management_callbacks(app):
    # Add this callback to your app
    @app.callback(
        Output("copy-config-clipboard", "content"),
        Input("copy-config-button", "n_clicks"),
        State("agent-config-md", "children"),
        prevent_initial_call=True,
    )
    def copy_config(n_clicks, content):
        # logger.info(f"Copying config to clipboard: {n_clicks}")
        # logger.info(f"Content: {content}")
        if n_clicks:
            # Copy the content to the clipboard
            return content
        return dash.no_update

    @app.callback(
        Output("token-modal", "opened"),
        Output("delete-modal", "opened"),
        Output("tokens-list", "children"),
        Output("display-token-modal", "opened"),
        Output("display-agent", "children"),
        Output("delete-token-id-store", "data"),
        Output("delete-confirm-input", "value"),
        Output("token-name-alert", "style"),
        Output("token-name-alert", "children"),
        Input("add-token-button", "n_clicks"),
        Input("save-token-name", "n_clicks"),
        Input("confirm-delete-button", "n_clicks"),
        Input("cancel-token-modal", "n_clicks"),
        Input("cancel-delete-modal", "n_clicks"),
        Input({"type": "delete-token", "index": ALL}, "n_clicks"),
        State("token-name-input", "value"),
        State("delete-confirm-input", "value"),
        State({"type": "delete-token", "index": ALL}, "id"),
        State("local-store", "data"),
        State("delete-token-id-store", "data"),
    )
    def handle_callbacks(
        add_clicks,
        save_clicks,
        confirm_delete_clicks,
        cancel_token_clicks,
        cancel_delete_clicks,
        delete_clicks,
        token_name,
        delete_confirm_input,
        delete_button_id,
        local_store,
        delete_token_id,
    ):
        logger.info("Handling token management callbacks")
        triggered = ctx.triggered_id

        if not local_store:
            raise PreventUpdate

        user = api_call_fetch_user_from_token(local_store["access_token"])

        tokens = api_call_list_tokens(
            current_token=local_store["access_token"], token_lifetime="long-lived"
        )
        # logger.info(f"tokens: {tokens}")
        # logger.info(f"triggered: {triggered}")
        # logger.info(f"local_store: {local_store}")
        delete_token_id = delete_token_id or {}

        if triggered == "add-token-button" and add_clicks > 0:
            return (
                True,
                False,
                render_tokens_list(tokens),
                False,
                "",
                delete_token_id,
                "",
                {"display": "none"},  # Hide alert initially
                "",
            )

        elif triggered == "cancel-token-modal" and cancel_token_clicks:
            return (
                False,
                False,
                render_tokens_list(tokens),
                False,
                "",
                delete_token_id,
                "",
                {"display": "none"},  # Hide alert initially
                "",
            )

        elif triggered == "cancel-delete-modal" and cancel_delete_clicks:
            return (
                False,
                False,
                render_tokens_list(tokens),
                False,
                "",
                delete_token_id,
                "",
                {"display": "none"},  # Hide alert initially
                "",
            )

        elif triggered == "save-token-name" and save_clicks > 0 and token_name:
            logger.info(f"Token name: {token_name}")

            if not token_name or (tokens and token_name in [t["name"] for t in tokens]):
                return (
                    True,
                    False,
                    render_tokens_list(tokens),
                    False,
                    "",
                    delete_token_id,
                    "",
                    {"display": "block"},  # Show alert
                    (
                        "CLI Configuration name already exists. Please choose a different name."
                        if token_name
                        else "CLI Configuration name is required."
                    ),
                )

            _token_data_dict = {
                "name": token_name,
                "token_lifetime": "long-lived",
                "token_type": "bearer",
                "sub": user.id,  # Explicitly pass the user ID
            }
            # logger.debug(f"Token data dict: {_token_data_dict}")
            token_data = TokenData(**_token_data_dict)
            # logger.debug(f"Token data: {format_pydantic(token_data)}")
            # logger.debug(token_data.model_dump())
            token_generated = api_call_create_token(token_data=token_data)

            if not token_generated:
                div = html.Div(
                    [
                        dmc.Alert(
                            title="Configuration Creation Failed",
                            children="A configuration with that name already exists. Please choose a different name.",
                            color="red",
                            icon=DashIconify(icon="mdi:alert-circle", width=24),
                        )
                    ]
                )

                return (
                    False,
                    False,
                    render_tokens_list(tokens),
                    True,
                    div,
                    delete_token_id,
                    "",
                    {"display": "none"},  # Show alert
                    "",
                )

            # logger.info(f"Token generated: {token_generated}")
            # Create TokenData for agent config generation
            token_data = TokenData(
                name=token_generated.get("name"),
                token_lifetime=token_generated.get("token_lifetime", "short-lived"),
                token_type=token_generated.get("token_type", "bearer"),
                sub=PyObjectId(token_generated.get("user_id")),
            )
            # logger.info(f"Token generated: {format_pydantic(token_data)}")
            agent_config = api_call_generate_agent_config(
                token=token_data, current_token=local_store["access_token"]
            )
            # logger.info(f"Config: {agent_config}")

            tokens = api_call_list_tokens(
                current_token=local_store["access_token"], token_lifetime="long-lived"
            )

            # Format token data for display using dcc.Markdown, using YAML format
            agent_config = yaml.dump(agent_config, default_flow_style=False)
            # logger.info(f"Token data: {token_data}")

            # Add extra formatting to color with YAML ('''...''') and add a copy button
            agent_config = f"""```yaml\n{agent_config}\n```"""

            # logger.info(f"Config: {agent_config}")

            # Modified component definition
            div_agent_config = html.Div(
                [
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:check-circle",
                                        width=28,
                                        style={"color": colors["green"]},
                                    ),
                                    dmc.Title(
                                        id="config-created-success",
                                        children="Configuration Created Successfully",
                                        order=3,
                                        style={"color": colors["green"]},
                                    ),
                                ],
                                spacing="sm",
                            ),
                            dmc.Alert(
                                title="Important",
                                color="yellow",
                                children=[
                                    html.Span(
                                        "Please copy the configuration and store it in a safe place, such as "
                                    ),
                                    dmc.Code("~/.depictio/CLI.yaml"),
                                    html.Span(
                                        ". You will not be able to access this configuration again once you close this dialog."
                                    ),
                                ],
                                icon=DashIconify(icon="mdi:alert", width=24),
                            ),
                            dmc.Paper(
                                children=[
                                    dcc.Markdown(id="agent-config-md", children=agent_config),
                                ],
                                withBorder=True,
                                p="sm",
                                style={
                                    "position": "relative",
                                    "backgroundColor": "#f8f9fa",
                                    "borderColor": colors["teal"] + "40",
                                },
                            ),
                            dmc.Group(
                                [
                                    # dmc.Button(
                                    #     "Copy Configuration",
                                    #     variant="filled",
                                    #     color="teal",
                                    #     radius="md",
                                    #     leftIcon=DashIconify(
                                    #         icon="mdi:content-copy", width=20
                                    #     ),
                                    #     id="copy-config-button",
                                    # ),
                                    # Styled clipboard component
                                    dcc.Clipboard(
                                        id="copy-config-clipboard",
                                        target_id="agent-config-md",
                                        className="clipboard-button",
                                        title="Copy to clipboard",  # Basic tooltip
                                        content="",
                                        n_clicks=0,
                                        style={
                                            "position": "absolute",
                                            "top": "270px",
                                            "right": "45px",
                                            # grey background
                                            "background-color": "#f8f9fa",
                                            "border": "none",
                                            "color": "grey",
                                            "border-radius": "4px",
                                            "padding": "8px",
                                            "cursor": "pointer",
                                            "box-shadow": "0 2px 5px rgba(0,0,0,0.2)",
                                        },
                                        # children=html.Img(
                                        #     src=clipboard_icon_uri,
                                        #     style={"width": "16px", "height": "16px"},
                                        # ),
                                    ),
                                ],
                                position="right",
                            ),
                        ],
                        spacing="md",
                    ),
                ]
            )

            return (
                False,
                False,
                render_tokens_list(tokens),
                True,
                div_agent_config,
                delete_token_id,
                "",
                {"display": "none"},  # Hide alert
                "",
            )

        elif isinstance(triggered, dict) and triggered.get("type") == "delete-token":
            logger.info(f"{triggered}")
            token_to_delete = triggered["index"]
            return (
                False,
                True,
                render_tokens_list(tokens),
                False,
                "",
                token_to_delete,
                "",
                {"display": "none"},  # Hide alert
                "",
            )

        elif (
            triggered == "confirm-delete-button"
            and confirm_delete_clicks > 0
            and delete_confirm_input == "delete"
        ):
            logger.info(f"Deleting config {delete_token_id}")
            # logger.info(f"tokens: {tokens}")
            if tokens and delete_token_id in [str(t["_id"]) for t in tokens]:
                # logger.info(f"Deleting token {delete_token_id}")
                api_call_delete_token(token_id=delete_token_id)
                tokens = [e for e in tokens if str(e["_id"]) != delete_token_id]

            return (
                False,
                False,
                render_tokens_list(tokens),
                False,
                "",
                {},
                "",
                {"display": "none"},
                "",
            )

        return (
            False,
            False,
            render_tokens_list(tokens),
            False,
            "",
            {},
            "",
            {"display": "none"},
            "",
        )
