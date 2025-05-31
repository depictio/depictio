"""
Main entry point for the Depictio Dash application.

This module initializes the Dash application, registers callbacks,
and sets up the application layout.
"""

# Standard library imports

# Depictio core imports
from depictio.api.v1.configs.config import settings

# Depictio dash core imports
from depictio.dash.core.app_factory import create_dash_app
from depictio.dash.core.callbacks import register_all_callbacks
from depictio.dash.flask_custom import register_static_routes
from depictio.dash.layouts.app_layout import create_app_layout

# Create and configure the Dash application
app, dev_mode = create_dash_app()

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
    app.run_server(
        host=settings.dash.host,
        port=settings.dash.port,
        debug=dev_mode,
    )
