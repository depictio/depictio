"""
Flask dispatcher module for multi-app Depictio architecture.

This module creates and manages three independent Dash applications mounted
on a shared Flask server. Each app has its own callback registry for true
isolation, preventing callback conflicts between different parts of the
application.

Applications:
    Management App (/): Authentication, dashboards, projects, admin
    Viewer App (/dashboard/): Read-only dashboard viewing
    Editor App (/dashboard-edit/): Dashboard editing and component builder

Key Functions:
    create_shared_dash_config: Create shared configuration for all Dash apps
    configure_flask_server: Configure Flask with orjson and static folders
    create_management_app: Create the Management Dash app
    create_viewer_app: Create the Dashboard Viewer Dash app
    create_editor_app: Create the Dashboard Editor Dash app
    create_multi_app_dispatcher: Create Flask server with all Dash applications
    serve_screenshots: Serve dashboard screenshot thumbnails

Module-level Execution:
    On import, this module creates all apps and wires up their layouts
    and callbacks. The 'application' variable is exported for WSGI compatibility.
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

# Shared HTML index template with favicon for all Dash apps
# Used because include_assets_files=False means we manually specify CSS and favicon
DASH_INDEX_STRING = """
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

# Shared external stylesheets for all Dash apps
EXTERNAL_STYLESHEETS = [
    {"href": "https://fonts.googleapis.com/icon?family=Material+Icons", "rel": "stylesheet"},
    "/assets/css/app.css",
    "/assets/dock-animation.css",
]


def create_shared_dash_config():
    """
    Create shared configuration for all Dash apps.

    Background Callbacks Strategy:
    - Editor app: Always configures Celery manager (required for design mode)
    - Design mode: Always uses background=True (requires Celery worker running)
    - View mode: Conditional via DEPICTIO_CELERY_ENABLED env var
    - Celery worker: Started conditionally via Docker Compose --profile celery

    Returns:
        tuple: (assets_folder, background_callback_manager, dev_mode)
    """
    # Check if in development mode
    dev_mode = os.environ.get("DEPICTIO_DEV_MODE", "false").lower() == "true"

    # Get the root path of the depictio.dash package
    dash_root_path = os.path.dirname(os.path.dirname(__file__))

    # Get the assets folder path
    assets_folder = os.path.join(dash_root_path, "assets")

    # Setup background callback manager - Always configure Celery for Editor app
    # The Celery worker container is started conditionally via Docker Compose profile
    background_callback_manager = None

    try:
        from depictio.dash.celery_app import celery_app

        background_callback_manager = dash.CeleryManager(celery_app)
    except Exception as e:
        logger.error(f"❌ FLASK DISPATCHER: Failed to setup Celery manager: {e}")
        logger.warning("⚠️  FLASK DISPATCHER: Design mode will not work without Celery!")
        background_callback_manager = None

    return assets_folder, background_callback_manager, dev_mode


