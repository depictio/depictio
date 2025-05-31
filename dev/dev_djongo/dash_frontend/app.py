import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from flask_cors import CORS

# Import components
from header import create_header
from auth_modals import auth_modals

# Initialize the Dash app with Bootstrap theme and Font Awesome
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://use.fontawesome.com/releases/v5.15.4/css/all.css",  # Font Awesome for icons
    ],
    suppress_callback_exceptions=True,
)

# Enable CORS for the Dash app
CORS(app.server)

# Create a server reference
server = app.server

# Define the app layout with a container for the content
app.layout = html.Div(
    [
        # Store for authentication state
        dcc.Store(id="auth-store", storage_type="local"),
        # URL routing
        dcc.Location(id="url", refresh=False),
        # Header with navigation - initialize with unauthenticated state
        html.Div(create_header(is_authenticated=False), id="header"),
        # Main content container
        html.Div(id="page-content", className="container mt-4"),
        # Authentication modals (login/register)
        html.Div(auth_modals(), id="auth-modals"),
        # Hidden div for login/register button clicks
        html.Div(
            [
                html.Button(id="hidden-login-trigger", style={"display": "none"}),
                html.Button(id="hidden-register-trigger", style={"display": "none"}),
            ],
            style={"display": "none"},
        ),
    ]
)

# Import callbacks after the app is defined
from callbacks import register_callbacks

# Register all callbacks
register_callbacks(app)

# Run the app
if __name__ == "__main__":
    app.run(debug=True, port=8050)
