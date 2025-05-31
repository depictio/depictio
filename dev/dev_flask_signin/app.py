import os
from flask import Flask, redirect, request, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required,
)
from werkzeug.security import generate_password_hash, check_password_hash
import dash
from dash import dcc, html, callback, Input, Output, State, ALL, MATCH, no_update
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
from functools import wraps
import json
import uuid

# Initialize Flask app
server = Flask(__name__)
server.config["SECRET_KEY"] = "your-secret-key"
server.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///users.db"
server.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize database
db = SQLAlchemy(server)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = "login"


# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Create database tables
with server.app_context():
    db.create_all()
    # Create admin user if it doesn't exist
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(
            username="admin",
            email="admin@example.com",
            password=generate_password_hash("admin", method="pbkdf2:sha256"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

# Initialize Dash app
app = dash.Dash(
    __name__,
    server=server,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1.0"}],
)


# Create some sample data for the dashboard
def create_sample_data():
    df = pd.DataFrame(
        {
            "Category": ["A", "B", "C", "D", "E"] * 5,
            "Values": [10, 20, 15, 25, 30] * 5,
            "Group": ["Group 1", "Group 2", "Group 3", "Group 1", "Group 2"] * 5,
        }
    )
    return df


# Authentication API endpoints
@server.route("/login", methods=["POST"])
def login_api():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    user = User.query.filter_by(username=username).first()

    if user and check_password_hash(user.password, password):
        login_user(user)
        return jsonify({"success": True, "username": user.username, "is_admin": user.is_admin})
    else:
        return jsonify({"success": False, "error": "Invalid username or password"}), 401


@server.route("/register", methods=["POST"])
def register_api():
    data = request.get_json()
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")

    if not username or not email or not password:
        return jsonify({"success": False, "error": "All fields are required"}), 400

    user = User.query.filter_by(username=username).first()
    if user:
        return jsonify({"success": False, "error": "Username already exists"}), 400

    user = User.query.filter_by(email=email).first()
    if user:
        return jsonify({"success": False, "error": "Email already exists"}), 400

    new_user = User(
        username=username,
        email=email,
        password=generate_password_hash(password, method="pbkdf2:sha256"),
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({"success": True, "message": "Registration successful! Please login."})


@server.route("/logout", methods=["GET"])
@login_required
def logout_api():
    logout_user()
    return jsonify({"success": True})


@server.route("/check-auth", methods=["GET"])
def check_auth():
    if current_user.is_authenticated:
        return jsonify(
            {
                "authenticated": True,
                "username": current_user.username,
                "is_admin": current_user.is_admin,
            }
        )
    return jsonify({"authenticated": False})


@server.route("/users", methods=["GET"])
@login_required
def get_users():
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Admin privileges required"}), 403

    users = User.query.all()
    users_list = [
        {"id": user.id, "username": user.username, "email": user.email, "is_admin": user.is_admin}
        for user in users
    ]
    return jsonify({"success": True, "users": users_list})


@server.route("/users/<int:user_id>", methods=["DELETE"])
@login_required
def delete_user_api(user_id):
    if not current_user.is_admin:
        return jsonify({"success": False, "error": "Admin privileges required"}), 403

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        return jsonify({"success": False, "error": "Cannot delete your own account"}), 400

    db.session.delete(user)
    db.session.commit()

    return jsonify({"success": True, "message": f"User {user.username} deleted successfully"})


# Dash components
def create_navbar(is_authenticated=False, is_admin=False, username=None):
    if is_authenticated:
        nav_items = [
            dbc.NavItem(dbc.NavLink("Dashboard", href="/dashboard")),
            dbc.NavItem(dbc.NavLink("Analytics", href="/analytics")),
        ]

        if is_admin:
            nav_items.append(dbc.NavItem(dbc.NavLink("Admin", href="/admin")))

        right_nav = dbc.Nav(
            [
                dbc.NavItem(html.Span(f"Welcome, {username}", className="navbar-text mr-3")),
                dbc.NavItem(dbc.NavLink("Logout", id="logout-button", href="#")),
            ],
            className="ml-auto",
        )
    else:
        nav_items = []
        right_nav = dbc.Nav(
            [
                dbc.NavItem(dbc.NavLink("Login", href="/login")),
                dbc.NavItem(dbc.NavLink("Register", href="/register")),
            ],
            className="ml-auto",
        )

    return dbc.Navbar(
        [
            dbc.Container(
                [
                    html.A(
                        dbc.Row(
                            [
                                dbc.Col(dbc.NavbarBrand("Dash-Flask App", className="ml-2")),
                            ],
                            align="center",
                        ),
                        href="/",
                    ),
                    dbc.NavbarToggler(id="navbar-toggler"),
                    dbc.Collapse(
                        [dbc.Nav(nav_items, className="mr-auto"), right_nav],
                        id="navbar-collapse",
                        navbar=True,
                    ),
                ]
            ),
        ],
        color="dark",
        dark=True,
        className="mb-4",
    )


# Login page layout
login_layout = dbc.Container(
    [
        html.H1("Login", className="text-center mb-4"),
        html.Div(id="login-alert"),
        dbc.Form(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Username", html_for="login-username"),
                                dbc.Input(
                                    type="text", id="login-username", placeholder="Enter username"
                                ),
                            ],
                            width=12,
                        )
                    ],
                    className="mb-3",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Password", html_for="login-password"),
                                dbc.Input(
                                    type="password",
                                    id="login-password",
                                    placeholder="Enter password",
                                ),
                            ],
                            width=12,
                        )
                    ],
                    className="mb-3",
                ),
                dbc.Button("Login", id="login-button", color="primary", className="mt-3"),
                html.Div(
                    [
                        html.P("Don't have an account?", className="mt-3"),
                        dcc.Link("Register here", href="/register", className="btn btn-link p-0"),
                    ],
                    className="mt-3",
                ),
            ]
        ),
    ],
    className="py-4",
)

