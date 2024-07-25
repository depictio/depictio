import re
from bson import ObjectId
from dash import html, Dash, dcc, Input, Output, State, ctx
import dash_mantine_components as dmc
import dash
import json
import os
import bcrypt
import httpx
from depictio.api.v1.db import users_collection
from depictio.api.v1.configs.config import API_BASE_URL, logger

from depictio.api.v1.endpoints.user_endpoints.utils import verify_password, hash_password, login_user, logout_user


# Function to find user by email
def find_user(email):
    # return users_collection.find_one({"email": email})
    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_email", params={"email": email})
    if response.status_code == 200:
        return response.json()
    return None



# Function to add a new user
def add_user(email, password):
    hashed_password = hash_password(password)
    user_dict = {"email": email, "password": hashed_password}
    response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/register", json=user_dict)
    if response.status_code == 200:
        logger.info(f"User {email} added successfully.")
    else:
        logger.error(f"Error adding user {email}: {response.text}")
    return response



def render_login_form():
    return dmc.Stack(
        [
            dmc.Center(html.Img(src=dash.get_asset_url("logo.png"), height=60, style={"margin-left": "0px"})),  # Center the logo
            dmc.Center(dmc.Title("Welcome to Depictio :", order=2, style={"fontFamily": "Virgil"}, align="center")),
            dmc.Space(h=10),
            dmc.TextInput(label="Email:", id="register-email", placeholder="Enter your email", style={"width": "100%", "display": "none"}),
            dmc.PasswordInput(label="Password:", id="register-password", placeholder="Enter your password", style={"width": "100%", "display": "none"}),
            dmc.TextInput(label="Email:", id="login-email", placeholder="Enter your email", style={"width": "100%"}),
            dmc.PasswordInput(label="Password:", id="login-password", placeholder="Enter your password", style={"width": "100%"}),
            dmc.PasswordInput(label="Confirm Password:", id="register-confirm-password", placeholder="Confirm your password", style={"width": "100%", "display": "none"}),
            html.Div(id="user-feedback"),
            dmc.Space(h=20),
            dmc.Group(
                [
                    dmc.Button("Login", radius="md", id="login-button", fullWidth=True),
                    dmc.Button("", radius="md", id="register-button", fullWidth=True, style={"display": "none"}),
                    # dmc.Button("", radius="md", id="logout-button", fullWidth=True, style={"display": "none"}),
                    html.A(dmc.Button("Register", radius="md", variant="outline", color="gray", fullWidth=True), id="open-register-form"),
                    html.A(dmc.Button("", radius="md", variant="outline", color="gray", fullWidth=True), id="open-login-form", style={"display": "none"}),
                ],
                position="center",
                mt="1rem",
            ),
        ],
        spacing="1rem",
        style={"width": "100%"},
    )


def render_register_form():
    return dmc.Stack(
        [
            dmc.Center(html.Img(src=dash.get_asset_url("logo.png"), height=60, style={"margin-left": "0px"})),  # Center the logo
            dmc.Center(dmc.Title("Please register :", order=2, style={"fontFamily": "Virgil"}, align="center")),
            dmc.Space(h=10),
            dmc.TextInput(label="Email:", id="register-email", placeholder="Enter your email", style={"width": "100%"}),
            dmc.PasswordInput(label="Password:", id="register-password", placeholder="Enter your password", style={"width": "100%"}),
            dmc.TextInput(label="Email:", id="login-email", placeholder="Enter your email", style={"width": "100%", "display": "none"}),
            dmc.PasswordInput(label="Password:", id="login-password", placeholder="Enter your password", style={"width": "100%", "display": "none"}),
            dmc.PasswordInput(label="Confirm Password:", id="register-confirm-password", placeholder="Confirm your password", style={"width": "100%"}),
            html.Div(id="user-feedback"),
            dmc.Space(h=20),
            dmc.Group(
                [
                    dmc.Button("", radius="md", id="login-button", fullWidth=True, style={"display": "none"}),
                    # dmc.Button("", radius="md", id="logout-button", fullWidth=True, style={"display": "none"}),
                    dmc.Button("Register", radius="md", id="register-button", fullWidth=True),
                    html.A(dmc.Button("", radius="md", variant="outline", color="gray", fullWidth=True), id="open-register-form", style={"display": "none"}),
                    html.A(dmc.Button("Back to Login", radius="md", variant="outline", color="gray", fullWidth=True), id="open-login-form"),
                ],
                position="center",
                mt="1rem",
            ),
        ],
        spacing="1rem",
        style={"width": "100%"},
    )


def validate_login(login_email, login_password):
    if not login_email or not login_password:
        return "Please fill in all fields.", True, dash.no_update

    user = find_user(login_email)
    if not user:
        return "Invalid email or password.", True, dash.no_update

    logger.info(f"User: {user}")

    if verify_password(user["password"], login_password):
        logger.info("Password verification successful.")
        return "Login successful!", False, login_user(user["email"])

    logger.info("Password verification failed.")
    return "Invalid email or password.", True, dash.no_update


# Function to handle registration
def handle_registration(register_email, register_password, register_confirm_password):
    if not register_email or not register_password or not register_confirm_password:
        return "Please fill in all fields.", True
    if find_user(register_email):
        return "Email already registered.", True
    if register_password != register_confirm_password:
        return "Passwords do not match.", True
    response = add_user(register_email, register_password)
    if response.status_code != 200:
        return f"Error registering user: {response.text}", True
    return "Registration successful! Please log in.", False


