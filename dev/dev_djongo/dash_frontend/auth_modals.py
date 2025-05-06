import dash_bootstrap_components as dbc
from dash import html, dcc

def create_login_modal():
    """
    Create a login modal with username and password fields
    """
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Login")),
            dbc.ModalBody([
                dbc.Alert(
                    id="login-alert",
                    is_open=False,
                    duration=4000,
                ),
                dbc.Form([
                    dbc.Row([
                        dbc.Label("Username", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="text",
                                id="login-username",
                                placeholder="Enter username",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Password", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="password",
                                id="login-password",
                                placeholder="Enter password",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button(
                    "Register Instead", 
                    id="switch-to-register", 
                    className="me-auto", 
                    color="link"
                ),
                dbc.Button(
                    "Close", 
                    id="login-close", 
                    className="ms-auto", 
                    color="secondary"
                ),
                dbc.Button("Login", id="login-button", color="primary"),
                html.Hr(),
                html.Div([
                    html.P("Or login with:", className="text-center mt-3"),
                    dbc.Button(
                        [html.I(className="fab fa-google me-2"), "Login with Google"],
                        id="google-login-button",
                        color="danger",
                        className="w-100 mt-2",
                        href="http://localhost:8000/accounts/google/login/",
                        external_link=True
                    ),
                ], className="w-100"),
            ]),
        ],
        id="login-modal",
        is_open=False,
    )

def create_register_modal():
    """
    Create a registration modal with all required fields
    """
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Register")),
            dbc.ModalBody([
                dbc.Alert(
                    id="register-alert",
                    is_open=False,
                    duration=4000,
                ),
                dbc.Form([
                    dbc.Row([
                        dbc.Label("Username", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="text",
                                id="register-username",
                                placeholder="Enter username",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Email", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="email",
                                id="register-email",
                                placeholder="Enter email",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("First Name", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="text",
                                id="register-first-name",
                                placeholder="Enter first name",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Last Name", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="text",
                                id="register-last-name",
                                placeholder="Enter last name",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Password", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="password",
                                id="register-password",
                                placeholder="Enter password",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Confirm Password", width=12),
                        dbc.Col([
                            dbc.Input(
                                type="password",
                                id="register-password2",
                                placeholder="Confirm password",
                            ),
                        ], width=12)
                    ], className="mb-3"),
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button(
                    "Login Instead", 
                    id="switch-to-login", 
                    className="me-auto", 
                    color="link"
                ),
                dbc.Button(
                    "Close", 
                    id="register-close", 
                    className="ms-auto", 
                    color="secondary"
                ),
                dbc.Button("Register", id="register-button", color="primary"),
            ]),
        ],
        id="register-modal",
        is_open=False,
        size="lg",
    )

def auth_modals():
    """
    Return both login and register modals
    """
    return html.Div([
        create_login_modal(),
        create_register_modal()
    ])
