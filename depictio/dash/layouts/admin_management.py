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
    badge_color = "green" if user.is_admin else "gray"
    badge_label = "Admin" if user.is_admin else "User"
    
    # Format dates for better readability
    registration_date = user.registration_date.strftime("%B %d, %Y %H:%M") if isinstance(user.registration_date, datetime.datetime) else user.registration_date
    last_login = user.last_login.strftime("%B %d, %Y %H:%M") if isinstance(user.last_login, datetime.datetime) else user.last_login
    
    layout = dmc.Card(
        children=[
            dmc.Group(
                position="left",
                style={"marginBottom": "15px"},
                children=[
                    dmc.Text(
                        user.email,
                        weight=500,
                        size="lg",
                        style={"flex": 1}
                    ),
                    dmc.Badge(
                        badge_label,
                        color=badge_color,
                        variant="light",
                        size="md",
                        radius="sm",
                    )
                ]
            ),
            dmc.Stack(
                # direction="column",
                spacing="xs",
                style={"marginBottom": "15px"},
                children=[
                    dmc.Text(f"Registration Date: {registration_date}", size="sm"),
                    dmc.Text(f"Last Login: {last_login}", size="sm"),
                    dmc.Text(f"Groups: {', '.join(user.groups) if user.groups else 'None'}", size="sm"),
                    dmc.Text(f"Account Status: {'Active' if user.is_active else 'Inactive'}", size="sm"),
                    dmc.Text(f"Verified: {'Yes' if user.is_verified else 'No'}", size="sm"),
                ]
            ),
            dmc.Group(
                spacing="xs",
                position="right",
                children=[
                    # dmc.Button(
                    #     [
                    #         DashIconify(icon="mdi:pencil", width=16, height=16),
                    #         " Edit"
                    #     ],
                    #     color="blue",
                    #     variant="filled",
                    #     size="sm",
                    #     id={"type": "edit-user-button", "index": str(user.id)},  # Replace `user.id` with the appropriate identifier
                    # ),
                    dmc.Button(
                        [
                            DashIconify(icon="mdi:delete", width=16, height=16),
                            " Delete"
                        ],
                        color="red",
                        variant="filled",
                        size="sm",
                        id={"type": "delete-user-button", "index": str(user.id)},  # Replace `user.id` with the appropriate identifier
                        styles={"root": {"marginLeft": "10px"}}
                    ),
                ]
            )
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        style=card_styles
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
