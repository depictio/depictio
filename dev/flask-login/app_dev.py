import os

import dash
from dash import dcc, html
from flask import Flask, redirect, render_template, request, session
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user

# Set up server and login manager
server = Flask(__name__)
server.secret_key = os.urandom(24)
login_manager = LoginManager(server)
print(os.listdir("."))
users = (
    pd.read_csv("users.csv")
    if os.path.isfile("users.csv")
    else pd.DataFrame(columns=["username", "password", "email"])
)
print(users)


class User(UserMixin):
    def __init__(self, series):
        self.series = series

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_authenticated(self):
        return True

    def get_id(self):
        return self.series["username"]

    def check_password(self, password):
        return password == self.series["password"]


@login_manager.user_loader
def load_user(user_id):
    if user_id in users["username"].values:
        series = users.loc[users["username"] == user_id].iloc[0]
        return User(series)
    else:
        return None


@server.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = load_user(request.form["username"])
        if user is not None and user.check_password(request.form["password"]):
            login_user(user)
            session["username"] = request.form["username"]
            return redirect("/dash")
    return render_template("login.html")


@server.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop("username", None)
    return redirect("/login")


# Initialize Dash app
app = dash.Dash(__name__, server=server, url_base_pathname="/dash/")

app.layout = html.Div(
    [
        html.Div(id="user-name"),
        html.Div(id="page-content", className="content"),
        dcc.Location(id="url", refresh=False),
    ]
)


@app.callback(
    dash.dependencies.Output("page-content", "children"),
    [dash.dependencies.Input("url", "pathname")],
)
def display_page(pathname):
    if "username" in session:
        return html.H2("Hello, {}. You're logged in!".format(session["username"]))
    else:
        return html.H2("You are not logged in.")


if __name__ == "__main__":
    server.run(debug=True, port=9050)
