import dash
from dash import dcc, html, Input, Output, callback, State
import dash_bootstrap_components as dbc
from flask_login import login_user, LoginManager, UserMixin, logout_user, current_user
# from app_login import User

dash.register_page(__name__, path="/home")

layout = html.Div([
        html.H1('Home page'),
])
