"""
Factory module for creating and configuring the Dash application.
"""

import os

import dash

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

    # Import the Dash-side Celery app
    # from depictio.dash.celery_app import celery_app

    # background_callback_manager = dash.CeleryManager(celery_app)
    # logger.info("✅ DASH: Celery background callback manager configured")

    # import diskcache
    # cache = diskcache.Cache("/app/cache")
    # background_callback_manager = DiskcacheManager(cache)
    # logger.info(
    #     f"Diskcache background callback manager configured with cache path: {cache.directory}"
    # )

    # logger.info("✅ DASH: Background callback manager configured")

    # Start the app with background callback manager
    app = dash.Dash(
        __name__,  # Use the current module name
        requests_pathname_prefix="/",
        external_stylesheets=[
            {
                "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
                "rel": "stylesheet",
            },
        ],
        suppress_callback_exceptions=True,
        title="Depictio",
        assets_folder=assets_folder,
        assets_url_path="/assets",  # Explicitly set the assets URL path
        # background_callback_manager=background_callback_manager,  # Enable background callbacks
        # show_undo_redo=False,
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
