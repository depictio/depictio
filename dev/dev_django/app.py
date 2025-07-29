import json
import os
from pathlib import Path

# Django setup - first configure settings
import django
from django.conf import settings

# Configure Django settings before importing models
BASE_DIR = Path(__file__).resolve().parent

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY="django-insecure-dummy-key-for-development-only",
        ROOT_URLCONF=__name__,
        MIDDLEWARE=[
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
        ],
        INSTALLED_APPS=[
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [os.path.join(BASE_DIR, "templates")],
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.debug",
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ],
                },
            },
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
            }
        },
        STATIC_URL="/static/",
        STATICFILES_DIRS=[os.path.join(BASE_DIR, "static")],
    )

# Initialize Django
django.setup()

# Now import Django modules that require settings
import threading

# Dash setup
import dash
import flask
import pandas as pd
import plotly.express as px
from dash import dcc, html
from dash.dependencies import Input, Output
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.wsgi import get_wsgi_application
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from flask import Flask

# Create a Flask server for Dash
server = Flask(__name__)
server.secret_key = settings.SECRET_KEY

# Create Dash app with Flask server
app = dash.Dash(__name__, server=server, url_base_pathname="/dash/")
app.config.suppress_callback_exceptions = True

# Sample data for the dashboard
df = pd.DataFrame(
    {
        "Fruit": ["Apples", "Oranges", "Bananas", "Apples", "Oranges", "Bananas"],
        "Amount": [4, 1, 2, 2, 4, 5],
        "City": ["SF", "SF", "SF", "NYC", "MTL", "NYC"],
    }
)


# Django views
def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard")
        else:
            error_message = "Invalid username or password"
            return render(request, "login.html", {"error_message": error_message})
    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required(login_url="login")
def dashboard_view(request):
    # Create a token for Dash authentication
    user = request.user
    auth_token = f"{user.id}:{user.username}:{user.is_staff or user.is_superuser}"

    # Pass the Dash app URL and auth token to the template
    dash_url = f"http://localhost:8050/dash/?token={auth_token}"
    return render(request, "dashboard.html", {"user": user, "dash_url": dash_url})


def home_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("login")


