import os
import warnings

import dash
import pandas as pd
from dash import dcc, html
from dash.dependencies import Input, Output, State
from flask import Flask, session
from flask_login import LoginManager, login_user


class User:
    def __init__(self, series):
        print(series)
        self.series = series

    @property
    def is_active(self):
        # This should return True if this is an active user
        # In your case, all users are active so just return True
        return True

    @property
    def is_anonymous(self):
        # This should return True only for fake users not supposed to log in (e.g. guest users)
        # In your case, there are no anonymous users so just return False
        return False

    @property
    def is_authenticated(self):
        # This should return True if the user is authenticated
        # In your case, all logged-in users are authenticated so just return True
        return True

    def get_id(self):
        # This should return a unique identifier for the user
        # Here we'll use the username as the unique identifier
        return self.series["username"]


warnings.filterwarnings("ignore")

server = Flask(__name__)
app = dash.Dash(__name__, server=server, suppress_callback_exceptions=True)
server.secret_key = os.urandom(24)

create = html.Div(
    [
        html.H1("Create User Account"),
        dcc.Location(id="create_user", refresh=True),
        dcc.Input(id="username", type="text", placeholder="user name", maxLength=15),
        dcc.Input(id="password", type="password", placeholder="password"),
        dcc.Input(id="email", type="email", placeholder="email", maxLength=50),
        html.Button("Create User", id="submit-val", n_clicks=0),
        html.Div(id="container-button-basic"),
    ]
)  # end div
login = html.Div(
    [
        dcc.Location(id="url_login", refresh=True),
        html.H2("""Please log in to continue:""", id="h1"),
        dcc.Input(placeholder="Enter your username", type="text", id="uname-box"),
        dcc.Input(placeholder="Enter your password", type="password", id="pwd-box"),
        html.Button(children="Login", n_clicks=0, type="submit", id="login-button"),
        html.Div(children="", id="output-state"),
    ]
)  # end div
success = html.Div(
    [
        dcc.Location(id="url_login_success", refresh=True),
        html.Div(
            [
                html.H2("Login successful."),
                html.Br(),
                html.P("Select a Dataset"),
                dcc.Link("Data", href="/data"),
            ]
        ),  # end div
        html.Div(
            [html.Br(), html.Button(id="back-button", children="Go back", n_clicks=0)]
        ),  # end div
    ]
)  # end div
data = html.Div(
    [
        dcc.Dropdown(
            id="dropdown",
            options=[{"label": i, "value": i} for i in ["Day 1", "Day 2"]],
            value="Day 1",
        ),
        html.Br(),
        html.Div([dcc.Graph(id="graph")]),
    ]
)  # end div
failed = html.Div(
    [
        dcc.Location(id="url_login_df", refresh=True),
        html.Div(
            [
                html.H2("Log in Failed. Please try again."),
                html.Br(),
                html.Div([login]),
                html.Br(),
                html.Button(id="back-button", children="Go back", n_clicks=0),
            ]
        ),  # end div
    ]
)  # end div
logout = html.Div(
    [
        dcc.Location(id="logout", refresh=True),
        html.Br(),
        html.Div(html.H2("You have been logged out - Please login")),
        html.Br(),
        html.Div([login]),
        html.Button(id="back-button", children="Go back", n_clicks=0),
    ]
)  # end div
app.layout = html.Div(
    [
        html.Div(id="user-name"),
        html.Div(id="page-content", className="content"),
        dcc.Location(id="url", refresh=False),
    ]
)


# Setup the LoginManager for the server
login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = "/login"

# Load the users data from a CSV file
users = (
    pd.read_csv("dev/flask-login/users.csv")
    if os.path.isfile("dev/flask-login/users.csv")
    else pd.DataFrame(columns=["username", "password", "email"])
)

print(users)


@login_manager.user_loader
def load_user(user_id):
    global users
    series = users.loc[users["username"] == user_id].iloc[0]
    return User(series)


