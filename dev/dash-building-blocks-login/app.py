import re
from dash import html, Dash, dcc, Input, Output, State
import dash_mantine_components as dmc
import dash
import json
import os
import bcrypt


# Dummy login function
def login_user():
    return {"logged_in": True}


# Dummy logout function
def logout_user():
    return {"logged_in": False}


# Check if user is logged in
def is_user_logged_in(session_data):
    return session_data.get("logged_in", False)


def hash_password(password: str) -> str:
    # Generate a salt
    salt = bcrypt.gensalt()
    # Hash the password with the salt
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    # Return the hashed password
    return hashed.decode("utf-8")


def verify_password(stored_hash: str, password: str) -> bool:
    # Verify the password against the stored hash
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


# Initialize the Dash app
app = Dash(__name__, suppress_callback_exceptions=True)

# Path to the JSON file for storing user data
USER_DATA_FILE = "/Users/tweber/Gits/depictio/dev/dash-building-blocks-login/user_data.json"

# Ensure the JSON file exists
if not os.path.exists(USER_DATA_FILE):
    with open(USER_DATA_FILE, "w") as f:
        json.dump({}, f)


# Function to load user data from the JSON file
def load_user_data():
    with open(USER_DATA_FILE, "r") as f:
        return json.load(f)


# Function to save user data to the JSON file
def save_user_data(data):
    with open(USER_DATA_FILE, "w") as f:
        json.dump(data, f)


# Function to find user by username
def find_user(email):
    users = load_user_data()
    for user in users:
        if user["email"] == email:
            return user
    return None


# Function to add a new user
def add_user(email, password):
    users = load_user_data()
    if not users:
        users = []
    users.append(
        {
            "email": email,
            "password": password,
            "last_login": None,
            "registration_date": None,
            "groups": [],
            "tokens": [],
            "username": None,
            "user_id": None,
        }
    )
    save_user_data(users)


app.layout = html.Div(
    [
        dcc.Store(
            id="modal-state-store", data="login"
        ),  # Store to control modal content state (login or register)
        dcc.Store(id="modal-open-store", data=True),  # Store to control modal state (open or close)
        dcc.Store(id="session-store", storage_type="session"),
        dmc.Modal(
            id="auth-modal",
            opened=True,
            centered=True,
            children=[dmc.Center(id="modal-content")],
            withCloseButton=False,
            closeOnEscape=False,
            closeOnClickOutside=False,
            size="lg",
        ),
        html.Div(id="landing-page-content"),
        # Hidden buttons for switching forms to ensure they exist in the layout
        html.Div(
            [
                dmc.Button("hidden-login-button", id="open-login-form", style={"display": "none"}),
                dmc.Button(
                    "hidden-register-button", id="open-register-form", style={"display": "none"}
                ),
                dmc.Button("hidden-login-button", id="login-button", style={"display": "none"}),
                dmc.Button("hidden-logout-button", id="logout-button", style={"display": "none"}),
                dmc.Button(
                    "hidden-register-button", id="register-button", style={"display": "none"}
                ),
                dmc.PasswordInput(
                    "hidden-register-password", id="register-password", style={"display": "none"}
                ),
                dmc.PasswordInput(
                    "hidden-register-confirm-password",
                    id="register-confirm-password",
                    style={"display": "none"},
                ),
                dmc.TextInput(
                    "hidden-register-email", id="register-email", style={"display": "none"}
                ),
                dmc.PasswordInput(
                    "hidden-login-password", id="login-password", style={"display": "none"}
                ),
                dmc.TextInput("hidden-login-email", id="login-email", style={"display": "none"}),
                html.Div(id="user-feedback"),
            ]
        ),
    ]
)


