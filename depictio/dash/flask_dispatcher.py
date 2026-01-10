"""
Flask dispatcher module for multi-app Depictio architecture.

This module creates and manages three independent Dash applications:
1. Management App (/) - Auth, dashboards, projects, admin
2. Viewer App (/dashboard/) - Read-only dashboard viewing
3. Editor App (/dashboard-edit/) - Dashboard editing and component builder

Each app has its own callback registry for true isolation.
"""

import os

import dash
from flask import Flask, send_from_directory

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.components.google_analytics import integrate_google_analytics
from depictio.dash.pages import dashboard_editor, dashboard_viewer, management_app

# Set environment context
os.environ["DEPICTIO_CONTEXT"] = "server"
from depictio.models.utils import get_depictio_context

DEPICTIO_CONTEXT = get_depictio_context()


def create_shared_dash_config():
    """
    Create shared configuration for all Dash apps.

    Returns:
        tuple: (assets_folder, background_callback_manager, dev_mode)
    """
    # Check if in development mode
    dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"

    # Get the root path of the depictio.dash package
    dash_root_path = os.path.dirname(os.path.dirname(__file__))

    # Get the assets folder path
    assets_folder = os.path.join(dash_root_path, "assets")

    # Check if Celery is enabled
    use_celery = os.getenv("DEPICTIO_CELERY_ENABLED", "false").lower() == "true"

    # Setup background callback manager
    # Priority: Celery (if env enabled) → Diskcache (fallback)
    background_callback_manager = None

    if use_celery:
        # Try Celery first when explicitly enabled
        logger.info("🔧 FLASK DISPATCHER: Celery ENABLED - Setting up Celery manager...")
        try:
            from depictio.dash.celery_app import celery_app

            background_callback_manager = dash.CeleryManager(celery_app)
            logger.info("✅ FLASK DISPATCHER: Celery background callback manager configured")
        except Exception as e:
            logger.error(f"❌ FLASK DISPATCHER: Failed to setup Celery manager: {e}")
            logger.warning("⚠️  FLASK DISPATCHER: Falling back to diskcache...")
            background_callback_manager = None

    # Fallback to diskcache if Celery not available or not enabled
    if background_callback_manager is None:
        logger.info("🔧 FLASK DISPATCHER: Setting up diskcache background callback manager...")
        try:
            import diskcache

            cache = diskcache.Cache("/app/cache")
            background_callback_manager = dash.DiskcacheManager(cache)
            logger.info(
                f"✅ FLASK DISPATCHER: Diskcache background callback manager configured (cache: {cache.directory})"
            )
        except Exception as e:
            logger.error(f"❌ FLASK DISPATCHER: Failed to setup diskcache manager: {e}")
            logger.warning(
                "⚠️  FLASK DISPATCHER: No background callback manager available - callbacks will fail!"
            )
            background_callback_manager = None

    return assets_folder, background_callback_manager, dev_mode


def configure_flask_server(server: Flask, dash_root_path: str):
    """
    Configure Flask server with orjson, static folders, and logging.

    Args:
        server: Flask server instance
        dash_root_path: Path to dash package root
    """
    # Configure Flask's logger to use custom logging settings
    server.logger.handlers = logger.handlers  # type: ignore
    server.logger.setLevel(logger.level)  # type: ignore

    # PERFORMANCE OPTIMIZATION: Configure Flask to use orjson for JSON serialization
    try:
        import orjson
        from flask.json.provider import JSONProvider

        class OrjsonProvider(JSONProvider):
            """Custom JSON provider using orjson for faster serialization."""

            def dumps(self, obj, **kwargs):
                """Serialize obj to JSON bytes using orjson."""
                return orjson.dumps(obj).decode("utf-8")

            def loads(self, s, **kwargs):
                """Deserialize JSON string to Python object using orjson."""
                if isinstance(s, str):
                    s = s.encode("utf-8")
                return orjson.loads(s)

        server.json = OrjsonProvider(server)
        logger.info("✅ FLASK DISPATCHER: Configured Flask to use orjson (10-16x faster)")
    except ImportError:
        logger.warning("⚠️  FLASK DISPATCHER: orjson not available, using standard json")

    # Configure Flask to serve assets folder at /assets/ for all three Dash apps
    # This solves multi-app asset path conflicts where dash.get_asset_url() returns
    # paths for the last registered app, causing 404s in Management and Viewer apps
    assets_folder = os.path.join(dash_root_path, "assets")
    server.static_folder = assets_folder  # type: ignore
    server.static_url_path = "/assets"  # type: ignore
    logger.info(
        f"✅ FLASK DISPATCHER: Configured Flask to serve assets at /assets/ from {assets_folder}"
    )