# API endpoint for Dash to verify authentication
@csrf_exempt
def verify_auth(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            token = data.get("token", "")

            # Parse token
            parts = token.split(":")
            if len(parts) != 3:
                return JsonResponse({"authenticated": False})

            user_id, username, is_admin = parts

            # Verify user exists
            try:
                user = User.objects.get(id=user_id, username=username)
                is_admin_actual = user.is_staff or user.is_superuser
                is_admin_bool = is_admin.lower() == "true"

                # Additional check for admin status
                if is_admin_bool != is_admin_actual:
                    return JsonResponse({"authenticated": False})

                return JsonResponse(
                    {
                        "authenticated": True,
                        "user_id": user.id,
                        "username": user.username,
                        "is_admin": is_admin_actual,
                    }
                )
            except User.DoesNotExist:
                return JsonResponse({"authenticated": False})
        except:
            return JsonResponse({"authenticated": False})

    return JsonResponse({"authenticated": False})


# URL patterns
urlpatterns = [
    path("", home_view, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("admin/", django.contrib.admin.site.urls),
    path("api/verify-auth/", verify_auth, name="verify_auth"),
]


# Create a superuser if it doesn't exist
def create_superuser():
    try:
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "adminpassword")
            print("Superuser created successfully!")
        else:
            print("Superuser already exists.")
    except Exception as e:
        print(f"Error creating superuser: {e}")


# WSGI application for Django
application = get_wsgi_application()

# Dash app layouts
login_layout = html.Div(
    [
        html.H1("Please Login", style={"textAlign": "center", "marginTop": "50px"}),
        html.P(
            "You need to be authenticated to view this dashboard.", style={"textAlign": "center"}
        ),
        html.Div(
            [
                html.A(
                    "Go to Login Page",
                    href="/login/",
                    style={
                        "display": "inline-block",
                        "backgroundColor": "#4CAF50",
                        "color": "white",
                        "padding": "10px 20px",
                        "textDecoration": "none",
                        "borderRadius": "5px",
                        "textAlign": "center",
                    },
                )
            ],
            style={"textAlign": "center", "marginTop": "20px"},
        ),
    ]
)

dashboard_layout = html.Div(
    [
        # Header with user info and logout button
        html.Div(
            [
                html.H1("Dash Dashboard", style={"display": "inline-block", "marginRight": "20px"}),
                html.Div(
                    [
                        html.Span(
                            id="user-display", style={"marginRight": "15px", "color": "white"}
                        ),
                        html.A(
                            "Logout",
                            href="/logout/",
                            style={
                                "backgroundColor": "#f44336",
                                "color": "white",
                                "padding": "8px 15px",
                                "textDecoration": "none",
                                "borderRadius": "3px",
                            },
                        ),
                    ],
                    style={"display": "inline-block", "float": "right"},
                ),
            ],
            style={
                "backgroundColor": "#333",
                "padding": "10px 20px",
                "color": "white",
                "marginBottom": "20px",
            },
        ),
        # Admin panel (only visible to admin users)
        html.Div(id="admin-panel", style={"display": "none", "marginBottom": "20px"}),
        # Dashboard content
        html.Div(
            [
                html.Label("Filter by city:"),
                dcc.Dropdown(
                    id="city-dropdown",
                    options=[{"label": city, "value": city} for city in df["City"].unique()],
                    value=None,
                    placeholder="Select a city",
                ),
            ],
            style={"marginBottom": "20px"},
        ),
        dcc.Graph(id="example-graph"),
        # Store for authentication data
        dcc.Store(id="auth-store"),
    ]
)


# Define a function to serve layout based on authentication
def serve_layout():
    # Get the token from the URL query string
    token = flask.request.args.get("token", "")

    if token:
        # Parse token
        parts = token.split(":")
        if len(parts) == 3:
            user_id, username, is_admin = parts

            # Check if user exists in Django DB
            try:
                user = User.objects.get(id=user_id, username=username)
                is_admin_actual = user.is_staff or user.is_superuser
                is_admin_bool = is_admin.lower() == "true"

                # If user is valid, show dashboard
                if is_admin_bool == is_admin_actual:
                    # Store auth data in session
                    auth_data = {
                        "authenticated": True,
                        "user_id": user.id,
                        "username": user.username,
                        "is_admin": is_admin_actual,
                    }

                    # Return dashboard layout
                    return html.Div([dcc.Store(id="auth-store", data=auth_data), dashboard_layout])
            except User.DoesNotExist:
                pass

    # Not authenticated, show login page
    return html.Div([dcc.Store(id="auth-store", data={"authenticated": False}), login_layout])


# Set the app layout to the serve_layout function
app.layout = serve_layout


# Callback to update user display
@app.callback(Output("user-display", "children"), [Input("auth-store", "data")])
def update_user_display(auth_data):
    if auth_data and auth_data.get("authenticated", False):
        return f"Welcome, {auth_data.get('username', 'User')}"
    return ""


# Callback to show/hide admin panel
@app.callback(
    [Output("admin-panel", "style"), Output("admin-panel", "children")],
    [Input("auth-store", "data")],
)
def toggle_admin_panel(auth_data):
    if auth_data and auth_data.get("authenticated", False) and auth_data.get("is_admin", False):
        # Get user count from Django
        user_count = User.objects.count()

        admin_content = [
            html.H3("Admin Panel"),
            html.P(f"Total users in database: {user_count}"),
            html.A(
                "Go to Django Admin",
                href="/admin/",
                target="_blank",
                style={
                    "display": "inline-block",
                    "backgroundColor": "#2196F3",
                    "color": "white",
                    "padding": "10px 15px",
                    "textDecoration": "none",
                    "borderRadius": "3px",
                },
            ),
        ]
        return {
            "display": "block",
            "padding": "15px",
            "backgroundColor": "#f9f9f9",
            "border": "1px solid #ddd",
            "borderRadius": "5px",
        }, admin_content

    return {"display": "none"}, []


# Callback for the graph
@app.callback(Output("example-graph", "figure"), [Input("city-dropdown", "value")])
def update_graph(selected_city):
    if selected_city:
        filtered_df = df[df["City"] == selected_city]
    else:
        filtered_df = df

    fig = px.bar(filtered_df, x="Fruit", y="Amount", color="City", barmode="group")
    return fig


# Run both Django and Dash
def run_dash():
    app.run_server(debug=False, port=8050)


if __name__ == "__main__":
    # Create necessary database tables
    from django.core.management import execute_from_command_line

    execute_from_command_line(["manage.py", "migrate"])

    # Create a superuser
    create_superuser()

    # Start Dash in a separate thread
    dash_thread = threading.Thread(target=run_dash)
    dash_thread.daemon = True
    dash_thread.start()

    print("Starting Django server on port 8000 and Dash server on port 8050")

    # Run the Django server
    execute_from_command_line(["manage.py", "runserver", "0.0.0.0:8001"])
