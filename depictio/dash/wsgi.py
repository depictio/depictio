"""
WSGI entry point for Depictio Dash application.

Exports the DispatcherMiddleware application which includes:
- Flask server with Management, Viewer, and Editor apps
- Vizro app mounted at /vizro/
"""

from depictio.dash.flask_dispatcher import application, server  # noqa: F401

# Export both for compatibility:
# - application: DispatcherMiddleware with Vizro support (recommended)
# - server: Bare Flask server (legacy compatibility)
__all__ = ["application", "server"]