def render_login_form():
    return dmc.Stack(
        [
            dmc.Title("Welcome to Depictio", align="center", order=2),
            dmc.Space(h=20),
            dmc.TextInput(
                label="Email:",
                id="register-email",
                placeholder="Enter your email",
                style={"width": "100%", "display": "none"},
            ),
            dmc.PasswordInput(
                label="Password:",
                id="register-password",
                placeholder="Enter your password",
                style={"width": "100%", "display": "none"},
            ),
            dmc.TextInput(
                label="Email:",
                id="login-email",
                placeholder="Enter your email",
                style={"width": "100%"},
            ),
            dmc.PasswordInput(
                label="Password:",
                id="login-password",
                placeholder="Enter your password",
                style={"width": "100%"},
            ),
            dmc.PasswordInput(
                label="Confirm Password:",
                id="register-confirm-password",
                placeholder="Confirm your password",
                style={"width": "100%", "display": "none"},
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
                    dmc.Button(
                        "",
                        radius="md",
                        id="logout-button",
                        fullWidth=True,
                        style={"display": "none"},
                    ),
                    html.A(
                        dmc.Button(
                            "Register", radius="md", variant="outline", color="gray", fullWidth=True
                        ),
                        href="#",
                        id="open-register-form",
                    ),
                    html.A(
                        dmc.Button(
                            "", radius="md", variant="outline", color="gray", fullWidth=True
                        ),
                        href="#",
                        id="open-login-form",
                        style={"display": "none"},
                    ),
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
            dmc.Title("Register for DMC/DBC", align="center", order=2),
            dmc.Space(h=20),
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
                    dmc.Button(
                        "",
                        radius="md",
                        id="logout-button",
                        fullWidth=True,
                        style={"display": "none"},
                    ),
                    dmc.Button("Register", radius="md", id="register-button", fullWidth=True),
                    html.A(
                        dmc.Button(
                            "", radius="md", variant="outline", color="gray", fullWidth=True
                        ),
                        href="#",
                        id="open-register-form",
                        style={"display": "none"},
                    ),
                    html.A(
                        dmc.Button(
                            "Back to Login",
                            radius="md",
                            variant="outline",
                            color="gray",
                            fullWidth=True,
                        ),
                        href="#",
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


@app.callback(
    Output("session-store", "data"),
    [Input("login-button", "n_clicks"), Input("logout-button", "n_clicks")],
    [State("session-store", "data")],
)
def update_session_store(login_clicks, logout_clicks, session_data):
    if session_data is None:
        session_data = {}
    if login_clicks:
        session_data = login_user()
    elif logout_clicks:
        session_data = logout_user()
    return session_data


@app.callback(
    [Output("login-button", "disabled"), Output("login-email", "error")],
    [Input("login-email", "value")],
)
def update_submit_button(email):
    if email:
        valid = re.match(r"^[a-zA-Z0-9_.+-]+@embl\.de$", email)
        return not valid, not valid
    return True, False  # Initially disabled with no error


@app.callback(
    [Output("register-button", "disabled"), Output("register-email", "error")],
    [Input("register-email", "value")],
)
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
        Output("landing-page-content", "children"),
    ],
    [
        Input("open-register-form", "n_clicks"),
        Input("open-login-form", "n_clicks"),
        Input("login-button", "n_clicks"),
        Input("register-button", "n_clicks"),
        Input("logout-button", "n_clicks"),
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
    # prevent_initial_call=True,
)
def handle_auth_and_switch_forms(
    n_clicks_register,
    n_clicks_login_form,
    n_clicks_login,
    n_clicks_register_form,
    n_clicks_logout,
    current_state,
    login_email,
    login_password,
    register_email,
    register_password,
    register_confirm_password,
    modal_open,
    session_data,
):
    if session_data and session_data.get("logged_in", False):
        return (
            False,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            html.Div(
                [
                    dmc.Title("Welcome to DMC/DBC", align="center"),
                    dmc.Space(h=20),
                    dmc.Text("You are now logged in.", align="center"),
                    dmc.Button(
                        "Logout",
                        id="logout-button",
                        variant="outline",
                        color="red",
                        size="lg",
                        fullWidth=True,
                    ),
                ]
            ),
        )

    print("\n")
    ctx = dash.callback_context
    print(ctx.triggered)

    # if not ctx.triggered:
    #     return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    feedback_message = ""
    landing_page_content = ""

    if button_id == "open-register-form":
        modal_state = "register"
        content = render_register_form()
        return modal_open, content, dash.no_update, modal_state, dash.no_update, dash.no_update
    elif button_id == "open-login-form" or not ctx.triggered:
        modal_state = "login"
        content = render_login_form()
        return modal_open, content, dash.no_update, modal_state, dash.no_update, dash.no_update
    elif button_id == "login-button":
        print("login")
        if login_email and login_password:
            print("login_email:", login_email)
            print("login_password:", login_password)

            user = find_user(login_email)
            print("user:", user)

            # print("user['password']:", user["password"])
            # print(verify_password(user["password"], login_password))
            # print(login_password)

            if user and verify_password(user["password"], login_password):
                feedback_message = dmc.Text("Login successful!", color="green")
                modal_open = False
                landing_page_content = html.Div(
                    [
                        dmc.Title("Welcome to DMC/DBC", align="center"),
                        dmc.Space(h=20),
                        dmc.Text("You are now logged in.", align="center"),
                        dmc.Button(
                            "Logout",
                            id="logout-button",
                            variant="outline",
                            color="red",
                            size="lg",
                            fullWidth=True,
                        ),
                    ]
                )
                return (
                    modal_open,
                    dash.no_update,
                    feedback_message,
                    current_state,
                    modal_open,
                    landing_page_content,
                )

            else:
                feedback_message = dmc.Text("Invalid email or password.", color="red")
                modal_open = True
        else:
            feedback_message = dmc.Text("Please fill in all fields.", color="red")
            modal_open = True

        content = render_login_form()
        return (
            modal_open,
            content,
            feedback_message,
            current_state,
            modal_open,
            landing_page_content,
        )
    elif button_id == "register-button":
        if register_email and register_password and register_confirm_password:
            if find_user(register_email):
                feedback_message = dmc.Text("Email already registered.", color="red")
                modal_open = True
            elif register_password != register_confirm_password:
                feedback_message = dmc.Text("Passwords do not match.", color="red")
                modal_open = True
            else:
                hashed_password = hash_password(register_password)
                add_user(register_email, hashed_password)
                # save_user_data(user_data)
                feedback_message = dmc.Text(
                    "Registration successful! Please log in.", color="green"
                )
                modal_state = "login"
                content = render_login_form()
                return (
                    modal_open,
                    content,
                    feedback_message,
                    modal_state,
                    modal_open,
                    dash.no_update,
                )
        else:
            feedback_message = dmc.Text("Please fill in all fields.", color="red")
            modal_open = True
        content = render_register_form()
        return modal_open, content, feedback_message, current_state, modal_open, dash.no_update
    elif button_id == "logout-button":
        modal_open = True
        landing_page_content = html.Div()
        content = render_login_form()
        return modal_open, content, dash.no_update, current_state, modal_open, landing_page_content

    return (
        dash.no_update,
        dash.no_update,
        dash.no_update,
        dash.no_update,
        dash.no_update,
        dash.no_update,
    )


if __name__ == "__main__":
    app.run_server(debug=True)
