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

    # Check if background callbacks are enabled
    use_background = os.getenv("DEPICTIO_USE_BACKGROUND_CALLBACKS", "false").lower() == "true"

    # Setup background callback manager
    # Priority: Celery (if env enabled) → Diskcache (fallback)
    background_callback_manager = None

    if use_background:
        # Try Celery first when explicitly enabled
        logger.info("🔧 DASH: Background callbacks ENABLED - Setting up Celery manager...")
        try:
            from depictio.dash.celery_app import celery_app

            background_callback_manager = dash.CeleryManager(celery_app)
            logger.info("✅ DASH: Celery background callback manager configured")
        except Exception as e:
            logger.error(f"❌ DASH: Failed to setup Celery manager: {e}")
            logger.warning("⚠️  DASH: Falling back to diskcache...")
            background_callback_manager = None

    # Fallback to diskcache if Celery not available or not enabled
    if background_callback_manager is None:
        logger.info("🔧 DASH: Setting up diskcache background callback manager...")
        try:
            import diskcache

            cache = diskcache.Cache("/app/cache")
            background_callback_manager = dash.DiskcacheManager(cache)
            logger.info(
                f"✅ DASH: Diskcache background callback manager configured (cache: {cache.directory})"
            )
        except Exception as e:
            logger.error(f"❌ DASH: Failed to setup diskcache manager: {e}")
            logger.warning(
                "⚠️  DASH: No background callback manager available - callbacks will fail!"
            )
            background_callback_manager = None

    # Start the app with optional background callback manager
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
        include_assets_files=True,
        assets_folder=assets_folder,
        assets_url_path="/assets",  # Explicitly set the assets URL path
        background_callback_manager=background_callback_manager,  # Only set if enabled
        # show_undo_redo=False,
    )

    # Configure Flask's logger to use custom logging settings
    server = app.server
    server.logger.handlers = logger.handlers  # type: ignore[possibly-unbound-attribute]
    server.logger.setLevel(logger.level)  # type: ignore[possibly-unbound-attribute]

    # PERFORMANCE OPTIMIZATION: Configure Flask to use orjson for JSON serialization
    # orjson is 10-16x faster than standard json library
    try:
        import orjson
        from flask.json.provider import JSONProvider

        class OrjsonProvider(JSONProvider):
            """Custom JSON provider using orjson for faster serialization."""

            def dumps(self, obj, **kwargs):
                """Serialize obj to JSON bytes using orjson."""
                # orjson.dumps returns bytes, Flask expects str
                return orjson.dumps(obj).decode("utf-8")

            def loads(self, s, **kwargs):
                """Deserialize JSON string to Python object using orjson."""
                # Convert to bytes if needed (orjson.loads accepts bytes or str)
                if isinstance(s, str):
                    s = s.encode("utf-8")
                return orjson.loads(s)

        server.json = OrjsonProvider(server)
        logger.info(
            "✅ DASH: Configured Flask to use orjson for JSON serialization (10-16x faster)"
        )
    except ImportError:
        logger.warning(
            "⚠️  DASH: orjson not available, using standard json (consider installing: pip install orjson)"
        )

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
