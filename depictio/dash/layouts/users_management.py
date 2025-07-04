import re

import dash
import dash_mantine_components as dmc
import httpx
from dash import Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate
from dash_extensions import EventListener
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _verify_password
from depictio.api.v1.endpoints.user_endpoints.utils import login_user
from depictio.dash.api_calls import (
    api_call_fetch_user_from_email,
    api_call_get_google_oauth_login_url,
    api_call_handle_google_oauth_callback,
    api_call_register_user,
)

event = {"event": "keydown", "props": ["key"]}


def render_login_form():
    return dmc.Stack(
        [
            dmc.Center(
                html.Img(
                    src=dash.get_asset_url("logo.png"),
                    height=60,
                    style={"margin-left": "0px"},
                )
            ),  # Center the logo
            dmc.Center(
                dmc.Title(
                    "Welcome to Depictio :",
                    order=2,
                    style={"fontFamily": "Virgil"},
                    align="center",
                )
            ),
            dmc.Space(h=10),
            dmc.TextInput(
                label="Email:",
                id="register-email",
                placeholder="Enter your email",
                style={"width": "100%", "display": "none"},
                # debounce=500,  # Add debounce to avoid too many requests
            ),
            dmc.PasswordInput(
                label="Password:",
                id="register-password",
                placeholder="Enter your password",
                style={"width": "100%", "display": "none"},
                # debounce=500,  # Add debounce to avoid too many requests
            ),
            dmc.TextInput(
                label="Email:",
                id="login-email",
                placeholder="Enter your email",
                style={"width": "100%"},
                # debounce=500,  # Add debounce to avoid too many requests
            ),
            dmc.PasswordInput(
                label="Password:",
                id="login-password",
                placeholder="Enter your password",
                style={"width": "100%"},
                # debounce=500,  # Add debounce to avoid too many requests
            ),
            dmc.PasswordInput(
                label="Confirm Password:",
                id="register-confirm-password",
                placeholder="Confirm your password",
                style={"width": "100%", "display": "none"},
                # debounce=500,  # Add debounce to avoid too many requests
            ),
            html.Div(id="user-feedback"),
            dmc.Space(h=20),
            dmc.Group(
                [
                    dmc.Button("Login", radius="md", id="login-button", fullWidth=True),
                    dmc.Button(
                        "",
                        radius="md",
                        id="register-button",
                        fullWidth=True,
                        style={"display": "none"},
                    ),
                    # dmc.Button("", radius="md", id="logout-button", fullWidth=True, style={"display": "none"}),
                    html.A(
                        dmc.Button(
                            "Register",
                            radius="md",
                            variant="outline",
                            color="gray",
                            fullWidth=True,
                            disabled=settings.auth.unauthenticated_mode,
                        ),
                        id="open-register-form",
                    ),
                    html.A(
                        dmc.Button(
                            "",
                            radius="md",
                            variant="outline",
                            color="gray",
                            fullWidth=True,
                        ),
                        id="open-login-form",
                        style={"display": "none"},
                    ),
                ],
                position="center",
                mt="1rem",
            ),
            # Google OAuth Section
            dmc.Stack(
                [
                    dmc.Divider(
                        label="Or",
                        labelPosition="center",
                        style={
                            "margin": "1rem 0",
                            "display": "block" if settings.auth.google_oauth_enabled else "none",
                        },
                    ),
                    dmc.Button(
                        [
                            DashIconify(
                                icon="devicon:google",
                                width=20,
                                height=20,
                                style={"marginRight": "8px"},
                            ),
                            "Sign in with Google",
                        ],
                        id="google-oauth-button",
                        radius="md",
                        variant="outline",
                        color="red",
                        fullWidth=True,
                        style={
                            "display": "block" if settings.auth.google_oauth_enabled else "none",
                            "border": "1px solid #db4437",
                            "color": "#db4437",
                        },
                    ),
                ],
                spacing="0.5rem",
                style={"display": "block" if settings.auth.google_oauth_enabled else "none"},
            ),
        ],
        spacing="1rem",
        style={"width": "100%"},
    )