def create_management_app(
    server: Flask, assets_folder: str, background_callback_manager, dev_mode: bool
):
    """
    Create the Management Dash app (/, /auth, /dashboards, /projects, /profile, /admin).

    Args:
        server: Flask server instance
        assets_folder: Path to assets folder
        background_callback_manager: Celery background callback manager
        dev_mode: Whether in development mode

    Returns:
        dash.Dash: Management app instance
    """
    app_management = dash.Dash(
        __name__,
        server=server,
        url_base_pathname="/",
        external_stylesheets=[
            # Google Material Icons
            {
                "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
                "rel": "stylesheet",
            },
            # Main application CSS (imports all modular CSS including fonts)
            "/assets/css/app.css",
            # Legacy dock animation (standalone)
            "/assets/dock-animation.css",
        ],
        suppress_callback_exceptions=True,
        title="Depictio - Management",
        # Assets served by Flask at /assets/ (shared across all apps)
        # When False, CSS and favicon must be manually specified
        include_assets_files=False,
        background_callback_manager=background_callback_manager,
    )

    # Manually add favicon link since include_assets_files=False
    # Dash expects filesystem path in _favicon, so we inject the link tag directly
    app_management.index_string = """
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            <link rel="icon" type="image/x-icon" href="/assets/images/icons/favicon.ico">
            {%css%}
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    """

    # Integrate Google Analytics
    integrate_google_analytics(app_management, title="Depictio - Management")

    # Setup profiling if enabled
    from depictio.dash.profiling import setup_profiling

    app_management = setup_profiling(app_management)

    # Enable dev tools
    app_management.enable_dev_tools(
        dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
    )

    logger.info("✅ FLASK DISPATCHER: Created Management app at /")
    return app_management


def create_viewer_app(
    server: Flask, assets_folder: str, background_callback_manager, dev_mode: bool
):
    """
    Create the Dashboard Viewer Dash app (/dashboard/{id}).

    Args:
        server: Flask server instance
        assets_folder: Path to assets folder
        background_callback_manager: Celery background callback manager
        dev_mode: Whether in development mode

    Returns:
        dash.Dash: Viewer app instance
    """
    app_viewer = dash.Dash(
        __name__,
        server=server,
        url_base_pathname="/dashboard/",
        external_stylesheets=[
            # Google Material Icons
            {
                "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
                "rel": "stylesheet",
            },
            # Main application CSS (imports all modular CSS including fonts)
            "/assets/css/app.css",
            # Legacy dock animation (standalone)
            "/assets/dock-animation.css",
        ],
        suppress_callback_exceptions=True,
        title="Depictio - Dashboard",
        # Assets served by Flask at /assets/ (shared across all apps)
        # When False, CSS and favicon must be manually specified
        include_assets_files=False,
        background_callback_manager=background_callback_manager,
    )

    # Manually add favicon link since include_assets_files=False
    app_viewer.index_string = """
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            <link rel="icon" type="image/x-icon" href="/assets/images/icons/favicon.ico">
            {%css%}
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    """

    # Integrate Google Analytics
    integrate_google_analytics(app_viewer, title="Depictio - Dashboard Viewer")

    # Setup profiling if enabled
    from depictio.dash.profiling import setup_profiling

    app_viewer = setup_profiling(app_viewer)

    # Enable dev tools
    app_viewer.enable_dev_tools(
        dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
    )

    logger.info("✅ FLASK DISPATCHER: Created Viewer app at /dashboard/")
    return app_viewer


def create_editor_app(
    server: Flask, assets_folder: str, background_callback_manager, dev_mode: bool
):
    """
    Create the Dashboard Editor Dash app (/dashboard-edit/{id}, /component/{id}/build).

    Args:
        server: Flask server instance
        assets_folder: Path to assets folder
        background_callback_manager: Celery background callback manager
        dev_mode: Whether in development mode

    Returns:
        dash.Dash: Editor app instance
    """
    app_editor = dash.Dash(
        __name__,
        server=server,
        url_base_pathname="/dashboard-edit/",
        external_stylesheets=[
            # Google Material Icons
            {
                "href": "https://fonts.googleapis.com/icon?family=Material+Icons",
                "rel": "stylesheet",
            },
            # Main application CSS (imports all modular CSS including fonts)
            "/assets/css/app.css",
            # Legacy dock animation (standalone)
            "/assets/dock-animation.css",
        ],
        suppress_callback_exceptions=True,
        title="Depictio - Dashboard Editor",
        # Assets served by Flask at /assets/ (shared across all apps)
        # When False, CSS and favicon must be manually specified
        include_assets_files=False,
        background_callback_manager=background_callback_manager,
    )

    # Manually add favicon link since include_assets_files=False
    app_editor.index_string = """
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            <link rel="icon" type="image/x-icon" href="/assets/images/icons/favicon.ico">
            {%css%}
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    """

    # Integrate Google Analytics
    integrate_google_analytics(app_editor, title="Depictio - Dashboard Editor")

    # Setup profiling if enabled
    from depictio.dash.profiling import setup_profiling

    app_editor = setup_profiling(app_editor)

    # Enable dev tools
    app_editor.enable_dev_tools(
        dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
    )

    logger.info("✅ FLASK DISPATCHER: Created Editor app at /dashboard-edit/")
    return app_editor