# Register page layout
register_layout = dbc.Container(
    [
        html.H1("Register", className="text-center mb-4"),
        html.Div(id="register-alert"),
        dbc.Form(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Username", html_for="register-username"),
                                dbc.Input(
                                    type="text",
                                    id="register-username",
                                    placeholder="Enter username",
                                ),
                            ],
                            width=12,
                        )
                    ],
                    className="mb-3",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Email", html_for="register-email"),
                                dbc.Input(
                                    type="email", id="register-email", placeholder="Enter email"
                                ),
                            ],
                            width=12,
                        )
                    ],
                    className="mb-3",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Password", html_for="register-password"),
                                dbc.Input(
                                    type="password",
                                    id="register-password",
                                    placeholder="Enter password",
                                ),
                            ],
                            width=12,
                        )
                    ],
                    className="mb-3",
                ),
                dbc.Button("Register", id="register-button", color="primary", className="mt-3"),
                html.Div(
                    [
                        html.P("Already have an account?", className="mt-3"),
                        dcc.Link("Login here", href="/login", className="btn btn-link p-0"),
                    ],
                    className="mt-3",
                ),
            ]
        ),
    ],
    className="py-4",
)

# Dashboard layout
dashboard_layout = dbc.Container(
    [
        html.H1("Dashboard", className="mb-4"),
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Card(
                            [
                                dbc.CardHeader("Welcome"),
                                dbc.CardBody(
                                    [
                                        html.P(
                                            "This is your main dashboard. You are successfully logged in."
                                        ),
                                        html.P(
                                            "This example demonstrates how to integrate Flask authentication with Plotly Dash."
                                        ),
                                        dbc.Button(
                                            "Go to Analytics", href="/analytics", color="primary"
                                        ),
                                    ]
                                ),
                            ]
                        )
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        dbc.Card(
                            [
                                dbc.CardHeader("Quick Stats"),
                                dbc.CardBody(
                                    [
                                        html.Div(
                                            [
                                                html.H4("5", className="d-inline"),
                                                html.P("Active Users", className="d-inline ml-2"),
                                            ],
                                            className="mb-3",
                                        ),
                                        html.Div(
                                            [
                                                html.H4("3", className="d-inline"),
                                                html.P("Data Sources", className="d-inline ml-2"),
                                            ],
                                            className="mb-3",
                                        ),
                                        html.Div(
                                            [
                                                html.H4("12", className="d-inline"),
                                                html.P(
                                                    "Reports Generated", className="d-inline ml-2"
                                                ),
                                            ]
                                        ),
                                    ]
                                ),
                            ]
                        )
                    ],
                    md=6,
                ),
            ]
        ),
        html.Div(id="dashboard-content"),
    ]
)

