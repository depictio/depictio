from flask import send_from_directory
from depictio.dash.app import app

# Assuming 'static' is in the same directory as your Dash app
import os

STATIC_DIRECTORY = os.path.join(os.path.dirname(__file__), 'static')

@app.server.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(STATIC_DIRECTORY, path)
