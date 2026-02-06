"""
User profile page layout and callbacks for Depictio.

This module provides the user profile page including:
- User avatar and information display
- Password editing functionality with validation
- Logout functionality
- Upgrade from anonymous to temporary user (for unauthenticated mode)
- CLI configurations page link

Features:
    - Two-column layout with avatar and user information
    - Password modal with old/new/confirm password validation
    - Support for temporary user upgrades in unauthenticated mode
    - Session expiry information display

The layout uses Dash Mantine Components (dmc) for consistent styling with
the rest of the application.
"""

from typing import Any

import dash
import dash_mantine_components as dmc
from dash import Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate
from dash_extensions.enrich import Input as enrich_Input
from dash_extensions.enrich import Output as enrich_Output
from dash_extensions.enrich import State as enrich_State
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _check_password
from depictio.api.v1.endpoints.user_endpoints.utils import logout_user
from depictio.dash.api_calls import (
    api_call_edit_password,
    api_call_fetch_user_from_token,
    api_call_upgrade_to_temporary_user,
)
from depictio.dash.colors import colors
from depictio.dash.layouts.layouts_toolbox import create_edit_password_modal

# Define consistent theme elements
CARD_SHADOW = "md"
CARD_RADIUS = "lg"
CARD_PADDING = "xl"
BUTTON_RADIUS = "md"
ICON_SIZE = 20

# Layout placeholders
avatar = html.Div(id="avatar-placeholder")
user_info = html.Div(id="user-info-placeholder")
event = {"event": "keydown", "props": ["key"]}

# Style the password modal with our color theme
password_modal = create_edit_password_modal(
    title="Edit Password",
    event=event,
)