def render_register_form():
    return dmc.Stack(
        [
            dmc.Center(
                html.Img(
                    src=dash.get_asset_url("logo.png"),
                    height=60,
                    style={"margin-left": "0px"},
                )
            ),  # Center the logo
            dmc.Center(
                dmc.Title(
                    "Please register :",
                    order=2,
                    style={"fontFamily": "Virgil"},
                    align="center",
                )
            ),
            dmc.Space(h=10),
            dmc.TextInput(
                label="Email:",
                id="register-email",
                placeholder="Enter your email",
                style={"width": "100%"},
            ),
            dmc.PasswordInput(
                label="Password:",
                id="register-password",
                placeholder="Enter your password",
                style={"width": "100%"},
            ),
            dmc.TextInput(
                label="Email:",
                id="login-email",
                placeholder="Enter your email",
                style={"width": "100%", "display": "none"},
            ),
            dmc.PasswordInput(
                label="Password:",
                id="login-password",
                placeholder="Enter your password",
                style={"width": "100%", "display": "none"},
            ),
            dmc.PasswordInput(
                label="Confirm Password:",
                id="register-confirm-password",
                placeholder="Confirm your password",
                style={"width": "100%"},
            ),
            html.Div(id="user-feedback"),
            dmc.Space(h=20),
            dmc.Group(
                [
                    dmc.Button(
                        "",
                        radius="md",
                        id="login-button",
                        fullWidth=True,
                        style={"display": "none"},
                    ),
                    # dmc.Button("", radius="md", id="logout-button", fullWidth=True, style={"display": "none"}),
                    dmc.Button("Register", radius="md", id="register-button", fullWidth=True),
                    html.A(
                        dmc.Button(
                            "",
                            radius="md",
                            variant="outline",
                            color="gray",
                            fullWidth=True,
                        ),
                        id="open-register-form",
                        style={"display": "none"},
                    ),
                    html.A(
                        dmc.Button(
                            "Back to Login",
                            id="back-to-login-button",
                            radius="md",
                            variant="outline",
                            color="gray",
                            fullWidth=True,
                        ),
                        id="open-login-form",
                    ),
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
        return "Please fill in all fields.", True, dash.no_update, dash.no_update

    user = api_call_fetch_user_from_email(login_email)
    if not user:
        return (
            "User not found. Please register first.",
            True,
            dash.no_update,
            dash.no_update,
        )

    logger.info(f"User: {user}")

    if _verify_password(user.password, login_password):
        logger.info("Password verification successful.")
        # from flask import make_response
        # resp = make_response("Login successful!")
        logger.info(f"API_BASE_URL: {API_BASE_URL}")

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/login",
            data={"username": user.email, "password": login_password},
        )
        logger.info(f"Response: {response}")
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response text: {response.text}")
        logger.info(f"Response json: {response.json()}")

        # Parse the response JSON to extract the token
        token_data = response.json()
        access_token = token_data.get("access_token")
        token_lifetime = token_data.get("token_lifetime")

        if not access_token or not token_lifetime:
            logger.error("Access token or token lifetime not found in response.")
            return (
                "Failed to retrieve access token.",
                True,
                dash.no_update,
                dash.no_update,
            )

        if response.status_code != 200:
            logger.error(f"Error logging in: {response.text}")
            return (
                f"Error logging in: {response.text}",
                True,
                dash.no_update,
                dash.no_update,
            )

        # return "Login successful!", False,
        logger.info(f"Login successful for user: {user.email}")
        return "Login successful!", False, login_user(user.email), token_data

    logger.error("Password verification failed.")
    return "Invalid email or password.", True, dash.no_update, dash.no_update


# Function to handle registration
def handle_registration(register_email, register_password, register_confirm_password):
    if not register_email or not register_password or not register_confirm_password:
        return "Please fill in all fields.", True
    if api_call_fetch_user_from_email(register_email):
        return "Email already registered.", True
    if register_password != register_confirm_password:
        return "Passwords do not match.", True
    # response = add_user(register_email, register_password)
    logger.info(f"Registering user with email: {register_email}")
    response = api_call_register_user(register_email, register_password)
    if not response:
        return f"Error registering user: {response.text}", True
    return "Registration successful! Please login.", False


layout = html.Div(
    [
        dcc.Store(
            id="modal-state-store", data="login"
        ),  # Store to control modal content state (login or register)
        dcc.Store(id="modal-open-store", data=True),  # Store to control modal state (open or close)
        dmc.Modal(
            id="auth-modal",
            opened=False,
            centered=True,
            children=EventListener(
                [dmc.Center(id="modal-content")],
                events=[event],
                logging=True,
                id="auth-modal-listener",
            ),
            withCloseButton=False,
            closeOnEscape=False,
            closeOnClickOutside=False,
            size="lg",
        ),
        # html.Div(id="landing-page-content"),
        # Hidden buttons for switching forms to ensure they exist in the layout
        html.Div(
            [
                dmc.Button(
                    id="open-login-form",
                    style={"display": "none"},
                ),
                dmc.Button(
                    id="open-register-form",
                    style={"display": "none"},
                ),
                dmc.Button(id="login-button", style={"display": "none"}),
                # dmc.Button("hidden-logout-button", id="logout-button", style={"display": "none"}),
                dmc.Button(
                    id="register-button",
                    style={"display": "none"},
                ),
                dmc.PasswordInput(
                    id="register-password",
                    style={"display": "none"},
                ),
                dmc.PasswordInput(
                    id="register-confirm-password",
                    style={"display": "none"},
                ),
                dmc.TextInput(
                    id="register-email",
                    style={"display": "none"},
                ),
                dmc.PasswordInput(
                    id="login-password",
                    style={"display": "none"},
                ),
                dmc.TextInput(id="login-email", style={"display": "none"}),
                html.Div(id="user-feedback"),
                # Google OAuth redirect component
                html.A(
                    id="google-oauth-redirect",
                    href="",
                    target="_self",
                    style={"display": "none"},
                ),
            ]
        ),
    ]
)


def register_callbacks_users_management(app):
    @app.callback(
        Output("login-button", "n_clicks"),
        Input("auth-modal-listener", "n_events"),
        State("auth-modal-listener", "event"),
        State("login-button", "disabled"),
    )
    def trigger_save_on_enter(n_events, e, disabled):
        if e is None or e["key"] != "Enter" or disabled:
            raise PreventUpdate()

        return 1  # Simulate a click on the save button

    @app.callback(
        [Output("login-button", "disabled"), Output("login-email", "error")],
        [Input("login-email", "value")],
    )
    def disable_login_button(email):
        if email:
            valid = re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email)
            return not valid, not valid
        return True, False  # Initially disabled with no error

    @app.callback(
        [Output("register-button", "disabled"), Output("register-email", "error")],
        [Input("register-email", "value")],
    )
    def disable_register_button(email):
        if email:
            valid = re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email)
            return not valid, not valid
        return True, False  # Initially disabled with no error

    @app.callback(
        [
            Output("auth-modal", "opened"),
            Output("modal-content", "children"),
            Output("user-feedback", "children"),
            Output("modal-state-store", "data"),
            Output("modal-open-store", "data"),
            Output("local-store", "data"),
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
            State("local-store", "data"),
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
        local_data,
    ):
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # logger.debug(f"Button ID: {button_id}")
        # logger.debug(f"Current state: {current_state}")
        # logger.debug(f"Local data: {local_data}")
        # logger.debug(f"Modal open: {modal_open}")
        # logger.debug(f"Login email: {login_email}")
        # logger.debug(f"Login password: {login_password}")
        # logger.debug(f"Register email: {register_email}")
        # logger.debug(f"Register password: {register_password}")
        # logger.debug(f"Register confirm password: {register_confirm_password}")

        # If user is already logged in, do not show the login form
        if local_data and local_data.get("logged_in", False):
            logger.info("User is already logged in.")
            return (
                False,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # If no button was clicked, return the current state
        if not ctx.triggered:
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Handle button clicks
        if button_id == "open-register-form":
            # Check if registration is disabled in unauthenticated mode
            if settings.auth.unauthenticated_mode:
                # Don't open register form if registration is disabled
                return (
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

            logger.info("Opening register form")
            modal_state = "register"
            content = render_register_form()
            return True, content, dash.no_update, modal_state, True, dash.no_update

        elif button_id == "open-login-form":
            logger.info("Opening login form")
            modal_state = "login"
            content = render_login_form()
            return True, content, dash.no_update, modal_state, True, dash.no_update

        elif button_id == "login-button":
            feedback_message, modal_open_new, session_data, local_data_new = validate_login(
                login_email, login_password
            )
            # logger.debug(f"Feedback message: {feedback_message}")
            # logger.debug(f"Modal open new: {modal_open_new}")
            # logger.debug(f"Session data: {session_data}")
            # logger.debug(f"Local data new: {local_data_new}")
            if not modal_open_new:
                content = render_login_form()
            else:
                content = render_login_form()

            return (
                modal_open_new,
                content,
                dmc.Text(
                    feedback_message,
                    id="user-feedback-message-login",
                    color="red" if modal_open_new else "green",
                ),
                current_state,
                modal_open_new,
                local_data_new,
            )

        elif button_id == "register-button":
            # Check if registration is disabled in unauthenticated mode
            if settings.auth.unauthenticated_mode:
                feedback_message = "User registration is disabled in unauthenticated mode"
                modal_open_new = True
                content = render_register_form()

                return (
                    True,
                    content,
                    dmc.Text(
                        feedback_message,
                        color="red",
                        id="user-feedback-message-register",
                    ),
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

            feedback_message, modal_open_new = handle_registration(
                register_email, register_password, register_confirm_password
            )

            logger.debug(f"Feedback message: {feedback_message}")
            logger.debug(f"Modal open new: {modal_open_new}")

            # if not modal_open_new:
            #     modal_state = "login"
            #     content = render_login_form()
            # else:
            #     modal_state = "register"
            content = render_register_form()
            # logger.debug(f"Modal state: {modal_state}")
            # logger.debug(f"Content: {content}")

            return (
                True,
                content,
                dmc.Text(
                    feedback_message,
                    color="red" if modal_open_new else "green",
                    id="user-feedback-message-register",
                ),
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )
            # return modal_open_new, content, dmc.Text(feedback_message, color="red" if modal_open_new else "green"), modal_state, modal_open_new, local_data

        logger.warning("No button clicked.")
        return (
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
        )


# Google OAuth callback using server-side callback
@dash.callback(
    Output("google-oauth-redirect", "href"),
    Input("google-oauth-button", "n_clicks"),
    prevent_initial_call=True,
)
def handle_google_oauth_login(n_clicks):
    """Handle Google OAuth login button click."""
    if not n_clicks:
        raise PreventUpdate

    if not settings.auth.google_oauth_enabled:
        logger.warning("Google OAuth is not enabled")
        raise PreventUpdate

    try:
        # Call the API to get the Google OAuth login URL
        oauth_data = api_call_get_google_oauth_login_url()

        if oauth_data and "authorization_url" in oauth_data:
            authorization_url = oauth_data["authorization_url"]
            logger.info(f"Redirecting to Google OAuth: {authorization_url}")
            return authorization_url
        else:
            logger.error("Failed to get OAuth URL from API")
            raise PreventUpdate

    except Exception as e:
        logger.error(f"Error initiating Google OAuth: {e}")
        raise PreventUpdate


# Add JavaScript redirect handling for Google OAuth
dash.clientside_callback(
    """
    function(href) {
        if (href && href !== "") {
            window.location.href = href;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("google-oauth-redirect", "target"),
    Input("google-oauth-redirect", "href"),
    prevent_initial_call=True,
)


# Add Google OAuth callback handler for when user returns from Google
@dash.callback(
    [
        Output("local-store", "data", allow_duplicate=True),
    ],
    [
        Input("url", "search"),
    ],
    [
        State("local-store", "data"),
    ],
    prevent_initial_call=True,
)
def handle_google_oauth_callback(search_params, local_data):
    """Handle OAuth callback when user returns from Google."""
    if not search_params:
        raise PreventUpdate

    # Parse URL parameters
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(f"?{search_params}" if not search_params.startswith("?") else search_params)
    params = parse_qs(parsed.query)

    # Check if this is an OAuth callback
    if "code" not in params or "state" not in params:
        raise PreventUpdate

    code = params["code"][0]
    state = params["state"][0]

    try:
        # Call the OAuth callback API
        oauth_result = api_call_handle_google_oauth_callback(code, state)

        if oauth_result and oauth_result.get("success"):
            # Extract token data and user info
            token_data = oauth_result["token"]
            user_data = oauth_result["user"]

            # Create session data similar to regular login (only include TokenBase compatible fields)
            session_data = {
                "access_token": token_data["access_token"],
                "refresh_token": token_data["refresh_token"],
                "token_type": token_data["token_type"],
                "expire_datetime": token_data["expire_datetime"],
                "refresh_expire_datetime": token_data["refresh_expire_datetime"],
                "logged_in": True,
                "user_id": token_data["user_id"],
            }

            logger.info(f"Google OAuth login successful for: {user_data['email']}")

            # Update session
            return [session_data]
        else:
            logger.error(
                f"OAuth callback failed: {oauth_result.get('message', 'Unknown error') if oauth_result else 'API call failed'}"
            )
            raise PreventUpdate

    except Exception as e:
        logger.error(f"Error handling OAuth callback: {e}")
        raise PreventUpdate
