import datetime
import dash_mantine_components as dmc
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, ctx
import httpx
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import User


def render_userwise_layout(user):
    user = User.from_mongo(user)

    # Define styles and colors
    card_styles = {
        "boxShadow": "0 4px 6px rgba(0, 0, 0, 0.1)",
        "borderRadius": "8px",
        "padding": "20px",
        "marginBottom": "20px",
    }

    # Badge color based on admin status
    badge_color = "blue" if user.is_admin else "gray"
    badge_label = "System Admin" if user.is_admin else "User"

    # Format dates for better readability
    registration_date = user.registration_date.strftime("%B %d, %Y %H:%M") if isinstance(user.registration_date, datetime.datetime) else user.registration_date
    last_login = user.last_login.strftime("%B %d, %Y %H:%M") if isinstance(user.last_login, datetime.datetime) else user.last_login

    layout = dmc.Accordion(
        children=[
            # dmc.Group(
            #     # position="",
            #     style={"marginBottom": "15px"},
            #     children=[
            dmc.AccordionItem(
                [
                    dmc.AccordionControl(
                        [
                            dmc.Group(
                                [
                                    dmc.Text(user.email, weight=500, size="lg", style={"flex": 1}),
                                    dmc.Badge(
                                        badge_label,
                                        color=badge_color,
                                        variant="light",
                                        size="md",
                                        radius="sm",
                                    ),
                                ],
                                position="apart",
                            ),
                        ]
                    ),
                    dmc.AccordionPanel(
                        [
                            dmc.Group(
                                spacing="xs",
                                position="apart",
                                children=[
                                    dmc.Stack(
                                        spacing="xs",
                                        style={"marginBottom": "15px"},
                                        children=[
                                            dmc.Group(
                                                [
                                                    dmc.Text("Registration Date: ", weight=700, size="sm"),
                                                    dmc.Text(registration_date, size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Last Login: ", weight=700, size="sm"),
                                                    dmc.Text(last_login, size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Groups: ", weight=700, size="sm"),
                                                    dmc.List([dmc.ListItem(group) for group in user.groups] if user.groups else [dmc.ListItem("None")], size="sm"),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Account Status: ", weight=700, size="sm"),
                                                    dmc.Badge(
                                                        "Active" if user.is_active else "Inactive",
                                                        color="green" if user.is_active else "red",
                                                        variant="light",
                                                        size="sm",
                                                        radius="sm",
                                                    ),
                                                ]
                                            ),
                                            dmc.Group(
                                                [
                                                    dmc.Text("Verified: ", weight=700, size="sm"),
                                                    dmc.Text("Yes" if user.is_verified else "No", size="sm"),
                                                ]
                                            ),
                                        ],
                                    ),
                                    # dmc.Button(
                                    #     [DashIconify(icon="mdi:delete", width=16, height=16), " Delete"],
                                    #     color="red",
                                    #     variant="filled",
                                    #     size="sm",
                                    #     id={"type": "delete-user-button", "index": str(user.id)},  # Replace user.id with the appropriate identifier
                                    #     styles={"root": {"marginLeft": "10px"}},
                                    # ),
                                ],
                            ),
                            #     ],
                            # ),
                        ],
                    ),
                ],
                value=str(user.id),
            ),
        ],
        # withBorder=True,
        # shadow="sm",
        radius="md",
        # style=card_styles,
    )

    return layout


def register_admin_callbacks(app):
    @app.callback(
        Output("admin-management-content", "children"),
        Input("url", "pathname"),
        Input("admin-tabs", "value"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def create_admin_management_content(pathname, active_tab, local_data):
        if not local_data["access_token"]:
            return html.P("No access token found. Please log in.")

        # content = html.Div(
        #     f"Hi there! You are logged in as {user.email}.",
        #     style={"padding": "20px"},
        # )

        if active_tab == "users":
            response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/list", headers={"Authorization": f"Bearer {local_data['access_token']}"})
            logger.info(f"Response: {response}")
            if response.status_code == 200:
                users = response.json()
                userwise_layouts = [render_userwise_layout(user) for user in users]
                content = html.Div(userwise_layouts)
            else:
                logger.error(f"Error fetching users: {response.json()}")
                content = html.P("Error fetching users. Please try again later.")

            return content
        else:
            return html.P("Under construction.")
