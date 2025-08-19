# Depictio core imports
from depictio.api.v1.configs.config import settings

# Depictio dash core imports
from depictio.dash.core.app_factory import create_dash_app
from depictio.dash.core.callbacks import register_all_callbacks
from depictio.dash.flask_custom import register_static_routes
from depictio.dash.layouts.app_layout import create_app_layout

# Create and configure the Dash application
app, dev_mode = create_dash_app()

app.enable_dev_tools(
    dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
)

# Set the application layout
app.layout = create_app_layout

# Register all callbacks
register_all_callbacks(app)

# Get the Flask server instance for WSGI
server = app.server


# Register custom static file routes
register_static_routes(server)

# Run the server if executed directly (not through WSGI)
if __name__ == "__main__":
    # This block won't be executed when run with Gunicorn
    # It's here for potential direct execution
    print(
        f"Starting Dash server on {settings.dash.host}:{settings.dash.external_port} with {settings.dash.workers} workers"
    )
    # Configure process and thread settings properly
    if settings.profiling.enabled:
        # Profiling mode: single process for proper profiling
        processes = 1
        threaded = False
    else:
        # Normal mode: use threaded for better performance, no processes
        processes = None  # Let Werkzeug handle this properly
        threaded = True

    app.run(
        host=settings.dash.host,
        port=settings.dash.external_port,
        debug=dev_mode,
        threaded=threaded,
        # Don't pass processes=None to avoid Werkzeug comparison error
        **({"processes": processes} if processes is not None else {}),
    )
