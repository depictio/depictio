import os

from flask import Flask
from flask_login import login_user, LoginManager, UserMixin, logout_user, current_user

import dash
from dash.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_html_components as html

# CREDIT: This code is copied from Dash official documentation:
# https://dash.plotly.com/urls

# Since we're adding callbacks to elements that don't exist in the app.layout,
# Dash will raise an exception to warn us that we might be
# doing something wrong.
# In this case, we're adding the elements through a callback, so we can ignore
# the exception.
# Exposing the Flask Server to enable configuring it for logging in
server = Flask(__name__)
app = dash.Dash(
    __name__,
    server=server,
    title="Example Dash login",
    update_title="Loading...",
    suppress_callback_exceptions=True,
)

# Updating the Flask Server configuration with Secret Key to encrypt the user session cookie
server.config.update(SECRET_KEY=os.getenv("SECRET_KEY"))

# Login manager object will be used to login / logout users
login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = "/login"

# User data model. It has to have at least self.id as a minimum


class User(UserMixin):
    def __init__(self, username):
        self.id = username


@login_manager.user_loader
def load_user(username):
    """This function loads the user by user id. Typically this looks up the user from a user database.
    We won't be registering or looking up users in this example, since we'll just login using LDAP server.
    So we'll simply return a User object with the passed in username.
    """
    return User(username)


# User status management views


# Login screen
login = html.Div(
    [
        dcc.Location(id="url_login", refresh=True),
        html.H2("""Please log in to continue:""", id="h1"),
        dcc.Input(placeholder="Enter your username", type="text", id="uname-box"),
        dcc.Input(placeholder="Enter your password", type="password", id="pwd-box"),
        html.Button(children="Login", n_clicks=0, type="submit", id="login-button"),
        html.Div(children="", id="output-state"),
        html.Br(),
        dcc.Link("Home", href="/"),
    ]
)

# Successful login
success = html.Div(
    [
        html.Div([html.H2("Login successful."), html.Br(), dcc.Link("Home", href="/")])  # end div
    ]
)  # end div

# Failed Login
failed = html.Div(
    [
        html.Div(
            [
                html.H2("Log in Failed. Please try again."),
                html.Br(),
                html.Div([login]),
                dcc.Link("Home", href="/"),
            ]
        )  # end div
    ]
)  # end div

# logout
logout = html.Div(
    [
        html.Div(html.H2("You have been logged out - Please login")),
        html.Br(),
        dcc.Link("Home", href="/"),
    ]
)  # end div

# Callback function to login the user, or update the screen if the username or password are incorrect


@app.callback(
    Output("url_login", "pathname"),
    Output("output-state", "children"),
    [Input("login-button", "n_clicks")],
    [State("uname-box", "value"), State("pwd-box", "value")],
)
def login_button_click(n_clicks, username, password):
    if n_clicks > 0:
        if username == "test" and password == "test":
            user = User(username)
            login_user(user)
            return "/success", ""
        else:
            return "/login", "Incorrect username or password"


# Main Layout
app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        dcc.Location(id="redirect", refresh=True),
        dcc.Store(id="login-status", storage_type="session"),
        html.Div(id="user-status-div"),
        html.Br(),
        html.Hr(),
        html.Br(),
        html.Div(id="page-content"),
    ]
)


index_page = html.Div(
    [
        dcc.Link("Go to Page 1", href="/page-1"),
        html.Br(),
        dcc.Link("Go to Page 2", href="/page-2"),
    ]
)

page_1_layout = html.Div(
    [
        html.H1("Page 1"),
        dcc.Dropdown(
            id="page-1-dropdown",
            options=[{"label": i, "value": i} for i in ["LA", "NYC", "MTL"]],
            value="LA",
        ),
        html.Div(id="page-1-content"),
        html.Br(),
        dcc.Link("Go to Page 2", href="/page-2"),
        html.Br(),
        dcc.Link("Go back to home", href="/"),
    ]
)


@app.callback(Output("page-1-content", "children"), [Input("page-1-dropdown", "value")])
def page_1_dropdown(value):
    return 'You have selected "{}"'.format(value)


page_2_layout = html.Div(
    [
        html.H1("Page 2"),
        dcc.RadioItems(
            id="page-2-radios",
            options=[{"label": i, "value": i} for i in ["Orange", "Blue", "Red"]],
            value="Orange",
        ),
        html.Div(id="page-2-content"),
        html.Br(),
        dcc.Link("Go to Page 1", href="/page-1"),
        html.Br(),
        dcc.Link("Go back to home", href="/"),
    ]
)


@app.callback(Output("page-2-content", "children"), [Input("page-2-radios", "value")])
def page_2_radios(value):
    return 'You have selected "{}"'.format(value)


@app.callback(
    Output("user-status-div", "children"),
    Output("login-status", "data"),
    [Input("url", "pathname")],
)
def login_status(url):
    """callback to display login/logout link in the header"""
    if (
        hasattr(current_user, "is_authenticated")
        and current_user.is_authenticated
        and url != "/logout"
    ):  # If the URL is /logout, then the user is about to be logged out anyways
        return dcc.Link("logout", href="/logout"), current_user.get_id()
    else:
        return dcc.Link("login", href="/login"), "loggedout"


# Main router


@app.callback(
    Output("page-content", "children"), Output("redirect", "pathname"), [Input("url", "pathname")]
)
def display_page(pathname):
    """callback to determine layout to return"""
    # We need to determine two things for everytime the user navigates:
    # Can they access this page? If so, we just return the view
    # Otherwise, if they need to be authenticated first, we need to redirect them to the login page
    # So we have two outputs, the first is which view we'll return
    # The second one is a redirection to another page is needed
    # In most cases, we won't need to redirect. Instead of having to return two variables everytime in the if statement
    # We setup the defaults at the beginning, with redirect to dash.no_update; which simply means, just keep the requested url
    view = None
    url = dash.no_update
    if pathname == "/login":
        view = login
    elif pathname == "/success":
        if current_user.is_authenticated:
            view = success
        else:
            view = failed
    elif pathname == "/logout":
        if current_user.is_authenticated:
            logout_user()
            view = logout
        else:
            view = login
            url = "/login"

    elif pathname == "/page-1":
        view = page_1_layout
    elif pathname == "/page-2":
        if current_user.is_authenticated:
            view = page_2_layout
        else:
            view = "Redirecting to login..."
            url = "/login"
    else:
        view = index_page
    # You could also return a 404 "URL not found" page here
    return view, url


if __name__ == "__main__":
    app.run_server(debug=True)
