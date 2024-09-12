import dash_mantine_components as dmc
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, ctx
import httpx
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.configs.logging import logger


def register_admin_callbacks(app):
    @app.callback(
        Output("admin-management-content", "children"),
        Input("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def create_admin_management_content(pathname, local_data):
        if not local_data["access_token"]:
            return html.P("No access token found. Please log in.")
        user = fetch_user_from_token(local_data["access_token"])

        content = html.Div(
            f"Hi there! You are logged in as {user.email}.",
            style={"padding": "20px"},
        )

        return content
