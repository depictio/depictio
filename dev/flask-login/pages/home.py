import dash
from dash import html

# from app_login import User

dash.register_page(__name__, path="/home")

layout = html.Div(
    [
        html.H1("Home page"),
    ]
)
