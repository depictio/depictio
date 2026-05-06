"""Auth sign-in modal for public mode.

This module provides a modal component for public Depictio instances that
allows users to sign in with Google (when OAuth is enabled). Public-mode
visitors automatically receive a temporary user session at boot, so the
"Sign in as Temporary User" affordance has been removed — Google OAuth is
the only remaining path to a persistent account.

The modal is displayed when users click "Sign in" in public mode.
"""

import dash_mantine_components as dmc
from dash import Input, Output, dcc, html
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_get_google_oauth_login_url
from depictio.dash.colors import colors


def create_auth_sign_in_modal() -> dmc.Modal:
    """Create the auth sign-in modal for public mode.

    Returns:
        Modal component with sign-in options.
    """
    sign_in_options: list = []

    # Google OAuth option (only if enabled)
    if settings.auth.google_oauth_enabled:
        sign_in_options.append(
            dmc.Paper(
                children=[
                    dmc.Group(
                        [
                            DashIconify(
                                icon="devicon:google",
                                height=28,
                            ),
                            dmc.Stack(
                                [
                                    dmc.Text(
                                        "Sign in with Google",
                                        fw=500,
                                        size="md",
                                    ),
                                    dmc.Text(
                                        "Persistent account",
                                        size="sm",
                                        c="dimmed",
                                    ),
                                ],
                                gap=2,
                            ),
                        ],
                        gap="md",
                    ),
                ],
                id="auth-modal-google-button",
                p="md",
                radius="md",
                withBorder=True,
                style={
                    "cursor": "pointer",
                    "transition": "all 0.2s ease",
                    "borderColor": "var(--app-border-color, #ddd)",
                },
                className="auth-option-card",
            )
        )

    return dmc.Modal(
        id="public-auth-modal",
        title=dmc.Group(
            [
                DashIconify(icon="mdi:login", height=24, color=colors["orange"]),
                dmc.Text("Sign In to Depictio", fw=600, size="lg"),
            ],
            gap="sm",
        ),
        opened=False,
        centered=True,
        size="md",
        children=[
            dmc.Stack(
                sign_in_options,
                gap="md",
            ),
            # Hidden stores and elements for OAuth flow
            dcc.Store(id="auth-modal-loading-store", data=False),
            html.A(
                id="auth-modal-google-redirect",
                href="",
                target="_self",
                style={"display": "none"},
            ),
        ],
        overlayProps={"opacity": 0.55, "blur": 3},
    )


def create_public_mode_sign_in_button() -> html.Div:
    """Create a sign-in button for public mode that opens the auth modal.

    Returns:
        Div containing the sign-in button (hidden if not in public mode).
    """
    if not settings.auth.is_public_mode:
        return html.Div(id="public-sign-in-button-container", style={"display": "none"})

    return html.Div(
        id="public-sign-in-button-container",
        children=[
            dmc.Button(
                "Sign In",
                id="public-sign-in-button",
                leftSection=DashIconify(icon="mdi:login", height=18),
                variant="outline",
                color=colors["blue"],
                size="sm",
            ),
        ],
    )


def register_auth_modal_callbacks(app) -> None:
    """Register callbacks for the public mode auth modal.

    Args:
        app: Dash application instance.
    """
    # Only register callbacks if public mode is possible
    # (callbacks need to exist even if mode is disabled for component existence)

    @app.callback(
        Output("public-auth-modal", "opened"),
        Input("public-sign-in-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_auth_modal(n_clicks):
        """Open the auth modal when sign-in button is clicked."""
        if not n_clicks:
            raise PreventUpdate
        return True

    # Google OAuth button handler (only if enabled)
    if settings.auth.google_oauth_enabled:

        @app.callback(
            Output("auth-modal-google-redirect", "href"),
            Input("auth-modal-google-button", "n_clicks"),
            prevent_initial_call=True,
        )
        def handle_google_oauth_from_modal(n_clicks):
            """Initiate Google OAuth flow from the auth modal."""
            if not n_clicks:
                raise PreventUpdate

            try:
                oauth_data = api_call_get_google_oauth_login_url()
                if oauth_data and "authorization_url" in oauth_data:
                    logger.info("Redirecting to Google OAuth from auth modal")
                    return oauth_data["authorization_url"]
                else:
                    logger.error("Failed to get OAuth URL")
                    raise PreventUpdate
            except Exception as e:
                logger.error(f"Error initiating Google OAuth: {e}")
                raise PreventUpdate

        # JavaScript redirect for Google OAuth
        app.clientside_callback(
            """
            function(href) {
                if (href && href !== "") {
                    window.location.href = href;
                }
                return window.dash_clientside.no_update;
            }
            """,
            Output("auth-modal-google-redirect", "target"),
            Input("auth-modal-google-redirect", "href"),
            prevent_initial_call=True,
        )
