from flask import send_from_directory


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
