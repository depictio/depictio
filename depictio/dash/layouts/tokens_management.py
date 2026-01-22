"""
CLI token and configuration management for Depictio.

This module provides the UI and callbacks for managing CLI configurations
(long-lived access tokens) that allow users to access Depictio via the
command-line interface.

Features:
    - List existing CLI configurations with expiration dates
    - Create new CLI configurations with custom names
    - Delete existing configurations with confirmation
    - Display generated YAML configuration for CLI setup
    - Copy configuration to clipboard functionality

UI Components:
    - Main layout with token list and add button
    - Token naming modal for new configurations
    - Delete confirmation modal with safety input
    - Configuration display modal with YAML output
"""

from typing import Any

import dash
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
from depictio.models.models.users import TokenBase, TokenData

# Define consistent theme elements
CARD_SHADOW = "md"
CARD_RADIUS = "lg"
CARD_PADDING = "xl"
BUTTON_RADIUS = "md"
ICON_SIZE = 20

# Layout placeholders
event = {"event": "keydown", "props": ["key"]}

clipboard_icon_uri = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'..."


def render_tokens_list(tokens: list[dict[str, Any]] | None) -> dmc.Center | dmc.Stack:
    """
    Render the list of CLI configuration tokens.

    Creates either an empty state message when no tokens exist, or a styled
    list of token cards showing name, expiration date, and delete button.

    Args:
        tokens: List of token dictionaries with keys '_id', 'name', 'expire_datetime',
               or None if no tokens exist.

    Returns:
        Either a centered empty state message or a stack of token cards.
    """
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
                                ta="center",
                                fw="bold",
                                size="xl",
                                style={"color": colors["blue"]},
                            ),
                            dmc.Text(
                                "Add a new configuration to access Depictio via the command line interface.",
                                ta="center",
                                c="gray",
                                size="sm",
                            ),
                        ],
                        align="center",
                        gap="sm",
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
                                                fw="bold",
                                                size="lg",
                                                style={"color": colors["blue"]},
                                            ),
                                            dmc.Text(
                                                f"Expires: {expiration}",
                                                size="xs",
                                                c="gray",
                                            ),
                                        ],
                                        gap=None,
                                    ),
                                ],
                                gap="sm",
                            ),
                            # Delete button
                            dmc.Button(
                                "Delete",
                                id={"type": "delete-token", "index": str(token["_id"])},
                                variant="subtle",
                                radius="md",
                                leftSection=DashIconify(
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
                        justify="space-between",
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


layout = dmc.Container(
    size="lg",
    p="md",
    children=[
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
                                        # style={"color": colors["green"]},
                                        c=colors["green"],
                                    ),
                                ],
                                gap="xs",
                                justify="center",
                            ),
                            # Description
                            dmc.Text(
                                "Security configurations to access Depictio via the command line interface.",
                                ta="center",
                                c="gray",
                                size="sm",
                            ),
                            # Add new config button with improved styling
                            dmc.Button(
                                "Add New Configuration",
                                id="add-token-button",
                                leftSection=DashIconify(
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
                        gap="xs",
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
                    justify="flex-start",
                    gap="sm",
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
                            # color=colors["green"],
                            c=colors["green"],
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
                    justify="flex-end",
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
                            c="gray",
                        ),
                        dmc.TextInput(
                            id="delete-confirm-input",
                            label="Type 'delete' to confirm",
                            required=True,
                            leftSection=DashIconify(icon="mdi:delete-alert", width=20),
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
                            justify="flex-end",
                            mt="xl",
                        ),
                    ],
                    gap="md",
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
)


def _create_default_response(
    tokens: list[dict[str, Any]] | None,
    delete_token_id: dict[str, Any],
) -> tuple:
    """
    Create the default callback response with closed modals.

    Args:
        tokens: List of token data for rendering.
        delete_token_id: Current delete token ID store value.

    Returns:
        Tuple of default values for all callback outputs.
    """
    return (
        False,  # token-modal opened
        False,  # delete-modal opened
        render_tokens_list(tokens),  # tokens-list children
        False,  # display-token-modal opened
        "",  # display-agent children
        delete_token_id,  # delete-token-id-store data
        "",  # delete-confirm-input value
        {"display": "none"},  # token-name-alert style
        "",  # token-name-alert children
    )


def _handle_add_token(
    tokens: list[dict[str, Any]] | None,
    delete_token_id: dict[str, Any],
) -> tuple:
    """
    Handle the add token button click - opens the token naming modal.

    Args:
        tokens: List of current tokens.
        delete_token_id: Current delete token ID.

    Returns:
        Tuple with token modal opened.
    """
    return (
        True,  # Open token modal
        False,
        render_tokens_list(tokens),
        False,
        "",
        delete_token_id,
        "",
        {"display": "none"},
        "",
    )


def _handle_cancel_modal(
    tokens: list[dict[str, Any]] | None,
    delete_token_id: dict[str, Any],
) -> tuple:
    """
    Handle cancel button clicks - closes all modals.

    Args:
        tokens: List of current tokens.
        delete_token_id: Current delete token ID.

    Returns:
        Tuple with all modals closed.
    """
    return (
        False,
        False,
        render_tokens_list(tokens),
        False,
        "",
        delete_token_id,
        "",
        {"display": "none"},
        "",
    )


