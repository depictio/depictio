import dash
import dash_bootstrap_components as dbc
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
from depictio.dash.colors import colors  # Import our color palette
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
layout = dbc.Container(
    [
        dmc.Paper(
            shadow=CARD_SHADOW,
            radius=CARD_RADIUS,
            p=CARD_PADDING,
            withBorder=True,
            # style={"borderColor": colors["teal"], "borderWidth": "2px"},
            children=[
                dbc.Row(
                    [
                        # Left side - Avatar with improved styling
                        dbc.Col(
                            dmc.Paper(
                                radius=CARD_RADIUS,
                                p="xl",
                                # withBorder=True,
                                shadow=CARD_SHADOW,
                                style={
                                    "backgroundColor": colors["purple"]
                                    + "10",  # Light purple background
                                    # "borderColor": colors["purple"],
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "minHeight": "200px",
                                    "minWidth": "200px",
                                },
                                children=[avatar],
                            ),
                            width="auto",
                            className="me-5",
                        ),
                        # Right side - User info and buttons
                        dbc.Col(
                            [
                                # Header with title and decorative line
                                dmc.Group(
                                    [
                                        dmc.Title(
                                            "User Profile",
                                            order=2,
                                            c=colors["black"],
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
                                            disabled=False,  # Enable logout button even in unauthenticated mode
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
                                                disabled=settings.auth.unauthenticated_mode,
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
                            width=True,
                        ),
                    ],
                    align="start",
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


def register_profile_callbacks(app):
    @app.callback(
        enrich_Output("save-password", "n_clicks"),
        enrich_Input("edit-password-modal-listener", "n_events"),
        enrich_State("edit-password-modal-listener", "event"),
    )
    def trigger_save_on_enter(n_events, e):
        if e is None or e["key"] != "Enter":
            raise PreventUpdate()
        return 1  # Simulate a click on the save button

    # Callback to edit user password
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
        ctx = dash.callback_context

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"triggered_id: {triggered_id}")

        if not local_data or "access_token" not in local_data:
            return (
                False,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        current_user = api_call_fetch_user_from_token(local_data["access_token"])

        if triggered_id == "old-password":
            if _check_password(current_user.email, old_password):
                return (
                    True,
                    "Old password is correct",
                    {"display": "none"},
                    False,
                    dash.no_update,
                    dash.no_update,
                )
            else:
                return (
                    True,
                    "Old password is incorrect",
                    {"display": "block", "color": colors["pink"]},
                    True,
                    dash.no_update,
                    dash.no_update,
                )

        elif triggered_id == "new-password":
            return (
                is_open,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        elif triggered_id == "confirm-new-password":
            if new_password != confirm_new_password:
                return (
                    True,
                    "Passwords do not match",
                    {"display": "block", "color": colors["pink"]},
                )
            else:
                return (
                    is_open,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

        elif triggered_id == "save-password":
            if not old_password or not new_password or not confirm_new_password:
                return (
                    True,
                    "Please fill all fields",
                    {"display": "block", "color": colors["pink"]},
                    True,
                    True,
                    True,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )
            if _check_password(current_user.email, old_password):
                if new_password != confirm_new_password:
                    return (
                        True,
                        "Passwords do not match",
                        {"display": "block", "color": colors["pink"]},
                        False,
                        True,
                        True,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                elif new_password == old_password:
                    return (
                        True,
                        "New password cannot be the same as old password",
                        {"display": "block", "color": colors["pink"]},
                        False,
                        True,
                        True,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                else:
                    response = api_call_edit_password(
                        old_password,
                        new_password,
                        local_data["access_token"],
                    )
                    if response["success"]:
                        return (
                            True,
                            "Password updated successfully",
                            {"display": "block", "color": colors["green"]},
                            False,
                            False,
                            False,
                            "",
                            "",
                            "",
                        )
                    else:
                        return (
                            True,
                            "Error updating password - please try again",
                            {"display": "block", "color": colors["pink"]},
                            True,
                            True,
                            True,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                        )
            else:
                return (
                    True,
                    "Old password is incorrect",
                    {"display": "block", "color": colors["pink"]},
                    True,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

        elif triggered_id == "edit-password":
            logger.info("Edit password triggered")
            return (
                True,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        else:
            return (
                is_open,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

    # Callback to populate user information based on email
    @app.callback(
        [
            Output("avatar-placeholder", "children"),
            Output("user-info-placeholder", "children"),
            Output("upgrade-to-temporary-button", "style"),
        ],
        [State("local-store", "data"), Input("url", "pathname")],
    )
    def populate_user_info(local_data, pathname):
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

        # Create more modern user info display with branded colors
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
                                    c=colors["black"],
                                    size="sm",
                                ),
                                dmc.Text(
                                    str(value),
                                    c=colors["black"],
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
                    # style={"borderColor": colors["teal"] + "50"}
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
