from datetime import datetime
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State
import dash
from depictio.api.v1.db import users_collection
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.utils import find_user, edit_password, check_password
from dash_extensions.enrich import DashProxy, html, Input, Output, State
from dash_extensions import EventListener
from dash.exceptions import PreventUpdate

# Layout placeholders
avatar = html.Div(id="avatar-placeholder")
user_info = html.Div(id="user-info-placeholder")
event = {"event": "keydown", "props": ["key"]}

# Main layout
layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(avatar, width="auto"),
                dbc.Col(
                    [
                        html.H3("User Profile"),
                        user_info,
                        dbc.Row(
                            [
                                dbc.Col(dmc.Button("Logout", id="logout-button", variant="outline", color="red", style={"marginTop": "20px"}), align="left", width="auto"),
                                dbc.Col(
                                    html.A(dmc.Button("Back to Home", id="back-to-homepage", variant="outline", color="blue", style={"marginTop": "20px"}), href="/"),
                                    align="left",
                                    width="auto",
                                ),
                                dbc.Col(
                                    html.A(dmc.Button("Edit password", id="edit-password", variant="outline", color="blue", style={"marginTop": "20px"})),
                                    align="left",
                                    width="auto",
                                ),
                                dbc.Col(
                                    html.A(dmc.Button("CLI Agents", id="tokens-page-redirection", variant="outline", color="green", style={"marginTop": "20px"}), href="/tokens"),
                                    align="left",
                                    width="auto",
                                ),
                            ],
                            align="left",
                        ),
                    ],
                    width=True,
                ),
            ],
            align="center",
            justify="center",
            className="mt-4",
        ),
        dmc.Modal(
            id="edit-password-modal",
            opened=False,
            centered=True,
            withCloseButton=True,
            closeOnEscape=True,
            closeOnClickOutside=True,
            size="lg",
            title="Edit Password",
            children=[
                EventListener(
                    html.Div(
                        [
                            dmc.PasswordInput(
                                placeholder="Old Password",
                                label="Old Password",
                                id="old-password",
                            ),
                            dmc.PasswordInput(placeholder="New Password", label="New Password", id="new-password"),
                            dmc.PasswordInput(placeholder="Confirm New Password", label="Confirm New Password", id="confirm-new-password"),
                            dmc.Text(id="message-password", color="red", style={"display": "none"}),
                            dmc.Button("Save", color="blue", id="save-password"),
                        ]
                    ),
                    events=[event],
                    logging=True,
                    id="edit-password-modal-listener",
                ),
            ],
        ),
    ],
    fluid=True,
)


def register_profile_callbacks(app):
    @app.callback(Output("save-password", "n_clicks"), Input("edit-password-modal-listener", "n_events"), State("edit-password-modal-listener", "event"))
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
            # Input("old-password", "value"),
            # Input("new-password", "value"),
            # Input("confirm-new-password", "value"),
        ],
        [
            State("edit-password-modal", "open"),
            State("old-password", "value"),
            State("new-password", "value"),
            State("confirm-new-password", "value"),
            State("session-store", "data"),
        ],
    )
    def edit_password_callback(edit_clicks, save_clicks, is_open, old_password, new_password, confirm_new_password, session_data):
        ctx = dash.callback_context

        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"triggered_id: {triggered_id}")

        if not session_data or "email" not in session_data:
            return False, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # if triggered_id == "old-password":
        #     if check_password(session_data["email"], old_password):
        #         return True, "Old password is correct", {"display": "none"}, False, dash.no_update, dash.no_update
        #     else:
        #         return True, "Old password is incorrect", {"display": "block"}, True, dash.no_update, dash.no_update

        # elif triggered_id == "new-password":
        #     return is_open, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # elif triggered_id == "confirm-new-password":
        #     if new_password != confirm_new_password:
        #         return True, "Passwords do not match", {"display": "block"}
        #     else:
        #         return is_open, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        elif triggered_id == "save-password":
            if not old_password or not new_password or not confirm_new_password:
                return True, "Please fill all fields", {"display": "block"}, True, True, True, dash.no_update, dash.no_update, dash.no_update
            if check_password(session_data["email"], old_password):
                if new_password != confirm_new_password:
                    return True, "Passwords do not match", {"display": "block"}, False, True, True, dash.no_update, dash.no_update, dash.no_update
                elif new_password == old_password:
                    return True, "New password cannot be the same as old password", {"display": "block"}, False, True, True, dash.no_update, dash.no_update, dash.no_update
                else:
                    response = edit_password(session_data["email"], old_password, new_password)
                    if response.status_code == 200:
                        return True, "Password updated successfully", {"display": "block", "color": "green"}, False, False, False, "", "", ""
                    else:
                        return (
                            True,
                            "Error updating password - please try again",
                            {
                                "display": "block",
                            },
                            True,
                            True,
                            True,
                            dash.no_update,
                            dash.no_update,
                            dash.no_update,
                        )
            else:
                return True, "Old password is incorrect", {"display": "block"}, True, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        elif triggered_id == "edit-password":
            logger.info("Edit password triggered")
            return True, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update


        else:
            return is_open, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # Callback to populate user information based on email
    @app.callback([Output("avatar-placeholder", "children"), Output("user-info-placeholder", "children")], [State("session-store", "data"), Input("url", "pathname")])
    def populate_user_info(session_data, pathname):
        logger.info(f"session_data: {session_data}")
        if session_data is None or "email" not in session_data:
            return html.Div(), html.Div()

        user = find_user(session_data["email"])
        user = user.dict()

        if not user:
            return html.Div(), html.Div()

        avatar = html.A(
            dmc.Tooltip(
                dmc.Avatar(
                    src="https://e7.pngegg.com/pngimages/799/987/png-clipart-computer-icons-avatar-icon-design-avatar-heroes" "-computer-wallpaper-thumbnail.png",
                    size="lg",
                    radius="xl",
                ),
                label="",
                position="bottom",
            )
        )


        user_metadata = {
            "Email": user.get("email", "N/A"),
            "Registration Date": user.get("registration_date", "N/A"),
            "Admin": user.get("is_admin", "N/A"),
            "Groups": user.get("groups", "N/A"),
        }

        metadata_items = [dbc.ListGroupItem(f"{key}: {value}") for key, value in user_metadata.items()]

        metadata_list = dbc.ListGroup(metadata_items, flush=True)

        return avatar, metadata_list

    @app.callback(
        [Output("url", "pathname", allow_duplicate=True), Output("session-store", "data", allow_duplicate=True)], [Input("logout-button", "n_clicks")], prevent_initial_call=True
    )
    def logout_user(n_clicks):
        if n_clicks is None:
            return dash.no_update, dash.no_update

        return "/auth", {"logged_in": False, "email": None}