# Analytics layout
analytics_layout = dbc.Container(
    [
        html.H1("Analytics Dashboard", className="mb-4"),
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H3("Bar Chart"),
                        dcc.Graph(
                            id="bar-chart",
                            figure=px.bar(
                                create_sample_data(),
                                x="Category",
                                y="Values",
                                color="Group",
                                title="Sample Bar Chart",
                            ),
                        ),
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        html.H3("Pie Chart"),
                        dcc.Graph(
                            id="pie-chart",
                            figure=px.pie(
                                create_sample_data(),
                                values="Values",
                                names="Category",
                                title="Sample Pie Chart",
                            ),
                        ),
                    ],
                    md=6,
                ),
            ]
        ),
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H3("Line Chart"),
                        dcc.Graph(
                            id="line-chart",
                            figure=px.line(
                                create_sample_data(),
                                x="Category",
                                y="Values",
                                color="Group",
                                title="Sample Line Chart",
                            ),
                        ),
                    ],
                    className="mt-4",
                )
            ]
        ),
    ]
)

# Admin layout
admin_layout = dbc.Container(
    [
        html.H1("User Management", className="mb-4"),
        html.Div(id="admin-alert"),
        dbc.Card(
            [
                dbc.CardHeader("User List"),
                dbc.CardBody(
                    [
                        html.P(
                            "This panel allows you to manage users in the system. You can view all registered users and delete them if needed."
                        ),
                        html.Div(id="user-table"),
                    ]
                ),
            ]
        ),
        dbc.Button("Back to Dashboard", href="/dashboard", color="primary", className="mt-4"),
    ]
)

# Main app layout
app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        html.Div(id="navbar-container"),
        html.Div(id="page-content"),
        dcc.Store(id="auth-store"),
        # Only check auth on initial load and URL changes, not periodically
        # This prevents clearing form inputs
    ]
)


# Callbacks
@app.callback(
    [Output("auth-store", "data"), Output("navbar-container", "children")],
    [Input("url", "pathname")],
)
def check_authentication(pathname):
    # Make a request to the Flask endpoint to check authentication
    response = server.test_client().get("/check-auth")
    auth_data = json.loads(response.data)

    # Create navbar based on authentication status
    navbar = create_navbar(
        is_authenticated=auth_data.get("authenticated", False),
        is_admin=auth_data.get("is_admin", False),
        username=auth_data.get("username"),
    )

    return auth_data, navbar


@app.callback(
    Output("page-content", "children"), [Input("url", "pathname"), Input("auth-store", "data")]
)
def display_page(pathname, auth_data):
    is_authenticated = auth_data.get("authenticated", False)
    is_admin = auth_data.get("is_admin", False)

    if pathname == "/login":
        if is_authenticated:
            return dcc.Location(pathname="/dashboard", id="redirect-to-dashboard")
        return login_layout

    elif pathname == "/register":
        if is_authenticated:
            return dcc.Location(pathname="/dashboard", id="redirect-to-dashboard")
        return register_layout

    elif pathname == "/dashboard":
        if not is_authenticated:
            return dcc.Location(pathname="/login", id="redirect-to-login")
        return dashboard_layout

    elif pathname == "/analytics":
        if not is_authenticated:
            return dcc.Location(pathname="/login", id="redirect-to-login")
        return analytics_layout

    elif pathname == "/admin":
        if not is_authenticated:
            return dcc.Location(pathname="/login", id="redirect-to-login")
        if not is_admin:
            return html.Div(
                [
                    html.H3("Access Denied", className="text-danger"),
                    html.P("You need admin privileges to access this page."),
                    dbc.Button("Back to Dashboard", href="/dashboard", color="primary"),
                ],
                className="container py-4",
            )
        return admin_layout

    else:
        if is_authenticated:
            return dcc.Location(pathname="/dashboard", id="redirect-to-dashboard")
        return dcc.Location(pathname="/login", id="redirect-to-login")


@app.callback(
    [Output("login-alert", "children"), Output("url", "pathname", allow_duplicate=True)],
    [Input("login-button", "n_clicks")],
    [State("login-username", "value"), State("login-password", "value")],
    prevent_initial_call=True,
)
def login_user_callback(n_clicks, username, password):
    if n_clicks is None:
        return no_update, no_update

    if not username or not password:
        return dbc.Alert("Please enter both username and password", color="danger"), no_update

    # Make a request to the Flask login endpoint
    response = server.test_client().post(
        "/login", json={"username": username, "password": password}, content_type="application/json"
    )

    data = json.loads(response.data)

    if data.get("success"):
        return dbc.Alert("Login successful! Redirecting...", color="success"), "/dashboard"
    else:
        return dbc.Alert(data.get("error", "Login failed"), color="danger"), no_update