def create_multi_app_dispatcher():
    """
    Create Flask server with four independent Dash applications.

    Returns:
        tuple: (server, app_management, app_viewer, app_editor, dev_mode)
    """
    logger.info("=" * 80)
    logger.info("🚀 FLASK DISPATCHER: Initializing multi-app architecture")
    logger.info("=" * 80)

    # Create Flask server
    server = Flask(__name__)

    # Get shared configuration
    assets_folder, background_callback_manager, dev_mode = create_shared_dash_config()

    # Get dash root path for static folder configuration
    dash_root_path = os.path.dirname(__file__)

    # Configure Flask server
    configure_flask_server(server, dash_root_path)

    # Create the three Dash apps
    app_management = create_management_app(
        server, assets_folder, background_callback_manager, dev_mode
    )
    app_viewer = create_viewer_app(server, assets_folder, background_callback_manager, dev_mode)
    app_editor = create_editor_app(server, assets_folder, background_callback_manager, dev_mode)

    logger.info("=" * 80)
    logger.info("✅ FLASK DISPATCHER: Multi-app initialization complete")
    logger.info("=" * 80)
    logger.info("📊 Management App: http://localhost:8050/")
    logger.info("👁️  Viewer App:     http://localhost:8050/dashboard/<id>/")
    logger.info("✏️  Editor App:     http://localhost:8050/dashboard-edit/<id>/")
    logger.info("🔧 Builder:        http://localhost:8050/component/<dashboard_id>/build/")
    logger.info("=" * 80)
    logger.info("🔐 Callback Isolation:")
    logger.info("   - app_management: Auth, dashboards, projects, admin (~70 callbacks)")
    logger.info("   - app_viewer: Read-only dashboard viewing (~30 callbacks)")
    logger.info("   - app_editor: Editing, design UI, component builder (~65 callbacks)")
    logger.info("=" * 80)

    return server, app_management, app_viewer, app_editor, dev_mode


# Create the apps
server, app_management, app_viewer, app_editor, dev_mode = create_multi_app_dispatcher()


# Register custom Flask route for dashboard screenshots
# This restores the /static/screenshots/ endpoint that was removed when we
# changed Flask's static_folder to point to assets/ directory
@server.route("/static/screenshots/<path:filename>")
def serve_screenshots(filename):
    """Serve dashboard screenshot thumbnails from static/screenshots/ directory."""
    screenshots_folder = os.path.join(os.path.dirname(__file__), "static", "screenshots")
    return send_from_directory(screenshots_folder, filename)


logger.info("✅ FLASK DISPATCHER: Registered /static/screenshots/ route for dashboard thumbnails")


# Register layouts and callbacks from separate modules
logger.info("==" * 40)
logger.info("🔌 FLASK DISPATCHER: Wiring up app modules")
logger.info("==" * 40)

# Wire up Management App
logger.info("📊 Wiring Management App...")
app_management.layout = management_app.layout
management_app.register_callbacks(app_management)
logger.info("✅ Management App wired up")

# Wire up Viewer App
logger.info("👁️  Wiring Viewer App...")
app_viewer.layout = dashboard_viewer.layout
dashboard_viewer.register_callbacks(app_viewer)
logger.info("✅ Viewer App wired up")


# Wire up Editor App
logger.info("✏️  Wiring Editor App...")
app_editor.layout = dashboard_editor.layout
dashboard_editor.register_callbacks(app_editor)
logger.info("✅ Editor App wired up")

logger.info("==" * 40)
logger.info("✅ FLASK DISPATCHER: All apps wired up")
logger.info("==" * 40)

# Export for WSGI compatibility (used by wsgi.py and production deployments)
application = server

if __name__ == "__main__":
    # Use run_simple for WSGI application support (DispatcherMiddleware is WSGI, not Flask)
    from werkzeug.serving import run_simple

    print("=" * 80)
    print(f"📊 Management:  http://{settings.dash.host}:{settings.dash.external_port}/")
    print(
        f"👁️  Viewer:      http://{settings.dash.host}:{settings.dash.external_port}/dashboard/<id>/"
    )
    print(
        f"✏️  Editor:      http://{settings.dash.host}:{settings.dash.external_port}/dashboard-edit/<id>/"
    )
    print("=" * 80)

    # Use run_simple with Flask server application
    run_simple(
        settings.dash.host,
        settings.dash.external_port,
        server,  # Flask application with all Dash apps mounted
        use_debugger=dev_mode,
        use_reloader=dev_mode,
        threaded=not settings.profiling.enabled,
    )
