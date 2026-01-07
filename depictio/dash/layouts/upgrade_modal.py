"""
Upgrade modal component for transitioning from anonymous to temporary user.
"""

import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_upgrade_to_temporary_user


def create_upgrade_modal():
    """Create the upgrade to temporary user modal."""
    return dmc.Modal(
        id="upgrade-modal",
        title="Enable Interactive Features",
        centered=True,
        size="md",
        children=[
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:account-arrow-up", width=30, color="blue"),
                            dmc.Title("Upgrade to Interactive Mode", order=3, c="blue"),
                        ],
                        gap="sm",
                    ),
                    dmc.Text(
                        "To duplicate or modify dashboards, you need an interactive session. "
                        "This will create a temporary account that expires in 24 hours.",
                        size="sm",
                        c="gray",
                    ),
                    dmc.Alert(
                        title="What you'll get:",
                        icon=DashIconify(icon="mdi:information"),
                        children=[
                            dmc.List(
                                [
                                    dmc.ListItem("• Ability to duplicate and modify dashboards"),
                                    dmc.ListItem("• Your own isolated workspace"),
                                    dmc.ListItem("• All changes auto-save to your session"),
                                    dmc.ListItem("• Session expires automatically in 24 hours"),
                                ]
                            ),
                        ],
                        color="blue",
                        variant="light",
                    ),
                    dmc.Group(
                        [
                            dmc.Button(
                                "Cancel",
                                id="upgrade-cancel-button",
                                variant="outline",
                                color="gray",
                            ),
                            dmc.Button(
                                [
                                    "Enable Interactive Mode ",
                                    DashIconify(icon="mdi:arrow-right", width=16),
                                ],
                                id="upgrade-confirm-button",
                                variant="filled",
                                color="blue",
                            ),
                        ],
                        justify="flex-end",
                        mt="md",
                    ),
                ],
                gap="md",
            ),
        ],
        opened=False,
    )


def register_upgrade_modal_callbacks(app):
    """Register callbacks for the upgrade modal."""

    @app.callback(
        Output("upgrade-modal", "opened"),
        [
            Input("upgrade-trigger", "n_clicks"),
            Input("upgrade-cancel-button", "n_clicks"),
            Input("upgrade-confirm-button", "n_clicks"),
        ],
        [State("upgrade-modal", "opened")],
        prevent_initial_call=True,
    )
    def toggle_upgrade_modal(trigger_clicks, cancel_clicks, confirm_clicks, is_open):
        """Toggle the upgrade modal visibility."""
        ctx = dash.callback_context
        if not ctx.triggered:
            return is_open

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if button_id == "upgrade-trigger":
            return True
        elif button_id in ["upgrade-cancel-button", "upgrade-confirm-button"]:
            return False

        return is_open

    @app.callback(
        [
            Output("local-store", "data", allow_duplicate=True),
            Output("upgrade-feedback", "children"),
        ],
        [Input("upgrade-confirm-button", "n_clicks")],
        [State("local-store", "data")],
        prevent_initial_call=True,
    )
    def handle_upgrade_confirmation(confirm_clicks, local_data):
        """Handle the upgrade confirmation."""
        if not confirm_clicks or not local_data:
            return dash.no_update, dash.no_update

        if not settings.auth.unauthenticated_mode:
            return dash.no_update, dmc.Alert(
                "Upgrade not available - not in unauthenticated mode",
                color="red",
                id="upgrade-error-alert",
            )

        # Check if already temporary user
        if local_data.get("is_temporary", False):
            return dash.no_update, dmc.Alert(
                "You already have an interactive session!",
                color="orange",
                id="upgrade-warning-alert",
            )

        # Attempt to upgrade
        try:
            access_token = local_data.get("access_token")
            if not access_token:
                return dash.no_update, dmc.Alert(
                    "Error: No access token found", color="red", id="upgrade-error-alert"
                )

            upgrade_result = api_call_upgrade_to_temporary_user(
                access_token,
                expiry_hours=settings.auth.temporary_user_expiry_hours,
            )

            if upgrade_result:
                logger.info("Successfully upgraded to temporary user")
                return upgrade_result, dmc.Alert(
                    "Successfully upgraded to interactive mode!",
                    color="green",
                    id="upgrade-success-alert",
                )
            else:
                return dash.no_update, dmc.Alert(
                    "Failed to upgrade - please try again", color="red", id="upgrade-error-alert"
                )

        except Exception as e:
            logger.error(f"Error during upgrade: {e}")
            return dash.no_update, dmc.Alert(
                f"Error during upgrade: {str(e)}", color="red", id="upgrade-error-alert"
            )


# Hidden trigger button for the upgrade modal
upgrade_trigger_button = html.Button(id="upgrade-trigger", style={"display": "none"}, n_clicks=0)

# Feedback area for upgrade messages
upgrade_feedback = html.Div(id="upgrade-feedback")

# Complete upgrade component layout
upgrade_layout = html.Div(
    [
        upgrade_trigger_button,
        upgrade_feedback,
        create_upgrade_modal(),
    ]
)
