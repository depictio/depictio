"""
Factory module for creating and configuring the Dash application.
"""

import os

import dash_bootstrap_components as dbc

# Import Celery background callback manager (Dash v3)
from celery import Celery

import dash
from dash import CeleryManager
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.components.google_analytics import integrate_google_analytics

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
    # assets_folder = os.path.join(dash_root_path, "assets/debug")
    assets_folder = os.path.join(dash_root_path, "assets")

    # Setup Celery background callback manager
    logger.info("🔧 DASH: Setting up Celery background callback manager...")

    # Import settings after context is set
    from depictio.api.v1.configs.config import settings

    # Reuse the backend Celery app instead of creating a new one
    try:
        from depictio.api.celery_app import celery_app

        logger.info("🔄 DASH: Reusing backend Celery app for background callbacks")
    except ImportError:
        logger.warning("⚠️ DASH: Backend Celery app not available, creating standalone app")
        # Fallback: create standalone app
        celery_app = Celery(
            "dash_background_callbacks",
            broker=settings.celery.broker_url,
            backend=settings.celery.result_backend_url,
        )

        celery_app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            result_expires=settings.celery.result_expires,
            task_soft_time_limit=settings.celery.task_soft_time_limit,
            task_time_limit=settings.celery.task_time_limit,
        )

    # Create the callback manager (Dash v3)
    background_callback_manager = CeleryManager(celery_app)

    logger.info("✅ DASH: Background callback manager configured")

    # Start the app with background callback manager
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
        background_callback_manager=background_callback_manager,  # Enable background callbacks
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

    # Integrate Google Analytics via index_string
    integrate_google_analytics(app, title="Depictio")

    # Setup profiling if enabled
    from depictio.dash.profiling import setup_profiling

    app = setup_profiling(app)

    return app, dev_mode