# Main layout with improved styling
layout = dmc.Container(
    size="lg",
    p="xl",
    children=[
        dmc.Paper(
            shadow=CARD_SHADOW,
            radius=CARD_RADIUS,
            p=CARD_PADDING,
            withBorder=True,
            children=[
                dmc.SimpleGrid(
                    cols=2,
                    spacing="xl",
                    children=[
                        # Left side - Avatar with improved styling
                        dmc.Paper(
                            radius=CARD_RADIUS,
                            p="xl",
                            shadow=CARD_SHADOW,
                            style={
                                "display": "flex",
                                "alignItems": "center",
                                "justifyContent": "center",
                                "minHeight": "200px",
                                "minWidth": "200px",
                            },
                            children=[avatar],
                        ),
                        # Right side - User info and buttons
                        dmc.Stack(
                            gap="lg",
                            children=[
                                # Header with title and decorative line
                                dmc.Group(
                                    [
                                        dmc.Title(
                                            "User Profile",
                                            order=2,
                                            style={"fontWeight": 600},
                                        ),
                                        DashIconify(
                                            icon="mdi:account-circle",
                                            width=36,
                                            height=36,
                                            # color=colors["violet"],
                                        ),
                                    ],
                                    justify="space-between",
                                ),
                                dmc.Divider(
                                    variant="dashed",
                                    my="md",
                                    # color=colors["teal"],
                                    size="sm",
                                ),
                                # User information
                                dmc.Stack(
                                    [user_info],
                                    gap="md",
                                    style={"padding": "16px 0"},
                                ),
                                # Action buttons row with improved styling
                                dmc.Group(
                                    [
                                        dmc.Button(
                                            "Logout",
                                            id="logout-button",
                                            variant="filled",
                                            # color=colors["pink"],
                                            radius=BUTTON_RADIUS,
                                            disabled=settings.auth.is_single_user_mode,  # Disable in single-user mode
                                            leftSection=DashIconify(
                                                icon="mdi:logout", width=ICON_SIZE
                                            ),
                                            styles={
                                                "root": {
                                                    "boxShadow": "0 2px 5px rgba(0, 0, 0, 0.1)",
                                                    "transition": "all 0.2s ease",
                                                    "&:hover": {
                                                        "transform": "translateY(-2px)",
                                                        "boxShadow": "0 4px 8px rgba(0, 0, 0, 0.2)",
                                                        "backgroundColor": colors["red"],
                                                    },
                                                    "backgroundColor": colors["red"],
                                                },
                                            },
                                        ),
                                        dmc.Button(
                                            "Login as a temporary user",
                                            id="upgrade-to-temporary-button",
                                            variant="filled",
                                            radius=BUTTON_RADIUS,
                                            style={
                                                "display": "none"
                                            },  # Hidden by default, shown conditionally
                                            leftSection=DashIconify(
                                                icon="mdi:account-arrow-up", width=ICON_SIZE
                                            ),
                                            styles={
                                                "root": {
                                                    "boxShadow": "0 2px 5px rgba(0, 0, 0, 0.1)",
                                                    "transition": "all 0.2s ease",
                                                    "&:hover": {
                                                        "transform": "translateY(-2px)",
                                                        "boxShadow": "0 4px 8px rgba(0, 0, 0, 0.2)",
                                                        "backgroundColor": colors["blue"],
                                                    },
                                                    "backgroundColor": colors["blue"],
                                                },
                                            },
                                        ),
                                        html.A(
                                            dmc.Button(
                                                "Edit Password",
                                                id="edit-password",
                                                variant="filled",
                                                # color=colors["blue"],
                                                radius=BUTTON_RADIUS,
                                                disabled=settings.auth.is_single_user_mode
                                                or settings.auth.is_public_mode
                                                or settings.auth.is_demo_mode,
                                                leftSection=DashIconify(
                                                    icon="mdi:lock-outline",
                                                    width=ICON_SIZE,
                                                ),
                                                styles={
                                                    "root": {
                                                        "boxShadow": "0 2px 5px rgba(0, 0, 0, 0.1)",
                                                        "transition": "all 0.2s ease",
                                                        "&:hover": {
                                                            "transform": "translateY(-2px)",
                                                            "boxShadow": "0 4px 8px rgba(0, 0, 0, 0.2)",
                                                            "backgroundColor": colors["blue"],
                                                        },
                                                        "backgroundColor": colors["blue"],
                                                    }
                                                },
                                            )
                                        ),
                                        dcc.Link(
                                            dmc.Button(
                                                "CLI Agents",
                                                id="tokens-page-redirection",
                                                variant="filled",
                                                # color=colors["green"],
                                                radius=BUTTON_RADIUS,
                                                disabled=settings.auth.unauthenticated_mode,
                                                leftSection=DashIconify(
                                                    icon="mdi:console", width=ICON_SIZE
                                                ),
                                                styles={
                                                    "root": {
                                                        "boxShadow": "0 2px 5px rgba(0, 0, 0, 0.1)",
                                                        "transition": "all 0.2s ease",
                                                        "&:hover": {
                                                            "transform": "translateY(-2px)",
                                                            "boxShadow": "0 4px 8px rgba(0, 0, 0, 0.2)",
                                                            "backgroundColor": colors["green"],
                                                        },
                                                        "backgroundColor": colors["green"],
                                                    }
                                                },
                                            ),
                                            href="/cli_configs"
                                            if not settings.auth.unauthenticated_mode
                                            else "#",
                                        ),
                                    ],
                                    gap="md",
                                    justify="flex-start",
                                    mt="lg",
                                ),
                                # Upgrade feedback area
                                html.Div(id="upgrade-feedback", style={"marginTop": "1rem"}),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        # Password modal (kept as is)
        password_modal,
        # Upgrade confirmation modal
        dmc.Modal(
            id="upgrade-confirmation-modal",
            title="Login as a temporary user",
            centered=True,
            size="lg",
            children=[
                dmc.Stack(
                    [
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:account-arrow-up", width=30, color="blue"),
                                dmc.Title("Login as a temporary user?", order=3, c="blue"),
                            ],
                            gap="lg",
                        ),
                        dmc.Text(
                            "This will create a temporary account that expires in 24 hours, "
                            "allowing you to duplicate and modify dashboards.",
                            size="sm",
                            c="gray",
                        ),
                        dmc.Alert(
                            title="What you'll get:",
                            icon=DashIconify(icon="mdi:information"),
                            children=[
                                dmc.List(
                                    [
                                        dmc.ListItem(
                                            "• Ability to duplicate and modify dashboards"
                                        ),
                                        dmc.ListItem("• Your own isolated workspace"),
                                        dmc.ListItem("• All changes auto-save to your session"),
                                        dmc.ListItem(
                                            f"• Session expires automatically in {str(settings.auth.temporary_user_expiry_hours)}:{str(settings.auth.temporary_user_expiry_minutes).zfill(2)} hours:minutes"
                                        ),
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
                                    id="upgrade-modal-cancel",
                                    variant="outline",
                                    color="gray",
                                ),
                                dmc.Button(
                                    [
                                        "Login as a temporary user ",
                                        DashIconify(icon="mdi:arrow-right", width=16),
                                    ],
                                    id="upgrade-modal-confirm",
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
        ),
    ],
    fluid=True,
    className="py-4",
)


def _create_password_error_response(
    message: str,
    old_error: bool = False,
    new_error: bool = False,
    confirm_error: bool = False,
) -> tuple:
    """
    Create a standardized error response for password validation.

    Args:
        message: Error message to display.
        old_error: Whether to mark old password field as error.
        new_error: Whether to mark new password field as error.
        confirm_error: Whether to mark confirm password field as error.

    Returns:
        Tuple of callback outputs for the password modal.
    """
    return (
        True,  # Keep modal open
        message,
        {"display": "block", "color": colors["pink"]},
        old_error,
        new_error,
        confirm_error,
        dash.no_update,
        dash.no_update,
        dash.no_update,
    )


def _create_password_success_response(message: str) -> tuple:
    """
    Create a success response for password change.

    Args:
        message: Success message to display.

    Returns:
        Tuple of callback outputs with cleared form fields.
    """
    return (
        True,  # Keep modal open to show success
        message,
        {"display": "block", "color": colors["green"]},
        False,
        False,
        False,
        "",  # Clear old password
        "",  # Clear new password
        "",  # Clear confirm password
    )


def _validate_password_fields(
    old_password: str | None,
    new_password: str | None,
    confirm_new_password: str | None,
    current_user_email: str,
    access_token: str,
) -> tuple | None:
    """
    Validate password fields and attempt password change if valid.

    Args:
        old_password: Current password entered by user.
        new_password: New password entered by user.
        confirm_new_password: Confirmation of new password.
        current_user_email: Email of the current user for password verification.
        access_token: User's access token for API call.

    Returns:
        Tuple of callback outputs, or None if validation passes without issues.
    """
    # Check all fields are filled
    if not old_password or not new_password or not confirm_new_password:
        return _create_password_error_response(
            "Please fill all fields",
            old_error=True,
            new_error=True,
            confirm_error=True,
        )

    # Verify old password
    if not _check_password(current_user_email, old_password):
        return _create_password_error_response("Old password is incorrect", old_error=True)

    # Check passwords match
    if new_password != confirm_new_password:
        return _create_password_error_response(
            "Passwords do not match", new_error=True, confirm_error=True
        )

    # Check new password is different
    if new_password == old_password:
        return _create_password_error_response(
            "New password cannot be the same as old password",
            new_error=True,
            confirm_error=True,
        )

    # Attempt to change password
    response = api_call_edit_password(old_password, new_password, access_token)

    if response["success"]:
        return _create_password_success_response("Password updated successfully")
    else:
        return _create_password_error_response(
            "Error updating password - please try again",
            old_error=True,
            new_error=True,
            confirm_error=True,
        )


def register_profile_callbacks(app: dash.Dash) -> None:
    """
    Register all callbacks for the user profile page.

    Registers callbacks for:
    - Password editing modal and validation
    - User information display
    - Logout functionality
    - Upgrade to temporary user functionality

    Args:
        app: The Dash application instance.
    """

    @app.callback(
        enrich_Output("save-password", "n_clicks"),
        enrich_Input("edit-password-modal-listener", "n_events"),
        enrich_State("edit-password-modal-listener", "event"),
    )
    def trigger_save_on_enter(n_events: int, e: dict[str, Any] | None) -> int:
        """Trigger save button click when Enter key is pressed in modal."""
        if e is None or e["key"] != "Enter":
            raise PreventUpdate()
        return 1

    @app.callback(
        [
            Output("edit-password-modal", "opened"),
            Output("message-password", "children"),
            Output("message-password", "style"),
            Output("old-password", "error"),
            Output("new-password", "error"),
            Output("confirm-new-password", "error"),
            Output("old-password", "value"),
            Output("new-password", "value"),
            Output("confirm-new-password", "value"),
        ],
        [
            Input("edit-password", "n_clicks"),
            Input("save-password", "n_clicks"),
        ],
        [
            State("edit-password-modal", "open"),
            State("old-password", "value"),
            State("new-password", "value"),
            State("confirm-new-password", "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def edit_password_callback(
        edit_clicks,
        save_clicks,
        is_open,
        old_password,
        new_password,
        confirm_new_password,
        local_data,
    ):
        """
        Handle password editing modal interactions.

        Routes to appropriate handler based on which input triggered the callback.
        Validates password fields and handles password change API calls.
        """
        ctx = dash.callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"triggered_id: {triggered_id}")

        # Check for valid local data
        if not local_data or "access_token" not in local_data:
            return (False,) + (dash.no_update,) * 8

        current_user = api_call_fetch_user_from_token(local_data["access_token"])

        # Handle edit password button - open modal
        if triggered_id == "edit-password":
            logger.info("Edit password triggered")
            return (True,) + (dash.no_update,) * 8

        # Handle save password button
        if triggered_id == "save-password":
            return _validate_password_fields(
                old_password,
                new_password,
                confirm_new_password,
                current_user.email,
                local_data["access_token"],
            )

        # Default - keep current state
        return (is_open,) + (dash.no_update,) * 8

    @app.callback(
        [
            Output("avatar-placeholder", "children"),
            Output("user-info-placeholder", "children"),
            Output("upgrade-to-temporary-button", "style"),
        ],
        [State("local-store", "data"), Input("url", "pathname")],
    )
    def populate_user_info(local_data, pathname):
        """
        Populate user avatar and information display.

        Fetches user data from the API and renders the avatar with initials
        and a list of user metadata (email, ID, registration date, etc.).
        Also determines visibility of the upgrade-to-temporary button.
        """
        logger.info(f"URL pathname: {pathname}")
        logger.info(f"session_data: {local_data}")
        if local_data is None or "access_token" not in local_data:
            return html.Div(), html.Div(), {"display": "none"}

        user = api_call_fetch_user_from_token(local_data["access_token"])
        logger.info(f"PROFILE user: {user}")

        if user is None:
            return html.Div(), html.Div(), {"display": "none"}

        user = user.model_dump()

        if not user:
            return html.Div(), html.Div(), {"display": "none"}

        # Use the Depictio brand color for avatar background
        avatar = html.Div(
            dmc.Avatar(
                src=f"https://ui-avatars.com/api/?format=svg&name={user.get('email', 'N/A')}&background={colors['purple'].replace('#', '')}&color=white&rounded=true&bold=true&format=svg&size=160",
                size="xl",
                radius="xl",
                styles={
                    "root": {
                        # "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.15)",
                        # "border": f"3px solid {colors['teal']}",
                    }
                },
            ),
            style={"textAlign": "center"},
        )

        user_metadata = {
            "Email": user.get("email", "N/A"),
            "Database ID": user.get("id", "N/A"),
            "Registration Date": user.get("registration_date", "N/A"),
            "Last login": user.get("last_login", "N/A"),
            "Admin": "Yes" if user.get("is_admin", False) else "No",
        }

        # Create more modern user info display with theme-aware colors
        info_items = []
        for key, value in user_metadata.items():
            info_items.append(
                dmc.Paper(
                    children=[
                        dmc.Group(
                            [
                                dmc.Text(
                                    key,
                                    fw="bold",
                                    size="sm",
                                ),
                                dmc.Text(
                                    str(value),
                                    fw="normal",
                                    size="sm",
                                ),
                            ],
                            justify="space-between",
                        )
                    ],
                    p="sm",
                    radius="md",
                    withBorder=True,
                )
            )

        user_info_display = dmc.Stack(info_items, gap="xs")

        # Determine if upgrade button should be visible
        # Show button in unauthenticated mode for anonymous users (not temporary)
        show_upgrade_button = (
            settings.auth.unauthenticated_mode
            and user.get("is_anonymous", False)
            and not user.get("is_temporary", False)
        )

        upgrade_button_style = {"display": "block"} if show_upgrade_button else {"display": "none"}

        return avatar, user_info_display, upgrade_button_style

    @app.callback(
        [
            Output("url", "pathname", allow_duplicate=True),
            Output("local-store", "data", allow_duplicate=True),
        ],
        [Input("logout-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def logout_user_callback(n_clicks):
        """Handle logout button click - clear session and redirect to auth page."""
        logger.info(f"Logout button clicked: {n_clicks}")
        if n_clicks is None:
            return dash.no_update, dash.no_update

        return "/auth", logout_user()

    @app.callback(
        Output("upgrade-confirmation-modal", "opened"),
        [Input("upgrade-to-temporary-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def show_upgrade_modal(n_clicks):
        """Show upgrade confirmation modal when button is clicked."""
        if n_clicks is None:
            return False
        return True

    @app.callback(
        Output("upgrade-confirmation-modal", "opened", allow_duplicate=True),
        [Input("upgrade-modal-cancel", "n_clicks")],
        prevent_initial_call=True,
    )
    def close_upgrade_modal(n_clicks):
        """Close upgrade confirmation modal when cancel is clicked."""
        if n_clicks is None:
            return dash.no_update
        return False

    @app.callback(
        [
            Output("local-store", "data", allow_duplicate=True),
            Output("upgrade-feedback", "children"),
            Output("url", "pathname", allow_duplicate=True),
            Output("upgrade-confirmation-modal", "opened", allow_duplicate=True),
        ],
        [Input("upgrade-modal-confirm", "n_clicks")],
        [State("local-store", "data")],
        prevent_initial_call=True,
    )
    def upgrade_to_temporary_callback(n_clicks, local_data):
        """Handle upgrade from anonymous to temporary user after confirmation."""
        logger.info(f"Upgrade confirm button clicked: {n_clicks}")
        if n_clicks is None:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not local_data or "access_token" not in local_data:
            return (
                dash.no_update,
                dmc.Alert("Error: No access token found", color="red", title="Upgrade Failed"),
                dash.no_update,
                False,
            )

        if not settings.auth.unauthenticated_mode:
            return (
                dash.no_update,
                dmc.Alert(
                    "Upgrade not available - not in unauthenticated mode",
                    color="red",
                    title="Upgrade Not Available",
                ),
                dash.no_update,
                False,
            )

        # Attempt to upgrade
        try:
            access_token = local_data.get("access_token")
            upgrade_result = api_call_upgrade_to_temporary_user(
                access_token,
                expiry_hours=settings.auth.temporary_user_expiry_hours,
            )

            if upgrade_result:
                logger.info("Successfully upgraded to temporary user")
                # Update local store and redirect to profile page to refresh UI
                return (
                    upgrade_result,
                    dmc.Alert(
                        "Successfully upgraded to interactive mode! You can now duplicate and modify dashboards. Your session will expire in 24 hours.",
                        color="green",
                        title="Upgrade Successful",
                    ),
                    "/profile",
                    False,
                )
            else:
                return (
                    dash.no_update,
                    dmc.Alert(
                        "You are already a temporary user or upgrade failed - please try again",
                        color="orange",
                        title="Upgrade Not Needed",
                    ),
                    dash.no_update,
                    False,
                )

        except Exception as e:
            logger.error(f"Error during upgrade: {e}")
            return (
                dash.no_update,
                dmc.Alert(f"Error during upgrade: {str(e)}", color="red", title="Upgrade Error"),
                dash.no_update,
                False,
            )