@app.callback(
    dash.dependencies.Output("page-content", "children"),
    [dash.dependencies.Input("url", "pathname")],
)
def display_page(pathname):
    if pathname == "/login":
        return login
    elif pathname == "/success":
        if "logged_in" in session:  # Check session key
            return success
        else:
            return login
    elif pathname == "/failed":
        return failed
    elif pathname == "/data":
        if "logged_in" in session:  # Check session key
            return data
        else:
            return login
    elif pathname == "/logout":
        session.pop("logged_in", None)  # Remove session key
        return logout
    else:
        return create  # this will be displayed when no path is provided, i.e., at startup


@app.callback(
    [Output("container-button-basic", "children")],
    [Input("submit-val", "n_clicks")],
    [State("username", "value"), State("password", "value"), State("email", "value")],
)
def insert_users(n_clicks, un, pw, em):
    global users
    if un is not None and pw is not None and em is not None:
        if un in users["username"].values:  # Check if username already exists
            return [html.Div("This username already exists, please choose another one.")]

        # hashed_password = generate_password_hash(pw, method="sha256")
        new_user = pd.DataFrame([[un, pw, em]], columns=["username", "password", "email"])
        users = pd.concat([users, new_user])
        users.to_csv("dev/flask-login/users.csv", index=False)  # Save back to the CSV file
        return [login]
    else:
        return [
            html.Div(
                [
                    html.H2("Already have a user account?"),
                    dcc.Link("Click here to Log In", href="/login"),
                ]
            )
        ]


@app.callback(
    Output("user-name", "children"),
    [Input("page-content", "children")],
)
def update_user_name(_):
    if "username" in session:
        return html.H5(f"Logged in as {session['username']}")
    else:
        return ""


@app.callback(
    Output("url_login", "pathname"),
    [Input("login-button", "n_clicks")],
    [State("uname-box", "value"), State("pwd-box", "value")],
)
def successful(n_clicks, input1, input2):
    series = (
        users[users["username"] == input1].iloc[0]
        if not users[users["username"] == input1].empty
        else None
    )
    print("TOTO")
    print(series)
    print(input1)
    print(users[users["username"] == input1])
    print("\n")

    user = User(series)
    print(user)
    print("\n")
    # print(user)
    if series is not None and series["password"] == input2:
        login_user(user)
        return "/success"


@app.callback(
    Output("output-state", "children"),
    [Input("login-button", "n_clicks")],
    [State("uname-box", "value"), State("pwd-box", "value")],
)
def update_output(n_clicks, input1, input2):
    if n_clicks > 0:
        print(input1, input2)
        user = (
            users[users["username"] == input1].iloc[0]
            if not users[users["username"] == input1].empty
            else None
        )
        print(user)
        # print(str(user["password"]), str(input2), check_password_hash(user["password"], input2))
        if user is not None:
            if user["password"] == input2:
                return ""
            else:
                return "Incorrect username or password"
        else:
            return "Incorrect username or password"
    else:
        return ""


@app.callback(Output("url_login_success", "pathname"), [Input("back-button", "n_clicks")])
def logout_dashboard(n_clicks):
    if n_clicks > 0:
        return "/"


@app.callback(Output("url_login_df", "pathname"), [Input("back-button", "n_clicks")])
def logout_dashboard(n_clicks):
    if n_clicks > 0:
        return "/"


# Create callbacks
@app.callback(Output("url_logout", "pathname"), [Input("back-button", "n_clicks")])
def logout_dashboard(n_clicks):
    if n_clicks > 0:
        return "/"


# set the callback for the dropdown interactivity
@app.callback([Output("graph", "figure")], [Input("dropdown", "value")])
def update_graph(dropdown_value):
    if dropdown_value == "Day 1":
        return [
            {
                "layout": {"title": "Graph of Day 1"},
                "data": [{"x": [1, 2, 3, 4], "y": [4, 1, 2, 1]}],
            }
        ]
    else:
        return [
            {
                "layout": {"title": "Graph of Day 2"},
                "data": [{"x": [1, 2, 3, 4], "y": [2, 3, 2, 4]}],
            }
        ]


if __name__ == "__main__":
    app.run_server(debug=True, port=9050)
