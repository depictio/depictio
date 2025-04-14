import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, Input, Output, State, dcc
import dash
from depictio.api.v1.configs.custom_logging import logger
from depictio.api.v1.endpoints.user_endpoints.utils import (
    edit_password,
    check_password,
    logout_user,
)
from dash_extensions.enrich import (
    Output as enrich_Output,
    Input as enrich_Input,
    State as enrich_State,
)
from dash_extensions import EventListener
from dash.exceptions import PreventUpdate

from depictio.dash.api_calls import api_call_fetch_user_from_token

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
                                dbc.Col(
                                    dmc.Button(
                                        "Logout",
                                        id="logout-button",
                                        variant="outline",
                                        color="red",
                                        style={"marginTop": "20px"},
                                    ),
                                    align="left",
                                    width="auto",
                                ),
                                dbc.Col(
                                    html.A(
                                        dmc.Button(
                                            "Edit password",
                                            id="edit-password",
                                            variant="outline",
                                            color="blue",
                                            style={"marginTop": "20px"},
                                        )
                                    ),
                                    align="left",
                                    width="auto",
                                ),
                                dbc.Col(
                                    dcc.Link(
                                        dmc.Button(
                                            "CLI Agents",
                                            id="tokens-page-redirection",
                                            variant="outline",
                                            color="green",
                                            style={"marginTop": "20px"},
                                        ),
                                        href="/cli_configs",
                                    ),
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
                            dmc.PasswordInput(
                                placeholder="New Password",
                                label="New Password",
                                id="new-password",
                            ),
                            dmc.PasswordInput(
                                placeholder="Confirm New Password",
                                label="Confirm New Password",
                                id="confirm-new-password",
                            ),
                            dmc.Text(
                                id="message-password",
                                color="red",
                                style={"display": "none"},
                            ),
                            dmc.Button(
                                "Save",
                                color="blue",
                                id="save-password",
                                style={"marginTop": "20px"},
                            ),
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
            if check_password(current_user.email, old_password):
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
                    {"display": "block"},
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
                return True, "Passwords do not match", {"display": "block"}
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
                    {"display": "block"},
                    True,
                    True,
                    True,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )
            if check_password(current_user.email, old_password):
                if new_password != confirm_new_password:
                    return (
                        True,
                        "Passwords do not match",
                        {"display": "block"},
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
                        {"display": "block"},
                        False,
                        True,
                        True,
                        dash.no_update,
                        dash.no_update,
                        dash.no_update,
                    )
                else:
                    response = edit_password(
                        current_user.email,
                        old_password,
                        new_password,
                        headers={
                            "Authorization": f"Bearer {local_data['access_token']}"
                        },
                    )
                    if response.status_code == 200:
                        return (
                            True,
                            "Password updated successfully",
                            {"display": "block", "color": "green"},
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
                return (
                    True,
                    "Old password is incorrect",
                    {"display": "block"},
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
        ],
        [State("local-store", "data"), Input("url", "pathname")],
    )
    def populate_user_info(local_data, pathname):
        logger.info(f"URL pathname: {pathname}")
        logger.info(f"session_data: {local_data}")
        if local_data is None or "access_token" not in local_data:
            return html.Div(), html.Div()

        user = api_call_fetch_user_from_token(local_data["access_token"])
        logger.info(f"PROFILE user: {user}")
        user = user.dict()

        if not user:
            return html.Div(), html.Div()

        avatar = html.A(
            dmc.Avatar(
                # pastel blue: #AEC8FF
                src=f"https://ui-avatars.com/api/?format=svg&name={user.get('email', 'N/A')}&background=AEC8FF&color=white&rounded=true&bold=true&format=svg&size=16",
                size="lg",
                radius="xl",
            )
        )

        # user_groups = user.get("groups", "N/A")
        # user_groups = [group.get("name", "N/A") for group in user_groups if group["name"] not in ["admin", "users"]]
        user_metadata = {
            "Email": user.get("email", "N/A"),
            "Database ID": user.get("id", "N/A"),
            "Registration Date": user.get("registration_date", "N/A"),
            "Last login": user.get("last_login", "N/A"),
            "Admin": user.get("is_admin", "N/A"),
            # "Groups": f"[{', '.join(user_groups)}]"
        }

        metadata_items = [
            dbc.ListGroupItem(f"{key}: {value}") for key, value in user_metadata.items()
        ]

        metadata_list = dbc.ListGroup(metadata_items, flush=True)

        return avatar, metadata_list

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