layout = html.Div(
    [
        dcc.Store(id="modal-state-store", data="login"),  # Store to control modal content state (login or register)
        dcc.Store(id="modal-open-store", data=True),  # Store to control modal state (open or close)
        dmc.Modal(
            id="auth-modal", opened=True, centered=True, children=[dmc.Center(id="modal-content")], withCloseButton=False, closeOnEscape=False, closeOnClickOutside=False, size="lg"
        ),
        html.Div(id="landing-page-content"),
        # Hidden buttons for switching forms to ensure they exist in the layout
        html.Div(
            [
                dmc.Button("hidden-login-button", id="open-login-form", style={"display": "none"}),
                dmc.Button("hidden-register-button", id="open-register-form", style={"display": "none"}),
                dmc.Button("hidden-login-button", id="login-button", style={"display": "none"}),
                # dmc.Button("hidden-logout-button", id="logout-button", style={"display": "none"}),
                dmc.Button("hidden-register-button", id="register-button", style={"display": "none"}),
                dmc.PasswordInput("hidden-register-password", id="register-password", style={"display": "none"}),
                dmc.PasswordInput("hidden-register-confirm-password", id="register-confirm-password", style={"display": "none"}),
                dmc.TextInput("hidden-register-email", id="register-email", style={"display": "none"}),
                dmc.PasswordInput("hidden-login-password", id="login-password", style={"display": "none"}),
                dmc.TextInput("hidden-login-email", id="login-email", style={"display": "none"}),
                html.Div(id="user-feedback"),
            ]
        ),
    ]
)


def register_callbacks_users_management(app):
    @app.callback([Output("login-button", "disabled"), Output("login-email", "error")], [Input("login-email", "value")])
    def update_submit_button(email):
        if email:
            valid = re.match(r"^[a-zA-Z0-9_.+-]+@embl\.de$", email)
            return not valid, not valid
        return True, False  # Initially disabled with no error

    @app.callback([Output("register-button", "disabled"), Output("register-email", "error")], [Input("register-email", "value")])
    def update_submit_button(email):
        if email:
            valid = re.match(r"^[a-zA-Z0-9_.+-]+@embl\.de$", email)
            return not valid, not valid
        return True, False  # Initially disabled with no error

    @app.callback(
        [
            Output("auth-modal", "opened"),
            Output("modal-content", "children"),
            Output("user-feedback", "children"),
            Output("modal-state-store", "data"),
            Output("modal-open-store", "data"),
            Output("session-store", "data"),
        ],
        [
            Input("open-register-form", "n_clicks"),
            Input("open-login-form", "n_clicks"),
            Input("login-button", "n_clicks"),
            Input("register-button", "n_clicks"),
            # Input("logout-button", "n_clicks"),
        ],
        [
            State("modal-state-store", "data"),
            State("login-email", "value"),
            State("login-password", "value"),
            State("register-email", "value"),
            State("register-password", "value"),
            State("register-confirm-password", "value"),
            State("modal-open-store", "data"),
            State("session-store", "data"),
        ],
    )
    def handle_auth_and_switch_forms(
        n_clicks_register,
        n_clicks_login_form,
        n_clicks_login,
        n_clicks_register_form,
        # n_clicks_logout,
        current_state,
        login_email,
        login_password,
        register_email,
        register_password,
        register_confirm_password,
        modal_open,
        session_data,
    ):
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        session_data = logout_user()

        # If user is already logged in, do not show the login form
        if session_data and session_data.get("logged_in", False):
            return (False, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update)

        # If no button was clicked, return the current state
        if not ctx.triggered:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Handle button clicks
        # If the register button was clicked, open the register form
        if button_id == "open-register-form":
            logger.info("Opening register form")
            modal_state = "register"
            content = render_register_form()
            logger.info(f"content: {content}")
            return modal_open, content, dash.no_update, modal_state, dash.no_update, session_data
        # If the login button was clicked, open the login form
        elif button_id == "open-login-form" or not ctx.triggered:
            modal_state = "login"
            content = render_login_form()
            return modal_open, content, dash.no_update, modal_state, dash.no_update, session_data
        # If the login button was clicked, validate the login
        elif button_id == "login-button":
            feedback_message, modal_open, session_data = validate_login(login_email, login_password)
            if not modal_open:
                content = dash.no_update
            else:
                content = render_login_form()
            return modal_open, content, dmc.Text(feedback_message, color="red" if modal_open else "green"), current_state, modal_open, session_data
        # If the register button was clicked, handle the registration
        elif button_id == "register-button":
            feedback_message, modal_open = handle_registration(register_email, register_password, register_confirm_password)
            if not modal_open:
                modal_state = "login"
                content = render_login_form()
            else:
                content = render_register_form()
            return modal_open, content, dmc.Text(feedback_message, color="red" if modal_open else "green"), modal_state, modal_open, session_data
        # If the logout button was clicked, log the user out
        # elif button_id == "logout-button":
        #     modal_open = True
        #     content = render_login_form()
        #     return modal_open, content, dash.no_update, current_state, modal_open, session_data

        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
