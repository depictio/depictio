"""
Admin security notifications for Depictio Dash application.
"""

import requests
from dash import Input, Output, no_update
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


def register_admin_notifications_callbacks(app):
    """
    Register callbacks for admin security notifications.

    Args:
        app (dash.Dash): The Dash application instance
    """

    @app.callback(
        Output("notification-container", "sendNotifications"),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
        ],
        prevent_initial_call=False,
    )
    def show_admin_password_warning(pathname, local_data):
        """
        Show warning notification if admin still has default password on specific routes.
        """
        # Only show on specific routes
        target_routes = ["/dashboards", "/profile", "/projects", "/about"]
        if pathname not in target_routes:
            return no_update

        # Only check if user is logged in
        if not local_data or not local_data.get("logged_in") or not local_data.get("access_token"):
            return no_update

        try:
            # Call API to check if admin has default password
            headers = {"Authorization": f"Bearer {local_data['access_token']}"}
            check_admin_default_password_url = (
                f"{settings.fastapi.url}/depictio/api/v1/auth/check_admin_default_password"
            )

            response = requests.get(check_admin_default_password_url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                if data.get("has_default_password", False):
                    # Show notification if admin has default password only for admin users

                    check_user_url = f"{settings.fastapi.url}/depictio/api/v1/auth/me"
                    user_response = requests.get(check_user_url, headers=headers, timeout=5)
                    if user_response.status_code == 200:
                        user_data = user_response.json()
                        if user_data.get("is_admin", False):
                            logger.warning("Admin still has default password")

                            return [
                                dict(
                                    id="admin-password-warning",
                                    title="Admin Security Warning",
                                    message="Your admin account still has the default password. Please change it for security reasons.",
                                    color="red",
                                    icon=DashIconify(icon="mdi:alert-circle", width=24),
                                    # autoClose=5000,
                                    autoClose=False,
                                    radius="xl",
                                    withCloseButton=False,
                                    position="bottom-center",
                                )
                            ]
        except Exception as e:
            logger.error(f"Error checking admin default password: {e}")

        return no_update
