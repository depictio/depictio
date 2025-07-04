"""
Factory module for creating and configuring the Dash application.
"""

import os

import dash
import dash_bootstrap_components as dbc

from depictio.api.v1.configs.logging_init import logger

# Set environment context
os.environ["DEPICTIO_CONTEXT"] = "server"
from depictio.models.utils import get_depictio_context

DEPICTIO_CONTEXT = get_depictio_context()


def create_dash_app():
    """
    Create and configure a new Dash application instance.

    Returns:
        dash.Dash: Configured Dash application instance
    """
    # Check if in development mode
    dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"

    # Get the root path of the depictio.dash package
    dash_root_path = os.path.dirname(os.path.dirname(__file__))

    # Get the assets folder path
    assets_folder = os.path.join(dash_root_path, "assets")

    # Start the app
    app = dash.Dash(
        __name__,  # Use the current module name
        requests_pathname_prefix="/",
        external_stylesheets=[
            dbc.themes.BOOTSTRAP,
            {
                "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
                "rel": "stylesheet",
            },
        ],
        suppress_callback_exceptions=True,
        title="Depictio",
        assets_folder=assets_folder,
        assets_url_path="/assets",  # Explicitly set the assets URL path
    )

    # Configure Flask's logger to use custom logging settings
    server = app.server
    server.logger.handlers = logger.handlers  # type: ignore[possibly-unbound-attribute]
    server.logger.setLevel(logger.level)  # type: ignore[possibly-unbound-attribute]

    # Configure static folder for Flask server
    # This is separate from Dash's assets folder
    static_folder = os.path.join(dash_root_path, "static")
    server.static_folder = static_folder  # type: ignore[invalid-assignment]
    server.static_url_path = "/static"  # type: ignore[invalid-assignment]

    return app, dev_mode