@app.callback(
    [Output("register-alert", "children"), Output("url", "pathname", allow_duplicate=True)],
    [Input("register-button", "n_clicks")],
    [
        State("register-username", "value"),
        State("register-email", "value"),
        State("register-password", "value"),
    ],
    prevent_initial_call=True,
)
def register_user_callback(n_clicks, username, email, password):
    if n_clicks is None:
        return no_update, no_update

    if not username or not email or not password:
        return dbc.Alert("All fields are required", color="danger"), no_update

    # Make a request to the Flask register endpoint
    response = server.test_client().post(
        "/register",
        json={"username": username, "email": email, "password": password},
        content_type="application/json",
    )

    data = json.loads(response.data)

    if data.get("success"):
        return dbc.Alert(
            "Registration successful! Redirecting to login...", color="success"
        ), "/login"
    else:
        return dbc.Alert(data.get("error", "Registration failed"), color="danger"), no_update


@app.callback(
    Output("url", "pathname", allow_duplicate=True),
    [Input("logout-button", "n_clicks")],
    prevent_initial_call=True,
)
def logout_user_callback(n_clicks):
    if n_clicks is None:
        return no_update

    # Make a request to the Flask logout endpoint
    server.test_client().get("/logout")
    return "/login"


@app.callback(Output("user-table", "children"), [Input("url", "pathname")])
def load_user_table(pathname):
    if pathname != "/admin":
        return no_update

    # Make a request to the Flask users endpoint
    response = server.test_client().get("/users")

    if response.status_code != 200:
        return html.Div("Error loading users")

    data = json.loads(response.data)

    if not data.get("success"):
        return html.Div("Error: " + data.get("error", "Unknown error"))

    users = data.get("users", [])

    table_header = [
        html.Thead(
            html.Tr(
                [
                    html.Th("ID"),
                    html.Th("Username"),
                    html.Th("Email"),
                    html.Th("Admin"),
                    html.Th("Actions"),
                ]
            )
        )
    ]

    rows = []
    for user in users:
        delete_button = (
            html.Button(
                "Delete",
                id={"type": "delete-user-button", "index": user["id"]},
                className="btn btn-sm btn-danger",
                disabled=user["id"] == current_user.get_id(),
            )
            if user["id"] != int(current_user.get_id())
            else html.Span("Current User", className="text-muted")
        )

        rows.append(
            html.Tr(
                [
                    html.Td(user["id"]),
                    html.Td(user["username"]),
                    html.Td(user["email"]),
                    html.Td("Yes" if user["is_admin"] else "No"),
                    html.Td(delete_button),
                ]
            )
        )

    table_body = [html.Tbody(rows)]

    return dbc.Table(table_header + table_body, bordered=True, striped=True, hover=True)


@app.callback(
    [Output("admin-alert", "children"), Output("user-table", "children", allow_duplicate=True)],
    [Input({"type": "delete-user-button", "index": ALL}, "n_clicks")],
    [State({"type": "delete-user-button", "index": ALL}, "id")],
    prevent_initial_call=True,
)
def delete_user_callback(n_clicks_list, button_ids):
    ctx = dash.callback_context

    if not ctx.triggered:
        return no_update, no_update

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    user_id = json.loads(button_id)["index"]

    # Make a request to the Flask delete user endpoint
    response = server.test_client().delete(f"/users/{user_id}")
    data = json.loads(response.data)

    if data.get("success"):
        # Refresh the user table
        users_response = server.test_client().get("/users")
        users_data = json.loads(users_response.data)

        if not users_data.get("success"):
            return dbc.Alert(
                data.get("message", "User deleted successfully"), color="success"
            ), no_update

        users = users_data.get("users", [])

        table_header = [
            html.Thead(
                html.Tr(
                    [
                        html.Th("ID"),
                        html.Th("Username"),
                        html.Th("Email"),
                        html.Th("Admin"),
                        html.Th("Actions"),
                    ]
                )
            )
        ]

        rows = []
        for user in users:
            delete_button = (
                html.Button(
                    "Delete",
                    id={"type": "delete-user-button", "index": user["id"]},
                    className="btn btn-sm btn-danger",
                )
                if user["id"] != int(current_user.get_id())
                else html.Span("Current User", className="text-muted")
            )

            rows.append(
                html.Tr(
                    [
                        html.Td(user["id"]),
                        html.Td(user["username"]),
                        html.Td(user["email"]),
                        html.Td("Yes" if user["is_admin"] else "No"),
                        html.Td(delete_button),
                    ]
                )
            )

        table_body = [html.Tbody(rows)]

        return dbc.Alert(
            data.get("message", "User deleted successfully"), color="success"
        ), table_header + table_body


if __name__ == "__main__":
    app.run_server(debug=True)
