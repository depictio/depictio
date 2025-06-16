from flask import abort, request, send_from_directory


def register_static_routes(server):
    """
    Register custom routes for serving static files.

    Args:
        server: The Flask server instance to register routes on
    """
    # Get the static directory path from the server configuration
    # This will use the path set in app_factory.py
    static_directory = server.static_folder

    # Add routes for serving static files
    @server.route("/static/<path:path>")
    def serve_static(path):
        return send_from_directory(static_directory, path)

    # Block debug endpoints
    @server.before_request
    def block_debug_endpoints():
        debug_paths = [
            "/console",
            "/__debugger__",
            "/debugger",
            "/debug",
            "/_debug_toolbar",
            "/werkzeug",
            "/debug-console",
        ]

        if request.path in debug_paths:
            abort(404)  # Return 404 instead of exposing debug interface