def configure_flask_server(server: Flask, dash_root_path: str) -> None:
    """
    Configure Flask server with orjson, static folders, and logging.

    Sets up Flask to use orjson for JSON serialization (10-16x faster),
    configures static folder for assets, and applies custom logging.

    Args:
        server: Flask server instance to configure.
        dash_root_path: Path to the dash package root directory.
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
    except ImportError:
        logger.warning("⚠️  FLASK DISPATCHER: orjson not available, using standard json")

    # Configure Flask to serve assets folder at /assets/ for all three Dash apps
    # This solves multi-app asset path conflicts where dash.get_asset_url() returns
    # paths for the last registered app, causing 404s in Management and Viewer apps
    assets_folder = os.path.join(dash_root_path, "assets")
    server.static_folder = assets_folder  # type: ignore
    server.static_url_path = "/assets"  # type: ignore


def create_management_app(
    server: Flask, assets_folder: str, background_callback_manager, dev_mode: bool
) -> dash.Dash:
    """
    Create the Management Dash app.

    Creates the main management app serving routes: /, /auth, /dashboards,
    /projects, /profile, /admin, /cli_configs, and /about.

    Args:
        server: Flask server instance to mount the app on.
        assets_folder: Path to assets folder for static files.
        background_callback_manager: Celery background callback manager
            (unused for Management app - no background callbacks).
        dev_mode: Whether to enable development mode features.

    Returns:
        Configured Dash application instance for management.
    """
    # Management app doesn't use background callbacks - pass None
    app_management = dash.Dash(
        __name__,
        server=server,
        url_base_pathname="/",
        external_stylesheets=EXTERNAL_STYLESHEETS,
        suppress_callback_exceptions=True,
        title="Depictio - Management",
        include_assets_files=False,
        background_callback_manager=None,
    )
    app_management.index_string = DASH_INDEX_STRING

    # Integrate Google Analytics
    integrate_google_analytics(app_management, title="Depictio - Management")

    # Setup profiling if enabled
    from depictio.dash.profiling import setup_profiling

    app_management = setup_profiling(app_management)

    # Enable dev tools
    app_management.enable_dev_tools(
        dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
    )

    return app_management


def create_viewer_app(
    server: Flask, assets_folder: str, background_callback_manager, dev_mode: bool
) -> dash.Dash:
    """
    Create the Dashboard Viewer Dash app.

    Creates the read-only viewer app serving routes: /dashboard/{id}.
    Uses background callbacks when Celery is enabled for improved performance.

    Args:
        server: Flask server instance to mount the app on.
        assets_folder: Path to assets folder for static files.
        background_callback_manager: Celery background callback manager,
            or None if Celery is not available.
        dev_mode: Whether to enable development mode features.

    Returns:
        Configured Dash application instance for dashboard viewing.
    """
    # Viewer uses background callbacks only when Celery enabled
    app_viewer = dash.Dash(
        __name__,
        server=server,
        url_base_pathname="/dashboard/",
        external_stylesheets=EXTERNAL_STYLESHEETS,
        suppress_callback_exceptions=True,
        title="Depictio - Dashboard",
        include_assets_files=False,
        background_callback_manager=background_callback_manager,
    )
    app_viewer.index_string = DASH_INDEX_STRING

    # Integrate Google Analytics
    integrate_google_analytics(app_viewer, title="Depictio - Dashboard Viewer")

    # Setup profiling if enabled
    from depictio.dash.profiling import setup_profiling

    app_viewer = setup_profiling(app_viewer)

    # Enable dev tools
    app_viewer.enable_dev_tools(
        dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
    )

    return app_viewer


def create_editor_app(
    server: Flask, assets_folder: str, background_callback_manager, dev_mode: bool
) -> dash.Dash:
    """
    Create the Dashboard Editor Dash app.

    Creates the editor app serving routes: /dashboard-edit/{id} and
    /component/{id}/build. Requires background callbacks for figure
    design mode stepper functionality.

    Args:
        server: Flask server instance to mount the app on.
        assets_folder: Path to assets folder for static files.
        background_callback_manager: Celery background callback manager,
            required for design mode to function properly.
        dev_mode: Whether to enable development mode features.

    Returns:
        Configured Dash application instance for dashboard editing.
    """
    # Editor app needs background callbacks for figure design mode (stepper)
    app_editor = dash.Dash(
        __name__,
        server=server,
        url_base_pathname="/dashboard-edit/",
        external_stylesheets=EXTERNAL_STYLESHEETS,
        suppress_callback_exceptions=True,
        title="Depictio - Dashboard Editor",
        include_assets_files=False,
        background_callback_manager=background_callback_manager,
    )
    app_editor.index_string = DASH_INDEX_STRING

    # Integrate Google Analytics
    integrate_google_analytics(app_editor, title="Depictio - Dashboard Editor")

    # Setup profiling if enabled
    from depictio.dash.profiling import setup_profiling

    app_editor = setup_profiling(app_editor)

    # Enable dev tools
    app_editor.enable_dev_tools(
        dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
    )

    return app_editor


def create_multi_app_dispatcher() -> tuple:
    """
    Create Flask server with three independent Dash applications.

    Initializes the multi-app architecture by creating a Flask server and
    mounting three independent Dash applications (management, viewer, editor).
    Configures shared assets, orjson serialization, and background callbacks.

    Returns:
        A tuple containing (server, app_management, app_viewer, app_editor, dev_mode).
    """
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

    return server, app_management, app_viewer, app_editor, dev_mode


# Create the apps
server, app_management, app_viewer, app_editor, dev_mode = create_multi_app_dispatcher()


# Register custom Flask route for dashboard screenshots
# This restores the /static/screenshots/ endpoint that was removed when we
# changed Flask's static_folder to point to assets/ directory
@server.route("/static/screenshots/<path:filename>")
def serve_screenshots(filename: str):
    """
    Serve dashboard screenshot thumbnails from static/screenshots/ directory.

    This endpoint restores the /static/screenshots/ route that was removed
    when Flask's static_folder was changed to point to assets/ directory.

    Args:
        filename: Name of the screenshot file to serve.

    Returns:
        The screenshot file from the static/screenshots/ directory.
    """
    screenshots_folder = os.path.join(os.path.dirname(__file__), "static", "screenshots")
    return send_from_directory(screenshots_folder, filename)


# Register layouts and callbacks from separate modules

# Wire up Management App
app_management.layout = management_app.layout
management_app.register_callbacks(app_management)

# Wire up Viewer App
app_viewer.layout = dashboard_viewer.layout
dashboard_viewer.register_callbacks(app_viewer)


# Wire up Editor App
app_editor.layout = dashboard_editor.layout
dashboard_editor.register_callbacks(app_editor)

# Export for WSGI compatibility (used by wsgi.py and production deployments)
application = server

if __name__ == "__main__":
    print("=" * 80)
    print(f"📊 Management:  http://{settings.dash.host}:{settings.dash.external_port}/")
    print(
        f"👁️  Viewer:      http://{settings.dash.host}:{settings.dash.external_port}/dashboard/<id>/"
    )
    print(
        f"✏️  Editor:      http://{settings.dash.host}:{settings.dash.external_port}/dashboard-edit/<id>/"
    )
    print("=" * 80)

    # Use Flask's native run() for dev mode
    server.run(
        host=settings.dash.host,
        port=settings.dash.external_port,
        debug=dev_mode,
        use_reloader=dev_mode,
        threaded=True,
    )
