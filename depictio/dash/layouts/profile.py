from datetime import datetime
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html, dcc, Input, Output, State
import dash
from depictio.api.v1.db import users_collection
from depictio.api.v1.configs.config import logger


# Function to find user by email
def find_user(email):
    return users_collection.find_one({"email": email})


# Layout placeholders
avatar = html.Div(id="avatar-placeholder")
user_info = html.Div(id="user-info-placeholder")

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
                                dbc.Col(html.A(dmc.Button("Back to Home", id="back-to-homepage", variant="outline", color="blue", style={"marginTop": "20px"}), href="/"), align="left", width="auto"),
                            ], align="left"
                        ),
                    ],
                    width=True,
                ),
            ],
            align="center",
            justify="center",
            className="mt-4",
        ),
    ],
    fluid=True,
)


def register_profile_callbacks(app):
    # Callback to populate user information based on email
    @app.callback([Output("avatar-placeholder", "children"), Output("user-info-placeholder", "children")], [State("session-store", "data"), Input("url", "pathname")])
    def populate_user_info(session_data, pathname):
        logger.info(f"session_data: {session_data}")
        if session_data is None or "email" not in session_data:
            return html.Div(), html.Div()

        user = find_user(session_data["email"])

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
            "Username": user.get("username", "N/A"),
            "Email": user.get("email", "N/A"),
            "Login Time": user.get("last_login", "N/A"),
            "Role": "Admin",  # Adjust this based on your actual role data
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
