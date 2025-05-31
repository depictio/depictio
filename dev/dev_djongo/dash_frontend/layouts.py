from dash import html, dcc
import dash_bootstrap_components as dbc


def home_layout():
    """
    Layout for the home page
    """
    return html.Div(
        [
            html.H1("Welcome to Dash + Django + MongoDB App"),
            html.P("This application demonstrates the integration of:"),
            html.Ul(
                [
                    html.Li("Django for authentication backend"),
                    html.Li("MongoDB as the database"),
                    html.Li("Dash for the frontend UI"),
                ]
            ),
            html.P("Use the navigation bar to login or register."),
            html.Hr(),
            html.Div(
                [
                    html.H3("Features"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Card(
                                        [
                                            dbc.CardHeader("Authentication"),
                                            dbc.CardBody(
                                                [
                                                    html.P("User authentication with JWT tokens"),
                                                    html.P("Secure password storage"),
                                                    html.P("Login/Register modals"),
                                                ]
                                            ),
                                        ]
                                    )
                                ],
                                width=4,
                            ),
                            dbc.Col(
                                [
                                    dbc.Card(
                                        [
                                            dbc.CardHeader("MongoDB Integration"),
                                            dbc.CardBody(
                                                [
                                                    html.P("Django with Djongo adapter"),
                                                    html.P("Store all data in MongoDB"),
                                                    html.P(
                                                        "Unified database for auth and app data"
                                                    ),
                                                ]
                                            ),
                                        ]
                                    )
                                ],
                                width=4,
                            ),
                            dbc.Col(
                                [
                                    dbc.Card(
                                        [
                                            dbc.CardHeader("Dash UI"),
                                            dbc.CardBody(
                                                [
                                                    html.P("Interactive dashboard"),
                                                    html.P("Bootstrap components"),
                                                    html.P("Client-side authentication state"),
                                                ]
                                            ),
                                        ]
                                    )
                                ],
                                width=4,
                            ),
                        ]
                    ),
                ],
                className="mt-4",
            ),
        ]
    )


def dashboard_layout():
    """
    Layout for the dashboard page (protected, requires authentication)
    """
    return html.Div(
        [
            html.H1("Dashboard"),
            html.Div(id="user-info-container", className="mb-4"),
            html.Hr(),
            html.Div(
                [
                    html.H3("Your Data"),
                    html.P("This is a protected dashboard that requires authentication."),
                    dbc.Alert(
                        "You are viewing authenticated content that is stored in MongoDB.",
                        color="success",
                    ),
                    # Placeholder for dashboard content
                    html.Div(id="dashboard-content", className="mt-4"),
                ]
            ),
        ]
    )


def unauthorized_layout():
    """
    Layout for unauthorized access attempts
    """
    return html.Div(
        [
            html.H1("Unauthorized", className="text-danger"),
            html.P("You need to login to access this page."),
            dbc.Button("Login", id="redirect-to-login", color="primary"),
        ],
        className="text-center",
    )


def error_layout(error_msg="Page not found"):
    """
    Layout for error pages
    """
    return html.Div(
        [
            html.H1("Error", className="text-danger"),
            html.P(error_msg),
            dbc.Button("Go Home", href="/", color="primary"),
        ],
        className="text-center",
    )
