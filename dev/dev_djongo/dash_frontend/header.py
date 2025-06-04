import dash_bootstrap_components as dbc
from dash import html


def create_header(is_authenticated=False, username=None):
    """
    Create a header with navigation and authentication buttons

    Args:
        is_authenticated: Boolean indicating if user is authenticated
        username: Username of the authenticated user
    """
    # Navigation links
    nav_items = [
        dbc.NavItem(dbc.NavLink("Home", href="/")),
        dbc.NavItem(dbc.NavLink("Dashboard", href="/dashboard")),
    ]

    # Authentication buttons/user info
    if is_authenticated:
        auth_items = [
            dbc.NavItem(html.Div(f"Welcome, {username}", className="nav-link")),
            dbc.NavItem(dbc.Button("Logout", id="logout-button", color="light", className="ms-2")),
        ]
    else:
        auth_items = [
            dbc.NavItem(
                dbc.Button("Login", id="login-btn", n_clicks=0, color="primary", className="ms-2")
            ),
            dbc.NavItem(
                dbc.Button(
                    "Register", id="register-btn", n_clicks=0, color="light", className="ms-2"
                )
            ),
        ]

    # Combine navigation and auth items
    navbar = dbc.Navbar(
        dbc.Container(
            [
                # Brand/logo
                dbc.NavbarBrand("Dash + Django + MongoDB", href="/"),
                # Toggle button for mobile view
                dbc.NavbarToggler(id="navbar-toggler"),
                # Collapsible navbar content
                dbc.Collapse(
                    [
                        # Left-aligned nav items
                        dbc.Nav(nav_items, className="me-auto", navbar=True),
                        # Right-aligned auth items
                        dbc.Nav(auth_items, navbar=True),
                    ],
                    id="navbar-collapse",
                    navbar=True,
                    is_open=False,
                ),
            ],
            fluid=True,
        ),
        color="dark",
        dark=True,
        className="mb-4",
    )

    return navbar