def _handle_delete_token_click(
    tokens: list[dict[str, Any]] | None,
    token_to_delete: str,
) -> tuple:
    """
    Handle delete token button click - opens delete confirmation modal.

    Args:
        tokens: List of current tokens.
        token_to_delete: ID of the token to delete.

    Returns:
        Tuple with delete modal opened and token ID stored.
    """
    return (
        False,
        True,  # Open delete modal
        render_tokens_list(tokens),
        False,
        "",
        token_to_delete,
        "",
        {"display": "none"},
        "",
    )


def _handle_confirm_delete(
    tokens: list[dict[str, Any]] | None,
    delete_token_id: str,
) -> tuple:
    """
    Handle confirmed token deletion.

    Args:
        tokens: List of current tokens.
        delete_token_id: ID of the token to delete.

    Returns:
        Tuple with updated token list after deletion.
    """
    if tokens and delete_token_id in [str(t["_id"]) for t in tokens]:
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


def _create_config_display(agent_config: str) -> html.Div:
    """
    Create the configuration display component with YAML code.

    Args:
        agent_config: YAML-formatted configuration string.

    Returns:
        Div containing the success message and configuration display.
    """
    return html.Div(
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
                                c=colors["green"],
                            ),
                        ],
                        gap="sm",
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
                            dmc.CodeHighlight(
                                id="agent-config-md", language="yaml", code=agent_config
                            ),
                        ],
                        p="sm",
                    ),
                ],
                gap="md",
            ),
        ]
    )


def _handle_save_token(
    token_name: str,
    tokens: list[dict[str, Any]] | None,
    delete_token_id: dict[str, Any],
    local_store: dict[str, Any],
    user: Any,
) -> tuple:
    """
    Handle saving a new token configuration.

    Creates a new long-lived token with the given name and generates
    the CLI configuration YAML.

    Args:
        token_name: Name for the new token.
        tokens: List of current tokens.
        delete_token_id: Current delete token ID.
        local_store: Local storage data with access token.
        user: Current user object.

    Returns:
        Tuple with either error alert or success display.
    """
    # Validate token name uniqueness
    if not token_name or (tokens and token_name in [t["name"] for t in tokens]):
        error_msg = (
            "CLI Configuration name already exists. Please choose a different name."
            if token_name
            else "CLI Configuration name is required."
        )
        return (
            True,  # Keep modal open
            False,
            render_tokens_list(tokens),
            False,
            "",
            delete_token_id,
            "",
            {"display": "block"},  # Show alert
            error_msg,
        )

    # Create token data and call API
    _token_data_dict = {
        "name": token_name,
        "token_lifetime": "long-lived",
        "token_type": "bearer",
        "sub": user.id,
    }
    token_data = TokenData(**_token_data_dict)
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
            {"display": "none"},
            "",
        )

    # Create TokenBase and generate config
    token_generated = TokenBase(
        user_id=token_generated["user_id"],
        access_token=token_generated["access_token"],
        refresh_token=token_generated["refresh_token"],
        expire_datetime=token_generated["expire_datetime"],
        refresh_expire_datetime=token_generated["refresh_expire_datetime"],
    )
    agent_config = api_call_generate_agent_config(
        token=token_generated, current_token=local_store["access_token"]
    )

    # Refresh tokens list
    tokens = api_call_list_tokens(
        current_token=local_store["access_token"], token_lifetime="long-lived"
    )

    # Format as YAML
    agent_config_yaml = yaml.dump(agent_config, default_flow_style=False)
    div_agent_config = _create_config_display(agent_config_yaml)

    return (
        False,
        False,
        render_tokens_list(tokens),
        True,  # Open display modal
        div_agent_config,
        delete_token_id,
        "",
        {"display": "none"},
        "",
    )


def register_tokens_management_callbacks(app: dash.Dash) -> None:
    """
    Register all callbacks for CLI token management.

    Registers callbacks for:
    - Copying configuration to clipboard
    - Opening/closing token naming modal
    - Saving new token configurations
    - Opening/closing delete confirmation modal
    - Confirming token deletion

    Args:
        app: The Dash application instance.
    """

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
        prevent_initial_call=True,
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
        """
        Main callback handler for token management actions.

        Routes to appropriate handler based on which button triggered the callback.
        """
        logger.info("Handling token management callbacks")
        triggered = ctx.triggered_id

        if not local_store:
            raise PreventUpdate

        user = api_call_fetch_user_from_token(local_store["access_token"])
        tokens = api_call_list_tokens(
            current_token=local_store["access_token"], token_lifetime="long-lived"
        )
        delete_token_id = delete_token_id or {}

        # Handle add token button
        if triggered == "add-token-button" and add_clicks:
            return _handle_add_token(tokens, delete_token_id)

        # Handle cancel buttons
        if triggered == "cancel-token-modal" and cancel_token_clicks:
            return _handle_cancel_modal(tokens, delete_token_id)

        if triggered == "cancel-delete-modal" and cancel_delete_clicks:
            return _handle_cancel_modal(tokens, delete_token_id)

        # Handle save token
        if triggered == "save-token-name" and save_clicks and token_name:
            logger.info(f"Token name: {token_name}")
            return _handle_save_token(token_name, tokens, delete_token_id, local_store, user)

        # Handle delete token button click
        if isinstance(triggered, dict) and triggered.get("type") == "delete-token":
            logger.info(f"{triggered}")
            return _handle_delete_token_click(tokens, triggered["index"])

        # Handle confirm delete
        if (
            triggered == "confirm-delete-button"
            and confirm_delete_clicks
            and delete_confirm_input == "delete"
        ):
            logger.info(f"Deleting config {delete_token_id}")
            return _handle_confirm_delete(tokens, delete_token_id)

        # Default response
        return _create_default_response(tokens, {})
